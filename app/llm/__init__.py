"""Gemini LLM Package."""

from app.llm.client import GeminiKitchenAgent, gemini_kitchen_agent
from app.llm.prompts import (
    DAILY_DISPATCH_PROMPT,
    IMAGE_INTAKE_PROMPT,
    KITCHEN_ASSISTANT_SYSTEM_PROMPT,
    MEAL_PLANNER_SYSTEM_PROMPT,
    MORNING_BRIEFING_PROMPT,
    RECEIPT_PARSER_PROMPT,
)
from app.llm.tools import execute_tool, get_gemini_tools

__all__ = [
    "GeminiKitchenAgent",
    "gemini_kitchen_agent",
    "KITCHEN_ASSISTANT_SYSTEM_PROMPT",
    "IMAGE_INTAKE_PROMPT",
    "MEAL_PLANNER_SYSTEM_PROMPT",
    "RECEIPT_PARSER_PROMPT",
    "DAILY_DISPATCH_PROMPT",
    "MORNING_BRIEFING_PROMPT",
    "get_gemini_tools",
    "execute_tool",
]
