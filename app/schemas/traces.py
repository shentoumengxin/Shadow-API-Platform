"""Trace-related schemas for audit and replay."""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from .rules import RuleEngineResult


class TraceRequest(BaseModel):
    """Trace information for a request."""

    raw: Dict[str, Any]
    modified: Optional[Dict[str, Any]] = None
    rule_results: Optional[RuleEngineResult] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class TraceResponse(BaseModel):
    """Trace information for a response."""

    raw: Optional[Dict[str, Any]] = None
    modified: Optional[Dict[str, Any]] = None
    rule_results: Optional[RuleEngineResult] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class TraceError(BaseModel):
    """Error information in a trace."""

    type: str
    message: str
    traceback: Optional[str] = None


class Trace(BaseModel):
    """Complete trace record for a request/response cycle."""

    trace_id: str
    provider: str
    model: str
    endpoint: str
    method: str

    # Request tracing
    request: TraceRequest

    # Response tracing
    response: Optional[TraceResponse] = None

    # Timing
    start_time: datetime
    end_time: Optional[datetime] = None
    duration_ms: Optional[int] = None

    # Error handling
    error: Optional[TraceError] = None

    # Metadata
    metadata: Dict[str, Any] = Field(default_factory=dict)
    tags: List[str] = Field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert trace to dictionary for JSON serialization."""
        return {
            "trace_id": self.trace_id,
            "provider": self.provider,
            "model": self.model,
            "endpoint": self.endpoint,
            "method": self.method,
            "request": {
                "raw": self.request.raw,
                "modified": self.request.modified,
                "rule_results": self.request.rule_results.to_dict()
                if self.request.rule_results
                else None,
                "timestamp": self.request.timestamp.isoformat(),
            },
            "response": {
                "raw": self.response.raw if self.response else None,
                "modified": self.response.modified if self.response else None,
                "rule_results": self.response.rule_results.to_dict()
                if self.response and self.response.rule_results
                else None,
                "timestamp": self.response.timestamp.isoformat() if self.response else None,
            },
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "duration_ms": self.duration_ms,
            "error": self.error.dict() if self.error else None,
            "metadata": self.metadata,
            "tags": self.tags,
        }


class TraceSummary(BaseModel):
    """Summary information for trace listing."""

    trace_id: str
    provider: str
    model: str
    endpoint: str
    start_time: datetime
    duration_ms: Optional[int] = None
    has_error: bool = False
    rules_matched: int = 0


class ReplayRequest(BaseModel):
    """Request to replay a trace."""

    use_modified_request: bool = Field(
        default=False, description="Use modified request instead of raw"
    )
    override_provider: Optional[str] = Field(
        default=None, description="Override provider for replay"
    )
    override_model: Optional[str] = Field(
        default=None, description="Override model for replay"
    )
