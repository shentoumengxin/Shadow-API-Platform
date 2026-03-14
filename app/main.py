"""Main FastAPI application for LLM Research Proxy."""

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, StreamingResponse

from app.config import Config
from app.rules.engine import RuleEngine
from app.schemas.intercept import InterceptModifyRequest, InterceptModifyResponse
from app.schemas.models import (
    AnthropicMessageRequest,
    AnthropicMessageResponse,
    OpenAIChatRequest,
    OpenAIChatResponse,
    ProxyInvokeRequest,
    ProxyInvokeResponse,
)
from app.schemas.traces import ReplayRequest, Trace, TraceSummary
from app.services.intercept import intercept_store, wait_for_session_action
from app.services.proxy import ProxyService
from app.services.replay import ReplayService
from app.services.trace_store import TraceStore

# Load environment variables
load_dotenv()

# Initialize configuration
config = Config.from_env()

# Set up logging
logger = logging.getLogger("llm_research_proxy")
logger.setLevel(getattr(logging, config.trace.log_level.upper(), logging.INFO))
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    )
    logger.addHandler(handler)

# Create FastAPI app
app = FastAPI(
    title="LLM Research Proxy",
    description="Lightweight LLM API proxy for research and experimentation",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# Add CORS middleware for web frontend access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # For research purposes - restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize services
proxy_service = ProxyService(config)
trace_store = TraceStore("logs")
replay_service = ReplayService(proxy_service, trace_store)

# Initialize rule engine for rule management endpoints
rule_engine = RuleEngine(rules_dir=config.rules_dir, dry_run=config.trace.dry_run)


# =============================================
# Health & Status Endpoints
# =============================================


@app.get("/")
async def root():
    """Root endpoint - API information."""
    return {
        "name": "LLM Research Proxy",
        "version": "0.1.0",
        "description": "Lightweight LLM API proxy for research",
        "endpoints": {
            "docs": "/docs",
            "health": "/health",
            "openai_compat": "/v1/chat/completions",
            "anthropic_compat": "/v1/messages",
            "proxy_invoke": "/proxy/{provider}/invoke",
            "traces": "/traces",
            "replay": "/replay/{trace_id}",
        },
    }


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "providers_available": list(proxy_service.adapters.keys()),
        "trace_enabled": config.trace.enabled,
        "dry_run": config.trace.dry_run,
    }


# =============================================
# OpenAI-Compatible Endpoints
# =============================================


@app.post("/v1/chat/completions")
async def openai_chat_completions(
    request: OpenAIChatRequest,
    x_api_key: Optional[str] = Header(None, alias="x-api-key"),
    authorization: Optional[str] = Header(None),
):
    """OpenAI-compatible chat completions endpoint.

    This endpoint accepts OpenAI-format requests and forwards them
    to the configured upstream provider. Supports both streaming and non-streaming.
    """
    # Determine provider from model or use default
    model_str = request.model.lower()
    if "claude" in model_str:
        provider = "anthropic"
    else:
        provider = "openai"  # Default to OpenAI

    # Check if provider is available
    if provider not in proxy_service.adapters:
        raise HTTPException(
            status_code=400,
            detail=f"Provider '{provider}' is not configured. Available: {list(proxy_service.adapters.keys())}",
        )

    # Convert to dict for processing - use mode="json" for proper serialization
    raw_request = request.model_dump(mode="json", exclude_none=True)

    logger.debug(f"Received request: model={request.model}, stream={request.stream}, messages={len(request.messages)}")

    # Get user's API key from headers
    user_api_key = authorization or x_api_key
    if user_api_key and user_api_key.startswith("Bearer "):
        user_api_key = user_api_key[7:]  # Remove "Bearer " prefix

    # If user provided a placeholder/invalid key (like "zzh-key"), treat as empty
    # Valid OpenRouter keys start with "sk-or-", valid OpenAI keys start with "sk-"
    if user_api_key and not (user_api_key.startswith("sk-") or len(user_api_key) > 30):
        logger.debug(f"Ignoring invalid API key format: {user_api_key[:10]}...")
        user_api_key = None

    # Handle streaming requests
    if request.stream:
        return await _handle_streaming_request(provider, raw_request, user_api_key, "/v1/chat/completions")

    # Process through proxy (non-streaming)
    try:
        response, trace_id = await proxy_service.process_request(
            provider=provider,
            raw_request=raw_request,
            endpoint="/v1/chat/completions",
        )

        # Return with trace header
        return JSONResponse(
            content=response,
            headers={
                "X-Research-Trace-Id": trace_id,
                "X-Proxy-Lab": "true",
            },
        )
    except Exception as e:
        logger.error(f"Error processing OpenAI-compatible request: {e}")
        raise HTTPException(status_code=502, detail=str(e))


