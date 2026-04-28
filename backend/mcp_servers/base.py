"""
MCP Server Base — abstract class for all LogistiQ AI MCP tool servers.

Every MCP server is a self-contained FastAPI router that exposes:
  GET  /tools              → list registered MCPToolSchema
  POST /call/{tool_name}   → validate params, dispatch, return MCPToolResult
"""

from __future__ import annotations

import time
import uuid
from abc import ABC, abstractmethod
from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ValidationError

log = structlog.get_logger(__name__)

# ─────────────────────────────────────────────────────────────
# Pydantic schemas
# ─────────────────────────────────────────────────────────────

JsonSchemaDict = dict[str, Any]


class MCPToolSchema(BaseModel):
    """Describes a single MCP tool exposed by a server."""
    name: str
    description: str
    parameters: JsonSchemaDict          # JSON Schema object for the parameters
    required: list[str] = []


class MCPToolResult(BaseModel):
    """Successful response envelope."""
    result: Any
    tool_name: str
    trace_id: str
    latency_ms: float


class MCPToolError(BaseModel):
    """Error response envelope (also used internally as exception payload)."""
    tool_name: str
    reason: str
    status_code: int = 422


class MCPCallRequest(BaseModel):
    """Body for POST /call/{tool_name}."""
    params: dict[str, Any] = {}
    tenant_id: str | None = None


# ─────────────────────────────────────────────────────────────
# Abstract base server
# ─────────────────────────────────────────────────────────────

class MCPServer(ABC):
    """
    Abstract base class for all MCP tool servers.

    Subclasses MUST:
      1. Define ``tools: dict[str, MCPToolSchema]`` as a class attribute.
      2. Implement ``async execute_tool(name, params, tenant_id) -> Any``.

    Call ``server.router`` to mount the generated FastAPI router.
    """

    # Subclasses override this at class level
    tools: dict[str, MCPToolSchema] = {}

    def __init__(self, prefix: str = "") -> None:
        self.router = APIRouter(prefix=prefix)
        self._register_routes()

    # ── Route registration ────────────────────────────────────

    def _register_routes(self) -> None:
        router = self.router

        @router.get("/tools", response_model=list[MCPToolSchema])
        async def list_tools() -> list[MCPToolSchema]:
            """Return all registered tool schemas."""
            return list(self.__class__.tools.values())

        @router.post("/call/{tool_name}", response_model=MCPToolResult)
        async def call_tool(
            tool_name: str,
            body: MCPCallRequest,
            request: Request,
        ) -> JSONResponse:
            return await self._dispatch(tool_name, body, request)

    # ── Dispatch / validation ─────────────────────────────────

    async def _dispatch(
        self,
        tool_name: str,
        body: MCPCallRequest,
        request: Request,
    ) -> JSONResponse:
        trace_id = str(uuid.uuid4())
        tenant_id = body.tenant_id or getattr(getattr(request, "state", None), "tenant_id", None)

        if tool_name not in self.__class__.tools:
            err = MCPToolError(
                tool_name=tool_name,
                reason=f"Unknown tool '{tool_name}'",
                status_code=404,
            )
            raise HTTPException(status_code=404, detail=err.model_dump())

        schema = self.__class__.tools[tool_name]
        params = body.params

        # ── JSON-schema required-field validation ─────────────
        missing = [f for f in schema.required if f not in params]
        if missing:
            err = MCPToolError(
                tool_name=tool_name,
                reason=f"Missing required parameters: {missing}",
                status_code=422,
            )
            raise HTTPException(status_code=422, detail=err.model_dump())

        t0 = time.perf_counter()
        try:
            result = await self.execute_tool(tool_name, params, tenant_id)
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            latency_ms = round((time.perf_counter() - t0) * 1000, 2)
            log.error(
                "mcp.call.error",
                tool=tool_name,
                tenant_id=tenant_id,
                trace_id=trace_id,
                latency_ms=latency_ms,
                error=str(exc),
            )
            err = MCPToolError(
                tool_name=tool_name,
                reason=str(exc),
                status_code=422,
            )
            raise HTTPException(status_code=422, detail=err.model_dump()) from exc

        latency_ms = round((time.perf_counter() - t0) * 1000, 2)
        log.info(
            "mcp.call",
            tool=tool_name,
            tenant_id=tenant_id,
            trace_id=trace_id,
            latency_ms=latency_ms,
        )

        payload = MCPToolResult(
            result=result,
            tool_name=tool_name,
            trace_id=trace_id,
            latency_ms=latency_ms,
        )
        return JSONResponse(content=payload.model_dump())

    # ── Abstract hook ─────────────────────────────────────────

    @abstractmethod
    async def execute_tool(
        self,
        name: str,
        params: dict[str, Any],
        tenant_id: str | None,
    ) -> Any:
        """
        Subclasses implement tool dispatch here.
        Raise any Exception on failure; the base class wraps it in MCPToolError.
        """
