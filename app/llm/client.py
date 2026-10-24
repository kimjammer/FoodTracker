"""
Gemini 3.5 Flash Lite LLM Client with autonomous Grocy MCP Tool Calling,
Token-bucket rate limiting, and Exponential Backoff.
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional

from google import genai
from google.genai import types

from app.llm.prompts import (
    DAILY_DISPATCH_PROMPT,
    GROCERY_LIST_PROMPT,
    IMAGE_INTAKE_PROMPT,
    KITCHEN_ASSISTANT_SYSTEM_PROMPT,
    MEAL_PLANNER_SYSTEM_PROMPT,
    MORNING_BRIEFING_PROMPT,
    SUNDAY_PREP_PROMPT,
)
from app.llm.rate_limiter import rate_limiter
from app.llm.tools import execute_tool, get_gemini_tools, is_tool_error_output
from app.services.profile_service import user_profile_service
from config import settings

logger = logging.getLogger(__name__)


class GeminiKitchenAgent:
    """
    Autonomous Kitchen Agent powered by Google Gemini 3.5 Flash Lite and Grocy MCP tools.
    Equipped with sliding-window pacing and exponential backoff retry.
    """

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        self.api_key = api_key or settings.gemini_api_key
        self.model = model or settings.gemini_model
        self._client: Optional[genai.Client] = None

    @property
    def client(self) -> genai.Client:
        if not self._client:
            if not self.api_key:
                raise ValueError("GEMINI_API_KEY is not configured. Please add your key to .env")
            self._client = genai.Client(api_key=self.api_key)
        return self._client

    async def run_agent_loop(
        self,
        prompt: str,
        system_instruction: str = KITCHEN_ASSISTANT_SYSTEM_PROMPT,
        max_turns: int = 15,
        on_rate_limit: Optional[Callable[[int, float], Any]] = None,
        history: Optional[List[types.Content]] = None,
    ) -> str:
        """
        Execute an autonomous multi-turn tool calling loop with Gemini and Grocy MCP.
        Supports up to 15 turns with rate-limit pacing, exponential backoff, and thread history.
        """
        tools = [await get_gemini_tools()]

        # Automatically inject user profile for general kitchen assistant conversations
        effective_system_instruction = system_instruction
        if system_instruction == KITCHEN_ASSISTANT_SYSTEM_PROMPT:
            profile = user_profile_service.get_profile()
            if profile:
                effective_system_instruction = f"{system_instruction}\n\nCurrent User Culinary Profile:\n{profile}"

        config = types.GenerateContentConfig(
            system_instruction=effective_system_instruction,
            temperature=0.3,
            tools=tools,
        )

        chat = self.client.aio.chats.create(model=self.model, config=config, history=history)

        # Initial prompt dispatch wrapped with rate limiter and backoff
        response = await rate_limiter.execute_with_retry(
            chat.send_message,
            prompt,
            on_rate_limit=on_rate_limit,
        )

        turns = 0
        unresolved_errors: Dict[str, str] = {}
        while turns < max_turns:
            turns += 1
            # Check if Gemini requested any tool/function calls
            function_calls = response.function_calls
            if not function_calls:
                break

            # Execute all requested function calls via Grocy MCP
            tool_responses: List[types.Part] = []
            for call in function_calls:
                tool_name = call.name
                tool_args = call.args or {}
                logger.info(f"Executing Grocy MCP tool: {tool_name}({tool_args})")
                try:
                    tool_output = await execute_tool(tool_name, tool_args)
                except Exception as e:
                    logger.error(f"Error executing {tool_name}: {e}")
                    tool_output = f"Error executing tool {tool_name}: {e}"

                if is_tool_error_output(tool_output):
                    unresolved_errors[tool_name] = tool_output
                else:
                    unresolved_errors.pop(tool_name, None)

                tool_responses.append(
                    types.Part.from_function_response(
                        name=tool_name,
                        response={"result": tool_output},
                    )
                )

            # Send tool outputs back to Gemini with rate limiter and backoff
            response = await rate_limiter.execute_with_retry(
                chat.send_message,
                tool_responses,
                on_rate_limit=on_rate_limit,
            )

        final_text = (response.text or "").strip()
        if not final_text:
            if unresolved_errors:
                err_lines = "\n".join(f"• `{k}`: {v}" for k, v in unresolved_errors.items())
                return f"⚠️ **An error occurred while processing your request:**\n{err_lines}"
            if turns >= max_turns and getattr(response, "function_calls", None):
                return "⚠️ **Error:** Reached the maximum number of tool execution steps before completing the response."
            return "I completed the request."

        if unresolved_errors:
            lower_text = final_text.lower()
            has_error_mention = any(
                token in lower_text for token in ("error", "failed", "could not", "unable to", "not found")
            )
            has_error_badge = "⚠️" in final_text or "❌" in final_text
            if not has_error_mention and not has_error_badge:
                err_lines = "\n".join(f"• {v}" for v in unresolved_errors.values())
                final_text = f"{final_text}\n\n⚠️ **Warning — An error occurred during execution:**\n{err_lines}"
            elif not has_error_badge:
                final_text = f"⚠️ {final_text}"

        return final_text

    async def parse_grocery_image(
        self,
        image_bytes: bytes,
        mime_type: str = "image/jpeg",
        on_rate_limit: Optional[Callable[[int, float], Any]] = None,
    ) -> Dict[str, Any]:
        """
        Multimodal computer vision pipeline to parse a grocery receipt or countertop food photo into structured JSON.
        """
        image_part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
        config = types.GenerateContentConfig(
            system_instruction=IMAGE_INTAKE_PROMPT,
            temperature=0.1,
            response_mime_type="application/json",
        )

        response = await rate_limiter.execute_with_retry(
            self.client.aio.models.generate_content,
            model=self.model,
            contents=[
                image_part,
                "Analyze this image. If it is a receipt or grocery haul photo, extract all food and grocery items.",
            ],
            config=config,
            on_rate_limit=on_rate_limit,
        )

        text = response.text or "{}"
        try:
            parsed = json.loads(text)
            if "items" not in parsed:
                parsed["items"] = []
            if "image_type" not in parsed:
                parsed["image_type"] = "receipt" if "store_name" in parsed else "grocery_haul"
            return parsed
        except json.JSONDecodeError as e:
            logger.error(f"Failed to decode grocery image JSON: {e}. Raw: {text}")
            return {
                "image_type": "error",
                "title": "Scan Error",
                "summary": "Could not parse image data.",
                "items": [],
                "error": str(e),
            }

    # Backward compatibility alias
    parse_receipt_image = parse_grocery_image

    async def ingest_receipt_items(
        self,
        items: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        Batch add parsed receipt items directly to Grocy inventory via Grocy tool bridge.
        Automatically creates missing products with their inferred locations and units.
        Runs locally against Grocy (consumes 0 Gemini API rate limit).
        """
        results = []
        for item in items:
            name = item.get("name")
            qty = float(item.get("quantity", 1.0))
            if not name:
                continue
            tool_args: Dict[str, Any] = {"product": name, "amount": qty}
            if item.get("unit"):
                tool_args["unit"] = item["unit"]
            if item.get("location"):
                tool_args["location"] = item["location"]
            if item.get("alternate_names"):
                tool_args["alternate_names"] = item["alternate_names"]
            try:
                res = await execute_tool("stock_add_tool", tool_args)
                if is_tool_error_output(res):
                    results.append({"name": name, "quantity": qty, "status": "error", "detail": res})
                else:
                    results.append({"name": name, "quantity": qty, "status": "success", "detail": res})
            except Exception as e:
                results.append({"name": name, "quantity": qty, "status": "error", "detail": str(e)})
        return results

    async def generate_weekly_meal_plan(
        self,
        user_feedback: Optional[str] = None,
        calendar_context: Optional[str] = None,
        on_rate_limit: Optional[Callable[[int, float], Any]] = None,
    ) -> str:
        """
        Autonomously query inventory and meal history, factoring in calendar conflicts,
        to produce a balanced 7-day meal plan.
        """
        today = datetime.now().date()
        days_ahead = 7 - today.weekday()
        start_date = today + timedelta(days=days_ahead)
        end_date = start_date + timedelta(days=6)

        context_parts = [
            (
                f"Please generate and record the 7-day dinner meal plan for next week "
                f"({start_date.isoformat()} Monday through {end_date.isoformat()} Sunday)."
            ),
            "1. Check current inventory and expiring stock using Grocy tools.",
            "2. Check existing recipes and past meal plans to ensure variety.",
            (
                "3. For each day (Monday through Sunday), call `meal_plan_add_tool` to record the meal in Grocy "
                "with its date (YYYY-MM-DD) and recipe name (or note)."
            ),
            (
                "4. Call `meal_plan_shopping_tool` or `shopping_list_add_missing_tool` to queue missing ingredients "
                "onto the shopping list."
            ),
        ]
        if calendar_context:
            context_parts.append(f"Calendar Evening Commitments:\n{calendar_context}")
        profile = user_profile_service.get_profile()
        if profile:
            context_parts.append(f"User Culinary Profile & Preferences:\n{profile}")
        if user_feedback:
            context_parts.append(f"User Preferences / Revision Notes:\n{user_feedback}")

        prompt = "\n".join(context_parts)
        return await self.run_agent_loop(
            prompt,
            system_instruction=MEAL_PLANNER_SYSTEM_PROMPT,
            on_rate_limit=on_rate_limit,
        )

    async def generate_morning_briefing(
        self,
        on_rate_limit: Optional[Callable[[int, float], Any]] = None,
    ) -> str:
        """
        Generate the 8:00 AM daily briefing identifying today's menu and prep steps.
        """
        prompt = (
            "Check today's meal plan in Grocy. If a dish is scheduled, inspect its ingredients "
            "and alert the user to any advance preparation needed today (such as thawing frozen proteins)."
        )
        return await self.run_agent_loop(
            prompt,
            system_instruction=MORNING_BRIEFING_PROMPT,
            on_rate_limit=on_rate_limit,
        )

    async def generate_evening_dispatch(
        self,
        dish_name: Optional[str] = None,
        on_rate_limit: Optional[Callable[[int, float], Any]] = None,
    ) -> str:
        """
        Generate the 5:30 PM rapid 4-step assembly instructions for dinner.
        """
        dish_info = f"for '{dish_name}'" if dish_name else "for tonight's dinner scheduled in Grocy"
        prompt = (
            f"Provide a 4-step assembly guide {dish_info}. Ensure the instructions take under "
            "15 minutes active cooking time and specify all ingredients needed."
        )
        return await self.run_agent_loop(
            prompt,
            system_instruction=DAILY_DISPATCH_PROMPT,
            on_rate_limit=on_rate_limit,
        )

    async def generate_sunday_grocery_list(
        self,
        on_rate_limit: Optional[Callable[[int, float], Any]] = None,
    ) -> str:
        """
        Generate the Sunday 9:00 AM consolidated grocery checklist for planned meals & staples.
        """
        prompt = (
            "Check the current meal plan in Grocy and identify all missing ingredients needed for the week. "
            "Also check if any staples or products are below minimum stock. "
            "Organize them into an aisle-categorized grocery checklist."
        )
        return await self.run_agent_loop(
            prompt,
            system_instruction=GROCERY_LIST_PROMPT,
            on_rate_limit=on_rate_limit,
        )

    async def generate_sunday_prep_directives(
        self,
        on_rate_limit: Optional[Callable[[int, float], Any]] = None,
    ) -> str:
        """
        Generate the Sunday 3:00 PM bulk component prep tasks.
        """
        prompt = (
            "Review the upcoming 7-day meal plan and recipes in Grocy. "
            "Identify high-leverage bulk prep steps to execute this afternoon (portion & freeze proteins, "
            "batch cook base grains, prepare multi-use sauces) so weeknight dinners take under 15 minutes."
        )
        return await self.run_agent_loop(
            prompt,
            system_instruction=SUNDAY_PREP_PROMPT,
            on_rate_limit=on_rate_limit,
        )


gemini_kitchen_agent = GeminiKitchenAgent()
