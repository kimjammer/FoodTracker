from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from app.bot.client import bot
from app.bot.handlers import is_image_attachment
from app.bot.views import DailyCookView, MealPlanApprovalView, ReceiptConfirmationView


def test_is_image_attachment():
    # Test by filename
    att_jpg = MagicMock(spec=discord.Attachment)
    att_jpg.filename = "receipt.jpg"
    att_jpg.content_type = None
    assert is_image_attachment(att_jpg)

    att_png = MagicMock(spec=discord.Attachment)
    att_png.filename = "photo.PNG"
    att_png.content_type = None
    assert is_image_attachment(att_png)

    # Test by content_type
    att_mime = MagicMock(spec=discord.Attachment)
    att_mime.filename = "upload.blob"
    att_mime.content_type = "image/webp"
    assert is_image_attachment(att_mime)

    # Test non-image
    att_pdf = MagicMock(spec=discord.Attachment)
    att_pdf.filename = "document.pdf"
    att_pdf.content_type = "application/pdf"
    assert not is_image_attachment(att_pdf)


def test_receipt_confirmation_view_init():
    items = [
        {"name": "Whole Milk", "quantity": 1.0, "unit": "Bottle", "location": "Fridge"},
        {"name": "Rice", "quantity": 2.0, "unit": "kg", "location": "Pantry"},
    ]
    view = ReceiptConfirmationView(items=items)
    assert len(view.items) == 2
    button_labels = [c.label for c in view.children if isinstance(c, discord.ui.Button)]
    assert "Add All to Grocy" in button_labels
    assert "Cancel" in button_labels


def test_meal_plan_approval_view_init():
    view = MealPlanApprovalView(plan_summary="7-day plan details")
    assert view.plan_summary == "7-day plan details"
    button_labels = [c.label for c in view.children if isinstance(c, discord.ui.Button)]
    assert "Approve Plan" in button_labels
    assert "Modify Plan" in button_labels


def test_daily_cook_view_init():
    view = DailyCookView(dish_name="Chicken Rice Bowl")
    assert view.dish_name == "Chicken Rice Bowl"
    button_labels = [c.label for c in view.children if isinstance(c, discord.ui.Button)]
    assert "Cooked!" in button_labels
    assert "Eating Out / Skip" in button_labels
    assert "Swap Dinner" in button_labels


def test_bot_slash_commands_registered():
    bot.register_slash_commands()
    command_names = [cmd.name for cmd in bot.tree.get_commands()]
    assert "plan" in command_names
    assert "inventory" in command_names
    assert "shopping" in command_names
    assert "cook" in command_names
    assert "status" in command_names
    assert "schedules" in command_names
    assert "toggle_schedule" in command_names
    assert "run_schedule" in command_names
    assert "profile" in command_names
    assert "set_profile" in command_names


async def test_on_message_no_channel_unmentioned_ignored(monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "discord_channel_id", None)

    mock_user = MagicMock()
    mock_user.id = 999
    bot._connection.user = mock_user

    msg = MagicMock(spec=discord.Message)
    msg.author.bot = False
    msg.channel = MagicMock(spec=discord.TextChannel)
    msg.channel.id = 123
    msg.mentions = []
    msg.attachments = []
    msg.content = "hello"

    with (
        patch("app.bot.client.handle_user_query", new_callable=AsyncMock) as mock_query,
        patch("app.bot.client.handle_receipt_attachment", new_callable=AsyncMock) as mock_receipt,
    ):
        await bot.on_message(msg)
        mock_query.assert_not_called()
        mock_receipt.assert_not_called()


async def test_on_message_no_channel_mentioned_invoked(monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "discord_channel_id", None)

    mock_user = MagicMock()
    mock_user.id = 999
    bot._connection.user = mock_user

    msg = MagicMock(spec=discord.Message)
    msg.author.bot = False
    msg.channel = MagicMock(spec=discord.TextChannel)
    msg.channel.id = 123
    msg.mentions = [mock_user]
    msg.attachments = []
    msg.content = f"<@{mock_user.id}> what should I cook?"

    with patch("app.bot.client.handle_user_query", new_callable=AsyncMock) as mock_query:
        await bot.on_message(msg)
        mock_query.assert_called_once()
        assert msg.content == "what should I cook?"


