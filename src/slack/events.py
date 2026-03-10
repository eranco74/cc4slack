"""Slack event handlers for mentions and direct messages."""

from __future__ import annotations

import asyncio
import logging
import re
from typing import TYPE_CHECKING, Any

from . import blocks
from .message_updater import SlackMessageUpdater

if TYPE_CHECKING:
    from slack_bolt.async_app import AsyncApp
    from slack_sdk.web.async_client import AsyncWebClient

    from ..claude.agent import ClaudeSlackAgent
    from ..sessions.manager import SessionManager

logger = logging.getLogger(__name__)

# Regex to clean bot mention from message text
MENTION_PATTERN = re.compile(r"<@[A-Z0-9]+>\s*")


def clean_mention(text: str) -> str:
    """Remove bot mention from message text."""
    return MENTION_PATTERN.sub("", text).strip()


def register_event_handlers(
    app: AsyncApp,
    session_manager: SessionManager,
    claude_agent: ClaudeSlackAgent,
) -> None:
    """Register Slack event handlers on the app."""

    @app.event("app_mention")
    async def handle_mention(
        event: dict[str, Any],
        client: AsyncWebClient,
        logger: logging.Logger,
    ) -> None:
        """Handle when the bot is mentioned in a channel."""
        user = event.get("user", "unknown")
        channel = event["channel"]
        text = event.get("text", "")
        # Use thread_ts if in a thread, otherwise start new thread with this message
        thread_ts = event.get("thread_ts") or event["ts"]

        logger.info(f"Mention from {user} in {channel}: {text[:50]}...")

        # Clean the mention from the text
        user_message = clean_mention(text)
        if not user_message:
            await client.chat_postMessage(
                channel=channel,
                thread_ts=thread_ts,
                text="Hi! How can I help you? Just mention me with your question.",
            )
            return

        await process_request(
            channel=channel,
            thread_ts=thread_ts,
            user_message=user_message,
            client=client,
            session_manager=session_manager,
            claude_agent=claude_agent,
        )

    @app.event("message")
    async def handle_message(
        event: dict[str, Any],
        client: AsyncWebClient,
        logger: logging.Logger,
    ) -> None:
        """Handle direct messages to the bot."""
        # Only handle direct messages
        if event.get("channel_type") != "im":
            return

        # Ignore bot messages and message edits
        if event.get("bot_id") or event.get("subtype"):
            return

        user = event.get("user", "unknown")
        channel = event["channel"]
        text = event.get("text", "")
        thread_ts = event.get("thread_ts") or event["ts"]

        logger.info(f"DM from {user}: {text[:50]}...")

        if not text.strip():
            return

        await process_request(
            channel=channel,
            thread_ts=thread_ts,
            user_message=text.strip(),
            client=client,
            session_manager=session_manager,
            claude_agent=claude_agent,
        )


async def process_request(
    channel: str,
    thread_ts: str,
    user_message: str,
    client: AsyncWebClient,
    session_manager: SessionManager,
    claude_agent: ClaudeSlackAgent,
) -> None:
    """Process a user request through Claude."""
    # Get or create session for this thread
    session = await session_manager.get_or_create(
        channel_id=channel,
        thread_ts=thread_ts,
    )

    # Check if session is already processing
    if session.is_processing:
        await client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text=":hourglass: I'm still working on the previous request. Please wait...",
        )
        return

    # Send initial "thinking" message
    result = await client.chat_postMessage(
        channel=channel,
        thread_ts=thread_ts,
        text="Claude is thinking...",
        blocks=blocks.thinking_indicator(),
    )

    message_ts = result["ts"]

    # Create message updater for streaming responses
    updater = SlackMessageUpdater(
        client=client,
        channel=channel,
        message_ts=message_ts,
        thread_ts=thread_ts,
    )

    # Process with Claude in background task
    # This allows the event handler to return quickly
    asyncio.create_task(
        _run_claude_task(
            session=session,
            user_message=user_message,
            updater=updater,
            client=client,
            claude_agent=claude_agent,
            session_manager=session_manager,
        )
    )


async def _run_claude_task(
    session: Any,
    user_message: str,
    updater: SlackMessageUpdater,
    client: AsyncWebClient,
    claude_agent: ClaudeSlackAgent,
    session_manager: SessionManager,
) -> None:
    """Run Claude agent task with error handling."""
    try:
        await claude_agent.process_message(
            session=session,
            user_message=user_message,
            updater=updater,
            slack_client=client,
        )
    except Exception as e:
        logger.exception(f"Error processing message: {e}")
        await updater.show_error(str(e))
    finally:
        # Ensure session is marked as not processing
        session.is_processing = False
        await session_manager.save(session)
