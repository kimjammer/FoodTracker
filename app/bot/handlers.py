"""
Discord message, attachment, and event handlers.
"""

import logging
import re
from typing import Any, Dict, List, Optional

import discord
from google.genai import types

from app.bot.views import ReceiptConfirmationView
from app.llm.client import gemini_kitchen_agent
from app.llm.prompts import KITCHEN_ASSISTANT_SYSTEM_PROMPT

logger = logging.getLogger(__name__)

IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".heic")
MAX_THREAD_TURNS = 5


def is_image_attachment(attachment: discord.Attachment) -> bool:
    """Check if a Discord attachment is an image."""
    if attachment.content_type and attachment.content_type.startswith("image/"):
        return True
    return any(attachment.filename.lower().endswith(ext) for ext in IMAGE_EXTENSIONS)


def generate_thread_title(content: str) -> str:
    """Generate a clean, human-readable title for a Discord thread."""
    first_line = content.strip().split("\n")[0].strip()
    cleaned = re.sub(r"^[#*\-`>\s]+", "", first_line)
    cleaned = re.sub(r"[\s\t]+", " ", cleaned).strip()
    return cleaned[:50].strip() or "Kitchen Conversation"


def count_bot_thread_replies(messages: List[discord.Message], bot_id: Optional[int]) -> int:
    """Count how many turn replies the bot has already made in this thread (tagged with (x/5))."""
    if not bot_id:
        return 0
    count = 0
    for m in messages:
        if m.author.id == bot_id and re.search(r"\([1-5]/5\)", m.content):
            count += 1
    return count


def build_gemini_history(past_messages: List[discord.Message], bot_id: Optional[int]) -> List[types.Content]:
    """
    Convert Discord thread history into alternating Gemini types.Content objects.
    Ensures strict alternation (user -> model) and strips previous turn counters.
    """
    if not past_messages or not bot_id:
        return []

    raw_turns = []
    for msg in past_messages:
        content = msg.clean_content.strip()
        if not content:
            continue
        if msg.author.id == bot_id:
            # Strip previous turn tag e.g. (1/5)
            cleaned = re.sub(r"\n*\([1-5]/5\)\s*$", "", content).strip()
            if cleaned:
                raw_turns.append(("model", cleaned))
        else:
            raw_turns.append(("user", content))

    if not raw_turns:
        return []

    cleaned_turns = []
    # If the first message is from model (e.g. thread started on a bot announcement or briefing),
    # wrap it as user context followed by model acknowledgement to satisfy Gemini's user-first constraint.
    if raw_turns[0][0] == "model":
        cleaned_turns.append(("user", f"[Prior Kitchen Update]: {raw_turns[0][1]}"))
        cleaned_turns.append(("model", "I posted this update earlier. How can I help you with it?"))
        raw_turns = raw_turns[1:]

    for role, text in raw_turns:
        if cleaned_turns and cleaned_turns[-1][0] == role:
            prev_role, prev_text = cleaned_turns[-1]
            cleaned_turns[-1] = (prev_role, f"{prev_text}\n{text}")
        else:
            cleaned_turns.append((role, text))

    # Gemini chats.create history MUST end with 'model' so that chat.send_message(prompt) is a 'user' turn
    while cleaned_turns and cleaned_turns[-1][0] == "user":
        cleaned_turns.pop()

    return [types.Content(role=role, parts=[types.Part.from_text(text=text)]) for role, text in cleaned_turns]


async def send_chunked_reply(destination: Any, reply_text: str, turn_tag: Optional[str] = None) -> None:
    """Send text to Discord channel/thread, chunking if exceeding 2000 chars."""
    if turn_tag:
        full_text = f"{reply_text}\n\n{turn_tag}"
    else:
        full_text = reply_text

    send_fn = destination.send if hasattr(destination, "send") else destination.reply

    if len(full_text) <= 2000:
        await send_fn(full_text)
        return

    # Split into chunks
    chunks = [reply_text[i : i + 1950] for i in range(0, len(reply_text), 1950)]
    for idx, chunk in enumerate(chunks):
        if idx == len(chunks) - 1 and turn_tag:
            await send_fn(f"{chunk}\n\n{turn_tag}")
        else:
            await send_fn(chunk)