async def test_on_message_no_channel_unmentioned_receipt_ignored(monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "discord_channel_id", None)

    mock_user = MagicMock()
    mock_user.id = 999
    bot._connection.user = mock_user

    att = MagicMock(spec=discord.Attachment)
    att.filename = "receipt.jpg"
    att.content_type = "image/jpeg"

    msg = MagicMock(spec=discord.Message)
    msg.author.bot = False
    msg.channel = MagicMock(spec=discord.TextChannel)
    msg.channel.id = 123
    msg.mentions = []
    msg.attachments = [att]
    msg.content = ""

    with patch("app.bot.client.handle_receipt_attachment", new_callable=AsyncMock) as mock_receipt:
        await bot.on_message(msg)
        mock_receipt.assert_not_called()


async def test_on_message_channel_specified_unmentioned_invoked(monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "discord_channel_id", 123)

    mock_user = MagicMock()
    mock_user.id = 999
    bot._connection.user = mock_user

    msg = MagicMock(spec=discord.Message)
    msg.author.bot = False
    msg.channel = MagicMock(spec=discord.TextChannel)
    msg.channel.id = 123
    msg.mentions = []
    msg.attachments = []
    msg.content = "what should I cook?"

    with patch("app.bot.client.handle_user_query", new_callable=AsyncMock) as mock_query:
        await bot.on_message(msg)
        mock_query.assert_called_once()


async def test_on_message_channel_specified_other_channel_unmentioned_ignored(monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "discord_channel_id", 123)

    mock_user = MagicMock()
    mock_user.id = 999
    bot._connection.user = mock_user

    msg = MagicMock(spec=discord.Message)
    msg.author.bot = False
    msg.channel = MagicMock(spec=discord.TextChannel)
    msg.channel.id = 456
    msg.mentions = []
    msg.attachments = []
    msg.content = "what should I cook?"

    with patch("app.bot.client.handle_user_query", new_callable=AsyncMock) as mock_query:
        await bot.on_message(msg)
        mock_query.assert_not_called()


@pytest.mark.asyncio
async def test_profile_slash_command_view_and_set(tmp_path):
    from app.services.profile_service import UserProfileService

    test_svc = UserProfileService(file_path=tmp_path / "bot_test_profile.json")
    profile_cmd = bot.tree.get_command("profile")
    if profile_cmd is None:
        bot.register_slash_commands()
        profile_cmd = bot.tree.get_command("profile")
    set_profile_cmd = bot.tree.get_command("set_profile")

    with patch("app.bot.client.user_profile_service", test_svc):
        # 1. View empty profile
        interaction = MagicMock(spec=discord.Interaction)
        interaction.response = MagicMock()
        interaction.response.send_message = AsyncMock()

        await profile_cmd.callback(interaction, text=None)
        interaction.response.send_message.assert_called_once()
        embed = interaction.response.send_message.call_args[1]["embed"]
        assert "No culinary profile is currently set" in embed.description

        # 2. Set profile via /set_profile
        interaction.response.send_message.reset_mock()
        await set_profile_cmd.callback(interaction, text="Enjoys Korean stews and rice bowls.")
        interaction.response.send_message.assert_called_once()
        embed = interaction.response.send_message.call_args[1]["embed"]
        assert "Enjoys Korean stews and rice bowls." in embed.description
        assert "Culinary Profile Saved" in embed.title

        # 3. View populated profile via /profile
        interaction.response.send_message.reset_mock()
        await profile_cmd.callback(interaction, text=None)
        interaction.response.send_message.assert_called_once()
        embed = interaction.response.send_message.call_args[1]["embed"]
        assert "Enjoys Korean stews and rice bowls." in embed.description


@pytest.mark.asyncio
async def test_status_slash_command_includes_calendar():
    status_cmd = bot.tree.get_command("status")
    interaction = MagicMock(spec=discord.Interaction)
    interaction.response = MagicMock()
    interaction.response.defer = AsyncMock()
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock()

    with (
        patch("app.bot.client.execute_tool", new_callable=AsyncMock) as mock_exec,
        patch("app.bot.client.calendar_service.check_status", new_callable=AsyncMock) as mock_cal_status,
    ):
        mock_exec.return_value = "System info OK"
        mock_cal_status.return_value = "✅ Connected ('Shovel')"

        await status_cmd.callback(interaction)

        interaction.response.defer.assert_called_once_with(ephemeral=True)
        interaction.followup.send.assert_called_once()
        sent_embed = interaction.followup.send.call_args[1]["embed"]

        field_names = [f.name for f in sent_embed.fields]
        assert "Grocy MCP Backend" in field_names
        assert "Gemini AI Engine" in field_names
        assert "Google Calendar" in field_names

        cal_field = next(f for f in sent_embed.fields if f.name == "Google Calendar")
        assert "Connected ('Shovel')" in cal_field.value


