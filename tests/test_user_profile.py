"""
Unit tests for Persistent User Profile and Preferences feature.
Tests profile service, LLM tools, agent prompt injection, and Discord commands.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.llm.client import GeminiKitchenAgent
from app.llm.prompts import GROCERY_LIST_PROMPT, KITCHEN_ASSISTANT_SYSTEM_PROMPT
from app.llm.tools import execute_tool, get_gemini_tools
from app.services.profile_service import (
    HARD_MAX_CHARS,
    RECOMMENDED_MAX_CHARS,
    UserProfileService,
)


@pytest.fixture
def temp_profile_service(tmp_path):
    """Fixture providing an isolated UserProfileService using a temporary file."""
    profile_path = tmp_path / "user_profile.json"
    return UserProfileService(file_path=profile_path)


def test_profile_service_empty_on_init(temp_profile_service):
    """Test that a fresh profile service returns empty string when no file exists."""
    assert temp_profile_service.get_profile() == ""
    meta = temp_profile_service.get_profile_metadata()
    assert meta["profile"] == ""
    assert meta["length"] == 0
    assert meta["updated_at"] is None


def test_profile_service_set_and_get(temp_profile_service):
    """Test saving and retrieving user preferences."""
    sample_text = "The user enjoys Korean home cooking and Japanese ramen. Spicy and savory."
    result = temp_profile_service.set_profile(sample_text)

    assert result["profile"] == sample_text
    assert result["length"] == len(sample_text)
    assert result["warning"] is None

    assert temp_profile_service.get_profile() == sample_text
    meta = temp_profile_service.get_profile_metadata()
    assert meta["profile"] == sample_text
    assert meta["length"] == len(sample_text)
    assert meta["updated_at"] is not None


def test_profile_service_soft_limit_warning(temp_profile_service):
    """Test that text between RECOMMENDED_MAX_CHARS (1000) and HARD_MAX_CHARS (2000) triggers a warning."""
    long_text = "A" * 1200
    result = temp_profile_service.set_profile(long_text)

    assert result["profile"] == long_text
    assert result["length"] == 1200
    assert result["warning"] is not None
    assert f"{RECOMMENDED_MAX_CHARS}" in result["warning"]
    assert temp_profile_service.get_profile() == long_text


def test_profile_service_hard_limit_rejection(temp_profile_service):
    """Test that text exceeding HARD_MAX_CHARS (2000) raises ValueError."""
    too_long = "B" * 2500
    with pytest.raises(ValueError) as exc_info:
        temp_profile_service.set_profile(too_long)

    assert f"{HARD_MAX_CHARS}" in str(exc_info.value)
    assert temp_profile_service.get_profile() == ""


def test_profile_service_clear(temp_profile_service):
    """Test clearing the profile removes the file."""
    temp_profile_service.set_profile("Loves kimchi stew")
    assert temp_profile_service.get_profile() == "Loves kimchi stew"

    temp_profile_service.clear_profile()
    assert temp_profile_service.get_profile() == ""


@pytest.mark.asyncio
async def test_tools_include_user_profile():
    """Verify user_profile_get_tool and user_profile_update_tool are declared in Gemini tools."""
    with patch("app.services.mcp_client.grocy_mcp_service.list_tools", new_callable=AsyncMock) as mock_mcp:
        mock_mcp.return_value = []
        gemini_tool = await get_gemini_tools()

        decl_names = [d.name for d in gemini_tool.function_declarations]
        assert "user_profile_get_tool" in decl_names
        assert "user_profile_update_tool" in decl_names


@pytest.mark.asyncio
async def test_execute_tool_profile_workflow(tmp_path):
    """Test executing user_profile_get_tool and user_profile_update_tool via execute_tool."""
    test_svc = UserProfileService(file_path=tmp_path / "test_exec_profile.json")
    with patch("app.llm.tools.user_profile_service", test_svc):
        # 1. Initial state
        get_res = await execute_tool("user_profile_get_tool", {})
        assert "No user culinary profile is currently set" in get_res

        # 2. Update profile
        update_res = await execute_tool(
            "user_profile_update_tool",
            {"profile": "Prefers quick 15-minute Korean banchan and stews."},
        )
        assert "User profile successfully updated" in update_res
        assert "49 characters" in update_res

        # 3. Read updated profile
        get_res_after = await execute_tool("user_profile_get_tool", {})
        assert get_res_after == "Prefers quick 15-minute Korean banchan and stews."

        # 4. Error on empty profile
        empty_res = await execute_tool("user_profile_update_tool", {"profile": ""})
        assert "cannot be empty" in empty_res

        # 5. Error on over-limit profile
        overflow_res = await execute_tool("user_profile_update_tool", {"profile": "Z" * 2500})
        assert "Error updating profile" in overflow_res


@pytest.mark.asyncio
async def test_meal_planner_injects_user_profile():
    """Verify that generate_weekly_meal_plan automatically injects user profile into context."""
    agent = GeminiKitchenAgent(api_key="fake-key")

    mock_profile_svc = MagicMock()
    mock_profile_svc.get_profile.return_value = "Enjoys bold Korean and Japanese dishes, adventurous eater."

    with (
        patch("app.llm.client.user_profile_service", mock_profile_svc),
        patch.object(agent, "run_agent_loop", new_callable=AsyncMock) as mock_loop,
    ):
        mock_loop.return_value = "Week Meal Plan"

        await agent.generate_weekly_meal_plan(user_feedback="More tofu")

        mock_loop.assert_called_once()
        sent_prompt = mock_loop.call_args[0][0]
        assert "User Culinary Profile & Preferences:" in sent_prompt
        assert "Enjoys bold Korean and Japanese dishes, adventurous eater." in sent_prompt
        assert "User Preferences / Revision Notes:\nMore tofu" in sent_prompt


@pytest.mark.asyncio
async def test_grocery_list_does_not_inject_user_profile():
    """Verify that grocery list organizer does NOT inject user profile."""
    agent = GeminiKitchenAgent(api_key="fake-key")

    mock_profile_svc = MagicMock()
    mock_profile_svc.get_profile.return_value = "User Profile Secret Information"

    with (
        patch("app.llm.client.user_profile_service", mock_profile_svc),
        patch.object(agent, "run_agent_loop", new_callable=AsyncMock) as mock_loop,
    ):
        mock_loop.return_value = "Grocery List"

        await agent.generate_sunday_grocery_list()

        mock_loop.assert_called_once()
        sent_prompt = mock_loop.call_args[0][0]
        sent_sys_instruction = mock_loop.call_args[1]["system_instruction"]
        # Profile should not be present in prompt or system instruction
        assert "User Profile Secret Information" not in sent_prompt
        assert sent_sys_instruction == GROCERY_LIST_PROMPT


@pytest.mark.asyncio
async def test_run_agent_loop_injects_profile_for_kitchen_assistant():
    """Verify that run_agent_loop injects profile into system instruction for KITCHEN_ASSISTANT_SYSTEM_PROMPT."""
    agent = GeminiKitchenAgent(api_key="fake-key")

    mock_profile_svc = MagicMock()
    mock_profile_svc.get_profile.return_value = "Korean staples & quick weeknight meals."

    mock_response = MagicMock()
    mock_response.function_calls = None
    mock_response.text = "Hello! I know you enjoy Korean staples."

    mock_chat = MagicMock()
    mock_chat.send_message = AsyncMock(return_value=mock_response)

    with (
        patch("app.llm.client.user_profile_service", mock_profile_svc),
        patch("app.llm.client.get_gemini_tools", new_callable=AsyncMock) as mock_tools,
        patch("app.llm.client.rate_limiter.execute_with_retry", new_callable=AsyncMock) as mock_rate,
        patch.object(agent, "_client") as mock_client,
    ):
        mock_tools.return_value = MagicMock()
        mock_client.aio.chats.create.return_value = mock_chat
        mock_rate.return_value = mock_response

        reply = await agent.run_agent_loop(
            prompt="What should I make tonight?",
            system_instruction=KITCHEN_ASSISTANT_SYSTEM_PROMPT,
        )

        assert "Hello!" in reply
        # Check config passed to create chat
        create_kwargs = mock_client.aio.chats.create.call_args[1]
        config = create_kwargs["config"]
        assert "Current User Culinary Profile:" in config.system_instruction
        assert "Korean staples & quick weeknight meals." in config.system_instruction
