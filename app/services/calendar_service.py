"""
Google Calendar read-only integration service.
Fetches evening calendar events to detect dinner conflicts.
Gracefully degrades if credentials are not configured.
"""

import json
import logging
import urllib.parse
from datetime import date, datetime, time
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from config import settings

logger = logging.getLogger(__name__)


class CalendarService:
    """
    Read-only Google Calendar client for detecting dinner-hour schedule conflicts.
    """

    def __init__(self, credentials_path: Optional[str] = None):
        self._custom_path = credentials_path

    @property
    def credentials_path(self) -> Path:
        return Path(self._custom_path or settings.google_calendar_credentials_path or "credentials.json")

    def is_configured(self) -> bool:
        """Check if a non-empty credentials file exists."""
        p = self.credentials_path
        return p.is_file() and p.stat().st_size > 0

    async def get_dinner_conflicts(
        self,
        start_date: date,
        end_date: date,
        dinner_hours: tuple[int, int] = (17, 21),
    ) -> List[Dict[str, Any]]:
        """
        Fetch events from Google Calendar between start_date and end_date that overlap
        with dinner hours (default: 5:00 PM - 9:00 PM).
        Returns a list of conflict dicts: [{'summary': ..., 'start': ..., 'end': ...}].
        """
        if not self.is_configured():
            logger.debug(f"Google Calendar credentials not found at {self.credentials_path}. Skipping conflict checks.")
            return []

        try:
            from google.auth.transport.requests import Request
            from google.oauth2 import service_account

            scopes = ["https://www.googleapis.com/auth/calendar.readonly"]
            with open(self.credentials_path, "r", encoding="utf-8") as f:
                cred_data = json.load(f)

            if cred_data.get("type") == "service_account":
                creds = service_account.Credentials.from_service_account_file(str(self.credentials_path), scopes=scopes)
                creds.refresh(Request())
                token = creds.token
            else:
                logger.warning(f"Unsupported credentials type in {self.credentials_path}. Expected 'service_account'.")
                return []

            # Query Google Calendar REST API
            calendar_id = settings.google_calendar_id or "primary"
            encoded_id = urllib.parse.quote(calendar_id, safe="")
            time_min = datetime.combine(start_date, time.min).isoformat() + "Z"
            time_max = datetime.combine(end_date, time.max).isoformat() + "Z"
            url = f"https://www.googleapis.com/calendar/v3/calendars/{encoded_id}/events"
            params = {
                "timeMin": time_min,
                "timeMax": time_max,
                "singleEvents": "true",
                "orderBy": "startTime",
            }
            headers = {"Authorization": f"Bearer {token}"}

            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(url, params=params, headers=headers)
                resp.raise_for_status()
                data = resp.json()

            conflicts = []
            for item in data.get("items", []):
                summary = item.get("summary", "Busy")
                start_raw = item.get("start", {}).get("dateTime")
                end_raw = item.get("end", {}).get("dateTime")
                if not start_raw:
                    continue  # Skip all-day events without specific hour bounds

                start_dt = datetime.fromisoformat(start_raw)
                event_hour = start_dt.hour
                if dinner_hours[0] <= event_hour < dinner_hours[1]:
                    conflicts.append(
                        {
                            "summary": summary,
                            "start": start_raw,
                            "end": end_raw,
                            "date": str(start_dt.date()),
                            "day_name": start_dt.strftime("%A"),
                        }
                    )

            return conflicts

        except Exception as e:
            logger.warning(f"Error checking Google Calendar conflicts: {e}")
            return []

    async def format_conflicts_context(self, start_date: date, end_date: date) -> str:
        """Format conflicts into natural language context for Gemini."""
        conflicts = await self.get_dinner_conflicts(start_date, end_date)
        if not conflicts:
            return "No evening calendar conflicts detected."

        lines = ["Evening calendar commitments:"]
        for c in conflicts:
            lines.append(f"- {c['day_name']} ({c['date']}): {c['summary']} (Event between 5 PM - 9 PM)")
        return "\n".join(lines)

    async def check_status(self) -> str:
        """
        Check connectivity to Google Calendar.
        Returns a human-readable status string for the /status command.
        """
        if not self.is_configured():
            return "⚠️ Not configured (credentials.json not found)"

        try:
            from google.auth.transport.requests import Request
            from google.oauth2 import service_account

            scopes = ["https://www.googleapis.com/auth/calendar.readonly"]
            with open(self.credentials_path, "r", encoding="utf-8") as f:
                cred_data = json.load(f)

            if cred_data.get("type") != "service_account":
                return f"❌ Unsupported credentials type: '{cred_data.get('type')}'"

            creds = service_account.Credentials.from_service_account_file(str(self.credentials_path), scopes=scopes)
            creds.refresh(Request())
            token = creds.token

            calendar_id = settings.google_calendar_id or "primary"
            encoded_id = urllib.parse.quote(calendar_id, safe="")
            url = f"https://www.googleapis.com/calendar/v3/calendars/{encoded_id}"
            headers = {"Authorization": f"Bearer {token}"}

            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(url, headers=headers)
                if resp.status_code == 200:
                    cal_data = resp.json()
                    cal_summary = cal_data.get("summary", calendar_id)
                    return f"✅ Connected ('{cal_summary}')"
                elif resp.status_code == 404:
                    return f"❌ Calendar '{calendar_id}' not found or not shared with service account"
                elif resp.status_code == 403:
                    return f"❌ Permission denied for calendar '{calendar_id}'"
                else:
                    return f"❌ Calendar API error (HTTP {resp.status_code})"
        except Exception as e:
            return f"❌ Calendar connection error: {e}"


calendar_service = CalendarService()