async def _handle_streaming_request(
    provider: str,
    raw_request: Dict[str, Any],
    user_api_key: Optional[str] = None,
    endpoint: str = "/v1/chat/completions",
    skip_intercept: bool = False,
):
    """Handle streaming request with intercept and trace support."""
    from datetime import datetime
    from app.services.intercept import intercept_store, wait_for_session_action
    from app.utils.ids import generate_trace_id
    from app.schemas.traces import Trace, TraceRequest, TraceResponse, TraceError

    adapter = proxy_service.adapters.get(provider)
    if not adapter:
        raise HTTPException(status_code=400, detail=f"Provider '{provider}' not available")

    trace_id = generate_trace_id()
    start_time = datetime.utcnow()

    # Normalize to canonical for rule processing
    try:
        canonical_request = adapter.normalize_to_canonical(raw_request)
        # Re-denormalize to get proper provider format (handles ContentBlock conversion)
        _, final_request_data, _ = adapter.denormalize_from_canonical(canonical_request)
    except Exception as e:
        logger.error(f"Failed to normalize request: {e}")
        raise HTTPException(status_code=400, detail=f"Invalid request format: {e}")

    # Apply request rules
    try:
        modified_request, request_rule_results = proxy_service.rule_engine.process_request(
            canonical_request, raw_request
        )
    except Exception as e:
        logger.error(f"Rule processing error: {e}")
        modified_request = canonical_request
        request_rule_results = None

    # Create trace request record
    trace_req = TraceRequest(
        raw=raw_request,
        modified=modified_request.model_dump(exclude_none=True) if modified_request else None,
        rule_results=request_rule_results,
        timestamp=start_time,
    )

    # Create initial trace
    trace = Trace(
        trace_id=trace_id,
        provider=provider,
        model=modified_request.model if modified_request else raw_request.get("model", "unknown"),
        endpoint=endpoint,
        method="POST",
        request=trace_req,
        start_time=start_time,
        metadata={"stream": True, "intercepted": False},
    )

    # Check if intercept mode is enabled
    from app.services.proxy import is_intercept_mode_enabled
    use_intercept = not skip_intercept and is_intercept_mode_enabled()

    if use_intercept:
        # Create intercept session
        session = intercept_store.create_session(
            request_data=modified_request.model_dump(exclude_none=True),
            endpoint=endpoint,
            method="POST",
        )

        # Save trace with pending status
        proxy_service.trace_store.save_trace(trace)

        # Wait for user action
        status = await wait_for_session_action(session.session_id, timeout=300)

        if status == "dropped":
            trace.end_time = datetime.utcnow()
            trace.duration_ms = int((trace.end_time - start_time).total_seconds() * 1000)
            trace.error = TraceError(type="Intercepted", message="Request dropped by user")
            proxy_service.trace_store.save_trace(trace)
            return JSONResponse(
                content={"error": {"message": "Request dropped in intercept mode"}},
                status_code=403,
            )

        # Get potentially modified request
        updated_session = intercept_store.get_session(session.session_id)
        if updated_session and updated_session.modified_request:
            final_request_data = updated_session.modified_request
        else:
            # Re-denormalize modified request for upstream
            _, final_request_data, _ = adapter.denormalize_from_canonical(modified_request)

        trace.metadata["intercepted"] = True
    else:
        # Re-denormalize modified request for upstream
        if modified_request:
            _, final_request_data, _ = adapter.denormalize_from_canonical(modified_request)
        else:
            final_request_data = raw_request

    # Use user's API key if provided, otherwise fall back to adapter's API key
    if user_api_key and user_api_key.strip():
        auth_token = user_api_key
    else:
        auth_token = adapter.api_key

    if not auth_token:
        raise HTTPException(status_code=400, detail="No API key available")

    # Prepare upstream request
    base_url = adapter.base_url
    upstream_endpoint = f"{base_url}/chat/completions"

    headers = {
        "Authorization": f"Bearer {auth_token}",
        "Content-Type": "application/json",
    }

    # Collect response chunks for trace and response interception
    response_chunks = []
    trace_saved = False

    async def collect_upstream_response():
        """Collect complete upstream response for potential interception."""
        chunks = []
        line_count = 0
        async with httpx.AsyncClient(timeout=300.0) as client:
            async with client.stream("POST", upstream_endpoint, headers=headers, json=final_request_data) as response:
                logger.info(f"Upstream response status: {response.status_code}, content-type: {response.headers.get('content-type')}")
                if response.status_code != 200:
                    error_body = await response.aread()
                    error_chunk = {"error": {"message": error_body.decode(), "type": "api_error"}}
                    chunks.append(error_chunk)
                    return chunks, True  # True indicates error

                content_type = response.headers.get('content-type', '')
                is_sse = 'text/event-stream' in content_type or 'event-stream' in content_type

                if is_sse:
                    # SSE format - process line by line
                    buffer = ""
                    async for text in response.aiter_text():
                        buffer += text
                        # Process complete lines from buffer
                        while "\n" in buffer:
                            idx = buffer.index("\n")
                            line = buffer[:idx].rstrip("\r")  # Handle \r\n
                            buffer = buffer[idx + 1:]
                            line_count += 1

                            if line.startswith("data: "):
                                data = line[6:]  # Remove "data: " prefix
                                if data == "[DONE]":
                                    chunks.append({"done": True})
                                    break
                                try:
                                    chunk = json.loads(data)
                                    chunks.append(chunk)
                                except json.JSONDecodeError:
                                    chunks.append({"raw": data})
                            elif line.strip() == "":
                                continue  # Skip empty lines
                            else:
                                logger.debug(f"Unexpected line in stream: {line[:100]}")

                    # Process any remaining content in buffer
                    if buffer.strip():
                        line = buffer.strip()
                        if line.startswith("data: "):
                            data = line[6:]
                            if data != "[DONE]":
                                try:
                                    chunk = json.loads(data)
                                    chunks.append(chunk)
                                except json.JSONDecodeError:
                                    chunks.append({"raw": data})
                else:
                    # Non-SSE response (e.g., JSON response for non-streaming)
                    body = await response.aread()
                    try:
                        data = json.loads(body.decode('utf-8'))
                        # Check if it's a chat completion response
                        if "choices" in data:
                            chunks.append(data)
                        else:
                            chunks.append({"raw": data})
                    except json.JSONDecodeError:
                        chunks.append({"raw": body.decode('utf-8')})

        logger.info(f"Collected {len(chunks)} chunks from {line_count} lines (is_sse={is_sse})")
        return chunks, False

    try:
        # Collect the complete response first (needed for interception)
        response_chunks, is_error = await collect_upstream_response()
    except Exception as e:
        logger.error(f"Failed to collect upstream response: {e}", exc_info=True)
        end_time = datetime.utcnow()
        trace.error = TraceError(type="CollectionError", message=str(e))
        trace.end_time = end_time
        trace.duration_ms = int((end_time - start_time).total_seconds() * 1000)
        proxy_service.trace_store.save_trace(trace)
        return JSONResponse(
            content={"error": {"message": f"Failed to collect response: {e}"}},
            status_code=502,
            headers={"X-Research-Trace-Id": trace_id},
        )

    # Handle error response
    if is_error:
        end_time = datetime.utcnow()
        error_chunk = response_chunks[0] if response_chunks else {"error": {"message": "Unknown error", "type": "api_error"}}
        trace.error = TraceError(
            type="APIError",
            message=error_chunk.get("error", {}).get("message", "Unknown error"),
        )
        trace.end_time = end_time
        trace.duration_ms = int((end_time - start_time).total_seconds() * 1000)
        proxy_service.trace_store.save_trace(trace)
        trace_saved = True
        return JSONResponse(
            content=error_chunk,
            status_code=502,
            headers={"X-Research-Trace-Id": trace_id},
        )

    # Check if we need to intercept the response
    if use_intercept:
        # Store upstream response in session for interception
        intercept_store.set_upstream_response(
            session.session_id,
            {"chunks": response_chunks},
        )

        # Wait for user action on response
        status = await wait_for_session_action(session.session_id, timeout=300)

        if status == "dropped":
            end_time = datetime.utcnow()
            trace.end_time = end_time
            trace.duration_ms = int((end_time - start_time).total_seconds() * 1000)
            trace.error = TraceError(type="Intercepted", message="Response dropped by user")
            proxy_service.trace_store.save_trace(trace)
            trace_saved = True
            intercept_store.mark_response_sent(session.session_id)
            return JSONResponse(
                content={"error": {"message": "Response dropped in intercept mode"}},
                status_code=403,
                headers={"X-Research-Trace-Id": trace_id},
            )

        # Get potentially modified response
        updated_session = intercept_store.get_session(session.session_id)
        if updated_session and updated_session.modified_response:
            # User modified the response
            modified_chunks = updated_session.modified_response.get("chunks", response_chunks)
            response_chunks = modified_chunks

        intercept_store.mark_response_sent(session.session_id)

    async def stream_generator():
        """Generate SSE stream from collected chunks."""
        nonlocal trace_saved
        try:
            for chunk in response_chunks:
                if chunk.get("done"):
                    yield "data: [DONE]\n\n"
                    break
                elif "raw" in chunk:
                    yield f"data: {chunk['raw']}\n\n"
                else:
                    yield f"data: {json.dumps(chunk)}\n\n"
        except Exception as e:
            logger.error(f"Error in stream generator: {e}")
            raise
        finally:
            # Ensure trace is saved even if client disconnects
            if not trace_saved:
                try:
                    end_time = datetime.utcnow()
                    duration_ms = int((end_time - start_time).total_seconds() * 1000)

                    # Build final content from chunks (handles multiple formats)
                    final_content = ""
                    reasoning_content = ""
                    for chunk in response_chunks:
                        if not isinstance(chunk, dict):
                            continue
                        # OpenAI streaming format: choices[].delta.content
                        if "choices" in chunk and isinstance(chunk["choices"], list):
                            for choice in chunk["choices"]:
                                if not isinstance(choice, dict):
                                    continue
                                delta = choice.get("delta", {})
                                # Extract content
                                if "content" in delta and delta["content"]:
                                    final_content += delta["content"]
                                # Extract reasoning (for models like o1, deepseek-r1)
                                if "reasoning" in delta and delta["reasoning"]:
                                    reasoning_content += delta["reasoning"]
                                # Extract reasoning_content (OpenAI reasoning models)
                                if "reasoning_content" in delta and delta["reasoning_content"]:
                                    reasoning_content += delta["reasoning_content"]
                        # Anthropic streaming format: type=content_block_delta
                        elif chunk.get("type") == "content_block_delta":
                            delta = chunk.get("delta", {})
                            if delta and "text" in delta:
                                final_content += delta["text"]
                        # Non-streaming format: choices[].message.content
                        elif "choices" in chunk and isinstance(chunk["choices"], list):
                            for choice in chunk["choices"]:
                                if not isinstance(choice, dict):
                                    continue
                                message = choice.get("message", {})
                                if message and "content" in message:
                                    final_content += message["content"]

                    # Combine content with reasoning if present
                    combined_content = final_content
                    if reasoning_content:
                        combined_content = f"[Reasoning]\n{reasoning_content}\n\n[Response]\n{final_content}"

                    # Create trace response
                    trace_resp = TraceResponse(
                        raw={"chunks": response_chunks},
                        modified={"content": combined_content, "reasoning": reasoning_content if reasoning_content else None},
                        timestamp=end_time,
                    )

                    trace.response = trace_resp
                    trace.end_time = end_time
                    trace.duration_ms = duration_ms
                    proxy_service.trace_store.save_trace(trace)
                    trace_saved = True
                except Exception as e:
                    logger.error(f"Failed to save trace: {e}")

    return StreamingResponse(
        stream_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Research-Trace-Id": trace_id,
            "X-Proxy-Lab": "true",
        },
    )


