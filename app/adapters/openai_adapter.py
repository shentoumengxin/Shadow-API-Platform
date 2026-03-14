"""OpenAI-compatible adapter."""

import time
from typing import Any, Dict, List, Optional, Tuple

from app.adapters.base import BaseAdapter
from app.schemas.models import (
    CanonicalRequest,
    CanonicalResponse,
    Message,
    OpenAIChatRequest,
    OpenAIChatResponse,
    OpenAIChoice,
)


class OpenAIAdapter(BaseAdapter):
    """Adapter for OpenAI-compatible APIs.

    Supports:
    - OpenAI API
    - Any OpenAI-compatible endpoint (vLLM, LocalAI, etc.)
    """

    def get_provider_name(self) -> str:
        """Return provider name."""
        return "openai"

    def normalize_to_canonical(self, raw_request: Dict[str, Any]) -> CanonicalRequest:
        """Convert OpenAI request to canonical format."""
        # Parse using Pydantic model
        request = OpenAIChatRequest(**raw_request)

        # Extract system message if present
        system = None
        messages = []
        for msg in request.messages:
            if msg.role == "system":
                system = msg.content if isinstance(msg.content, str) else None
            else:
                messages.append(msg)

        return CanonicalRequest(
            provider="openai",
            model=request.model,
            messages=messages,
            system=system,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            top_p=request.top_p,
            tools=request.model_dump().get("tools"),
            tool_choice=request.tool_choice,
            stream=request.stream or False,
            stop=request.stop,
            metadata={},
            headers={},
        )

    def denormalize_from_canonical(
        self, canonical_request: CanonicalRequest
    ) -> Tuple[str, Dict[str, Any], Dict[str, str]]:
        """Convert canonical request to OpenAI format."""
        # Build messages list, including system message
        messages = []

        # Add system message first if present
        if canonical_request.system:
            messages.append({"role": "system", "content": canonical_request.system})

        # Add other messages
        for msg in canonical_request.messages:
            msg_dict = {"role": msg.role, "content": msg.content}
            if msg.name:
                msg_dict["name"] = msg.name
            if msg.tool_call_id:
                msg_dict["tool_call_id"] = msg.tool_call_id
            if msg.tool_calls:
                msg_dict["tool_calls"] = msg.tool_calls
            messages.append(msg_dict)

        # Build request body
        body = {
            "model": canonical_request.model,
            "messages": messages,
        }

        # Add optional parameters
        if canonical_request.temperature is not None:
            body["temperature"] = canonical_request.temperature
        if canonical_request.max_tokens is not None:
            body["max_tokens"] = canonical_request.max_tokens
        if canonical_request.top_p is not None:
            body["top_p"] = canonical_request.top_p
        if canonical_request.stop is not None:
            body["stop"] = canonical_request.stop
        if canonical_request.tools:
            body["tools"] = canonical_request.tools
        if canonical_request.tool_choice is not None:
            body["tool_choice"] = canonical_request.tool_choice

        # Build endpoint URL
        endpoint = f"{self.base_url}/chat/completions"

        # Build headers
        headers = self.get_default_headers()

        return endpoint, body, headers

    def normalize_response(
        self, provider_response: Dict[str, Any], canonical_request: CanonicalRequest
    ) -> CanonicalResponse:
        """Convert OpenAI response to canonical format."""
        response = OpenAIChatResponse(**provider_response)
        choice = response.choices[0] if response.choices else None

        content = ""
        finish_reason = None

        if choice and choice.message:
            content = choice.message.content or ""
            finish_reason = choice.finish_reason

        return CanonicalResponse(
            id=response.id,
            model=response.model,
            provider="openai",
            content=content,
            role="assistant",
            finish_reason=finish_reason,
            usage=response.usage.model_dump() if response.usage else None,
            metadata={},
        )

    def denormalize_response(
        self, canonical_response: CanonicalResponse, original_request: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Convert canonical response back to OpenAI format."""
        # Build a proper OpenAI response structure
        choice = {
            "index": 0,
            "message": {
                "role": canonical_response.role,
                "content": canonical_response.content,
            },
            "finish_reason": canonical_response.finish_reason,
        }

        response = {
            "id": canonical_response.id,
            "object": "chat.completion",
            "created": int(time.time()),
            "model": canonical_response.model,
            "choices": [choice],
        }

        if canonical_response.usage:
            response["usage"] = canonical_response.usage

        return response


class OpenAICompatibleAdapter(OpenAIAdapter):
    """Alias for OpenAIAdapter - same implementation for any OpenAI-compatible API."""

    pass
