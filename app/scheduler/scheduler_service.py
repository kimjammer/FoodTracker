"""
APScheduler lifecycle management service.
Registers and manages the 5 autonomous kitchen routines.
"""

import logging
import zoneinfo
from typing import Optional

import discord
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.scheduler.jobs import JOB_RUNNERS
from app.scheduler.schedule_manager import SCHEDULE_DEFINITIONS, schedule_manager
from config import settings

logger = logging.getLogger(__name__)


class SchedulerService:
    """
    Manages the AsyncIOScheduler instance and lifecycle of automated jobs.
    """

    def __init__(self):
        self._scheduler: Optional[AsyncIOScheduler] = None
        self._bot: Optional[discord.Client] = None

    @property
    def scheduler(self) -> AsyncIOScheduler:
        if self._scheduler is None:
            self._scheduler = AsyncIOScheduler()
        return self._scheduler

    def start(self, bot: discord.Client) -> None:
        """
        Initialize and start the scheduler with all defined routines.
        """
        self._bot = bot
        try:
            tz = zoneinfo.ZoneInfo(settings.timezone)
        except Exception as e:
            logger.warning(f"Invalid timezone '{settings.timezone}': {e}. Falling back to UTC.")
            tz = zoneinfo.ZoneInfo("UTC")

        if not self.scheduler.running:
            self.scheduler.start()
            logger.info("APScheduler started successfully.")

        # Register jobs
        for job_id, meta in SCHEDULE_DEFINITIONS.items():
            runner = JOB_RUNNERS.get(job_id)
            if not runner:
                continue

            # Bind runner with default parameter to avoid late-binding closure bug
            async def make_job_wrapper(r=runner):
                if self._bot:
                    await r(self._bot)

            trigger = CronTrigger.from_crontab(meta.cron, timezone=tz)
            job = self.scheduler.add_job(
                make_job_wrapper,
                trigger=trigger,
                id=job_id,
                name=meta.name,
                replace_existing=True,
            )

            # Pause if disabled in state
            if not schedule_manager.is_enabled(job_id):
                job.pause()
                logger.info(f"Registered job '{job_id}' (PAUSED).")
            else:
                next_run = getattr(job, "next_run_time", None)
                logger.info(f"Registered job '{job_id}' ({meta.schedule_display}, next: {next_run}).")

    def shutdown(self) -> None:
        """Gracefully shut down scheduler."""
        if self._scheduler and self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            logger.info("APScheduler shut down.")

    def sync_job_state(self, job_id: str) -> None:
        """Sync APScheduler job pause/resume state with schedule_manager."""
        if not self._scheduler:
            return
        job = self.scheduler.get_job(job_id)
        if not job:
            return

        if schedule_manager.is_enabled(job_id):
            job.resume()
            logger.info(f"Resumed job '{job_id}' (next run: {job.next_run_time}).")
        else:
            job.pause()
            logger.info(f"Paused job '{job_id}'.")

    async def trigger_now(
        self,
        job_id: str,
        bot: Optional[discord.Client] = None,
        channel_id: Optional[int] = None,
    ) -> bool:
        """Manually trigger a job immediately for testing or on-demand execution."""
        runner = JOB_RUNNERS.get(job_id)
        target_bot = bot or self._bot
        if not runner or not target_bot:
            logger.error(f"Cannot trigger job '{job_id}': runner or bot not found.")
            return False

        return await runner(target_bot, channel_id=channel_id)

    def get_job_next_run(self, job_id: str) -> Optional[str]:
        """Return human-readable next run time for a job."""
        if not self._scheduler:
            return None
        job = self.scheduler.get_job(job_id)
        if job:
            next_run = getattr(job, "next_run_time", None)
            if next_run:
                return next_run.strftime("%a %b %d, %I:%M %p")
        return None


scheduler_service = SchedulerService()
