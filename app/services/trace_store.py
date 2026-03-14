"""File-based trace storage."""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.schemas.traces import Trace, TraceSummary
from app.utils.ids import generate_trace_id
from app.utils.logging import JsonlWriter


class TraceStore:
    """File-based trace storage.

    Stores traces in two ways:
    1. Individual JSON files per trace in logs/traces/
    2. Index file (JSONL) for quick listing in logs/index.jsonl
    """

    def __init__(self, logs_dir: str = "logs"):
        """Initialize the trace store.

        Args:
            logs_dir: Base directory for logs
        """
        self.logs_dir = Path(logs_dir)
        self.traces_dir = self.logs_dir / "traces"
        self.index_file = self.logs_dir / "index.jsonl"

        # Ensure directories exist
        self.traces_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)

        # Index writer
        self.index_writer = JsonlWriter(str(self.index_file))

    def save_trace(self, trace: Trace) -> str:
        """Save a trace to storage.

        Args:
            trace: Trace object to save

        Returns:
            The trace ID
        """
        trace_id = trace.trace_id

        # Save individual trace file
        trace_file = self.traces_dir / f"{trace_id}.json"
        trace_data = trace.to_dict()

        with open(trace_file, "w", encoding="utf-8") as f:
            json.dump(trace_data, f, indent=2, default=str)

        # Append to index
        index_entry = {
            "trace_id": trace_id,
            "provider": trace.provider,
            "model": trace.model,
            "endpoint": trace.endpoint,
            "method": trace.method,
            "start_time": trace.start_time.isoformat(),
            "end_time": trace.end_time.isoformat() if trace.end_time else None,
            "duration_ms": trace.duration_ms,
            "has_error": trace.error is not None,
            "rules_matched": len(trace.request.rule_results.matched_rules)
            if trace.request.rule_results
            else 0,
        }
        self.index_writer.write(index_entry)

        return trace_id

    def get_trace(self, trace_id: str) -> Optional[Trace]:
        """Retrieve a trace by ID.

        Args:
            trace_id: Trace ID to retrieve

        Returns:
            Trace object or None if not found
        """
        trace_file = self.traces_dir / f"{trace_id}.json"

        if not trace_file.exists():
            return None

        with open(trace_file, "r", encoding="utf-8") as f:
            trace_data = json.load(f)

        # Reconstruct Trace object
        return self._dict_to_trace(trace_data)

    def list_traces(
        self,
        limit: int = 100,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        has_error: Optional[bool] = None,
    ) -> List[TraceSummary]:
        """List traces with optional filtering.

        Args:
            limit: Maximum number of traces to return
            provider: Filter by provider
            model: Filter by model (substring match)
            has_error: Filter by error status

        Returns:
            List of TraceSummary objects
        """
        summaries = []

        # Read from index file (most recent first)
        index_records = self.index_writer.read_all()
        index_records.reverse()  # Most recent first

        for record in index_records:
            # Apply filters
            if provider and record.get("provider") != provider:
                continue
            if model and model.lower() not in record.get("model", "").lower():
                continue
            if has_error is not None and record.get("has_error") != has_error:
                continue

            summaries.append(
                TraceSummary(
                    trace_id=record["trace_id"],
                    provider=record["provider"],
                    model=record["model"],
                    endpoint=record["endpoint"],
                    start_time=datetime.fromisoformat(record["start_time"]),
                    duration_ms=record.get("duration_ms"),
                    has_error=record.get("has_error", False),
                    rules_matched=record.get("rules_matched", 0),
                )
            )

            if len(summaries) >= limit:
                break

        return summaries

    def delete_trace(self, trace_id: str) -> bool:
        """Delete a trace.

        Args:
            trace_id: Trace ID to delete

        Returns:
            True if deleted, False if not found
        """
        trace_file = self.traces_dir / f"{trace_id}.json"

        if not trace_file.exists():
            return False

        trace_file.unlink()
        return True

    def clear_all(self) -> int:
        """Clear all traces.

        Returns:
            Number of traces deleted
        """
        count = 0
        for trace_file in self.traces_dir.glob("*.json"):
            trace_file.unlink()
            count += 1

        # Truncate index file
        with open(self.index_file, "w", encoding="utf-8") as f:
            pass

        return count

    def _dict_to_trace(self, data: Dict[str, Any]) -> Trace:
        """Convert dictionary to Trace object.

        Args:
            data: Dictionary from JSON

        Returns:
            Trace object
        """
        # Import here to avoid circular imports
        from app.schemas.rules import RuleEngineResult, RuleExecutionResult
        from app.schemas.traces import TraceRequest, TraceResponse, TraceError

        # Reconstruct rule results
        def make_rule_results(raw: Optional[Dict]) -> Optional[RuleEngineResult]:
            if not raw:
                return None
            result = RuleEngineResult()
            for r in raw.get("matched_rules", []):
                result.add_result(
                    RuleExecutionResult(
                        rule_id=r["rule_id"],
                        matched=r["matched"],
                        modified=r["modified"],
                        description=r["description"],
                        details=r.get("details"),
                    )
                )
            result.modified = raw.get("modified", False)
            result.modifications = raw.get("modifications", [])
            return result

        # Reconstruct request
        req_data = data.get("request", {})
        request = TraceRequest(
            raw=req_data.get("raw", {}),
            modified=req_data.get("modified"),
            rule_results=make_rule_results(req_data.get("rule_results")),
            timestamp=datetime.fromisoformat(req_data["timestamp"]),
        )

        # Reconstruct response
        response = None
        resp_data = data.get("response")
        if resp_data:
            response = TraceResponse(
                raw=resp_data.get("raw"),
                modified=resp_data.get("modified"),
                rule_results=make_rule_results(resp_data.get("rule_results")),
                timestamp=datetime.fromisoformat(resp_data["timestamp"])
                if resp_data.get("timestamp")
                else datetime.utcnow(),
            )

        # Reconstruct error
        error = None
        err_data = data.get("error")
        if err_data:
            error = TraceError(
                type=err_data["type"],
                message=err_data["message"],
                traceback=err_data.get("traceback"),
            )

        return Trace(
            trace_id=data["trace_id"],
            provider=data["provider"],
            model=data["model"],
            endpoint=data["endpoint"],
            method=data["method"],
            request=request,
            response=response,
            start_time=datetime.fromisoformat(data["start_time"]),
            end_time=datetime.fromisoformat(data["end_time"]) if data.get("end_time") else None,
            duration_ms=data.get("duration_ms"),
            error=error,
            metadata=data.get("metadata", {}),
            tags=data.get("tags", []),
        )
