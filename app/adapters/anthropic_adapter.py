"""Anthropic adapter."""

import time
from typing import Any, Dict, List, Optional, Tuple, Union

from app.adapters.base import BaseAdapter
from app.schemas.models import (
    CanonicalRequest,
    CanonicalResponse,
    ContentBlock,
    Message,
)


class AnthropicAdapter(BaseAdapter):
    """Adapter for Anthropic API.

    Supports:
    - Anthropic Messages API
    - Tool use
    """

    # Anthropic API version header
    ANTHROPIC_VERSION = "2023-06-01"

    def get_provider_name(self) -> str:
        """Return provider name."""
        return "anthropic"

    def get_auth_headers(self) -> Dict[str, str]:
        """Get Anthropic-specific authentication headers."""
        return {
            "x-api-key": self.api_key,
        }

    def get_default_headers(self) -> Dict[str, str]:
        """Get default headers for Anthropic API."""
        return {
            "Content-Type": "application/json",
            "anthropic-version": self.ANTHROPIC_VERSION,
            **self.get_auth_headers(),
        }

    def normalize_to_canonical(self, raw_request: Dict[str, Any]) -> CanonicalRequest:
        """Convert Anthropic request to canonical format."""
        # Extract fields from Anthropic format
        model = raw_request.get("model", "claude-3-opus-20240229")
        messages = raw_request.get("messages", [])
        system = raw_request.get("system")
        max_tokens = raw_request.get("max_tokens", 1024)
        temperature = raw_request.get("temperature")
        top_p = raw_request.get("top_p")
        tools = raw_request.get("tools")
        tool_choice = raw_request.get("tool_choice")

        # Parse messages into Message objects
        parsed_messages = []
        for msg in messages:
            parsed_messages.append(
                Message(
                    role=msg.get("role", "user"),
                    content=msg.get("content", ""),
                    name=msg.get("name"),
                )
            )

        # Handle system - can be string or list of content blocks
        system_str = None
        if isinstance(system, str):
            system_str = system
        elif isinstance(system, list) and system:
            # Take text from first content block
            first_block = system[0]
            if isinstance(first_block, str):
                system_str = first_block
            elif isinstance(first_block, dict):
                system_str = first_block.get("text")

        return CanonicalRequest(
            provider="anthropic",
            model=model,
            messages=parsed_messages,
            system=system_str,
            temperature=temperature,
            max_tokens=max_tokens,
            top_p=top_p,
            tools=tools,
            tool_choice=tool_choice,
            stream=raw_request.get("stream", False),
            metadata={},
            headers={},
        )

    def denormalize_from_canonical(
        self, canonical_request: CanonicalRequest
    ) -> Tuple[str, Dict[str, Any], Dict[str, str]]:
        """Convert canonical request to Anthropic format."""
        # Build messages for Anthropic format
        messages = []
        for msg in canonical_request.messages:
            msg_dict = {
                "role": msg.role,
                "content": msg.content,
            }
            messages.append(msg_dict)

        # Build request body
        body = {
            "model": canonical_request.model,
            "messages": messages,
            "max_tokens": canonical_request.max_tokens or 1024,
        }

        # Add system if present
        if canonical_request.system:
            body["system"] = canonical_request.system

        # Add optional parameters
        if canonical_request.temperature is not None:
            body["temperature"] = canonical_request.temperature
        if canonical_request.top_p is not None:
            body["top_p"] = canonical_request.top_p
        if canonical_request.tools:
            body["tools"] = canonical_request.tools
        if canonical_request.tool_choice is not None:
            body["tool_choice"] = canonical_request.tool_choice
        if canonical_request.stream:
            body["stream"] = True

        # Build endpoint URL
        endpoint = f"{self.base_url}/v1/messages"

        # Build headers
        headers = self.get_default_headers()

        return endpoint, body, headers

    def _parse_content(self, content: Any) -> Union[str, List[ContentBlock]]:
        """Parse content from various formats."""
        if isinstance(content, str):
            return content

        if isinstance(content, list):
            blocks = []
            for item in content:
                if isinstance(item, str):
                    blocks.append(ContentBlock(type="text", text=item))
                elif isinstance(item, dict):
                    block_type = item.get("type", "text")
                    if block_type == "text":
                        blocks.append(ContentBlock(type="text", text=item.get("text", "")))
                    elif block_type == "tool_use":
                        blocks.append(
                            ContentBlock(
                                type="tool_use",
                                id=item.get("id"),
                                name=item.get("name"),
                                input=item.get("input"),
                            )
                        )
                    elif block_type == "tool_result":
                        blocks.append(
                            ContentBlock(
                                type="tool_result",
                                text=item.get("content"),
                            )
                        )
            return blocks

        return str(content)

    def normalize_response(
        self, provider_response: Dict[str, Any], canonical_request: CanonicalRequest
    ) -> CanonicalResponse:
        """Convert Anthropic response to canonical format."""
        # Parse response fields
        response_id = provider_response.get("id", "")
        model = provider_response.get("model", canonical_request.model)
        content = provider_response.get("content", [])
        stop_reason = provider_response.get("stop_reason")
        usage = provider_response.get("usage", {})

        # Extract text content
        text_content = ""
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    text_content += block.get("text", "")
                elif isinstance(block, ContentBlock) and block.type == "text":
                    text_content += block.text or ""
        elif isinstance(content, str):
            text_content = content

        # Convert usage
        usage_dict = None
        if usage:
            usage_dict = {
                "prompt_tokens": usage.get("input_tokens", 0),
                "completion_tokens": usage.get("output_tokens", 0),
                "total_tokens": usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
            }

        return CanonicalResponse(
            id=response_id,
            model=model,
            provider="anthropic",
            content=text_content,
            role="assistant",
            finish_reason=stop_reason,
            usage=usage_dict,
            metadata={"raw_content": content} if isinstance(content, list) else {},
        )

    def denormalize_response(
        self, canonical_response: CanonicalResponse, original_request: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Convert canonical response back to Anthropic format."""
        # Build content - for Anthropic, we use text blocks
        content = [{"type": "text", "text": canonical_response.content}]

        # Check if there's raw content from metadata (preserves tool calls)
        raw_content = canonical_response.metadata.get("raw_content")
        if raw_content:
            content = raw_content

        response = {
            "id": canonical_response.id,
            "type": "message",
            "role": canonical_response.role,
            "content": content,
            "model": canonical_response.model,
            "stop_reason": canonical_response.finish_reason,
        }

        if canonical_response.usage:
            usage = canonical_response.usage
            response["usage"] = {
                "input_tokens": usage.get("prompt_tokens", 0),
                "output_tokens": usage.get("completion_tokens", 0),
            }

        return response
