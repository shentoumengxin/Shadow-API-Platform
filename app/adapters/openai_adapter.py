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
    - OpenRouter API
    - Any OpenAI-compatible endpoint (vLLM, LocalAI, etc.)
    """

    def __init__(self, api_key: str, base_url: str = "https://api.openai.com/v1"):
        """Initialize adapter with API key and base URL.

        Args:
            api_key: API key for authentication
            base_url: Base URL for the API endpoint
        """
        super().__init__(api_key, base_url)
        # Detect if this is OpenRouter
        self.is_openrouter = "openrouter" in base_url.lower()

    def get_provider_name(self) -> str:
        """Return provider name."""
        return "openai"

    def get_default_headers(self) -> Dict[str, str]:
        """Get default headers for API requests.

        For OpenRouter, adds required identification headers.
        """
        headers = {
            "Content-Type": "application/json",
        }

        if self.is_openrouter:
            # OpenRouter uses different auth header
            headers["Authorization"] = f"Bearer {self.api_key}"
            # OpenRouter requires these headers for ranking
            headers["HTTP-Referer"] = "https://github.com/llm-research-proxy"
            headers["X-Title"] = "LLM Research Proxy"
        else:
            headers["Authorization"] = f"Bearer {self.api_key}"

        return headers

    def normalize_to_canonical(self, raw_request: Dict[str, Any]) -> CanonicalRequest:
        """Convert OpenAI request to canonical format."""
        # Ensure raw_request is a plain dict (not Pydantic model)
        # This prevents serialization issues later
        if hasattr(raw_request, 'model_dump'):
            raw_request = raw_request.model_dump(mode="json", exclude_none=True)

        # Parse using Pydantic model
        request = OpenAIChatRequest(**raw_request)

        # Extract system message if present
        system = None
        messages = []
        for msg in request.messages:
            if msg.role == "system":
                # Handle content that may be ContentBlock list
                if isinstance(msg.content, str):
                    system = msg.content
                elif isinstance(msg.content, list):
                    # Extract text from ContentBlock objects
                    texts = []
                    for block in msg.content:
                        if hasattr(block, 'text') and block.text:
                            texts.append(block.text)
                        elif isinstance(block, dict) and block.get('text'):
                            texts.append(block['text'])
                    system = "\n".join(texts)
                else:
                    system = None
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
            system_content = canonical_request.system
            if isinstance(system_content, list):
                # Extract text from ContentBlock objects
                texts = []
                for block in system_content:
                    if hasattr(block, 'text') and block.text:
                        texts.append(block.text)
                    elif isinstance(block, dict) and block.get('text'):
                        texts.append(block['text'])
                system_content = "\n".join(texts)
            messages.append({"role": "system", "content": system_content})

        # Add other messages
        for msg in canonical_request.messages:
            # Handle content that may be ContentBlock list
            content = msg.content
            if isinstance(content, list):
                # Extract text from ContentBlock objects
                texts = []
                for block in content:
                    if hasattr(block, 'text') and block.text:
                        texts.append(block.text)
                    elif isinstance(block, dict) and block.get('text'):
                        texts.append(block['text'])
                content = "\n".join(texts)
            msg_dict = {"role": msg.role, "content": content}
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
        if canonical_request.stream:
            body["stream"] = True

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
        tool_calls = None

        if choice and choice.message:
            # Use content if available, otherwise fallback to reasoning
            content = choice.message.content or ""
            if not content and hasattr(choice.message, 'reasoning') and choice.message.reasoning:
                content = choice.message.reasoning
            finish_reason = choice.finish_reason
            tool_calls = choice.message.tool_calls

        # Build metadata with tool_calls if present
        metadata = {}
        if tool_calls:
            metadata["tool_calls"] = tool_calls

        return CanonicalResponse(
            id=response.id,
            model=response.model,
            provider="openai",
            content=content,
            role="assistant",
            finish_reason=finish_reason,
            usage=response.usage.model_dump() if response.usage else None,
            metadata=metadata,
        )

    def denormalize_response(
        self, canonical_response: CanonicalResponse, original_request: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Convert canonical response back to OpenAI format."""
        # Build message
        message = {
            "role": canonical_response.role,
            "content": canonical_response.content or "",
        }

        # Add tool_calls if present in metadata
        tool_calls = canonical_response.metadata.get("tool_calls")
        if tool_calls:
            message["tool_calls"] = tool_calls

        # Build a proper OpenAI response structure
        # Note: Always return content as string (standard OpenAI format)
        # even if request used ContentBlock format
        choice = {
            "index": 0,
            "message": message,
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
