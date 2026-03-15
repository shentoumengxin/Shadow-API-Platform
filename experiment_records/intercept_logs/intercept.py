"""Schemas for manual intercept feature."""

import json
from datetime import datetime
from typing import Any, Dict, List, Optional, Literal, Union

from pydantic import BaseModel, Field, field_validator


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

    modified_request: Union[Dict[str, Any], str]
    action: Literal["forward", "drop"] = "forward"

    @field_validator('modified_request', mode='before')
    @classmethod
    def parse_modified_request(cls, v):
        """Parse modified_request if it's a JSON string."""
        if isinstance(v, str):
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                raise ValueError("modified_request must be a valid JSON object or string")
        return v


class InterceptModifyResponse(BaseModel):
    """Request to modify an intercepted response."""

    modified_response: Union[Dict[str, Any], str]
    action: Literal["send", "drop"] = "send"

    @field_validator('modified_response', mode='before')
    @classmethod
    def parse_modified_response(cls, v):
        """Parse modified_response if it's a JSON string."""
        if isinstance(v, str):
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                raise ValueError("modified_response must be a valid JSON object or string")
        return v


class InterceptResponse(BaseModel):
    """Response for intercept API."""

    success: bool
    session_id: Optional[str] = None
    status: Optional[str] = None
    message: Optional[str] = None
    request: Optional[Dict[str, Any]] = None
    response: Optional[Dict[str, Any]] = None