def test_generate_thread_title():
    from app.bot.handlers import generate_thread_title

    assert generate_thread_title("What can I make with chicken?") == "What can I make with chicken?"
    assert generate_thread_title("# Breakfast Ideas\nSecond line") == "Breakfast Ideas"
    assert generate_thread_title("") == "Kitchen Conversation"
    long_msg = "A" * 100
    assert len(generate_thread_title(long_msg)) == 50


def test_count_bot_thread_replies():
    from app.bot.handlers import count_bot_thread_replies

    bot_id = 999
    m1 = MagicMock()
    m1.author.id = 123
    m1.content = "User question"

    m2 = MagicMock()
    m2.author.id = 999
    m2.content = "Bot answer (1/5)"

    m3 = MagicMock()
    m3.author.id = 999
    m3.content = "Bot answer (2/5)"

    m4 = MagicMock()
    m4.author.id = 999
    m4.content = "Some other message without counter"

    assert count_bot_thread_replies([m1, m2, m3, m4], bot_id) == 2
    assert count_bot_thread_replies([m1, m4], bot_id) == 0


def test_build_gemini_history():
    from app.bot.handlers import build_gemini_history

    bot_id = 999
    m1 = MagicMock()
    m1.author.id = 100
    m1.clean_content = "Hello bot"

    m2 = MagicMock()
    m2.author.id = 999
    m2.clean_content = "Hi user! (1/5)"

    h = build_gemini_history([m1, m2], bot_id)
    assert len(h) == 2
    assert h[0].role == "user"
    assert h[0].parts[0].text == "Hello bot"
    assert h[1].role == "model"
    assert h[1].parts[0].text == "Hi user!"

    # Test bot announcement as first message
    m_ann = MagicMock()
    m_ann.author.id = 999
    m_ann.clean_content = "Morning briefing alert"

    h_ann = build_gemini_history([m_ann], bot_id)
    assert len(h_ann) == 2
    assert h_ann[0].role == "user"
    assert "[Prior Kitchen Update]" in h_ann[0].parts[0].text
    assert h_ann[1].role == "model"


@pytest.mark.asyncio
async def test_handle_user_query_creates_thread_on_main_message():
    from app.bot.handlers import handle_user_query

    msg = MagicMock(spec=discord.Message)
    msg.clean_content = "Can I make pancakes?"
    msg.content = "Can I make pancakes?"
    msg.channel = MagicMock(spec=discord.TextChannel)
    msg.guild = MagicMock()
    msg.guild.me.id = 999

    mock_thread = MagicMock(spec=discord.Thread)
    mock_thread.send = AsyncMock()
    mock_thread.typing.return_value.__aenter__ = AsyncMock()
    mock_thread.typing.return_value.__aexit__ = AsyncMock()

    msg.create_thread = AsyncMock(return_value=mock_thread)

    with patch("app.bot.handlers.gemini_kitchen_agent.run_agent_loop", new_callable=AsyncMock) as mock_agent:
        mock_agent.return_value = "Yes, here is a pancake recipe."

        await handle_user_query(msg)

        msg.create_thread.assert_called_once_with(name="Can I make pancakes?")
        mock_thread.send.assert_called_once()
        sent_content = mock_thread.send.call_args[0][0]
        assert "Yes, here is a pancake recipe." in sent_content
        assert "(1/5)" in sent_content


@pytest.mark.asyncio
async def test_handle_user_query_in_thread_stops_at_limit():
    from app.bot.handlers import handle_user_query

    mock_thread = MagicMock(spec=discord.Thread)
    msg = MagicMock(spec=discord.Message)
    msg.content = "Follow up question"
    msg.channel = mock_thread
    msg.guild = MagicMock()
    msg.guild.me.id = 999
    msg.reply = AsyncMock()

    past_msgs = []
    for i in range(1, 6):
        bot_m = MagicMock()
        bot_m.author.id = 999
        bot_m.content = f"Answer ({i}/5)"
        past_msgs.append(bot_m)

    async def mock_history(*args, **kwargs):
        for m in past_msgs:
            yield m

    mock_thread.history = mock_history

    with patch("app.bot.handlers.gemini_kitchen_agent.run_agent_loop", new_callable=AsyncMock) as mock_agent:
        await handle_user_query(msg)

        # Agent should NOT be called at all
        mock_agent.assert_not_called()
        msg.reply.assert_called_once()
        assert "limit reached" in msg.reply.call_args[0][0].lower()


