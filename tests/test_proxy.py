"""Tests for LLM Research Proxy."""

import json
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

# Add app to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.schemas.models import CanonicalRequest, Message
from app.schemas.rules import Rule, RuleAction, RuleMatch


# =============================================
# Fixtures
# =============================================


@pytest.fixture
def sample_openai_request():
    """Sample OpenAI-format request."""
    return {
        "model": "gpt-3.5-turbo",
        "messages": [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Hello, how are you?"},
        ],
        "temperature": 0.7,
        "max_tokens": 100,
    }


@pytest.fixture
def sample_anthropic_request():
    """Sample Anthropic-format request."""
    return {
        "model": "claude-3-haiku-20240307",
        "messages": [
            {"role": "user", "content": "Hello, how are you?"},
        ],
        "system": "You are a helpful assistant.",
        "max_tokens": 1024,
    }


@pytest.fixture
def sample_rule():
    """Sample rule for testing."""
    return Rule(
        id="test_rule",
        enabled=True,
        priority=50,
        scope="request",
        description="Test rule for testing",
        match=RuleMatch(role="user", keyword="hello"),
        action=RuleAction(type="append_text", text=" [APPENDED]"),
    )


# =============================================
# Model Tests
# =============================================


class TestModels:
    """Tests for Pydantic models."""

    def test_openai_request_parsing(self, sample_openai_request):
        """Test OpenAI request parsing."""
        from app.schemas.models import OpenAIChatRequest

        request = OpenAIChatRequest(**sample_openai_request)
        assert request.model == "gpt-3.5-turbo"
        assert len(request.messages) == 2
        assert request.messages[0].role == "system"
        assert request.messages[1].role == "user"
        assert request.temperature == 0.7

    def test_anthropic_request_parsing(self, sample_anthropic_request):
        """Test Anthropic request parsing."""
        from app.schemas.models import AnthropicMessageRequest

        request = AnthropicMessageRequest(**sample_anthropic_request)
        assert request.model == "claude-3-haiku-20240307"
        assert len(request.messages) == 1
        assert request.system == "You are a helpful assistant."
        assert request.max_tokens == 1024

    def test_canonical_request_creation(self, sample_openai_request):
        """Test canonical request creation."""
        from app.schemas.models import OpenAIChatRequest

        parsed = OpenAIChatRequest(**sample_openai_request)

        # Extract system message
        system = None
        messages = []
        for msg in parsed.messages:
            if msg.role == "system":
                system = msg.content
            else:
                messages.append(msg)

        canonical = CanonicalRequest(
            provider="openai",
            model=parsed.model,
            messages=messages,
            system=system,
            temperature=parsed.temperature,
            max_tokens=parsed.max_tokens,
        )

        assert canonical.provider == "openai"
        assert canonical.model == "gpt-3.5-turbo"
        assert canonical.system == "You are a helpful assistant."
        assert len(canonical.messages) == 1


# =============================================
# Rule Engine Tests
# =============================================


