"""Slack event handlers for mentions and direct messages."""

from __future__ import annotations

import asyncio
import logging
import os
import re
from typing import TYPE_CHECKING, Any

from . import blocks
from .message_updater import SlackMessageUpdater

if TYPE_CHECKING:
    from slack_bolt.async_app import AsyncApp
    from slack_sdk.web.async_client import AsyncWebClient

    from ..claude.agent import ClaudeSlackAgent
    from ..config import Settings
    from ..sessions.manager import SessionManager

logger = logging.getLogger(__name__)

# Regex to clean bot mention from message text
MENTION_PATTERN = re.compile(r"<@[A-Z0-9]+>\s*")

# Regex to match connect command with optional session ID
CONNECT_PATTERN = re.compile(r"^connect\s*(.*)$", re.IGNORECASE)

# Regex to match sessions command
SESSIONS_PATTERN = re.compile(r"^sessions?\s*$", re.IGNORECASE)


def clean_mention(text: str) -> str:
    """Remove bot mention from message text."""
    return MENTION_PATTERN.sub("", text).strip()


def register_event_handlers(
    app: AsyncApp,
    session_manager: SessionManager,
    claude_agent: ClaudeSlackAgent,
    config: Settings | None = None,
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

        # Check for connect command
        connect_match = CONNECT_PATTERN.match(user_message)
        if connect_match:
            await handle_connect(
                channel=channel,
                thread_ts=thread_ts,
                session_id_arg=connect_match.group(1).strip(),
                client=client,
                session_manager=session_manager,
                config=config,
            )
            return

        # Check for sessions command
        if SESSIONS_PATTERN.match(user_message):
            await handle_list_sessions(
                channel=channel,
                thread_ts=thread_ts,
                client=client,
                config=config,
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

        # Check for connect command
        stripped = text.strip()
        connect_match = CONNECT_PATTERN.match(stripped)
        if connect_match:
            await handle_connect(
                channel=channel,
                thread_ts=thread_ts,
                session_id_arg=connect_match.group(1).strip(),
                client=client,
                session_manager=session_manager,
                config=config,
            )
            return

        # Check for sessions command
        if SESSIONS_PATTERN.match(stripped):
            await handle_list_sessions(
                channel=channel,
                thread_ts=thread_ts,
                client=client,
                config=config,
            )
            return

        await process_request(
            channel=channel,
            thread_ts=thread_ts,
            user_message=stripped,
            client=client,
            session_manager=session_manager,
            claude_agent=claude_agent,
        )


def read_session_id_from_file(file_path: str) -> str | None:
    """Read a Claude session ID from a file on disk."""
    try:
        if os.path.exists(file_path):
            content = open(file_path).read().strip()
            if content:
                return content
    except Exception as e:
        logger.warning(f"Failed to read session file {file_path}: {e}")
    return None


def get_session_title(file_path: str) -> str:
    """Extract the first user message from a session transcript as a title."""
    import json

    try:
        with open(file_path) as f:
            for line in f:
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if (
                    data.get("type") == "user"
                    and data.get("message", {}).get("role") == "user"
                    and not data.get("isMeta")
                ):
                    content = data["message"].get("content", "")
                    if isinstance(content, str) and content.strip():
                        title = content.strip()[:80]
                        if len(content.strip()) > 80:
                            title += "..."
                        return title
    except Exception as e:
        logger.debug(f"Failed to read session title from {file_path}: {e}")
    return "(no title)"


def list_available_sessions(
    claude_dir: str = os.path.expanduser("~/.claude/projects"),
    project_dir: str | None = None,
) -> list[tuple[str, str, str, float]]:
    """List available session IDs from Claude's project directories.

    Args:
        claude_dir: Base Claude projects directory.
        project_dir: If set, only list sessions from this project's directory.

    Returns list of (session_id, file_path, title, mtime) tuples, sorted by most recent first.
    """
    sessions: list[tuple[str, str, str, float]] = []
    try:
        if project_dir:
            # Encode the project path the same way Claude does
            encoded = project_dir.replace("/", "-")
            if encoded.startswith("-"):
                encoded = encoded  # Claude keeps the leading dash
            search_dir = os.path.join(claude_dir, encoded)
            if not os.path.isdir(search_dir):
                search_dir = claude_dir  # fallback to all
        else:
            search_dir = claude_dir

        if not os.path.isdir(search_dir):
            return sessions

        for root, _dirs, files in os.walk(search_dir):
            for f in files:
                if f.endswith(".jsonl") and not f.startswith("agent-"):
                    full_path = os.path.join(root, f)
                    session_id = f.removesuffix(".jsonl")
                    mtime = os.path.getmtime(full_path)
                    sessions.append((session_id, full_path, "", mtime))

        sessions.sort(key=lambda x: x[3], reverse=True)

        # Only fetch titles for top results (avoid reading too many files)
        result = []
        for sid, path, _, mtime in sessions[:10]:
            title = get_session_title(path)
            result.append((sid, path, title, mtime))

        return result
    except Exception as e:
        logger.warning(f"Failed to list sessions from {claude_dir}: {e}")
        return []


async def handle_connect(
    channel: str,
    thread_ts: str,
    session_id_arg: str,
    client: AsyncWebClient,
    session_manager: SessionManager,
    config: Settings | None = None,
) -> None:
    """Handle the 'connect' command to attach to an existing Claude session."""
    from ..config import get_settings

    if config is None:
        config = get_settings()

    claude_session_id: str | None = None

    if session_id_arg:
        # User provided a specific session ID
        claude_session_id = session_id_arg
    else:
        # Try to read from the session file
        claude_session_id = read_session_id_from_file(config.claude_session_file)

    if not claude_session_id:
        # No session ID found - show available sessions
        available = list_available_sessions(project_dir=config.working_directory)
        if available:
            session_list = "\n".join(
                f"• `{sid[:12]}...` — {title}" for sid, _, title, _ in available[:5]
            )
            await client.chat_postMessage(
                channel=channel,
                thread_ts=thread_ts,
                text=(
                    f":warning: No session ID found in `{config.claude_session_file}`.\n\n"
                    f"*Recent sessions found on disk:*\n{session_list}\n\n"
                    f"Use `connect <session-id>` to connect to one of these sessions.\n\n"
                    f"_Tip: Set up a SessionStart hook to auto-write the session ID. "
                    f"See the README for details._"
                ),
            )
        else:
            await client.chat_postMessage(
                channel=channel,
                thread_ts=thread_ts,
                text=(
                    f":warning: No session ID found.\n\n"
                    f"• No file at `{config.claude_session_file}`\n"
                    f"• No sessions found in `~/.claude/projects/`\n\n"
                    f"*To connect:*\n"
                    f"1. Run `/status` in your Claude terminal to get the session ID\n"
                    f"2. Then use `connect <session-id>` here\n\n"
                    f"_Or set up a SessionStart hook to auto-write the ID._"
                ),
            )
        return

    # Get or create the Slack session for this thread
    session = await session_manager.get_or_create(
        channel_id=channel,
        thread_ts=thread_ts,
    )

    # Set the Claude session ID to connect to the existing session
    session.claude_session_id = claude_session_id
    await session_manager.save(session)

    # Try to get a summary of the session being connected to
    summary = _get_session_summary(claude_session_id, config.working_directory)

    connect_text = (
        f":link: *Connected to Claude session*\n"
        f"Session ID: `{claude_session_id[:12]}...`\n\n"
    )
    if summary:
        connect_text += f"*Session context:*\n{summary}\n\n"
    connect_text += (
        "Messages in this thread will resume that session's conversation history.\n"
        "_Note: The terminal session must not be actively running. "
        "Close it first if it's still open._"
    )

    await client.chat_postMessage(
        channel=channel,
        thread_ts=thread_ts,
        text=connect_text,
    )
    logger.info(f"Connected Slack thread {channel}:{thread_ts} to Claude session {claude_session_id}")


async def handle_list_sessions(
    channel: str,
    thread_ts: str,
    client: AsyncWebClient,
    config: Settings | None = None,
) -> None:
    """Handle the 'sessions' command to list available Claude sessions."""
    import time
    from ..config import get_settings

    if config is None:
        config = get_settings()

    available = list_available_sessions(project_dir=config.working_directory)

    if not available:
        await client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text=":file_folder: No sessions found.",
        )
        return

    now = time.time()
    lines = []
    for sid, _path, title, mtime in available[:10]:
        age_s = now - mtime
        if age_s < 3600:
            age = f"{int(age_s / 60)}m ago"
        elif age_s < 86400:
            age = f"{int(age_s / 3600)}h ago"
        else:
            age = f"{int(age_s / 86400)}d ago"
        lines.append(f"• `{sid[:12]}...` ({age})\n   _{title}_")

    session_list = "\n".join(lines)
    await client.chat_postMessage(
        channel=channel,
        thread_ts=thread_ts,
        text=(
            f":file_folder: *Available sessions* ({config.working_directory})\n\n"
            f"{session_list}\n\n"
            f"_Use `connect <session-id>` to resume a session._"
        ),
    )


def _get_session_summary(session_id: str, working_directory: str) -> str:
    """Get a summary of a session by reading its transcript.

    Returns a short summary with the first user message and the last few exchanges.
    """
    import json

    claude_dir = os.path.expanduser("~/.claude/projects")
    encoded = working_directory.replace("/", "-")
    session_file = os.path.join(claude_dir, encoded, f"{session_id}.jsonl")

    if not os.path.exists(session_file):
        # Search all project dirs
        for root, _dirs, files in os.walk(claude_dir):
            if f"{session_id}.jsonl" in files:
                session_file = os.path.join(root, f"{session_id}.jsonl")
                break
        else:
            return ""

    try:
        first_user_msg = ""
        user_messages: list[str] = []

        with open(session_file) as f:
            for line in f:
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if (
                    data.get("type") == "user"
                    and data.get("message", {}).get("role") == "user"
                    and not data.get("isMeta")
                ):
                    content = data["message"].get("content", "")
                    if isinstance(content, str) and content.strip():
                        msg = content.strip()[:100]
                        if len(content.strip()) > 100:
                            msg += "..."
                        if not first_user_msg:
                            first_user_msg = msg
                        user_messages.append(msg)

        if not first_user_msg:
            return ""

        parts = [f"> *First message:* {first_user_msg}"]
        if len(user_messages) > 1:
            parts.append(f"> *Total messages:* {len(user_messages)}")
            last_msg = user_messages[-1]
            if last_msg != first_user_msg:
                parts.append(f"> *Last message:* {last_msg}")

        return "\n".join(parts)
    except Exception as e:
        logger.debug(f"Failed to read session summary: {e}")
        return ""


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
