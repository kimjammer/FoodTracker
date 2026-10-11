"""
Scheduled Job Implementations.
Contains the actual autonomous workflows triggered by APScheduler or manual on-demand execution.
"""

import logging
from datetime import date, timedelta
from typing import Optional

import discord

from app.bot.views import DailyCookView, MealPlanApprovalView
from app.llm.client import gemini_kitchen_agent
from app.scheduler.schedule_manager import schedule_manager
from app.services.calendar_service import calendar_service
from config import settings

logger = logging.getLogger(__name__)


async def get_dispatch_channel(
    bot: discord.Client,
    channel_id: Optional[int] = None,
) -> Optional[discord.abc.Messageable]:
    """
    Find the target Discord channel for automated dispatches.
    Falls back to the first available text channel in the bot's guilds if not explicitly configured.
    """
    target_id = channel_id or settings.discord_channel_id
    if target_id:
        channel = bot.get_channel(target_id)
        if channel:
            return channel
        try:
            channel = await bot.fetch_channel(target_id)
            if channel:
                return channel
        except Exception as e:
            logger.warning(f"Could not fetch channel with ID {target_id}: {e}")

    # Fallback: search for first available writable text channel
    for guild in bot.guilds:
        for channel in guild.text_channels:
            if channel.permissions_for(guild.me).send_messages:
                logger.info(f"Using fallback channel #{channel.name} in guild '{guild.name}'")
                return channel

    logger.error("No valid Discord text channel found to send scheduled dispatch.")
    return None


async def run_saturday_plan_job(bot: discord.Client, channel_id: Optional[int] = None) -> bool:
    """
    Saturday 2:00 PM: Weekly Plan generation & dialogue.
    """
    if not schedule_manager.is_enabled("saturday_plan"):
        logger.info("Skipping saturday_plan job: routine is currently disabled.")
        return False

    channel = await get_dispatch_channel(bot, channel_id)
    if not channel:
        return False

    logger.info("Executing Saturday weekly meal plan routine...")
    try:
        # Check calendar conflicts for next week (next Monday to Sunday)
        today = date.today()
        # Find next Monday
        days_ahead = (0 - today.weekday()) % 7
        if days_ahead == 0:
            days_ahead = 7
        next_monday = today + timedelta(days=days_ahead)
        next_sunday = next_monday + timedelta(days=6)

        calendar_context = await calendar_service.format_conflicts_context(next_monday, next_sunday)

        plan_text = await gemini_kitchen_agent.generate_weekly_meal_plan(
            calendar_context=calendar_context,
        )

        embed = discord.Embed(
            title="🥗 Proposed 7-Day Meal Plan",
            description=plan_text[:4000],
            color=discord.Color.green(),
        )
        embed.set_footer(text="Click 'Approve Plan' or send a message to modify dishes.")
        view = MealPlanApprovalView(plan_summary=plan_text)

        await channel.send(
            content="📢 **Weekly Meal Planning Time!** Here is the proposed dinner plan for next week:",
            embed=embed,
            view=view,
        )
        logger.info("Successfully dispatched Saturday meal plan.")
        return True

    except Exception as e:
        logger.error(f"Error in run_saturday_plan_job: {e}", exc_info=True)
        await channel.send(f"⚠️ Failed to generate weekly meal plan: {e}")
        return False


async def run_sunday_grocery_job(bot: discord.Client, channel_id: Optional[int] = None) -> bool:
    """
    Sunday 9:00 AM: Missing ingredient grocery list compilation.
    """
    if not schedule_manager.is_enabled("sunday_grocery"):
        logger.info("Skipping sunday_grocery job: routine is currently disabled.")
        return False

    channel = await get_dispatch_channel(bot, channel_id)
    if not channel:
        return False

    logger.info("Executing Sunday grocery list routine...")
    try:
        grocery_text = await gemini_kitchen_agent.generate_sunday_grocery_list()

        embed = discord.Embed(
            title="🛒 Sunday Grocery Checklist",
            description=grocery_text[:4000],
            color=discord.Color.orange(),
        )
        embed.set_footer(text="Upload your receipt photo when you're done shopping to update stock automatically!")

        await channel.send(
            content="🛍️ **Sunday Grocery Run!** Here is your consolidated shopping list for this week:",
            embed=embed,
        )
        logger.info("Successfully dispatched Sunday grocery list.")
        return True

    except Exception as e:
        logger.error(f"Error in run_sunday_grocery_job: {e}", exc_info=True)
        await channel.send(f"⚠️ Failed to generate Sunday grocery list: {e}")
        return False


