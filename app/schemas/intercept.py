"""Schemas for manual intercept feature."""

from datetime import datetime
from typing import Any, Dict, List, Optional, Literal

from pydantic import BaseModel, Field


class InterceptSession(BaseModel):
    """A manual intercept session."""

    session_id: str
    created_at: datetime
    status: Literal["pending", "forwarded", "dropped", "modified", "waiting_response", "completed"]

    # Original request from client
    original_request: Dict[str, Any]

    # Modified request (if user edited)
    modified_request: Optional[Dict[str, Any]] = None

    # Upstream response (after forwarding)
    upstream_response: Optional[Dict[str, Any]] = None

    # Modified response (if user edited)
    modified_response: Optional[Dict[str, Any]] = None

    # Metadata
    endpoint: str
    method: str
    client_info: Optional[Dict[str, Any]] = None

    # Intercept flags
    intercept_request: bool = True  # Whether to intercept request
    intercept_response: bool = True  # Whether to intercept response


class InterceptCreateRequest(BaseModel):
    """Request to create an intercept session."""

    request_data: Dict[str, Any]
    endpoint: str
    method: str


class InterceptModifyRequest(BaseModel):
    """Request to modify an intercepted request."""

    modified_request: Dict[str, Any]
    action: Literal["forward", "drop"] = "forward"


class InterceptModifyResponse(BaseModel):
    """Request to modify an intercepted response."""

    modified_response: Dict[str, Any]
    action: Literal["send", "drop"] = "send"


class InterceptResponse(BaseModel):
    """Response for intercept API."""

    success: bool
    session_id: Optional[str] = None
    status: Optional[str] = None
    message: Optional[str] = None
    request: Optional[Dict[str, Any]] = None
    response: Optional[Dict[str, Any]] = None
