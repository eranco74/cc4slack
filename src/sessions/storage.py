"""Session storage implementations."""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .manager import Session


class SessionStorage(ABC):
    """Abstract base class for session storage."""

    @abstractmethod
    async def get(self, thread_key: str) -> Session | None:
        """Get session by thread key (channel_id:thread_ts)."""
        pass

    @abstractmethod
    async def get_by_id(self, session_id: str) -> Session | None:
        """Get session by session ID."""
        pass

    @abstractmethod
    async def save(self, session: Session) -> None:
        """Save session."""
        pass

    @abstractmethod
    async def delete(self, thread_key: str) -> None:
        """Delete session by thread key."""
        pass

    @abstractmethod
    async def cleanup_older_than(self, seconds: int) -> int:
        """Remove sessions older than given seconds. Returns count deleted."""
        pass


class MemorySessionStorage(SessionStorage):
    """In-memory session storage implementation."""

    def __init__(self) -> None:
        # Import here to avoid circular import
        from .manager import Session

        self._by_thread: dict[str, Session] = {}
        self._by_id: dict[str, Session] = {}
        self._lock = asyncio.Lock()

    async def get(self, thread_key: str) -> Session | None:
        """Get session by thread key."""
        async with self._lock:
            return self._by_thread.get(thread_key)

    async def get_by_id(self, session_id: str) -> Session | None:
        """Get session by session ID."""
        async with self._lock:
            return self._by_id.get(session_id)

    async def save(self, session: Session) -> None:
        """Save session to memory."""
        async with self._lock:
            self._by_thread[session.thread_key] = session
            self._by_id[session.id] = session

    async def delete(self, thread_key: str) -> None:
        """Delete session by thread key."""
        async with self._lock:
            session = self._by_thread.pop(thread_key, None)
            if session:
                self._by_id.pop(session.id, None)

    async def cleanup_older_than(self, seconds: int) -> int:
        """Remove sessions older than given seconds."""
        async with self._lock:
            now = datetime.now(timezone.utc)
            expired_keys: list[str] = []

            for key, session in self._by_thread.items():
                age = (now - session.last_activity).total_seconds()
                if age > seconds:
                    expired_keys.append(key)

            for key in expired_keys:
                session = self._by_thread.pop(key, None)
                if session:
                    self._by_id.pop(session.id, None)

            return len(expired_keys)
