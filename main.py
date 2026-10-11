"""
Autonomous Kitchen & Meal Planning System - Application Entrypoint.
"""

import asyncio
import logging
import sys

from app.bot.client import bot
from config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("kitchen-agent")


PLACEHOLDERS = {
    "your_grocy_api_key_here",
    "your_gemini_api_key_here",
    "your_discord_bot_token_here",
}


def verify_configuration() -> bool:
    """Check required credentials before starting daemon."""
    missing = []
    if not settings.grocy_api_key or settings.grocy_api_key in PLACEHOLDERS:
        missing.append("GROCY_API_KEY (generate via Grocy: Manage API Keys)")
    if not settings.gemini_api_key or settings.gemini_api_key in PLACEHOLDERS:
        missing.append("GEMINI_API_KEY (get free key from https://aistudio.google.com)")
    if not settings.discord_bot_token or settings.discord_bot_token in PLACEHOLDERS:
        missing.append("DISCORD_BOT_TOKEN (Discord Developer Portal -> Bot -> Token)")

    if missing:
        logger.error("Missing or unconfigured credentials in .env:")
        for item in missing:
            logger.error(f"  • {item}")
        return False
    return True


async def main():
    logger.info("Initializing Autonomous Kitchen Agent Daemon...")

    if not verify_configuration():
        logger.warning(
            "Daemon cannot start until required tokens are configured in .env. "
            "Pacing 30s before exit to prevent tight Docker restart loops..."
        )
        await asyncio.sleep(30)
        sys.exit(1)

    logger.info("Starting Discord bot...")
    try:
        await bot.start(settings.discord_bot_token)
    except Exception as e:
        logger.error(f"Fatal error running Discord bot: {e}", exc_info=True)
    finally:
        if not bot.is_closed():
            await bot.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Shutting down Kitchen Agent Daemon.")