class TestRuleEngine:
    """Tests for the rule engine."""

    def test_rule_matching(self, sample_rule):
        """Test rule matching logic."""
        from app.rules.matchers import RuleMatcher

        request = CanonicalRequest(
            provider="openai",
            model="gpt-3.5-turbo",
            messages=[Message(role="user", content="Hello, how are you?")],
        )

        matcher = RuleMatcher(sample_rule)
        assert matcher.match_request(request) is True

    def test_rule_not_matching(self, sample_rule):
        """Test rule not matching."""
        from app.rules.matchers import RuleMatcher

        request = CanonicalRequest(
            provider="openai",
            model="gpt-3.5-turbo",
            messages=[Message(role="user", content="Goodbye!")],
        )

        matcher = RuleMatcher(sample_rule)
        assert matcher.match_request(request) is False

    def test_rule_action_append(self, sample_rule):
        """Test append text action."""
        from app.rules.actions import RuleActionExecutor

        request = CanonicalRequest(
            provider="openai",
            model="gpt-3.5-turbo",
            messages=[Message(role="user", content="Hello")],
        )

        executor = RuleActionExecutor(sample_rule)
        modified, was_modified, description = executor.execute_on_request(request)

        assert was_modified is True
        assert "[APPENDED]" in modified.messages[0].content

    def test_rule_action_replace(self):
        """Test replace text action."""
        rule = Rule(
            id="replace_rule",
            enabled=True,
            priority=50,
            scope="request",
            description="Replace test",
            match=RuleMatch(role="user", keyword="bad"),
            action=RuleAction(type="replace_text", original="bad", replacement="good"),
        )

        from app.rules.actions import RuleActionExecutor

        request = CanonicalRequest(
            provider="openai",
            model="gpt-3.5-turbo",
            messages=[Message(role="user", content="This is bad")],
        )

        executor = RuleActionExecutor(rule)
        modified, was_modified, description = executor.execute_on_request(request)

        assert was_modified is True
        assert "good" in modified.messages[0].content
        assert "bad" not in modified.messages[0].content

    def test_dry_run_mode(self, sample_rule):
        """Test dry run mode doesn't modify."""
        from app.rules.actions import RuleActionExecutor

        request = CanonicalRequest(
            provider="openai",
            model="gpt-3.5-turbo",
            messages=[Message(role="user", content="Hello")],
        )

        executor = RuleActionExecutor(sample_rule)
        modified, was_modified, description = executor.execute_on_request(
            request, dry_run=True
        )

        assert was_modified is True  # Indicates would modify
        assert "[DRY_RUN]" in description
        assert modified.messages[0].content == "Hello"  # But didn't actually change


# =============================================
# Adapter Tests
# =============================================


class TestAdapters:
    """Tests for provider adapters."""

    def test_openai_adapter_normalize(self, sample_openai_request):
        """Test OpenAI adapter normalization."""
        from app.adapters.openai_adapter import OpenAIAdapter

        adapter = OpenAIAdapter(api_key="test-key", base_url="https://api.openai.com/v1")
        canonical = adapter.normalize_to_canonical(sample_openai_request)

        assert canonical.provider == "openai"
        assert canonical.model == "gpt-3.5-turbo"
        assert canonical.system == "You are a helpful assistant."

    def test_openai_adapter_denormalize(self, sample_openai_request):
        """Test OpenAI adapter denormalization."""
        from app.adapters.openai_adapter import OpenAIAdapter
        from app.schemas.models import CanonicalRequest, Message

        adapter = OpenAIAdapter(api_key="test-key", base_url="https://api.openai.com/v1")

        canonical = CanonicalRequest(
            provider="openai",
            model="gpt-4",
            messages=[Message(role="user", content="Test")],
            system="System prompt",
            temperature=0.5,
            max_tokens=500,
        )

        endpoint, body, headers = adapter.denormalize_from_canonical(canonical)

        assert endpoint == "https://api.openai.com/v1/chat/completions"
        assert body["model"] == "gpt-4"
        assert body["temperature"] == 0.5
        assert len(body["messages"]) == 2  # System + user

    def test_anthropic_adapter_normalize(self, sample_anthropic_request):
        """Test Anthropic adapter normalization."""
        from app.adapters.anthropic_adapter import AnthropicAdapter

        adapter = AnthropicAdapter(api_key="test-key", base_url="https://api.anthropic.com")
        canonical = adapter.normalize_to_canonical(sample_anthropic_request)

        assert canonical.provider == "anthropic"
        assert canonical.model == "claude-3-haiku-20240307"
        assert canonical.system == "You are a helpful assistant."

    def test_anthropic_adapter_headers(self):
        """Test Anthropic adapter headers."""
        from app.adapters.anthropic_adapter import AnthropicAdapter

        adapter = AnthropicAdapter(api_key="test-key", base_url="https://api.anthropic.com")
        headers = adapter.get_default_headers()

        assert "x-api-key" in headers
        assert "anthropic-version" in headers
        assert headers["x-api-key"] == "test-key"


# =============================================
# Trace Store Tests
# =============================================


