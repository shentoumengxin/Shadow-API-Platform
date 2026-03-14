"""Pydantic models for LLM API requests and responses."""

from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field


# =============================================
# Message Models
# =============================================


class ContentBlock(BaseModel):
    """A block of content (text or tool use) in a message."""

    type: Literal["text", "tool_use", "tool_result"] = "text"
    text: Optional[str] = None
    id: Optional[str] = None
    name: Optional[str] = None
    input: Optional[Dict[str, Any]] = None


class Message(BaseModel):
    """A chat message."""

    role: Literal["system", "user", "assistant", "tool"]
    content: Union[str, List[ContentBlock]]
    name: Optional[str] = None
    tool_call_id: Optional[str] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None


class ToolDefinition(BaseModel):
    """A tool definition for function calling."""

    type: Literal["function"] = "function"
    function: Dict[str, Any]


# =============================================
# OpenAI-compatible Request/Response
# =============================================


class OpenAIChatRequest(BaseModel):
    """OpenAI-compatible chat completion request."""

    model: str
    messages: List[Message]
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    top_p: Optional[float] = None
    frequency_penalty: Optional[float] = None
    presence_penalty: Optional[float] = None
    stream: Optional[bool] = False
    stop: Optional[Union[str, List[str]]] = None
    tools: Optional[List[ToolDefinition]] = None
    tool_choice: Optional[Union[str, Dict[str, Any]]] = None
    user: Optional[str] = None

    class Config:
        extra = "allow"


class OpenAIChoice(BaseModel):
    """A choice from OpenAI chat completion response."""

    index: int
    message: Message
    finish_reason: Optional[str] = None
    logprobs: Optional[Dict[str, Any]] = None


class OpenAIUsage(BaseModel):
    """Token usage information."""

    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class OpenAIChatResponse(BaseModel):
    """OpenAI-compatible chat completion response."""

    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: List[OpenAIChoice]
    usage: Optional[OpenAIUsage] = None
    system_fingerprint: Optional[str] = None

    class Config:
        extra = "allow"


# =============================================
# Anthropic-compatible Request/Response
# =============================================


class AnthropicMessageRequest(BaseModel):
    """Anthropic messages API request."""

    model: str
    messages: List[Message]
    system: Optional[Union[str, List[ContentBlock]]] = None
    max_tokens: int = Field(default=1024, ge=1)
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    top_k: Optional[int] = None
    stream: Optional[bool] = False
    stop_sequences: Optional[List[str]] = None
    tools: Optional[List[Dict[str, Any]]] = None
    tool_choice: Optional[Dict[str, Any]] = None
    metadata: Optional[Dict[str, Any]] = None

    class Config:
        extra = "allow"


class AnthropicUsage(BaseModel):
    """Anthropic token usage."""

    input_tokens: int
    output_tokens: int


class AnthropicMessage(BaseModel):
    """Anthropic message response."""

    id: str
    type: str = "message"
    role: str = "assistant"
    content: List[ContentBlock]
    model: str
    stop_reason: Optional[str] = None
    stop_sequence: Optional[str] = None
    usage: Optional[AnthropicUsage] = None


class AnthropicMessageResponse(BaseModel):
    """Anthropic messages API response."""

    id: str
    type: str = "message"
    role: str = "assistant"
    content: List[ContentBlock]
    model: str
    stop_reason: Optional[str] = None
    stop_sequence: Optional[str] = None
    usage: Optional[AnthropicUsage] = None

    class Config:
        extra = "allow"


# =============================================
# Internal Canonical Models
# =============================================


class CanonicalRequest(BaseModel):
    """Internal canonical request format for unified processing."""

    provider: str  # openai, anthropic, etc.
    model: str
    messages: List[Message]
    system: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    top_p: Optional[float] = None
    tools: Optional[List[Dict[str, Any]]] = None
    tool_choice: Optional[Union[str, Dict[str, Any]]] = None
    stream: bool = False
    stop: Optional[Union[str, List[str]]] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    headers: Dict[str, str] = Field(default_factory=dict)

    class Config:
        extra = "allow"


class CanonicalResponse(BaseModel):
    """Internal canonical response format for unified processing."""

    id: str
    model: str
    provider: str
    content: Union[str, List[ContentBlock]]
    role: str = "assistant"
    finish_reason: Optional[str] = None
    usage: Optional[Dict[str, int]] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    class Config:
        extra = "allow"


# =============================================
# Proxy Request/Response Wrappers
# =============================================


class ProxyInvokeRequest(BaseModel):
    """Unified proxy invoke request."""

    provider: str
    model: str
    messages: List[Message]
    system: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    top_p: Optional[float] = None
    tools: Optional[List[Dict[str, Any]]] = None
    stream: bool = False

    class Config:
        extra = "allow"


class ProxyInvokeResponse(BaseModel):
    """Unified proxy invoke response."""

    success: bool
    provider: str
    model: str
    response: Dict[str, Any]
    trace_id: Optional[str] = None
    error: Optional[str] = None
    duration_ms: Optional[int] = None
