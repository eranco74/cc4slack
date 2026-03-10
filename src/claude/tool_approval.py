"""Tool approval coordination between Slack and Claude."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class ApprovalResult:
    """Result of a tool approval request."""

    approved: bool
    reason: str = ""


@dataclass
class PendingApproval:
    """A pending tool approval request."""

    id: str
    session_id: str
    tool_name: str
    tool_input: dict[str, Any]
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # Internal state for async coordination
    _decision_event: asyncio.Event = field(default_factory=asyncio.Event)
    _approved: bool = False
    _reason: str = ""

    async def wait_for_decision(self) -> ApprovalResult:
        """Wait for the user to make a decision."""
        await self._decision_event.wait()
        return ApprovalResult(
            approved=self._approved,
            reason=self._reason,
        )

    def approve(self) -> None:
        """Approve this tool request."""
        self._approved = True
        self._reason = ""
        self._decision_event.set()

    def reject(self, reason: str = "User rejected this action") -> None:
        """Reject this tool request."""
        self._approved = False
        self._reason = reason
        self._decision_event.set()

    @property
    def is_decided(self) -> bool:
        """Check if a decision has been made."""
        return self._decision_event.is_set()

    @property
    def age_seconds(self) -> float:
        """Get the age of this request in seconds."""
        return (datetime.now(timezone.utc) - self.created_at).total_seconds()


class ApprovalManager:
    """Manages pending tool approval requests."""

    def __init__(self, default_timeout: float = 300.0) -> None:
        self._pending: dict[str, PendingApproval] = {}
        self._lock = asyncio.Lock()
        self.default_timeout = default_timeout

    async def create_pending(
        self,
        session_id: str,
        tool_name: str,
        tool_input: dict[str, Any],
    ) -> PendingApproval:
        """Create a new pending approval request."""
        async with self._lock:
            pending = PendingApproval(
                id=str(uuid.uuid4()),
                session_id=session_id,
                tool_name=tool_name,
                tool_input=tool_input,
            )
            self._pending[pending.id] = pending
            return pending

    async def get_pending(self, pending_id: str) -> PendingApproval | None:
        """Get a pending approval by ID."""
        async with self._lock:
            return self._pending.get(pending_id)

    async def approve(self, pending_id: str) -> bool:
        """Approve a pending request. Returns True if found and approved."""
        async with self._lock:
            pending = self._pending.get(pending_id)
            if pending and not pending.is_decided:
                pending.approve()
                # Keep in dict briefly so result can be retrieved
                return True
            return False

    async def reject(self, pending_id: str, reason: str = "") -> bool:
        """Reject a pending request. Returns True if found and rejected."""
        async with self._lock:
            pending = self._pending.get(pending_id)
            if pending and not pending.is_decided:
                pending.reject(reason or "User rejected this action")
                return True
            return False

    async def remove(self, pending_id: str) -> None:
        """Remove a pending approval from tracking."""
        async with self._lock:
            self._pending.pop(pending_id, None)

    async def cleanup_expired(self, max_age_seconds: float = 300.0) -> int:
        """Remove expired pending approvals. Returns count removed."""
        async with self._lock:
            expired_ids: list[str] = []

            for pending_id, pending in self._pending.items():
                if pending.age_seconds > max_age_seconds:
                    # Reject expired requests so waiting coroutines don't hang
                    if not pending.is_decided:
                        pending.reject("Approval request expired")
                    expired_ids.append(pending_id)

            for pending_id in expired_ids:
                del self._pending[pending_id]

            return len(expired_ids)

    async def cancel_session_approvals(self, session_id: str) -> int:
        """Cancel all pending approvals for a session. Returns count cancelled."""
        async with self._lock:
            cancelled = 0
            to_remove: list[str] = []

            for pending_id, pending in self._pending.items():
                if pending.session_id == session_id and not pending.is_decided:
                    pending.reject("Session cancelled")
                    to_remove.append(pending_id)
                    cancelled += 1

            for pending_id in to_remove:
                del self._pending[pending_id]

            return cancelled

    @property
    def pending_count(self) -> int:
        """Get count of pending approvals."""
        return len(self._pending)