async def handle_receipt_attachment(message: discord.Message) -> None:
    """
    Handle a user uploading an image of a grocery receipt or a photo of groceries on a counter/table.
    Downloads the image, classifies it with Gemini 3.5 Flash Lite, extracts items, and displays confirmation buttons.
    """
    image_attachments = [a for a in message.attachments if is_image_attachment(a)]
    if not image_attachments:
        return

    attachment = image_attachments[0]
    status_msg = await message.reply("🔍 **Scanning image with Gemini 3.5 Flash Lite (receipt or grocery haul)...**")

    # Rate-limit notification callback for user feedback
    async def notify_rate_limit(attempt: int, delay: float):
        try:
            await status_msg.edit(
                content=f"⏳ **Rate limit reached:** Waiting {delay:.0f}s before retrying scan (attempt {attempt})..."
            )
        except Exception as e:
            logger.warning(f"Could not edit rate limit status message: {e}")

    try:
        # Download image bytes
        image_bytes = await attachment.read()
        mime_type = attachment.content_type or "image/jpeg"

        # Multimodal extraction (receipts or countertop grocery haul)
        parsed_data = await gemini_kitchen_agent.parse_grocery_image(
            image_bytes=image_bytes,
            mime_type=mime_type,
            on_rate_limit=notify_rate_limit,
        )

        image_type = parsed_data.get("image_type", "receipt")
        title = parsed_data.get("title") or parsed_data.get("store_name") or "Grocery Scan"
        items: List[Dict[str, Any]] = parsed_data.get("items", [])

        # Check if an error occurred during vision parsing
        if image_type == "error" or parsed_data.get("error"):
            err_detail = parsed_data.get("error") or parsed_data.get("summary") or "Could not parse image data."
            try:
                if hasattr(message, "add_reaction"):
                    await message.add_reaction("❌")
            except Exception:
                pass
            await status_msg.edit(content=f"❌ An error occurred while scanning the image: {err_detail}")
            return

        # Check if image was deemed unrelated to groceries
        if image_type == "unrelated":
            summary = parsed_data.get("summary", "This image does not appear to contain groceries or a receipt.")
            await status_msg.edit(content=f"⚠️ {summary}")
            return

        if not items:
            await status_msg.edit(
                content="⚠️ No grocery items could be identified from this image. "
                "Please ensure the receipt or food items are clear and well-lit."
            )
            return

        # Choose title & embed color based on image type
        if image_type == "grocery_haul":
            embed_title = f"🍎 Grocery Haul Detected: {title}"
            embed_desc = f"Identified **{len(items)} items** on the counter/table. Review before adding to Grocy:"
            embed_color = discord.Color.green()
        else:
            embed_title = f"🧾 Receipt Scanned: {title}"
            embed_desc = f"Identified **{len(items)} items**. Review before adding to Grocy:"
            embed_color = discord.Color.blue()

        embed = discord.Embed(
            title=embed_title,
            description=embed_desc,
            color=embed_color,
        )

        if parsed_data.get("summary"):
            embed.add_field(name="Summary", value=parsed_data["summary"], inline=False)

        item_lines = []
        for item in items:
            name = item.get("name", "Unknown")
            qty = item.get("quantity", 1)
            unit = item.get("unit", "Piece")
            location = item.get("location", "Pantry")
            item_lines.append(f"• **{name}**: {qty} {unit} → *{location}*")

        # Discord embed fields have a 1024 character limit, chunk if necessary
        chunk_text = "\n".join(item_lines)
        if len(chunk_text) > 1000:
            chunk_text = chunk_text[:990] + "\n• *(and more items...)*"

        embed.add_field(name="Detected Items", value=chunk_text, inline=False)
        embed.set_footer(text="Click 'Add All to Grocy' to record inventory additions.")

        view = ReceiptConfirmationView(items=items)
        await status_msg.edit(content=None, embed=embed, view=view)

    except Exception as e:
        logger.error(f"Error handling image attachment: {e}", exc_info=True)
        try:
            if hasattr(message, "add_reaction"):
                await message.add_reaction("❌")
        except Exception:
            pass
        err_msg = str(e)[:1500]
        await status_msg.edit(content=f"❌ An error occurred while parsing the image: {err_msg}")


async def _indicate_query_error(
    message: discord.Message,
    destination: Any,
    error: Exception,
    status_msg: Optional[discord.Message] = None,
    use_reply: bool = False,
) -> None:
    """Clean up any pending status message, react with ❌, and send an error message to the user."""
    if status_msg is not None:
        try:
            await status_msg.delete()
        except Exception:
            pass

    try:
        if hasattr(message, "add_reaction"):
            await message.add_reaction("❌")
    except Exception:
        pass

    err_msg = str(error)[:1500] or type(error).__name__
    error_text = f"❌ Error processing request: {err_msg}"

    try:
        if use_reply and hasattr(message, "reply"):
            await message.reply(error_text)
        elif hasattr(destination, "send"):
            await destination.send(error_text)
        elif hasattr(message, "reply"):
            await message.reply(error_text)
    except Exception as send_err:
        logger.warning(f"Failed to send error message to primary destination: {send_err}")
        try:
            if hasattr(message, "reply"):
                await message.reply(error_text)
        except Exception:
            pass


