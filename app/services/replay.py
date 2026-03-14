"""Replay service for traces."""

from typing import Any, Dict, Optional, Tuple

from app.services.proxy import ProxyService
from app.services.trace_store import TraceStore


class ReplayService:
    """Service for replaying traces.

    Provides methods to:
    - Replay original requests
    - Replay modified requests
    - Compare results
    """

    def __init__(self, proxy_service: ProxyService, trace_store: TraceStore):
        """Initialize the replay service.

        Args:
            proxy_service: Proxy service for making requests
            trace_store: Trace store for retrieving traces
        """
        self.proxy_service = proxy_service
        self.trace_store = trace_store

    async def replay(
        self,
        trace_id: str,
        use_modified: bool = False,
        override_provider: Optional[str] = None,
        override_model: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Replay a trace and return comparison info.

        Args:
            trace_id: Trace ID to replay
            use_modified: Use modified request instead of raw
            override_provider: Override provider
            override_model: Override model

        Returns:
            Dictionary with replay results
        """
        # Get original trace
        original_trace = self.trace_store.get_trace(trace_id)
        if not original_trace:
            return {
                "success": False,
                "error": f"Trace not found: {trace_id}",
            }

        # Determine request to replay
        if use_modified and original_trace.request.modified:
            request_to_replay = original_trace.request.modified
        else:
            request_to_replay = original_trace.request.raw

        # Apply overrides
        provider = override_provider or original_trace.provider
        if override_model:
            request_to_replay = request_to_replay.copy()
            request_to_replay["model"] = override_model

        # Process through proxy
        response, new_trace_id = await self.proxy_service.process_request(
            provider=provider,
            raw_request=request_to_replay,
            endpoint=f"/replay/{trace_id}",
        )

        return {
            "success": True,
            "original_trace_id": trace_id,
            "new_trace_id": new_trace_id,
            "response": response,
            "used_modified_request": use_modified,
            "provider_used": provider,
        }

    def compare_traces(
        self, trace_id_1: str, trace_id_2: str
    ) -> Dict[str, Any]:
        """Compare two traces.

        Args:
            trace_id_1: First trace ID
            trace_id_2: Second trace ID

        Returns:
            Comparison dictionary
        """
        trace_1 = self.trace_store.get_trace(trace_id_1)
        trace_2 = self.trace_store.get_trace(trace_id_2)

        if not trace_1 or not trace_2:
            return {
                "success": False,
                "error": "One or both traces not found",
            }

        # Compare requests
        req_1 = trace_1.request.modified or trace_1.request.raw
        req_2 = trace_2.request.modified or trace_2.request.raw

        # Compare responses
        resp_1 = trace_1.response.modified if trace_1.response else None
        resp_2 = trace_2.response.modified if trace_2.response else None

        return {
            "success": True,
            "trace_1": {
                "trace_id": trace_id_1,
                "provider": trace_1.provider,
                "model": trace_1.model,
                "duration_ms": trace_1.duration_ms,
                "has_error": trace_1.error is not None,
            },
            "trace_2": {
                "trace_id": trace_id_2,
                "provider": trace_2.provider,
                "model": trace_2.model,
                "duration_ms": trace_2.duration_ms,
                "has_error": trace_2.error is not None,
            },
            "request_same": req_1 == req_2,
            "response_same": resp_1 == resp_2,
        }
