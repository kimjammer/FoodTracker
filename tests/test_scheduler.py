"""
Unit tests for Milestone 5: APScheduler integration, toggleable routines, and calendar service.
"""

import asyncio
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from app.bot.schedule_views import ScheduleManagementView, build_schedule_embed
from app.scheduler.jobs import (
    run_daily_evening_job,
    run_daily_morning_job,
    run_saturday_plan_job,
    run_sunday_grocery_job,
    run_sunday_prep_job,
)
from app.scheduler.schedule_manager import SCHEDULE_DEFINITIONS, ScheduleManager
from app.scheduler.scheduler_service import SchedulerService
from app.services.calendar_service import CalendarService


def test_schedule_manager_initialization(tmp_path: Path):
    test_state_file = tmp_path / "schedules.json"
    mgr = ScheduleManager(state_file=test_state_file)

    # All defined routines should default to True (enabled)
    for job_id in SCHEDULE_DEFINITIONS:
        assert mgr.is_enabled(job_id) is True

    # State file should have been persisted
    assert test_state_file.is_file()


def test_schedule_manager_toggle_and_set_all(tmp_path: Path):
    test_state_file = tmp_path / "schedules.json"
    mgr = ScheduleManager(state_file=test_state_file)

    # Toggle single job
    new_state = mgr.toggle("saturday_plan")
    assert new_state is False
    assert mgr.is_enabled("saturday_plan") is False

    # Toggle back
    new_state = mgr.toggle("saturday_plan")
    assert new_state is True
    assert mgr.is_enabled("saturday_plan") is True

    # Disable all
    mgr.set_all(False)
    for job_id in SCHEDULE_DEFINITIONS:
        assert mgr.is_enabled(job_id) is False

    # Enable all
    mgr.set_all(True)
    for job_id in SCHEDULE_DEFINITIONS:
        assert mgr.is_enabled(job_id) is True


def test_schedule_manager_get_jobs_info(tmp_path: Path):
    mgr = ScheduleManager(state_file=tmp_path / "schedules.json")
    all_info = mgr.get_all_jobs_info()
    assert len(all_info) == len(SCHEDULE_DEFINITIONS)
    assert any(j["id"] == "saturday_plan" for j in all_info)
    assert any(j["id"] == "daily_evening" for j in all_info)


def test_calendar_service_unconfigured():
    cal = CalendarService(credentials_path="non_existent_credentials.json")
    assert cal.is_configured() is False


@pytest.mark.asyncio
async def test_calendar_service_get_conflicts_unconfigured():
    cal = CalendarService(credentials_path="non_existent_credentials.json")
    conflicts = await cal.get_dinner_conflicts(date(2026, 10, 12), date(2026, 10, 18))
    assert conflicts == []

    context = await cal.format_conflicts_context(date(2026, 10, 12), date(2026, 10, 18))
    assert "No evening calendar conflicts detected" in context


@pytest.mark.asyncio
async def test_calendar_service_check_status_unconfigured():
    cal = CalendarService(credentials_path="non_existent_credentials.json")
    status = await cal.check_status()
    assert "Not configured" in status
    assert "credentials.json not found" in status


@pytest.mark.asyncio
async def test_calendar_service_check_status_connected(tmp_path):
    cred_file = tmp_path / "credentials.json"
    cred_file.write_text('{"type": "service_account"}')
    cal = CalendarService(credentials_path=str(cred_file))

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"summary": "Shovel", "id": "test_cal"}

    mock_client = MagicMock()
    mock_client.get = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with (
        patch("google.oauth2.service_account.Credentials.from_service_account_file") as mock_creds,
        patch("httpx.AsyncClient", return_value=mock_client),
    ):
        mock_creds_inst = MagicMock()
        mock_creds_inst.token = "fake-token"
        mock_creds.return_value = mock_creds_inst

        status = await cal.check_status()
        assert "Connected ('Shovel')" in status


@pytest.mark.asyncio
async def test_scheduler_service_lifecycle():
    service = SchedulerService()
    mock_bot = MagicMock(spec=discord.Client)

    # Start service
    service.start(mock_bot)
    assert service.scheduler.running

    # Check registered jobs
    registered_ids = [job.id for job in service.scheduler.get_jobs()]
    for expected_id in SCHEDULE_DEFINITIONS:
        assert expected_id in registered_ids

    # Sync job state
    service.sync_job_state("saturday_plan")

    # Shutdown
    service.shutdown()
    await asyncio.sleep(0.01)
    assert not service.scheduler.running


