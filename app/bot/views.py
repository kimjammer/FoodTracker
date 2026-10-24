"""
Discord Interactive UI Views and Buttons (discord.ui.View).
Provides buttons for plan approvals, recipe cooking confirmations, and receipt intake.
"""

import logging
from typing import Any, Dict, List

import discord
from discord import ui

from app.llm.client import gemini_kitchen_agent
from app.llm.tools import execute_tool, is_tool_error_output

logger = logging.getLogger(__name__)


class _BaseKitchenView(ui.View):
    """Base interactive view that indicates errors to the user if a callback fails."""

    async def on_error(self, interaction: discord.Interaction, error: Exception, item: ui.Item[Any]) -> None:
        logger.error(f"Error in Discord UI View ({self.__class__.__name__}): {error}", exc_info=True)
        err_msg = f"❌ An error occurred while processing this action: {error}"
        try:
            if interaction.response.is_done():
                await interaction.followup.send(err_msg, ephemeral=True)
            else:
                await interaction.response.send_message(err_msg, ephemeral=True)
        except Exception:
            pass


class ReceiptConfirmationView(_BaseKitchenView):
    """
    Interactive confirmation view for items parsed from a receipt photo.
    """

    def __init__(self, items: List[Dict[str, Any]], timeout: float = 300.0):
        super().__init__(timeout=timeout)
        self.items = items

    @ui.button(label="Add All to Grocy", style=discord.ButtonStyle.success, emoji="🛒")
    async def confirm_add(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer()
        button.disabled = True
        self.stop()

        # Disable all buttons
        for child in self.children:
            child.disabled = True

        try:
            # Ingest items into Grocy
            results = await gemini_kitchen_agent.ingest_receipt_items(self.items)
        except Exception as e:
            logger.error(f"Error ingesting receipt items: {e}", exc_info=True)
            embed = (
                interaction.message.embeds[0] if interaction.message.embeds else discord.Embed(title="Receipt Intake")
            )
            embed.color = discord.Color.red()
            embed.set_footer(text=f"❌ Error adding items to Grocy: {e}")
            await interaction.message.edit(embed=embed, view=self)
            await interaction.followup.send(f"❌ Error adding items to Grocy: {e}", ephemeral=True)
            return

        success_count = sum(1 for r in results if r.get("status") == "success")
        failed_items = [r for r in results if r.get("status") != "success"]

        embed = interaction.message.embeds[0] if interaction.message.embeds else discord.Embed(title="Receipt Intake")

        if failed_items:
            embed.color = discord.Color.red() if success_count == 0 else discord.Color.orange()
            embed.set_footer(
                text=f"⚠️ Added {success_count}/{len(self.items)} items to Grocy ({len(failed_items)} failed)."
            )
            err_lines = [f"• **{r.get('name', 'Item')}**: {r.get('detail', 'Error')}" for r in failed_items[:5]]
            if len(failed_items) > 5:
                err_lines.append(f"• *(and {len(failed_items) - 5} more errors...)*")
            embed.add_field(name="⚠️ Errors", value="\n".join(err_lines)[:1024], inline=False)
            await interaction.message.edit(embed=embed, view=self)
            await interaction.followup.send(
                f"⚠️ Logged **{success_count}/{len(self.items)} items** into Grocy, "
                f"but **{len(failed_items)} item(s) encountered errors**:\n" + "\n".join(err_lines),
                ephemeral=True,
            )
        else:
            embed.color = discord.Color.green()
            embed.set_footer(text=f"✅ Added {success_count}/{len(self.items)} items to Grocy inventory.")
            await interaction.message.edit(embed=embed, view=self)
            await interaction.followup.send(
                f"🎉 Successfully logged **{success_count} items** into Grocy!",
                ephemeral=True,
            )

    @ui.button(label="Cancel", style=discord.ButtonStyle.secondary, emoji="❌")
    async def cancel(self, interaction: discord.Interaction, button: ui.Button):
        for child in self.children:
            child.disabled = True
        self.stop()

        if interaction.message:
            embed = interaction.message.embeds[0] if interaction.message.embeds else discord.Embed()
            embed.set_footer(text="Intake cancelled.")
            await interaction.response.edit_message(embed=embed, view=self)
        else:
            await interaction.response.send_message("Cancelled intake.", ephemeral=True)


class MealPlanApprovalView(_BaseKitchenView):
    """
    Interactive view for the weekly 7-day meal plan.
    """

    def __init__(self, plan_summary: str, timeout: float = 600.0):
        super().__init__(timeout=timeout)
        self.plan_summary = plan_summary

    @ui.button(label="Approve Plan", style=discord.ButtonStyle.success, emoji="✅")
    async def approve_plan(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer()
        for child in self.children:
            child.disabled = True
        self.stop()

        # Populate missing ingredients for planned meals on Grocy shopping list
        shopping_error = None
        try:
            res = await execute_tool("meal_plan_shopping_tool", {})
            if is_tool_error_output(res):
                shopping_error = res
        except Exception as e:
            logger.warning(f"Could not populate shopping list from meal plan: {e}")
            shopping_error = str(e)

        embed = interaction.message.embeds[0] if interaction.message.embeds else discord.Embed()
        if shopping_error:
            embed.color = discord.Color.orange()
            embed.title = "⚠️ 7-Day Meal Plan Approved (with warnings)"
            embed.add_field(
                name="⚠️ Shopping List Warning",
                value=f"Plan approved, but encountered an error updating the shopping list: {shopping_error[:900]}",
                inline=False,
            )
            await interaction.message.edit(embed=embed, view=self)
            await interaction.followup.send(
                f"⚠️ Plan marked as approved, but an error occurred while updating the shopping list: {shopping_error}",
                ephemeral=True,
            )
        else:
            embed.color = discord.Color.green()
            embed.title = "✅ 7-Day Meal Plan Approved!"
            embed.add_field(
                name="Next Step: Sunday Grocery Run",
                value="Missing ingredients have been recorded. Snap a photo of your receipt here after shopping!",
                inline=False,
            )
            await interaction.message.edit(embed=embed, view=self)
            await interaction.followup.send("Plan marked as approved! 🥗", ephemeral=True)

    @ui.button(label="Modify Plan", style=discord.ButtonStyle.primary, emoji="✏️")
    async def modify_plan(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_message(
            "💬 To modify the plan, just reply in this channel with your requested changes! "
            "(e.g., *'Swap Thursday for Korean beef bowls'* or *'Make Friday an emergency quick meal'*).",
            ephemeral=True,
        )


class DailyCookView(_BaseKitchenView):
    """
    Interactive execution buttons for tonight's dinner dispatch.
    """

    def __init__(self, dish_name: str, timeout: float = 3600.0):
        super().__init__(timeout=timeout)
        self.dish_name = dish_name

    @ui.button(label="Cooked!", style=discord.ButtonStyle.success, emoji="🍳")
    async def mark_cooked(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer()
        for child in self.children:
            child.disabled = True
        self.stop()

        # Deduct recipe/ingredients from Grocy
        consume_error = None
        try:
            res = await execute_tool("recipe_consume_tool", {"recipe": self.dish_name})
            if is_tool_error_output(res):
                consume_error = res
        except Exception as e:
            logger.warning(f"Failed recipe consume: {e}")
            consume_error = str(e)

        embed = interaction.message.embeds[0] if interaction.message.embeds else discord.Embed()
        embed.title = f"🍳 Dinner Cooked: {self.dish_name}"

        if consume_error:
            embed.color = discord.Color.orange()
            embed.set_footer(text=f"⚠️ Marked cooked, but stock deduction failed: {consume_error[:200]}")
            await interaction.message.edit(embed=embed, view=self)
            await interaction.followup.send(
                f"⚠️ Logged **{self.dish_name}** as cooked, but encountered an error deducting stock: {consume_error}",
                ephemeral=True,
            )
        else:
            embed.color = discord.Color.gold()
            embed.set_footer(text=f"✅ Deducted ingredients for '{self.dish_name}' from Grocy stock.")
            await interaction.message.edit(embed=embed, view=self)
            await interaction.followup.send(f"Bon appétit! Logged **{self.dish_name}** as cooked.", ephemeral=True)

    @ui.button(label="Eating Out / Skip", style=discord.ButtonStyle.secondary, emoji="🥡")
    async def skip_dinner(self, interaction: discord.Interaction, button: ui.Button):
        for child in self.children:
            child.disabled = True
        self.stop()

        embed = interaction.message.embeds[0] if interaction.message.embeds else discord.Embed()
        embed.color = discord.Color.light_grey()
        embed.set_footer(
            text="🥡 Meal skipped. Check if any fresh proteins in your fridge need freezing to prevent decay!"
        )

        await interaction.response.edit_message(embed=embed, view=self)

    @ui.button(label="Swap Dinner", style=discord.ButtonStyle.primary, emoji="🔄")
    async def swap_dinner(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer()

        # Ask Gemini to propose a quick alternative based on inventory
        prompt = (
            f"The user wants to swap out tonight's planned meal ('{self.dish_name}'). "
            "Inspect current Fridge and Pantry stock using Grocy tools and propose a fast, delicious "
            "alternative meal under 15 minutes, with brief 4-step assembly instructions."
        )

        try:
            alternative_text = await gemini_kitchen_agent.run_agent_loop(prompt)
            new_embed = discord.Embed(
                title="🔄 Dinner Alternative for Tonight",
                description=alternative_text,
                color=discord.Color.blue(),
            )
            new_embed.set_footer(text="Proposed based on current Grocy stock.")

            new_view = DailyCookView(dish_name="Dinner Alternative")
            await interaction.followup.send(embed=new_embed, view=new_view)
        except Exception as e:
            logger.error(f"Error swapping dinner: {e}", exc_info=True)
            await interaction.followup.send(f"❌ Error generating dinner alternative: {e}", ephemeral=True)