# =============================================
# Anthropic-Compatible Endpoints
# =============================================


@app.post("/v1/messages")
async def anthropic_messages(
    request: AnthropicMessageRequest,
    x_api_key: Optional[str] = Header(None, alias="x-api-key"),
):
    """Anthropic-compatible messages endpoint.

    This endpoint accepts Anthropic-format requests and forwards them
    to the Anthropic API.
    """
    provider = "anthropic"

    # Check if provider is available
    if provider not in proxy_service.adapters:
        raise HTTPException(
            status_code=400,
            detail=f"Provider 'anthropic' is not configured.",
        )

    # Convert to dict for processing
    raw_request = request.model_dump(mode="json")

    # Process through proxy
    try:
        response, trace_id = await proxy_service.process_request(
            provider=provider,
            raw_request=raw_request,
            endpoint="/v1/messages",
        )

        # Return with trace header
        return JSONResponse(
            content=response,
            headers={
                "X-Research-Trace-Id": trace_id,
                "X-Proxy-Lab": "true",
            },
        )
    except Exception as e:
        logger.error(f"Error processing Anthropic-compatible request: {e}")
        raise HTTPException(status_code=502, detail=str(e))


# =============================================
# Unified Proxy Endpoints
# =============================================


@app.post("/proxy/{provider}/invoke")
async def proxy_invoke(
    provider: str,
    request: ProxyInvokeRequest,
):
    """Unified proxy invoke endpoint.

    This is the internal debugging endpoint that allows specifying
    any configured provider.
    """
    # Check if provider is available
    if provider not in proxy_service.adapters:
        raise HTTPException(
            status_code=400,
            detail=f"Provider '{provider}' is not configured. Available: {list(proxy_service.adapters.keys())}",
        )

    # Convert to dict for processing
    raw_request = request.model_dump(mode="json")
    raw_request["provider"] = provider

    # Process through proxy
    try:
        response, trace_id = await proxy_service.process_request(
            provider=provider,
            raw_request=raw_request,
            endpoint=f"/proxy/{provider}/invoke",
        )

        return ProxyInvokeResponse(
            success=True,
            provider=provider,
            model=request.model,
            response=response,
            trace_id=trace_id,
        )
    except Exception as e:
        logger.error(f"Error processing proxy invoke request: {e}")
        return ProxyInvokeResponse(
            success=False,
            provider=provider,
            model=request.model,
            response={},
            error=str(e),
        )