class TestTraceStore:
    """Tests for trace storage."""

    @pytest.fixture
    def temp_trace_store(self, tmp_path):
        """Create a temporary trace store."""
        from app.services.trace_store import TraceStore

        store = TraceStore(str(tmp_path))
        return store

    def test_save_and_get_trace(self, temp_trace_store):
        """Test saving and retrieving a trace."""
        from datetime import datetime

        from app.schemas.traces import Trace, TraceRequest

        trace = Trace(
            trace_id="test_trace_123",
            provider="openai",
            model="gpt-3.5-turbo",
            endpoint="/v1/chat/completions",
            method="POST",
            request=TraceRequest(raw={"test": "data"}, timestamp=datetime.utcnow()),
            start_time=datetime.utcnow(),
        )

        saved_id = temp_trace_store.save_trace(trace)
        assert saved_id == "test_trace_123"

        retrieved = temp_trace_store.get_trace("test_trace_123")
        assert retrieved is not None
        assert retrieved.provider == "openai"
        assert retrieved.model == "gpt-3.5-turbo"

    def test_list_traces(self, temp_trace_store):
        """Test listing traces."""
        from datetime import datetime

        from app.schemas.traces import Trace, TraceRequest

        for i in range(5):
            trace = Trace(
                trace_id=f"test_trace_{i}",
                provider="openai",
                model="gpt-3.5-turbo",
                endpoint="/v1/chat/completions",
                method="POST",
                request=TraceRequest(raw={"test": "data"}, timestamp=datetime.utcnow()),
                start_time=datetime.utcnow(),
            )
            temp_trace_store.save_trace(trace)

        traces = temp_trace_store.list_traces(limit=10)
        assert len(traces) == 5


# =============================================
# API Tests
# =============================================


class TestAPI:
    """Tests for FastAPI endpoints."""

    @pytest.fixture
    def client(self):
        """Create test client."""
        from fastapi.testclient import TestClient

        # Mock environment
        with patch.dict(
            os.environ,
            {
                "OPENAI_API_KEY": "test-key",
                "ANTHROPIC_API_KEY": "test-key",
            },
        ):
            from app.main import app

            with TestClient(app) as client:
                yield client

    def test_health_endpoint(self, client):
        """Test health endpoint."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"

    def test_root_endpoint(self, client):
        """Test root endpoint."""
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert "LLM Research Proxy" in data["name"]

    def test_traces_endpoint_empty(self, client):
        """Test traces endpoint when empty."""
        response = client.get("/traces")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    def test_rules_endpoint(self, client):
        """Test rules endpoint."""
        response = client.get("/rules")
        assert response.status_code == 200
        data = response.json()
        assert "rules" in data

    @pytest.mark.asyncio
    async def test_openai_endpoint_mock(self, sample_openai_request):
        """Test OpenAI endpoint with mock."""
        from app.config import Config
        from app.services.proxy import ProxyService
        from app.schemas.traces import TraceRequest

        # Create a proxy service with test config
        config = Config(
            providers={
                "openai": {"api_key": "test-key", "base_url": "https://api.openai.com/v1"},
                "anthropic": {"api_key": "test-key", "base_url": "https://api.anthropic.com"},
            },
            trace={"dry_run": True},  # Enable dry run to avoid actual modifications
        )
        proxy = ProxyService(config)

        # Mock the HTTP call
        mock_response = {
            "id": "test-123",
            "object": "chat.completion",
            "created": 1234567890,
            "model": "gpt-3.5-turbo",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "Hello!"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }

        with patch.object(
            proxy.adapters["openai"],
            "invoke",
            new=AsyncMock(return_value=(None, mock_response)),
        ):
            response, trace_id = await proxy.process_request(
                provider="openai",
                raw_request=sample_openai_request,
            )

            assert trace_id is not None
            # Response should have error key only if there was an error
            # In dry run mode with mocked response, it should succeed


# =============================================
# Integration Tests
# =============================================


class TestIntegration:
    """Integration tests for the full flow."""

    def test_full_request_flow(self, sample_openai_request):
        """Test full request flow through proxy."""
        from app.config import Config
        from app.services.proxy import ProxyService

        # Create config without real API keys
        config = Config(
            providers={
                "openai": {"api_key": None},  # No key for testing
                "anthropic": {"api_key": None},
            }
        )

        # Proxy should initialize even without keys
        proxy = ProxyService(config)

        # OpenAI adapter should not be available without key
        assert "openai" not in proxy.adapters


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
