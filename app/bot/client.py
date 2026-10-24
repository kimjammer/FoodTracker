"""
Discord Bot Client with Slash Commands, Event Routing, and Interactive Views.
"""

import logging
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from app.bot.handlers import handle_receipt_attachment, handle_user_query, is_image_attachment
from app.bot.schedule_views import ScheduleManagementView, build_schedule_embed
from app.bot.views import DailyCookView, MealPlanApprovalView
from app.llm.client import gemini_kitchen_agent
from app.llm.tools import execute_tool, is_tool_error_output
from app.scheduler.schedule_manager import SCHEDULE_DEFINITIONS, schedule_manager
from app.scheduler.scheduler_service import scheduler_service
from app.services.calendar_service import calendar_service
from app.services.profile_service import RECOMMENDED_MAX_CHARS, user_profile_service
from config import settings

logger = logging.getLogger(__name__)


class KitchenBot(commands.Bot):
    """
    Discord Bot for the Autonomous Kitchen & Meal Planning System.
    """

    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.guilds = True

        super().__init__(command_prefix="!", intents=intents)
        self.tree.on_error = self.on_app_command_error

    async def on_app_command_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        logger.error(f"Unhandled slash command error: {error}", exc_info=True)
        err_msg = f"❌ An error occurred while responding: {str(error)[:1800]}"
        try:
            if interaction.response.is_done():
                await interaction.followup.send(err_msg, ephemeral=True)
            else:
                await interaction.response.send_message(err_msg, ephemeral=True)
        except Exception:
            pass

    async def setup_hook(self):
        """Register application commands and sync command tree."""
        self.register_slash_commands()
        try:
            synced = await self.tree.sync()
            logger.info(f"Synced {len(synced)} slash commands.")
        except Exception as e:
            logger.warning(f"Failed to sync slash commands: {e}")

    async def on_ready(self):
        logger.info(f"KitchenBot logged in as {self.user} (ID: {self.user.id})")
        logger.info(f"Active in {len(self.guilds)} guild(s).")
        try:
            scheduler_service.start(self)
        except Exception as e:
            logger.error(f"Failed to start scheduler service: {e}", exc_info=True)

    async def close(self):
        try:
            scheduler_service.shutdown()
        except Exception as e:
            logger.warning(f"Error shutting down scheduler: {e}")
        await super().close()

    async def on_message(self, message: discord.Message):
        # Ignore messages from bots (including self)
        if message.author.bot:
            return

        is_dm = isinstance(message.channel, discord.DMChannel)
        is_thread = isinstance(message.channel, discord.Thread)
        is_mentioned = bool(self.user and self.user in message.mentions)

        # For threads, check the parent channel ID against the designated channel ID
        effective_channel_id = message.channel.parent_id if is_thread else message.channel.id
        is_designated_channel = bool(
            settings.discord_channel_id and effective_channel_id == settings.discord_channel_id
        )

        should_handle = is_designated_channel or is_dm or is_mentioned
        if not should_handle and is_thread:
            # Also handle if the thread was created on a bot message (e.g. following up on announcements)
            starter = message.channel.starter_message
            if starter and self.user and starter.author.id == self.user.id:
                should_handle = True

        if not should_handle:
            return

        try:
            # Check for receipt photo upload
            if message.attachments and any(is_image_attachment(a) for a in message.attachments):
                await handle_receipt_attachment(message)
                return

            # Clean mention prefix if present
            clean_content = message.content
            if self.user:
                clean_content = clean_content.replace(f"<@{self.user.id}>", "").replace(f"<@!{self.user.id}>", "")
            clean_content = clean_content.strip()

            if clean_content:
                message.content = clean_content
                await handle_user_query(message, bot_user=self.user)
        except Exception as e:
            logger.error(f"Error in on_message handler: {e}", exc_info=True)
            try:
                if hasattr(message, "add_reaction"):
                    await message.add_reaction("❌")
            except Exception:
                pass
            err_text = f"❌ An error occurred while responding: {str(e)[:1500]}"
            try:
                await message.reply(err_text)
            except Exception:
                try:
                    await message.channel.send(err_text)
                except Exception:
                    pass

    def register_slash_commands(self):
        """Define application slash commands."""

        @self.tree.command(name="plan", description="Generate a 7-day dinner meal plan")
        @app_commands.describe(notes="Optional revision notes or preferences (e.g. 'extra pasta this week')")
        async def plan_command(interaction: discord.Interaction, notes: Optional[str] = None):
            await interaction.response.defer()

            # Status message for user feedback
            async def notify_rate_limit(attempt: int, delay: float):
                try:
                    await interaction.followup.send(
                        f"⏳ **Rate limit reached:** Waiting {delay:.0f}s before continuing plan generation...",
                        ephemeral=True,
                    )
                except Exception as e:
                    logger.warning(f"Failed to send rate limit notice: {e}")

            try:
                plan_text = await gemini_kitchen_agent.generate_weekly_meal_plan(
                    user_feedback=notes,
                    on_rate_limit=notify_rate_limit,
                )

                embed = discord.Embed(
                    title="🥗 Proposed 7-Day Meal Plan",
                    description=plan_text[:4000],
                    color=discord.Color.green(),
                )
                embed.set_footer(text="Review and click 'Approve Plan' or reply to modify.")

                view = MealPlanApprovalView(plan_summary=plan_text)
                await interaction.followup.send(embed=embed, view=view)

            except Exception as e:
                logger.error(f"Error generating meal plan: {e}", exc_info=True)
                await interaction.followup.send(f"❌ Failed to generate meal plan: {str(e)[:1800]}")

        @self.tree.command(name="inventory", description="View current Grocy stock overview")
        @app_commands.describe(search="Optional search query to filter products")
        async def inventory_command(interaction: discord.Interaction, search: Optional[str] = None):
            await interaction.response.defer()
            try:
                if search:
                    output = await execute_tool("stock_search_tool", {"query": search})
                    title = f"📦 Inventory Search: '{search}'"
                else:
                    output = await execute_tool("stock_overview_tool", {})
                    title = "📦 Kitchen Stock Overview"

                if is_tool_error_output(output):
                    await interaction.followup.send(f"❌ Error fetching stock: {output[:1800]}")
                    return

                embed = discord.Embed(
                    title=title,
                    description=output[:4000] if output else "No stock items found.",
                    color=discord.Color.blue(),
                )
                await interaction.followup.send(embed=embed)
            except Exception as e:
                await interaction.followup.send(f"❌ Error fetching stock: {str(e)[:1800]}")

        @self.tree.command(name="shopping", description="View current Grocy shopping list")
        async def shopping_command(interaction: discord.Interaction):
            await interaction.response.defer()
            try:
                output = await execute_tool("shopping_list_view_tool", {})
                if is_tool_error_output(output):
                    await interaction.followup.send(f"❌ Error fetching shopping list: {output[:1800]}")
                    return
                embed = discord.Embed(
                    title="🛒 Grocy Shopping List",
                    description=output[:4000] if output else "Shopping list is empty.",
                    color=discord.Color.orange(),
                )
                await interaction.followup.send(embed=embed)
            except Exception as e:
                await interaction.followup.send(f"❌ Error fetching shopping list: {str(e)[:1800]}")

        @self.tree.command(name="cook", description="Get 4-step assembly instructions for dinner")
        @app_commands.describe(dish="Specific dish name (defaults to tonight's scheduled recipe)")
        async def cook_command(interaction: discord.Interaction, dish: Optional[str] = None):
            await interaction.response.defer()
            try:
                instructions = await gemini_kitchen_agent.generate_evening_dispatch(dish_name=dish)
                embed = discord.Embed(
                    title=f"🍳 Tonight's Dinner Guide: {dish or 'Scheduled Dinner'}",
                    description=instructions[:4000],
                    color=discord.Color.gold(),
                )
                view = DailyCookView(dish_name=dish or "Tonight's Dinner")
                await interaction.followup.send(embed=embed, view=view)
            except Exception as e:
                await interaction.followup.send(f"❌ Error generating cooking guide: {str(e)[:1800]}")

        @self.tree.command(name="status", description="Check system connectivity (Grocy, Gemini & Google Calendar)")
        async def status_command(interaction: discord.Interaction):
            await interaction.response.defer(ephemeral=True)
            # Check Grocy
            try:
                sys_res = await execute_tool("system_info_tool", {})
                if is_tool_error_output(sys_res):
                    grocy_status = f"❌ Grocy connection error: {sys_res[:900]}"
                else:
                    grocy_status = "✅ Connected to Grocy"
            except Exception as e:
                grocy_status = f"❌ Grocy connection error: {str(e)[:900]}"

            # Check Gemini API Key
            gemini_status = (
                f"✅ Gemini API key configured ({settings.gemini_model})"
                if settings.gemini_api_key
                else "⚠️ GEMINI_API_KEY missing in .env"
            )

            # Check Google Calendar
            calendar_status = await calendar_service.check_status()

            embed = discord.Embed(title="🔧 System Health & Status", color=discord.Color.purple())
            embed.add_field(name="Grocy MCP Backend", value=grocy_status, inline=False)
            embed.add_field(name="Gemini AI Engine", value=gemini_status, inline=False)
            embed.add_field(name="Google Calendar", value=calendar_status, inline=False)
            await interaction.followup.send(embed=embed, ephemeral=True)

        @self.tree.command(name="schedules", description="View and toggle automated kitchen schedules")
        async def schedules_command(interaction: discord.Interaction):
            embed = build_schedule_embed()
            view = ScheduleManagementView()
            await interaction.response.send_message(embed=embed, view=view)

        @self.tree.command(name="toggle_schedule", description="Toggle an automated kitchen routine on or off")
        @app_commands.describe(routine="Select the routine to toggle")
        @app_commands.choices(
            routine=[
                app_commands.Choice(name=f"{m.emoji} {m.name} ({m.schedule_display})", value=job_id)
                for job_id, m in SCHEDULE_DEFINITIONS.items()
            ]
        )
        async def toggle_schedule_command(interaction: discord.Interaction, routine: str):
            if routine not in SCHEDULE_DEFINITIONS:
                await interaction.response.send_message(f"❌ Unknown routine '{routine}'.", ephemeral=True)
                return
            new_state = schedule_manager.toggle(routine)
            scheduler_service.sync_job_state(routine)
            meta = SCHEDULE_DEFINITIONS[routine]
            status_text = "🟢 **Enabled**" if new_state else "🔴 **Paused**"
            await interaction.response.send_message(f"{meta.emoji} **{meta.name}** is now {status_text}.")

        @self.tree.command(name="run_schedule", description="Manually trigger an automated kitchen routine now")
        @app_commands.describe(routine="Select the routine to run immediately")
        @app_commands.choices(
            routine=[
                app_commands.Choice(name=f"{m.emoji} {m.name} ({m.schedule_display})", value=job_id)
                for job_id, m in SCHEDULE_DEFINITIONS.items()
            ]
        )
        async def run_schedule_command(interaction: discord.Interaction, routine: str):
            if routine not in SCHEDULE_DEFINITIONS:
                await interaction.response.send_message(f"❌ Unknown routine '{routine}'.", ephemeral=True)
                return
            meta = SCHEDULE_DEFINITIONS[routine]
            await interaction.response.send_message(
                f"⏳ Triggering **{meta.name}** now in this channel...",
                ephemeral=True,
            )
            try:
                success = await scheduler_service.trigger_now(
                    routine,
                    bot=self,
                    channel_id=interaction.channel_id,
                )
                if not success:
                    await interaction.followup.send(
                        f"⚠️ Routine **{meta.name}** completed without dispatching (it may be paused).",
                        ephemeral=True,
                    )
            except Exception as e:
                logger.error(f"Error triggering routine {routine}: {e}", exc_info=True)
                await interaction.followup.send(f"❌ Error triggering {meta.name}: {str(e)[:1800]}", ephemeral=True)

        @self.tree.command(name="profile", description="View or update your persistent culinary profile")
        @app_commands.describe(text="Optional new profile text to save. Leave blank to view current profile.")
        async def profile_command(interaction: discord.Interaction, text: Optional[str] = None):
            if text:
                try:
                    res = user_profile_service.set_profile(text)
                    embed = discord.Embed(
                        title="👤 Culinary Profile Updated",
                        description=res["profile"],
                        color=discord.Color.green(),
                    )
                    length_text = f"{res['length']} / {RECOMMENDED_MAX_CHARS} characters"
                    if res.get("warning"):
                        length_text += f"\n⚠️ *{res['warning']}*"
                    embed.add_field(name="Profile Length", value=length_text, inline=False)
                    embed.set_footer(text="Agents (meal planner, kitchen assistant) will now use this profile.")
                    await interaction.response.send_message(embed=embed)
                except ValueError as ve:
                    await interaction.response.send_message(f"❌ {ve}", ephemeral=True)
            else:
                meta = user_profile_service.get_profile_metadata()
                profile_text = meta["profile"]
                if not profile_text:
                    embed = discord.Embed(
                        title="👤 Culinary Profile",
                        description=(
                            "*No culinary profile is currently set.*\n\n"
                            "Use `/set_profile text: <preferences>` or `/profile text: <preferences>` to define "
                            "your favorite cuisines, dietary restrictions, and cooking constraints, "
                            "or simply tell the bot in chat!"
                        ),
                        color=discord.Color.blue(),
                    )
                else:
                    embed = discord.Embed(
                        title="👤 Culinary Profile & Preferences",
                        description=profile_text,
                        color=discord.Color.blue(),
                    )
                    length_status = f"{meta['length']} / {RECOMMENDED_MAX_CHARS} characters (Guideline: under ~1000)"
                    embed.add_field(name="Length", value=length_status, inline=True)
                    if meta.get("updated_at"):
                        updated_str = meta["updated_at"][:19].replace("T", " ") + " UTC"
                        embed.add_field(name="Last Updated", value=updated_str, inline=True)
                    embed.set_footer(text="Edit with /set_profile, /profile text: ..., or by asking in chat.")
                await interaction.response.send_message(embed=embed)

        @self.tree.command(name="set_profile", description="Set or update your persistent culinary profile")
        @app_commands.describe(text="Your culinary profile (cuisines, flavors, restrictions, cooking constraints)")
        async def set_profile_command(interaction: discord.Interaction, text: str):
            try:
                res = user_profile_service.set_profile(text)
                embed = discord.Embed(
                    title="👤 Culinary Profile Saved",
                    description=res["profile"],
                    color=discord.Color.green(),
                )
                length_text = f"{res['length']} / {RECOMMENDED_MAX_CHARS} characters"
                if res.get("warning"):
                    length_text += f"\n⚠️ *{res['warning']}*"
                embed.add_field(name="Profile Length", value=length_text, inline=False)
                embed.set_footer(text="Agents (meal planner, kitchen assistant) will now use this profile.")
                await interaction.response.send_message(embed=embed)
            except ValueError as ve:
                await interaction.response.send_message(f"❌ {ve}", ephemeral=True)


bot = KitchenBot()
