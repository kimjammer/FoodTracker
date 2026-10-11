"""
Persistent User Profile and Culinary Preferences Service.
Stores user dietary preferences, favorite cuisines, and cooking constraints
in a local JSON file without hardcoding user data into application code.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

DEFAULT_PROFILE_FILE = Path("data/user_profile.json")

# Soft length guideline: Recommend staying under ~1000 characters (~150-200 words).
# Hard upper limit: 2000 characters to prevent excessive context window consumption.
RECOMMENDED_MAX_CHARS = 1000
HARD_MAX_CHARS = 2000


class UserProfileService:
    """
    Manages persistent storage and retrieval of user culinary profiles and preferences.
    """

    def __init__(self, file_path: Optional[Path] = None):
        self.file_path = file_path or DEFAULT_PROFILE_FILE

    def get_profile(self) -> str:
        """
        Retrieve the current user profile text.
        Returns empty string if no profile is saved.
        """
        if not self.file_path.exists():
            return ""

        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("profile", "").strip()
        except Exception as e:
            logger.warning(f"Failed to read user profile from {self.file_path}: {e}")
            return ""

    def get_profile_metadata(self) -> Dict[str, Any]:
        """
        Retrieve the profile text along with metadata (updated timestamp, character length).
        """
        if not self.file_path.exists():
            return {"profile": "", "length": 0, "updated_at": None}

        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                profile = data.get("profile", "").strip()
                return {
                    "profile": profile,
                    "length": len(profile),
                    "updated_at": data.get("updated_at"),
                }
        except Exception as e:
            logger.warning(f"Failed to read profile metadata from {self.file_path}: {e}")
            return {"profile": "", "length": 0, "updated_at": None}

    def set_profile(self, profile_text: str) -> Dict[str, Any]:
        """
        Save an updated user profile.
        Softly enforces length guidelines (recommends <= 1000 chars, rejects > 2000 chars).

        Returns:
            Dict containing 'profile', 'length', and optional 'warning' if exceeding recommended length.
        Raises:
            ValueError: If profile exceeds hard limit of 2000 characters.
        """
        clean_text = profile_text.strip()
        length = len(clean_text)

        if length > HARD_MAX_CHARS:
            raise ValueError(
                f"Profile length ({length} characters) exceeds the maximum limit of {HARD_MAX_CHARS} characters. "
                f"Please condense your preferences to under {RECOMMENDED_MAX_CHARS} characters."
            )

        warning: Optional[str] = None
        if length > RECOMMENDED_MAX_CHARS:
            warning = (
                f"Profile is {length} characters, which exceeds the recommended guideline of "
                f"{RECOMMENDED_MAX_CHARS} characters. For optimal AI performance, consider keeping it concise."
            )

        data = {
            "profile": clean_text,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

        try:
            self.file_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            logger.info(f"User profile saved successfully ({length} chars) to {self.file_path}")
        except Exception as e:
            logger.error(f"Failed to save user profile to {self.file_path}: {e}")
            raise

        return {
            "profile": clean_text,
            "length": length,
            "warning": warning,
        }

    def clear_profile(self) -> None:
        """Clear the user profile."""
        if self.file_path.exists():
            try:
                self.file_path.unlink()
                logger.info(f"User profile removed at {self.file_path}")
            except Exception as e:
                logger.error(f"Failed to delete {self.file_path}: {e}")
                raise


user_profile_service = UserProfileService()
