"""Core proxy service."""

import threading
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import httpx

from app.adapters.anthropic_adapter import AnthropicAdapter
from app.adapters.base import BaseAdapter
from app.adapters.openai_adapter import OpenAIAdapter
from app.config import Config, ProviderConfig
from app.rules.engine import RuleEngine
from app.schemas.models import CanonicalRequest, CanonicalResponse, Message
from app.schemas.traces import Trace, TraceError, TraceRequest, TraceResponse
from app.services.intercept import intercept_store, wait_for_session_action
from app.services.trace_store import TraceStore
from app.utils.ids import generate_trace_id


# Global intercept mode toggle
intercept_mode_enabled = False
intercept_mode_lock = threading.Lock()


class ProxyService:
    """Core proxy service for handling LLM API requests.

    Responsibilities:
    - Route requests to appropriate provider adapter
    - Apply rule engine for request/response modification
    - Record traces for audit and replay
    - Handle errors gracefully
    """

    def __init__(self, config: Config):
        """Initialize the proxy service.

        Args:
            config: Application configuration
        """
        self.config = config
        self.trace_store = TraceStore("logs")

        # Initialize rule engine
        self.rule_engine = RuleEngine(
            rules_dir=config.rules_dir,
            dry_run=config.trace.dry_run,
        )

        # Initialize adapters
        self.adapters: Dict[str, BaseAdapter] = {}

        openai_config = config.providers.openai
        if openai_config.api_key:
            self.adapters["openai"] = OpenAIAdapter(
                api_key=openai_config.api_key,
                base_url=openai_config.base_url or "https://api.openai.com/v1",
            )

        anthropic_config = config.providers.anthropic
        if anthropic_config.api_key:
            self.adapters["anthropic"] = AnthropicAdapter(
                api_key=anthropic_config.api_key,
                base_url=anthropic_config.base_url or "https://api.anthropic.com",
            )

    def get_adapter(self, provider: str) -> Optional[BaseAdapter]:
        """Get adapter for a provider.

        Args:
            provider: Provider name

        Returns:
            Adapter instance or None
        """
        return self.adapters.get(provider.lower())

    def register_adapter(self, provider: str, adapter: BaseAdapter) -> None:
        """Register a custom adapter.

        Args:
            provider: Provider name
            adapter: Adapter instance
        """
        self.adapters[provider.lower()] = adapter

    async def process_request(
        self,
        provider: str,
        raw_request: Dict[str, Any],
        endpoint: str = "/proxy/invoke",
        method: str = "POST",
        extra_headers: Optional[Dict[str, str]] = None,
        skip_intercept: bool = False,
    ) -> Tuple[Dict[str, Any], str]:
        """Process a request through the proxy.

        Args:
            provider: Provider name
            raw_request: Raw request from client
            endpoint: API endpoint for trace
            method: HTTP method for trace
            extra_headers: Extra headers to add
            skip_intercept: Skip manual intercept even if enabled

        Returns:
            Tuple of (response_dict, trace_id)
        """
        trace_id = generate_trace_id()
        start_time = datetime.utcnow()

        # Get adapter
        adapter = self.get_adapter(provider)
        if not adapter:
            raise ValueError(f"Unknown provider: {provider}. Available: {list(self.adapters.keys())}")

        # Check if manual intercept is enabled
        use_intercept = not skip_intercept and is_intercept_mode_enabled()

        try:
            # Normalize to canonical format
            canonical_request = adapter.normalize_to_canonical(raw_request)
            canonical_request.headers = extra_headers or {}

            # Apply request rules
            modified_request, request_rule_results = self.rule_engine.process_request(
                canonical_request, raw_request
            )

            # Apply passive rules
            passive_rule_results = self.rule_engine.process_passive(modified_request, scope="request")

            # Merge rule results for trace
            all_request_rules = request_rule_results
            for r in passive_rule_results.matched_rules:
                all_request_rules.add_result(r)

            # Create trace request record
            trace_request = TraceRequest(
                raw=raw_request,
                modified=modified_request.model_dump(exclude_none=True),
                rule_results=all_request_rules,
                timestamp=start_time,
            )

            # Create initial trace
            trace = Trace(
                trace_id=trace_id,
                provider=provider,
                model=canonical_request.model,
                endpoint=endpoint,
                method=method,
                request=trace_request,
                start_time=start_time,
                metadata={"dry_run": self.config.trace.dry_run, "intercepted": use_intercept},
            )

            if use_intercept:
                # Manual intercept mode - wait for user action
                session = intercept_store.create_session(
                    request_data=modified_request.model_dump(exclude_none=True),
                    endpoint=endpoint,
                    method=method,
                )

                # Save trace with pending status
                self.trace_store.save_trace(trace)

                # Wait for user to forward or drop
                status = await wait_for_session_action(session.session_id, timeout=300)

                if status == "dropped":
                    trace.end_time = datetime.utcnow()
                    trace.duration_ms = int((trace.end_time - start_time).total_seconds() * 1000)
                    trace.error = TraceError(type="Intercepted", message="Request dropped by user")
                    self.trace_store.save_trace(trace)
                    return {"error": {"message": "Request dropped in intercept mode"}}, trace_id

                # User forwarded - get potentially modified request
                updated_session = intercept_store.get_session(session.session_id)
                if updated_session and updated_session.modified_request:
                    # Use modified request
                    final_request_data = updated_session.modified_request
                else:
                    final_request_data = modified_request.model_dump(exclude_none=True)

                # Re-convert to canonical for sending
                final_canonical = adapter.normalize_to_canonical(final_request_data)

                # Invoke upstream with potentially modified request
                canonical_response, raw_upstream_response = await adapter.invoke(
                    final_canonical, extra_headers
                )

                # Check if we need to intercept response
                # User can modify response if the session is still active
                session = intercept_store.get_session(session.session_id)
                if session and session.intercept_response:
                    # User wants to intercept response - store and wait
                    intercept_store.set_upstream_response(
                        session.session_id,
                        raw_upstream_response,
                    )

                    # Wait for user action on response
                    status = await wait_for_session_action(session.session_id, timeout=300)

                    if status == "dropped":
                        trace.end_time = datetime.utcnow()
                        trace.duration_ms = int((trace.end_time - start_time).total_seconds() * 1000)
                        trace.error = TraceError(type="Intercepted", message="Response dropped by user")
                        self.trace_store.save_trace(trace)
                        return {"error": {"message": "Response dropped in intercept mode"}}, trace_id

                    # Get potentially modified response
                    updated_session = intercept_store.get_session(session.session_id)
                    if updated_session and updated_session.modified_response:
                        raw_upstream_response = updated_session.modified_response

                    # Mark as fully completed
                    intercept_store.mark_response_sent(session.session_id)

                    # Re-parse as canonical response
                    canonical_response = adapter.normalize_response(
                        raw_upstream_response, final_canonical
                    )
            else:
                # Normal mode - no intercept
                # Invoke upstream
                canonical_response, raw_upstream_response = await adapter.invoke(
                    modified_request, extra_headers
                )

            # Apply response rules
            modified_response, response_rule_results = self.rule_engine.process_response(
                canonical_response, modified_request
            )

            # Apply passive rules on response
            passive_response_rules = self.rule_engine.process_passive(modified_response, scope="response")

            # Merge rule results
            all_response_rules = response_rule_results
            for r in passive_response_rules.matched_rules:
                all_response_rules.add_result(r)

            end_time = datetime.utcnow()
            duration_ms = int((end_time - start_time).total_seconds() * 1000)

            # Create trace response record
            trace_response = TraceResponse(
                raw=raw_upstream_response,
                modified=adapter.denormalize_response(modified_response, raw_request),
                rule_results=all_response_rules,
                timestamp=end_time,
            )

            # Update trace
            trace.response = trace_response
            trace.end_time = end_time
            trace.duration_ms = duration_ms

            # Save trace
            self.trace_store.save_trace(trace)

            # Build final response
            final_response = adapter.denormalize_response(modified_response, raw_request)

            # Add trace header info to response metadata
            if not isinstance(final_response, dict):
                final_response = {"response": final_response}

            return final_response, trace_id

        except httpx.HTTPStatusError as e:
            return await self._handle_error(
                trace_id, provider, canonical_request.model, endpoint, method, start_time, e
            )
        except Exception as e:
            return await self._handle_error(
                trace_id, provider, canonical_request.model, endpoint, method, start_time, e
            )

    async def replay_trace(
        self,
        trace_id: str,
        use_modified: bool = False,
        override_provider: Optional[str] = None,
        override_model: Optional[str] = None,
    ) -> Tuple[Dict[str, Any], str]:
        """Replay a trace."""
        trace = self.trace_store.get_trace(trace_id)
        if not trace:
            raise ValueError(f"Trace not found: {trace_id}")

        if use_modified and trace.request.modified:
            request_to_replay = trace.request.modified
        else:
            request_to_replay = trace.request.raw

        provider = override_provider or trace.provider
        if override_model:
            request_to_replay["model"] = override_model

        return await self.process_request(
            provider=provider,
            raw_request=request_to_replay,
            endpoint=f"/replay/{trace_id}",
        )

    async def _handle_error(
        self,
        trace_id: str,
        provider: str,
        model: str,
        endpoint: str,
        method: str,
        start_time: datetime,
        error: Exception,
    ) -> Tuple[Dict[str, Any], str]:
        """Handle an error during proxy processing."""
        from app.schemas.traces import Trace, TraceError, TraceRequest

        end_time = datetime.utcnow()

        trace = Trace(
            trace_id=trace_id,
            provider=provider,
            model=model,
            endpoint=endpoint,
            method=method,
            request=TraceRequest(raw={}, timestamp=start_time),
            response=None,
            start_time=start_time,
            end_time=end_time,
            duration_ms=int((end_time - start_time).total_seconds() * 1000),
            error=TraceError(
                type=type(error).__name__,
                message=str(error),
            ),
        )

        self.trace_store.save_trace(trace)

        error_response = {
            "error": {
                "message": str(error),
                "type": type(error).__name__,
            }
        }

        return error_response, trace_id


def enable_intercept_mode():
    """Enable manual intercept mode."""
    global intercept_mode_enabled
    with intercept_mode_lock:
        intercept_mode_enabled = True


def disable_intercept_mode():
    """Disable manual intercept mode."""
    global intercept_mode_enabled
    with intercept_mode_lock:
        intercept_mode_enabled = False


def is_intercept_mode_enabled() -> bool:
    """Check if manual intercept mode is enabled."""
    with intercept_mode_lock:
        return intercept_mode_enabled