# =============================================
# Trace Management Endpoints
# =============================================


@app.get("/traces")
async def list_traces(
    limit: int = 100,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    has_error: Optional[bool] = None,
) -> List[TraceSummary]:
    """List traces with optional filtering."""
    return trace_store.list_traces(
        limit=limit,
        provider=provider,
        model=model,
        has_error=has_error,
    )


@app.get("/traces/{trace_id}")
async def get_trace(trace_id: str) -> Dict[str, Any]:
    """Get a specific trace by ID."""
    trace = trace_store.get_trace(trace_id)
    if not trace:
        raise HTTPException(status_code=404, detail=f"Trace not found: {trace_id}")

    return trace.to_dict()


@app.delete("/traces/{trace_id}")
async def delete_trace(trace_id: str) -> Dict[str, Any]:
    """Delete a specific trace."""
    if not trace_store.delete_trace(trace_id):
        raise HTTPException(status_code=404, detail=f"Trace not found: {trace_id}")

    return {"success": True, "message": f"Trace {trace_id} deleted"}


@app.delete("/traces")
async def clear_traces() -> Dict[str, Any]:
    """Clear all traces."""
    count = trace_store.clear_all()
    return {"success": True, "message": f"Deleted {count} traces"}


# =============================================
# Replay Endpoints
# =============================================


@app.post("/replay/{trace_id}")
async def replay_trace(
    trace_id: str,
    replay_request: Optional[ReplayRequest] = None,
):
    """Replay a trace.

    Args:
        trace_id: Trace ID to replay
        replay_request: Optional replay configuration
    """
    if not trace_store.get_trace(trace_id):
        raise HTTPException(status_code=404, detail=f"Trace not found: {trace_id}")

    use_modified = False
    override_provider = None
    override_model = None

    if replay_request:
        use_modified = replay_request.use_modified_request
        override_provider = replay_request.override_provider
        override_model = replay_request.override_model

    try:
        result, new_trace_id = await proxy_service.replay_trace(
            trace_id=trace_id,
            use_modified=use_modified,
            override_provider=override_provider,
            override_model=override_model,
        )

        return {
            "success": True,
            "original_trace_id": trace_id,
            "new_trace_id": new_trace_id,
            "response": result,
            "used_modified": use_modified,
        }
    except Exception as e:
        logger.error(f"Error replaying trace {trace_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/replay/{trace_id}/compare/{other_trace_id}")
async def compare_traces(trace_id: str, other_trace_id: str) -> Dict[str, Any]:
    """Compare two traces."""
    return replay_service.compare_traces(trace_id, other_trace_id)


# =============================================
# Rule Management Endpoints
# =============================================


@app.get("/rules")
async def list_rules(scope: Optional[str] = None):
    """List all rules, optionally filtered by scope."""
    if scope and scope not in ["request", "response", "passive"]:
        raise HTTPException(
            status_code=400, detail="Invalid scope. Must be 'request', 'response', or 'passive'"
        )

    if scope:
        rules = rule_engine.explain_rules(scope)
    else:
        rules = {
            "request": rule_engine.explain_rules("request"),
            "response": rule_engine.explain_rules("response"),
            "passive": rule_engine.explain_rules("passive"),
        }

    return {"rules": rules, "dry_run": config.trace.dry_run}


@app.post("/rules/reload")
async def reload_rules():
    """Reload rules from disk."""
    rule_engine.reload_rules()
    return {"success": True, "message": "Rules reloaded"}


@app.get("/rules/toggle-model-force")
async def toggle_model_force(enable: bool):
    """Toggle the force_model_openrouter rule."""
    import yaml
    rules_file = "/home/XXBAi/HKUST/router/rules/request.yaml"

    with open(rules_file, "r") as f:
        rules_data = yaml.safe_load(f)

    # Find and update the force_model_openrouter rule
    for rule in rules_data.get("rules", []):
        if rule.get("id") == "force_model_openrouter":
            rule["enabled"] = enable
            break

    with open(rules_file, "w") as f:
        yaml.safe_dump(rules_data, f, allow_unicode=True, default_flow_style=False)

    # Reload rules
    rule_engine.reload_rules()

    return {
        "success": True,
        "message": f"Force model rule {'enabled' if enable else 'disabled'}",
        "enabled": enable
    }