async def run_sunday_prep_job(bot: discord.Client, channel_id: Optional[int] = None) -> bool:
    """
    Sunday 3:00 PM: High-leverage bulk component prep directives.
    """
    if not schedule_manager.is_enabled("sunday_prep"):
        logger.info("Skipping sunday_prep job: routine is currently disabled.")
        return False

    channel = await get_dispatch_channel(bot, channel_id)
    if not channel:
        return False

    logger.info("Executing Sunday component prep routine...")
    try:
        prep_text = await gemini_kitchen_agent.generate_sunday_prep_directives()

        embed = discord.Embed(
            title="🔪 Sunday Bulk Component Prep Directives",
            description=prep_text[:4000],
            color=discord.Color.purple(),
        )
        embed.set_footer(text="Executing these prep tasks ensures weeknight dinners take under 15 minutes!")

        await channel.send(
            content="🍲 **Sunday Prep Time!** Here are high-leverage bulk prep tasks for this afternoon:",
            embed=embed,
        )
        logger.info("Successfully dispatched Sunday prep directives.")
        return True

    except Exception as e:
        logger.error(f"Error in run_sunday_prep_job: {e}", exc_info=True)
        await channel.send(f"⚠️ Failed to generate Sunday prep directives: {e}")
        return False


async def run_daily_morning_job(bot: discord.Client, channel_id: Optional[int] = None) -> bool:
    """
    Daily 8:00 AM: Morning briefing and prerequisite reminders.
    """
    if not schedule_manager.is_enabled("daily_morning"):
        logger.info("Skipping daily_morning job: routine is currently disabled.")
        return False

    channel = await get_dispatch_channel(bot, channel_id)
    if not channel:
        return False

    logger.info("Executing Daily Morning Briefing routine...")
    try:
        briefing_text = await gemini_kitchen_agent.generate_morning_briefing()

        embed = discord.Embed(
            title="☀️ Morning Kitchen Briefing",
            description=briefing_text[:4000],
            color=discord.Color.blue(),
        )

        await channel.send(
            content="🌅 **Good morning!** Here is your daily kitchen briefing:",
            embed=embed,
        )
        logger.info("Successfully dispatched Daily Morning Briefing.")
        return True

    except Exception as e:
        logger.error(f"Error in run_daily_morning_job: {e}", exc_info=True)
        await channel.send(f"⚠️ Failed to generate daily morning briefing: {e}")
        return False


async def run_daily_evening_job(bot: discord.Client, channel_id: Optional[int] = None) -> bool:
    """
    Daily 5:30 PM: Evening execution prompt with quick instructions & interactive buttons.
    """
    if not schedule_manager.is_enabled("daily_evening"):
        logger.info("Skipping daily_evening job: routine is currently disabled.")
        return False

    channel = await get_dispatch_channel(bot, channel_id)
    if not channel:
        return False

    logger.info("Executing Daily Evening Cook Guide routine...")
    try:
        instructions = await gemini_kitchen_agent.generate_evening_dispatch()

        embed = discord.Embed(
            title="🍳 Tonight's Dinner Execution Guide",
            description=instructions[:4000],
            color=discord.Color.gold(),
        )
        embed.set_footer(text="Click 'Cooked' to deduct ingredients, or 'Swap Dinner' for alternatives.")
        view = DailyCookView(dish_name="Tonight's Dinner")

        await channel.send(
            content="🍽️ **Dinner Time!** Here is your 4-step assembly guide for tonight:",
            embed=embed,
            view=view,
        )
        logger.info("Successfully dispatched Daily Evening Cook Guide.")
        return True

    except Exception as e:
        logger.error(f"Error in run_daily_evening_job: {e}", exc_info=True)
        await channel.send(f"⚠️ Failed to generate dinner execution guide: {e}")
        return False


# Map of job id -> execution function
JOB_RUNNERS = {
    "saturday_plan": run_saturday_plan_job,
    "sunday_grocery": run_sunday_grocery_job,
    "sunday_prep": run_sunday_prep_job,
    "daily_morning": run_daily_morning_job,
    "daily_evening": run_daily_evening_job,
}