async def handle_user_query(message: discord.Message, bot_user: Optional[discord.User] = None) -> None:
    """
    Handle natural language user messages sent to the bot:
    - User queries at main level: Creates a thread and replies in that thread.
    - User replies inside a thread: Loads full thread context, tracks 5-message counter (x/5).
    - If 5-message limit is reached: Does NOT call the LLM; returns a short limit message.
    - Non-user queries (announcements): Users can start a thread on them to follow up.
    - DMs: Replies directly without thread creation.
    """
    bot_id = bot_user.id if bot_user else (message.guild.me.id if message.guild and message.guild.me else None)
    is_dm = isinstance(message.channel, discord.DMChannel)
    is_thread = isinstance(message.channel, discord.Thread)

    # 1. Direct Messages (threads not supported in DMs)
    if is_dm:
        async with message.channel.typing():
            status_msg: Optional[discord.Message] = None

            async def notify_rate_limit(attempt: int, delay: float):
                nonlocal status_msg
                if not status_msg:
                    status_msg = await message.reply(
                        f"⏳ **Rate limit reached:** Waiting {delay:.0f}s before continuing..."
                    )
                else:
                    await status_msg.edit(
                        content=f"⏳ **Rate limit reached:** Waiting {delay:.0f}s (attempt {attempt})..."
                    )

            try:
                response_text = await gemini_kitchen_agent.run_agent_loop(
                    prompt=message.content,
                    system_instruction=KITCHEN_ASSISTANT_SYSTEM_PROMPT,
                    on_rate_limit=notify_rate_limit,
                )
                if status_msg:
                    await status_msg.delete()
                await send_chunked_reply(message.channel, response_text)
            except Exception as e:
                logger.error(f"Error handling DM query: {e}", exc_info=True)
                await _indicate_query_error(message, message.channel, e, status_msg=status_msg, use_reply=True)
        return

    # 2. Follow-ups inside an existing Thread
    if is_thread:
        thread: discord.Thread = message.channel
        try:
            thread_messages = [m async for m in thread.history(limit=50, oldest_first=True)]
        except Exception as e:
            logger.warning(f"Failed to fetch thread history: {e}")
            thread_messages = []

        bot_reply_count = count_bot_thread_replies(thread_messages, bot_id)

        # Enforce 5-message limit: Do NOT call LLM when max is reached
        if bot_reply_count >= MAX_THREAD_TURNS:
            await message.reply(
                "⚠️ **Conversation limit reached (5/5).**\n"
                "This thread conversation has reached the 5-message limit to keep discussions focused and "
                "cost-effective. Please ask a new question in the main channel to continue!"
            )
            return

        turn = bot_reply_count + 1
        turn_tag = f"({turn}/{MAX_THREAD_TURNS})"

        # Fetch starter message if thread was created on an existing message
        starter = thread.starter_message
        if starter is None and thread.parent:
            try:
                starter = await thread.parent.fetch_message(thread.id)
            except Exception:
                starter = None

        all_past = []
        if starter and starter.id not in [m.id for m in thread_messages]:
            all_past.append(starter)
        all_past.extend([m for m in thread_messages if m.id != message.id])

        history = build_gemini_history(all_past, bot_id)

        async with thread.typing():
            status_msg = None

            async def notify_rate_limit(attempt: int, delay: float):
                nonlocal status_msg
                if not status_msg:
                    status_msg = await thread.send(
                        f"⏳ **Rate limit reached:** Waiting {delay:.0f}s before continuing..."
                    )
                else:
                    await status_msg.edit(
                        content=f"⏳ **Rate limit reached:** Waiting {delay:.0f}s (attempt {attempt})..."
                    )

            try:
                response_text = await gemini_kitchen_agent.run_agent_loop(
                    prompt=message.content,
                    system_instruction=KITCHEN_ASSISTANT_SYSTEM_PROMPT,
                    history=history,
                    on_rate_limit=notify_rate_limit,
                )
                if status_msg:
                    await status_msg.delete()
                await send_chunked_reply(thread, response_text, turn_tag=turn_tag)
            except Exception as e:
                logger.error(f"Error handling thread query: {e}", exc_info=True)
                await _indicate_query_error(message, thread, e, status_msg=status_msg)
        return

    # 3. Main channel user query -> Create a new thread and reply in thread
    thread_title = generate_thread_title(message.clean_content)
    thread = None
    try:
        thread = await message.create_thread(name=thread_title)
    except Exception as e:
        logger.warning(f"Could not create thread for message: {e}")

    target_dest = thread if thread is not None else message.channel
    turn_tag = f"(1/{MAX_THREAD_TURNS})" if thread is not None else None

    async with target_dest.typing():
        status_msg = None

        async def notify_rate_limit(attempt: int, delay: float):
            nonlocal status_msg
            if not status_msg:
                status_msg = await target_dest.send(
                    f"⏳ **Rate limit reached:** Waiting {delay:.0f}s before continuing..."
                )
            else:
                await status_msg.edit(content=f"⏳ **Rate limit reached:** Waiting {delay:.0f}s (attempt {attempt})...")

        try:
            response_text = await gemini_kitchen_agent.run_agent_loop(
                prompt=message.content,
                system_instruction=KITCHEN_ASSISTANT_SYSTEM_PROMPT,
                on_rate_limit=notify_rate_limit,
            )
            if status_msg:
                await status_msg.delete()
            await send_chunked_reply(target_dest, response_text, turn_tag=turn_tag)
        except Exception as e:
            logger.error(f"Error handling main query: {e}", exc_info=True)
            await _indicate_query_error(message, target_dest, e, status_msg=status_msg)