# =============================================
# Manual Intercept Endpoints (Burp Suite Style)
# =============================================


@app.get("/intercept/mode")
async def get_intercept_mode():
    """Get current intercept mode status."""
    from app.services.proxy import is_intercept_mode_enabled
    return {
        "enabled": is_intercept_mode_enabled(),
        "description": "When enabled, requests will be held for manual inspection before forwarding",
    }


@app.post("/intercept/mode/enable")
async def enable_intercept_mode_endpoint():
    """Enable manual intercept mode."""
    from app.services.proxy import enable_intercept_mode
    enable_intercept_mode()
    return {"success": True, "message": "Manual intercept mode enabled"}


@app.post("/intercept/mode/disable")
async def disable_intercept_mode_endpoint():
    """Disable manual intercept mode."""
    from app.services.proxy import disable_intercept_mode
    disable_intercept_mode()
    return {"success": True, "message": "Manual intercept mode disabled"}


@app.get("/intercept")
async def list_intercepts(limit: int = 50):
    """List all intercept sessions."""
    sessions = intercept_store.list_all_sessions(limit=limit)
    return {
        "sessions": [
            {
                "session_id": s.session_id,
                "created_at": s.session_id,
                "status": s.status,
                "endpoint": s.endpoint,
                "method": s.method,
            }
            for s in sessions
        ],
        "stats": intercept_store.get_stats(),
    }


@app.get("/intercept/pending")
async def list_pending_intercepts():
    """List pending intercept sessions waiting for action."""
    sessions = intercept_store.list_pending_sessions()
    return {
        "sessions": [
            {
                "session_id": s.session_id,
                "created_at": s.created_at.isoformat(),
                "endpoint": s.endpoint,
                "method": s.method,
            }
            for s in sessions
        ],
        "count": len(sessions),
    }


@app.get("/intercept/stats")
async def intercept_stats():
    """Get intercept statistics."""
    return intercept_store.get_stats()


@app.get("/intercept/ui", response_class=HTMLResponse)
async def intercept_ui():
    """Burp Suite style intercept UI."""
    html_file = Path(__file__).parent.parent / "intercept.html"
    if html_file.exists():
        with open(html_file, "r", encoding="utf-8") as f:
            return HTMLResponse(f.read())
    return HTMLResponse("<h1>Intercept UI not found</h1>")


@app.get("/intercept/{session_id}")
async def get_intercept(session_id: str):
    """Get details of a specific intercept session."""
    session = intercept_store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    return {
        "session_id": session.session_id,
        "created_at": session.created_at.isoformat(),
        "status": session.status,
        "endpoint": session.endpoint,
        "method": session.method,
        "original_request": session.original_request,
        "modified_request": session.modified_request,
        "upstream_response": session.upstream_response,
        "modified_response": session.modified_response,
        "intercept_response": session.intercept_response,
    }


@app.post("/intercept/{session_id}/modify-request")
async def modify_intercept_request(session_id: str, data: InterceptModifyRequest):
    """Modify an intercepted request and optionally forward or drop."""
    session = intercept_store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    intercept_store.modify_request(session_id, data.modified_request)

    if data.action == "drop":
        intercept_store.drop_request(session_id)
        return {"success": True, "message": "Request dropped"}

    intercept_store.forward_request(session_id)
    return {"success": True, "message": "Request forwarded"}


@app.post("/intercept/{session_id}/modify-response")
async def modify_intercept_response(session_id: str, data: InterceptModifyResponse):
    """Modify an intercepted response and optionally send or drop."""
    session = intercept_store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    intercept_store.modify_response(session_id, data.modified_response)

    if data.action == "drop":
        intercept_store.drop_response(session_id)
        return {"success": True, "message": "Response dropped"}

    intercept_store.send_response(session_id)
    return {"success": True, "message": "Response sent"}


@app.post("/intercept/{session_id}/forward")
async def forward_intercept(session_id: str):
    """Forward the current request/response without modification."""
    session = intercept_store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if session.upstream_response is None:
        intercept_store.forward_request(session_id)
        return {"success": True, "message": "Request forwarded"}
    else:
        intercept_store.send_response(session_id)
        return {"success": True, "message": "Response sent"}


@app.post("/intercept/{session_id}/drop")
async def drop_intercept(session_id: str):
    """Drop the current request/response."""
    session = intercept_store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if session.upstream_response is None:
        intercept_store.drop_request(session_id)
        return {"success": True, "message": "Request dropped"}
    else:
        intercept_store.drop_response(session_id)
        return {"success": True, "message": "Response dropped"}