@pytest.mark.asyncio
async def test_handle_user_query_indicates_error_on_exception():
    from app.bot.handlers import handle_user_query

    msg = MagicMock(spec=discord.Message)
    msg.clean_content = "Add 2 cartons of milk"
    msg.content = "Add 2 cartons of milk"
    msg.channel = MagicMock(spec=discord.TextChannel)
    msg.guild = MagicMock()
    msg.guild.me.id = 999
    msg.add_reaction = AsyncMock()
    msg.reply = AsyncMock()

    mock_thread = MagicMock(spec=discord.Thread)
    mock_thread.send = AsyncMock()
    mock_thread.typing.return_value.__aenter__ = AsyncMock()
    mock_thread.typing.return_value.__aexit__ = AsyncMock()
    msg.create_thread = AsyncMock(return_value=mock_thread)

    with patch("app.bot.handlers.gemini_kitchen_agent.run_agent_loop", new_callable=AsyncMock) as mock_agent:
        mock_agent.side_effect = RuntimeError("Grocy connection timed out")

        await handle_user_query(msg)

        msg.add_reaction.assert_called_once_with("❌")
        mock_thread.send.assert_called_once()
        assert "❌ Error processing request: Grocy connection timed out" in mock_thread.send.call_args[0][0]


@pytest.mark.asyncio
async def test_receipt_confirmation_view_indicates_partial_errors():
    items = [
        {"name": "Whole Milk", "quantity": 1.0, "unit": "Bottle", "location": "Fridge"},
        {"name": "Bad Item", "quantity": 1.0, "unit": "Piece", "location": "Pantry"},
    ]
    view = ReceiptConfirmationView(items=items)

    interaction = MagicMock(spec=discord.Interaction)
    interaction.response = MagicMock()
    interaction.response.defer = AsyncMock()
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock()
    interaction.message = MagicMock()
    interaction.message.embeds = [discord.Embed(title="Receipt Scanned")]
    interaction.message.edit = AsyncMock()

    mock_results = [
        {"name": "Whole Milk", "quantity": 1.0, "status": "success", "detail": "Added"},
        {"name": "Bad Item", "quantity": 1.0, "status": "error", "detail": "Error adding stock"},
    ]

    with patch(
        "app.bot.views.gemini_kitchen_agent.ingest_receipt_items",
        new_callable=AsyncMock,
        return_value=mock_results,
    ):
        await view.confirm_add.callback(interaction)

        interaction.message.edit.assert_called_once()
        edited_embed = interaction.message.edit.call_args[1]["embed"]
        assert edited_embed.color == discord.Color.orange()
        assert "1 failed" in edited_embed.footer.text

        interaction.followup.send.assert_called_once()
        followup_msg = interaction.followup.send.call_args[0][0]
        assert "⚠️" in followup_msg
        assert "Bad Item" in followup_msg


@pytest.mark.asyncio
async def test_handle_receipt_attachment_uses_unicode_arrow():
    from app.bot.handlers import handle_receipt_attachment

    att = MagicMock(spec=discord.Attachment)
    att.filename = "receipt.jpg"
    att.content_type = "image/jpeg"
    att.read = AsyncMock(return_value=b"fake_bytes")

    status_msg = MagicMock(spec=discord.Message)
    status_msg.edit = AsyncMock()

    msg = MagicMock(spec=discord.Message)
    msg.attachments = [att]
    msg.reply = AsyncMock(return_value=status_msg)

    parsed_payload = {
        "image_type": "receipt",
        "title": "H-Mart Receipt",
        "summary": "Scanned 1 item",
        "items": [{"name": "Tofu (두부)", "quantity": 2.0, "unit": "Pack", "location": "Fridge"}],
    }

    with patch(
        "app.bot.handlers.gemini_kitchen_agent.parse_grocery_image",
        new_callable=AsyncMock,
        return_value=parsed_payload,
    ):
        await handle_receipt_attachment(msg)

        status_msg.edit.assert_called_once()
        embed = status_msg.edit.call_args[1]["embed"]
        detected_field = next(f for f in embed.fields if f.name == "Detected Items")
        assert "→" in detected_field.value
        assert "rightarrow" not in detected_field.value
        assert "$" not in detected_field.value


