"""
Schedule Manager: Handles job definitions, enabled/disabled state, and persistence.
Allows routines to be toggled on and off via Discord.
"""

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

DEFAULT_STATE_FILE = Path("data/schedules_state.json")


@dataclass
class JobMetadata:
    id: str
    name: str
    description: str
    cron: str
    schedule_display: str
    emoji: str


SCHEDULE_DEFINITIONS: Dict[str, JobMetadata] = {
    "saturday_plan": JobMetadata(
        id="saturday_plan",
        name="Weekly Meal Plan",
        description="7-day dinner plan with interactive approval buttons",
        cron="0 14 * * sat",
        schedule_display="Saturdays at 2:00 PM",
        emoji="🥗",
    ),
    "sunday_grocery": JobMetadata(
        id="sunday_grocery",
        name="Sunday Grocery List",
        description="Aisle-categorized grocery checklist for missing items & low staples",
        cron="0 9 * * sun",
        schedule_display="Sundays at 9:00 AM",
        emoji="🛒",
    ),
    "sunday_prep": JobMetadata(
        id="sunday_prep",
        name="Sunday Bulk Prep",
        description="Batch prep tasks (meats, grains, marinades) for <15m weeknight dinners",
        cron="0 15 * * sun",
        schedule_display="Sundays at 3:00 PM",
        emoji="🔪",
    ),
    "daily_morning": JobMetadata(
        id="daily_morning",
        name="Morning Briefing",
        description="Daily dinner alert & advance prep tasks (e.g. thawing proteins)",
        cron="0 8 * * *",
        schedule_display="Daily at 8:00 AM",
        emoji="☀️",
    ),
    "daily_evening": JobMetadata(
        id="daily_evening",
        name="Dinner Cook Guide",
        description="4-step rapid assembly instructions with [Cooked] & [Swap] buttons",
        cron="30 17 * * *",
        schedule_display="Daily at 5:30 PM",
        emoji="🍳",
    ),
}


class ScheduleManager:
    """
    Manages the enabled state of scheduled routines and persists state across reboots.
    """

    def __init__(self, state_file: Optional[Path] = None):
        self.state_file = state_file or DEFAULT_STATE_FILE
        self._state: Dict[str, bool] = {}
        self._load_state()

    def _load_state(self) -> None:
        """Load enabled states from persistence file; defaults to all enabled."""
        if self.state_file.is_file():
            try:
                with open(self.state_file, "r", encoding="utf-8") as f:
                    self._state = json.load(f)
            except Exception as e:
                logger.warning(f"Failed to read {self.state_file}: {e}. Initializing default state.")
                self._state = {}
        else:
            self._state = {}

        # Ensure all defined jobs exist in state (default to True)
        changed = False
        for job_id in SCHEDULE_DEFINITIONS:
            if job_id not in self._state:
                self._state[job_id] = True
                changed = True

        if changed:
            self._save_state()

    def _save_state(self) -> None:
        """Persist state to disk."""
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.state_file, "w", encoding="utf-8") as f:
                json.dump(self._state, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save schedule state to {self.state_file}: {e}")

    def is_enabled(self, job_id: str) -> bool:
        """Check if a routine is enabled."""
        return self._state.get(job_id, True)

    def set_enabled(self, job_id: str, enabled: bool) -> bool:
        """Set enabled status of a routine. Returns new status."""
        if job_id not in SCHEDULE_DEFINITIONS:
            raise KeyError(f"Unknown schedule job ID: {job_id}")
        self._state[job_id] = enabled
        self._save_state()
        return enabled

    def toggle(self, job_id: str) -> bool:
        """Toggle enabled status of a routine. Returns new status."""
        current = self.is_enabled(job_id)
        return self.set_enabled(job_id, not current)

    def set_all(self, enabled: bool) -> None:
        """Enable or disable all routines at once."""
        for job_id in SCHEDULE_DEFINITIONS:
            self._state[job_id] = enabled
        self._save_state()

    def get_job_info(self, job_id: str) -> Dict[str, Any]:
        """Get full status and metadata for a single routine."""
        meta = SCHEDULE_DEFINITIONS[job_id]
        enabled = self.is_enabled(job_id)
        return {
            "id": meta.id,
            "name": meta.name,
            "description": meta.description,
            "cron": meta.cron,
            "schedule_display": meta.schedule_display,
            "emoji": meta.emoji,
            "enabled": enabled,
            "status_str": "🟢 Enabled" if enabled else "🔴 Disabled",
        }

    def get_all_jobs_info(self) -> List[Dict[str, Any]]:
        """Get status and metadata for all defined routines."""
        return [self.get_job_info(job_id) for job_id in SCHEDULE_DEFINITIONS]


schedule_manager = ScheduleManager()