@app.delete("/intercept/{session_id}")
async def delete_intercept(session_id: str):
    """Delete an intercept session."""
    if not intercept_store.delete_session(session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    return {"success": True, "message": "Session deleted"}


@app.delete("/intercept")
async def clear_intercepts():
    """Clear all intercept sessions."""
    count = intercept_store.clear_all()
    return {"success": True, "message": f"Cleared {count} sessions"}


@app.get("/intercept/stats")
async def intercept_stats():
    """Get intercept statistics."""
    return intercept_store.get_stats()


# =============================================
# Debug & Inspection Endpoints
# =============================================


@app.get("/debug/providers")
async def debug_providers():
    """Debug endpoint to see configured providers."""
    return {
        "configured_providers": list(proxy_service.adapters.keys()),
        "openai_configured": "openai" in proxy_service.adapters,
        "anthropic_configured": "anthropic" in proxy_service.adapters,
    }


@app.get("/debug/last-trace")
async def debug_last_trace(provider: Optional[str] = None):
    """Get the most recent trace, optionally filtered by provider."""
    traces = trace_store.list_traces(limit=1, provider=provider)
    if not traces:
        return {"message": "No traces found"}

    trace = trace_store.get_trace(traces[0].trace_id)
    return trace.to_dict() if trace else {"message": "Trace not found"}


# =============================================
# Simple Web Frontend
# =============================================


@app.get("/ui", response_class=HTMLResponse)
async def web_frontend():
    """Simple web frontend for monitoring and interacting with the proxy."""

    html = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>LLM Research Proxy</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #1a1a2e;
            color: #eee;
            padding: 20px;
            min-height: 100vh;
        }
        .container { max-width: 1400px; margin: 0 auto; }
        h1 { color: #00d9ff; margin-bottom: 10px; }
        h2 { color: #00d9ff; margin: 20px 0 10px; font-size: 1.2em; }
        .header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 20px;
            padding-bottom: 20px;
            border-bottom: 1px solid #333;
        }
        .status { display: flex; gap: 15px; align-items: center; }
        .status-item { background: #16213e; padding: 8px 15px; border-radius: 5px; }
        .status-label { color: #888; font-size: 0.85em; }
        .status-value { color: #00d9ff; font-weight: bold; }
        .status-value.ok { color: #00ff88; }
        .status-value.error { color: #ff4466; }
        .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
        .panel {
            background: #16213e;
            border-radius: 10px;
            padding: 20px;
            border: 1px solid #333;
        }
        .btn {
            background: #00d9ff;
            color: #1a1a2e;
            border: none;
            padding: 10px 20px;
            border-radius: 5px;
            cursor: pointer;
            font-weight: bold;
            transition: all 0.2s;
        }
        .btn:hover { background: #00b8d9; transform: translateY(-1px); }
        .btn.danger { background: #ff4466; color: white; }
        .btn.danger:hover { background: #ff2244; }
        .btn.secondary { background: #333; color: #eee; }
        .btn.secondary:hover { background: #444; }
        table { width: 100%; border-collapse: collapse; }
        th, td { padding: 12px; text-align: left; border-bottom: 1px solid #333; }
        th { color: #888; font-weight: normal; font-size: 0.9em; }
        tr:hover { background: #1a1a2e; }
        .trace-id { font-family: monospace; color: #00d9ff; }
        .provider { padding: 3px 8px; border-radius: 3px; font-size: 0.85em; }
        .provider.openai { background: #2d5016; color: #88ff88; }
        .provider.anthropic { background: #4a2d50; color: #d988ff; }
        .error { color: #ff4466; }
        .success { color: #00ff88; }
        .log-entry {
            font-family: monospace;
            font-size: 0.85em;
            padding: 8px;
            border-left: 3px solid #00d9ff;
            background: #1a1a2e;
            margin: 5px 0;
        }
        .log-entry.error { border-left-color: #ff4466; }
        .form-group { margin-bottom: 15px; }
        .form-group label { display: block; margin-bottom: 5px; color: #888; }
        .form-group input, .form-group select, .form-group textarea {
            width: 100%;
            padding: 10px;
            border: 1px solid #333;
            border-radius: 5px;
            background: #1a1a2e;
            color: #eee;
            font-family: inherit;
        }
        .form-group textarea { min-height: 100px; resize: vertical; }
        .tabs { display: flex; gap: 5px; margin-bottom: 20px; }
        .tab {
            padding: 10px 20px;
            background: #16213e;
            border: 1px solid #333;
            border-radius: 5px 5px 0 0;
            cursor: pointer;
            transition: all 0.2s;
        }
        .tab:hover { background: #1a1a2e; }
        .tab.active { background: #00d9ff; color: #1a1a2e; border-color: #00d9ff; }
        .tab-content { display: none; }
        .tab-content.active { display: block; }
        .rule-card {
            background: #1a1a2e;
            border: 1px solid #333;
            border-radius: 5px;
            padding: 15px;
            margin-bottom: 10px;
        }
        .rule-header { display: flex; justify-content: space-between; align-items: center; }
        .rule-id { color: #00d9ff; font-family: monospace; }
        .rule-enabled { color: #00ff88; font-size: 0.85em; }
        .rule-disabled { color: #ff4466; font-size: 0.85em; }
        .flex { display: flex; gap: 10px; }
        .flex-grow { flex-grow: 1; }
        #testResult { white-space: pre-wrap; font-family: monospace; }
        @media (max-width: 768px) {
            .grid { grid-template-columns: 1fr; }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div>
                <h1>🔬 LLM Research Proxy</h1>
                <p style="color: #888;">Lightweight API proxy for model research and experimentation</p>
            </div>
            <div class="status">
                <div class="status-item">
                    <div class="status-label">Status</div>
                    <div class="status-value ok" id="healthStatus">● Online</div>
                </div>
                <div class="status-item">
                    <div class="status-label">Providers</div>
                    <div class="status-value" id="providerCount">-</div>
                </div>
                <div class="status-item">
                    <div class="status-label">Dry Run</div>
                    <div class="status-value" id="dryRunStatus">Off</div>
                </div>
            </div>
        </div>

        <div class="tabs">
            <div class="tab active" data-tab="traces">📊 Traces</div>
            <div class="tab" data-tab="test">🧪 Test Request</div>
            <div class="tab" data-tab="rules">⚙️ Rules</div>
            <div class="tab" data-tab="settings">🔧 Settings</div>
        </div>

        <!-- Traces Tab -->
        <div class="tab-content active" id="traces-tab">
            <div class="grid">
                <div class="panel">
                    <div class="flex" style="justify-content: space-between; margin-bottom: 15px;">
                        <h2>Recent Traces</h2>
                        <div class="flex">
                            <button class="btn secondary" onclick="refreshTraces()">↻ Refresh</button>
                            <button class="btn danger" onclick="clearTraces()">🗑 Clear All</button>
                        </div>
                    </div>
                    <table>
                        <thead>
                            <tr>
                                <th>Trace ID</th>
                                <th>Provider</th>
                                <th>Model</th>
                                <th>Duration</th>
                                <th>Status</th>
                                <th>Actions</th>
                            </tr>
                        </thead>
                        <tbody id="tracesTable">
                            <tr><td colspan="6" style="text-align: center; color: #888;">Loading...</td></tr>
                        </tbody>
                    </table>
                </div>
                <div class="panel">
                    <h2>Trace Details</h2>
                    <div id="traceDetails" style="margin-top: 15px;">
                        <p style="color: #888; text-align: center;">Select a trace to view details</p>
                    </div>
                </div>
            </div>
        </div>

        <!-- Test Request Tab -->
        <div class="tab-content" id="test-tab">
            <div class="grid">
                <div class="panel">
                    <h2>Send Test Request</h2>
                    <form id="testForm" style="margin-top: 15px;">
                        <div class="form-group">
                            <label>Provider</label>
                            <select id="testProvider" required>
                                <option value="openai">OpenAI</option>
                                <option value="anthropic">Anthropic</option>
                            </select>
                        </div>
                        <div class="form-group">
                            <label>Model</label>
                            <input type="text" id="testModel" placeholder="e.g., gpt-3.5-turbo or claude-3-haiku-20240307" required>
                        </div>
                        <div class="form-group">
                            <label>System Prompt (optional)</label>
                            <textarea id="testSystem" placeholder="You are a helpful assistant..."></textarea>
                        </div>
                        <div class="form-group">
                            <label>Message</label>
                            <textarea id="testMessage" placeholder="Hello, how are you?" required></textarea>
                        </div>
                        <button type="submit" class="btn">🚀 Send Request</button>
                    </form>
                </div>
                <div class="panel">
                    <h2>Response</h2>
                    <div id="testResult" style="margin-top: 15px; background: #1a1a2e; padding: 15px; border-radius: 5px; min-height: 200px;">
                        <span style="color: #888;">Response will appear here...</span>
                    </div>
                </div>
            </div>
        </div>

        <!-- Rules Tab -->
        <div class="tab-content" id="rules-tab">
            <div class="panel">
                <div class="flex" style="justify-content: space-between; margin-bottom: 15px;">
                    <h2>Active Rules</h2>
                    <button class="btn secondary" onclick="refreshRules()">↻ Refresh</button>
                </div>
                <div id="rulesList">
                    <p style="color: #888; text-align: center;">Loading rules...</p>
                </div>
            </div>
        </div>

        <!-- Settings Tab -->
        <div class="tab-content" id="settings-tab">
            <div class="panel">
                <h2>API Information</h2>
                <div style="margin-top: 15px;">
                    <div class="form-group">
                        <label>Base URL</label>
                        <input type="text" id="baseUrl" value="http://localhost:8765" readonly>
                    </div>
                    <div class="form-group">
                        <label>OpenAI-compatible Endpoint</label>
                        <input type="text" value="http://localhost:8765/v1/chat/completions" readonly>
                    </div>
                    <div class="form-group">
                        <label>Anthropic-compatible Endpoint</label>
                        <input type="text" value="http://localhost:8765/v1/messages" readonly>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <script>
        // Tab switching
        document.querySelectorAll('.tab').forEach(tab => {
            tab.addEventListener('click', () => {
                document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
                document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
                tab.classList.add('active');
                document.getElementById(tab.dataset.tab + '-tab').classList.add('active');
            });
        });

        // Health check
        async function checkHealth() {
            try {
                const res = await fetch('/health');
                const data = await res.json();
                document.getElementById('healthStatus').textContent = '● Online';
                document.getElementById('healthStatus').className = 'status-value ok';
                document.getElementById('providerCount').textContent = data.providers_available.join(', ') || 'None';
                document.getElementById('dryRunStatus').textContent = data.dry_run ? 'On' : 'Off';
                document.getElementById('dryRunStatus').className = data.dry_run ? 'status-value error' : 'status-value ok';
            } catch (e) {
                document.getElementById('healthStatus').textContent = '● Offline';
                document.getElementById('healthStatus').className = 'status-value error';
            }
        }

        // Load traces
        async function loadTraces() {
            try {
                const res = await fetch('/traces?limit=20');
                const traces = await res.json();
                const tbody = document.getElementById('tracesTable');
                if (traces.length === 0) {
                    tbody.innerHTML = '<tr><td colspan="6" style="text-align: center; color: #888;">No traces yet</td></tr>';
                    return;
                }
                tbody.innerHTML = traces.map(t => `
                    <tr>
                        <td class="trace-id">${t.trace_id}</td>
                        <td><span class="provider ${t.provider}">${t.provider}</span></td>
                        <td>${t.model}</td>
                        <td>${t.duration_ms || '-'}ms</td>
                        <td class="${t.has_error ? 'error' : 'success'}">${t.has_error ? 'Error' : 'OK'}</td>
                        <td>
                            <button class="btn secondary" style="padding: 5px 10px; font-size: 0.85em;" onclick="viewTrace('${t.trace_id}')">View</button>
                            <button class="btn secondary" style="padding: 5px 10px; font-size: 0.85em;" onclick="replayTrace('${t.trace_id}')">Replay</button>
                        </td>
                    </tr>
                `).join('');
            } catch (e) {
                console.error('Failed to load traces:', e);
            }
        }

        // View trace details
        async function viewTrace(traceId) {
            try {
                const res = await fetch('/traces/' + traceId);
                const trace = await res.json();
                document.getElementById('traceDetails').innerHTML = `
                    <div class="rule-card">
                        <div class="rule-header">
                            <span class="rule-id">${trace.trace_id}</span>
                            <span>${trace.provider} / ${trace.model}</span>
                        </div>
                        <div style="margin-top: 10px;">
                            <strong>Request:</strong>
                            <pre style="background: #1a1a2e; padding: 10px; border-radius: 5px; margin-top: 5px; overflow-x: auto;">${JSON.stringify(trace.request.raw, null, 2)}</pre>
                        </div>
                        ${trace.response ? `
                        <div style="margin-top: 10px;">
                            <strong>Response:</strong>
                            <pre style="background: #1a1a2e; padding: 10px; border-radius: 5px; margin-top: 5px; overflow-x: auto;">${JSON.stringify(trace.response.modified || trace.response.raw, null, 2)}</pre>
                        </div>
                        ` : ''}
                        ${trace.request.rule_results && trace.request.rule_results.matched_rules.length > 0 ? `
                        <div style="margin-top: 10px;">
                            <strong>Rules Applied:</strong>
                            <ul style="margin-top: 5px; margin-left: 20px;">
                                ${trace.request.rule_results.matched_rules.map(r => `<li>${r.rule_id}: ${r.details || r.description}</li>`).join('')}
                            </ul>
                        </div>
                        ` : ''}
                        ${trace.duration_ms ? `<div style="margin-top: 10px;"><strong>Duration:</strong> ${trace.duration_ms}ms</div>` : ''}
                    </div>
                `;
            } catch (e) {
                document.getElementById('traceDetails').innerHTML = `<p class="error">Failed to load trace: ${e.message}</p>`;
            }
        }

        // Refresh traces
        function refreshTraces() {
            loadTraces();
        }

        // Clear all traces
        async function clearTraces() {
            if (!confirm('Are you sure you want to delete all traces?')) return;
            try {
                await fetch('/traces', { method: 'DELETE' });
                loadTraces();
            } catch (e) {
                alert('Failed to clear traces: ' + e.message);
            }
        }

        // Replay trace
        async function replayTrace(traceId) {
            try {
                const res = await fetch('/replay/' + traceId, { method: 'POST' });
                const result = await res.json();
                alert('Replay complete! New trace ID: ' + result.new_trace_id);
                loadTraces();
            } catch (e) {
                alert('Failed to replay: ' + e.message);
            }
        }

        // Test request
        document.getElementById('testForm').addEventListener('submit', async (e) => {
            e.preventDefault();
            const provider = document.getElementById('testProvider').value;
            const model = document.getElementById('testModel').value;
            const system = document.getElementById('testSystem').value;
            const message = document.getElementById('testMessage').value;
            const resultDiv = document.getElementById('testResult');

            resultDiv.innerHTML = '<span style="color: #888;">Sending request...</span>';

            try {
                const payload = {
                    model: model,
                    messages: [
                        ...(system ? [{ role: 'system', content: system }] : []),
                        { role: 'user', content: message }
                    ]
                };

                const endpoint = provider === 'anthropic' ? '/v1/messages' : '/v1/chat/completions';
                const res = await fetch(endpoint, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });

                const data = await res.json();
                const traceId = res.headers.get('X-Research-Trace-Id');

                resultDiv.innerHTML = `
                    <div style="color: #00d9ff; margin-bottom: 10px;">Trace ID: ${traceId || 'N/A'}</div>
                    <pre>${JSON.stringify(data, null, 2)}</pre>
                `;

                loadTraces();
            } catch (e) {
                resultDiv.innerHTML = `<span class="error">Error: ${e.message}</span>`;
            }
        });

        // Load rules
        async function loadRules() {
            try {
                const res = await fetch('/rules');
                const data = await res.json();
                const rulesList = document.getElementById('rulesList');

                const allRules = [
                    ...data.rules.request.map(r => ({ ...r, scope: 'request' })),
                    ...data.rules.response.map(r => ({ ...r, scope: 'response' })),
                    ...data.rules.passive.map(r => ({ ...r, scope: 'passive' }))
                ];

                if (allRules.length === 0) {
                    rulesList.innerHTML = '<p style="color: #888; text-align: center;">No rules defined</p>';
                    return;
                }

                rulesList.innerHTML = allRules.map(rule => `
                    <div class="rule-card">
                        <div class="rule-header">
                            <div>
                                <span class="rule-id">${rule.id}</span>
                                <span style="color: #888; margin-left: 10px;">[${rule.scope}]</span>
                            </div>
                            <span class="${rule.enabled ? 'rule-enabled' : 'rule-disabled'}">
                                ${rule.enabled ? '● Enabled' : '○ Disabled'}
                            </span>
                        </div>
                        <p style="margin-top: 10px; color: #ccc;">${rule.description}</p>
                        <div style="margin-top: 10px; font-size: 0.85em;">
                            <span style="color: #888;">Priority:</span> ${rule.priority} |
                            <span style="color: #888;">Match:</span> ${JSON.stringify(rule.match)}
                        </div>
                    </div>
                `).join('');
            } catch (e) {
                document.getElementById('rulesList').innerHTML = `<p class="error">Failed to load rules: ${e.message}</p>`;
            }
        }

        function refreshRules() {
            loadRules();
        }

        // Initialize
        checkHealth();
        loadTraces();
        loadRules();

        // Auto-refresh health every 30 seconds
        setInterval(checkHealth, 30000);
    </script>
</body>
</html>
    """

    return html


# =============================================
# Startup Event
# =============================================


@app.on_event("startup")
async def startup_event():
    """Log startup information."""
    logger.info("=" * 50)
    logger.info("LLM Research Proxy starting...")
    logger.info(f"Host: {config.server.host}:{config.server.port}")
    logger.info(f"Trace enabled: {config.trace.enabled}")
    logger.info(f"Dry run: {config.trace.dry_run}")
    logger.info(f"Rules directory: {config.rules_dir}")
    logger.info(f"Providers configured: {list(proxy_service.adapters.keys())}")
    logger.info("=" * 50)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host=config.server.host,
        port=config.server.port,
    )
