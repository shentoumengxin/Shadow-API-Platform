"""Manual intercept service for Burp Suite-style interception."""

import threading
import time
from datetime import datetime
from typing import Any, Dict, Optional
from collections import OrderedDict

from app.schemas.intercept import InterceptSession
from app.utils.ids import generate_short_id


class InterceptStore:
    """In-memory store for intercepted requests.

    Similar to Burp Suite's intercept queue.
    """

    def __init__(self, max_size: int = 100):
        """Initialize the intercept store.

        Args:
            max_size: Maximum number of sessions to keep
        """
        self.max_size = max_size
        self.sessions: OrderedDict[str, InterceptSession] = OrderedDict()
        self.pending_sessions: set = set()  # Sessions waiting for user action
        self._lock = threading.Lock()

        # Auto-cleanup interval (seconds)
        self.cleanup_interval = 300  # 5 minutes
        self._cleanup_thread: Optional[threading.Thread] = None
        self._start_cleanup_thread()

    def _start_cleanup_thread(self) -> None:
        """Start background cleanup thread."""
        def cleanup_loop():
            while True:
                time.sleep(self.cleanup_interval)
                self.cleanup_old_sessions()

        self._cleanup_thread = threading.Thread(target=cleanup_loop, daemon=True)
        self._cleanup_thread.start()

    def create_session(
        self,
        request_data: Dict[str, Any],
        endpoint: str,
        method: str,
    ) -> InterceptSession:
        """Create a new intercept session.

        Args:
            request_data: Original request data
            endpoint: API endpoint
            method: HTTP method

        Returns:
            New intercept session
        """
        with self._lock:
            session_id = f"intercept_{generate_short_id()}"

            session = InterceptSession(
                session_id=session_id,
                created_at=datetime.utcnow(),
                status="pending",
                original_request=request_data,
                modified_request=None,
                upstream_response=None,
                modified_response=None,
                endpoint=endpoint,
                method=method,
                intercept_request=True,
                intercept_response=True,
            )

            self.sessions[session_id] = session
            self.pending_sessions.add(session_id)

            # Move to end (most recent)
            self.sessions.move_to_end(session_id)

            # Cleanup if too many
            if len(self.sessions) > self.max_size:
                self._remove_oldest()

            return session

    def get_session(self, session_id: str) -> Optional[InterceptSession]:
        """Get a session by ID."""
        return self.sessions.get(session_id)

    def list_pending_sessions(self) -> list:
        """List all pending sessions waiting for action."""
        with self._lock:
            return [
                self.sessions[sid]
                for sid in self.pending_sessions
                if sid in self.sessions
            ]

    def list_all_sessions(self, limit: int = 50) -> list:
        """List all sessions, most recent first."""
        with self._lock:
            sessions = list(self.sessions.values())
            sessions.reverse()
            return sessions[:limit]

    def modify_request(
        self,
        session_id: str,
        modified_request: Dict[str, Any],
    ) -> Optional[InterceptSession]:
        """Modify an intercepted request.

        Args:
            session_id: Session ID
            modified_request: Modified request data

        Returns:
            Updated session or None
        """
        with self._lock:
            session = self.sessions.get(session_id)
            if not session:
                return None

            session.modified_request = modified_request
            # Set status to "forwarded" to wake up wait_for_session_action
            session.status = "forwarded"

            return session

    def forward_request(self, session_id: str) -> Optional[InterceptSession]:
        """Mark request as forwarded.

        Args:
            session_id: Session ID

        Returns:
            Updated session or None
        """
        with self._lock:
            session = self.sessions.get(session_id)
            if not session:
                return None

            # Change status to 'forwarded' to wake up wait_for_session_action
            # The code will then send the request
            session.status = "forwarded"

            return session

    def mark_request_forwarded(self, session_id: str) -> Optional[InterceptSession]:
        """Mark request as forwarded.

        Args:
            session_id: Session ID

        Returns:
            Updated session or None
        """
        with self._lock:
            session = self.sessions.get(session_id)
            if not session:
                return None

            session.status = "forwarded"
            return session

    def mark_response_sent(self, session_id: str) -> Optional[InterceptSession]:
        """Mark response as sent, session completed.

        Args:
            session_id: Session ID

        Returns:
            Updated session or None
        """
        with self._lock:
            session = self.sessions.get(session_id)
            if not session:
                return None

            session.status = "completed"
            self.pending_sessions.discard(session_id)

            return session

    def enable_response_intercept(self, session_id: str) -> Optional[InterceptSession]:
        """Enable response interception for a session.

        Args:
            session_id: Session ID

        Returns:
            Updated session or None
        """
        with self._lock:
            session = self.sessions.get(session_id)
            if not session:
                return None

            session.intercept_response = True
            return session

    def drop_request(self, session_id: str) -> Optional[InterceptSession]:
        """Mark request as dropped.

        Args:
            session_id: Session ID

        Returns:
            Updated session or None
        """
        with self._lock:
            session = self.sessions.get(session_id)
            if not session:
                return None

            session.status = "dropped"
            self.pending_sessions.discard(session_id)

            return session

    def set_upstream_response(
        self,
        session_id: str,
        upstream_response: Dict[str, Any],
    ) -> Optional[InterceptSession]:
        """Set the upstream response for a session.

        Args:
            session_id: Session ID
            upstream_response: Response from upstream

        Returns:
            Updated session or None
        """
        with self._lock:
            session = self.sessions.get(session_id)
            if not session:
                return None

            session.upstream_response = upstream_response
            if session.modified_response is None:
                session.status = "waiting_response"  # Waiting for response action

            return session

    def modify_response(
        self,
        session_id: str,
        modified_response: Dict[str, Any],
    ) -> Optional[InterceptSession]:
        """Modify an intercepted response.

        Args:
            session_id: Session ID
            modified_response: Modified response data

        Returns:
            Updated session or None
        """
        with self._lock:
            session = self.sessions.get(session_id)
            if not session:
                return None

            session.modified_response = modified_response
            session.status = "modified"

            return session

    def send_response(self, session_id: str) -> Optional[InterceptSession]:
        """Mark response as ready to send to client.

        Args:
            session_id: Session ID

        Returns:
            Updated session or None
        """
        with self._lock:
            session = self.sessions.get(session_id)
            if not session:
                return None

            session.status = "forwarded"
            self.pending_sessions.discard(session_id)

            return session

    def drop_response(self, session_id: str) -> Optional[InterceptSession]:
        """Mark response as dropped.

        Args:
            session_id: Session ID

        Returns:
            Updated session or None
        """
        with self._lock:
            session = self.sessions.get(session_id)
            if not session:
                return None

            session.status = "dropped"
            self.pending_sessions.discard(session_id)

            return session

    def delete_session(self, session_id: str) -> bool:
        """Delete a session.

        Args:
            session_id: Session ID

        Returns:
            True if deleted
        """
        with self._lock:
            if session_id in self.sessions:
                del self.sessions[session_id]
                self.pending_sessions.discard(session_id)
                return True
            return False

    def clear_all(self) -> int:
        """Clear all sessions.

        Returns:
            Number of sessions cleared
        """
        with self._lock:
            count = len(self.sessions)
            self.sessions.clear()
            self.pending_sessions.clear()
            return count

    def cleanup_old_sessions(self, max_age_seconds: int = 3600) -> int:
        """Remove old sessions.

        Args:
            max_age_seconds: Maximum age in seconds

        Returns:
            Number of sessions removed
        """
        with self._lock:
            now = datetime.utcnow()
            to_remove = []

            for session_id, session in self.sessions.items():
                age = (now - session.created_at).total_seconds()
                if age > max_age_seconds and session_id not in self.pending_sessions:
                    to_remove.append(session_id)

            for session_id in to_remove:
                del self.sessions[session_id]

            return len(to_remove)

    def _remove_oldest(self) -> None:
        """Remove oldest non-pending session."""
        for session_id in list(self.sessions.keys()):
            if session_id not in self.pending_sessions:
                del self.sessions[session_id]
                return

    def get_stats(self) -> Dict[str, int]:
        """Get intercept statistics."""
        with self._lock:
            pending = len(self.pending_sessions)
            total = len(self.sessions)

            status_counts = {}
            for session in self.sessions.values():
                status = session.status
                status_counts[status] = status_counts.get(status, 0) + 1

            return {
                "total_sessions": total,
                "pending": pending,
                "by_status": status_counts,
            }


# Global intercept store instance
intercept_store = InterceptStore(max_size=100)


async def wait_for_session_action(
    session_id: str,
    timeout: float = 300,
    poll_interval: float = 0.5,
) -> Optional[str]:
    """Wait for user action on a session.

    Args:
        session_id: Session ID to wait for
        timeout: Maximum wait time in seconds
        poll_interval: Polling interval in seconds

    Returns:
        Session status when action taken, or None on timeout
    """
    import asyncio
    start_time = time.time()

    while time.time() - start_time < timeout:
        session = intercept_store.get_session(session_id)
        if not session:
            return None

        # Wait until status changes from initial 'pending' state
        # Status 'forwarded', 'completed', or 'dropped' means action was taken
        if session.status in ["forwarded", "completed", "dropped"]:
            return session.status

        await asyncio.sleep(poll_interval)

    return None  # Timeout