def test_schedule_views_embed_and_components():
    embed = build_schedule_embed()
    assert "Autonomous Kitchen Schedules" in embed.title
    assert len(embed.fields) == len(SCHEDULE_DEFINITIONS)

    view = ScheduleManagementView(selected_job_id="daily_evening")
    assert len(view.children) >= 4
    # Check select component is present
    selects = [c for c in view.children if isinstance(c, discord.ui.Select)]
    assert len(selects) == 1
    assert len(selects[0].options) == len(SCHEDULE_DEFINITIONS)


@pytest.mark.asyncio
async def test_run_disabled_job_skips():
    mock_bot = MagicMock(spec=discord.Client)
    with patch("app.scheduler.jobs.schedule_manager.is_enabled", return_value=False):
        result = await run_saturday_plan_job(mock_bot)
        assert result is False


@pytest.mark.asyncio
async def test_run_daily_evening_job_success():
    mock_channel = AsyncMock()
    mock_bot = MagicMock(spec=discord.Client)
    mock_bot.get_channel = MagicMock(return_value=mock_channel)

    agent_patch = "app.scheduler.jobs.gemini_kitchen_agent.generate_evening_dispatch"
    with (
        patch("app.scheduler.jobs.schedule_manager.is_enabled", return_value=True),
        patch(agent_patch, new_callable=AsyncMock) as mock_agent,
    ):
        mock_agent.return_value = "Step 1: Prep chicken. Step 2: Cook. Step 3: Serve."
        result = await run_daily_evening_job(mock_bot, channel_id=123)

        assert result is True
        mock_channel.send.assert_called_once()
        _, kwargs = mock_channel.send.call_args
        assert "embed" in kwargs
        assert "view" in kwargs


@pytest.mark.asyncio
async def test_run_saturday_plan_job_success():
    mock_channel = AsyncMock()
    mock_bot = MagicMock(spec=discord.Client)
    mock_bot.get_channel = MagicMock(return_value=mock_channel)

    agent_patch = "app.scheduler.jobs.gemini_kitchen_agent.generate_weekly_meal_plan"
    with (
        patch("app.scheduler.jobs.schedule_manager.is_enabled", return_value=True),
        patch(agent_patch, new_callable=AsyncMock) as mock_agent,
        patch("app.scheduler.jobs.calendar_service.format_conflicts_context", new_callable=AsyncMock) as mock_cal,
    ):
        mock_agent.return_value = "Monday: Tacos. Tuesday: Salmon."
        mock_cal.return_value = "No conflicts"

        result = await run_saturday_plan_job(mock_bot, channel_id=123)
        assert result is True
        mock_channel.send.assert_called_once()


@pytest.mark.asyncio
async def test_run_sunday_grocery_and_prep_jobs_success():
    mock_channel = AsyncMock()
    mock_bot = MagicMock(spec=discord.Client)
    mock_bot.get_channel = MagicMock(return_value=mock_channel)

    groc_patch = "app.scheduler.jobs.gemini_kitchen_agent.generate_sunday_grocery_list"
    prep_patch = "app.scheduler.jobs.gemini_kitchen_agent.generate_sunday_prep_directives"
    with (
        patch("app.scheduler.jobs.schedule_manager.is_enabled", return_value=True),
        patch(groc_patch, new_callable=AsyncMock) as mock_groc,
        patch(prep_patch, new_callable=AsyncMock) as mock_prep,
    ):
        mock_groc.return_value = "- [ ] Milk\n- [ ] Eggs"
        mock_prep.return_value = "1. Marinate chicken\n2. Cook rice"

        res_groc = await run_sunday_grocery_job(mock_bot, channel_id=123)
        assert res_groc is True

        res_prep = await run_sunday_prep_job(mock_bot, channel_id=123)
        assert res_prep is True


@pytest.mark.asyncio
async def test_run_daily_morning_job_success():
    mock_channel = AsyncMock()
    mock_bot = MagicMock(spec=discord.Client)
    mock_bot.get_channel = MagicMock(return_value=mock_channel)

    brief_patch = "app.scheduler.jobs.gemini_kitchen_agent.generate_morning_briefing"
    with (
        patch("app.scheduler.jobs.schedule_manager.is_enabled", return_value=True),
        patch(brief_patch, new_callable=AsyncMock) as mock_briefing,
    ):
        mock_briefing.return_value = "Today is Chicken Rice Bowl. Defrost chicken!"
        result = await run_daily_morning_job(mock_bot, channel_id=123)
        assert result is True
        mock_channel.send.assert_called_once()
