"""Model Context Protocol (MCP) Server Endpoint (JSON-RPC 2.0)."""

from typing import Any, Dict
from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse

from app.mcp.server import mcp_server

router = APIRouter(prefix="/mcp", tags=["mcp"])


@router.post("/messages", status_code=status.HTTP_200_OK)
async def handle_mcp_message(request: Request) -> JSONResponse:
    """Handle standard JSON-RPC 2.0 Model Context Protocol request."""
    body = await request.json()
    response_payload = await mcp_server.handle_request(body)
    return JSONResponse(content=response_payload)


@router.get("/tools", status_code=status.HTTP_200_OK)
async def get_mcp_tools() -> Dict[str, Any]:
    """Expose available MCP tools for discovery."""
    response_payload = await mcp_server.handle_request({
        "jsonrpc": "2.0",
        "id": "discovery",
        "method": "tools/list",
        "params": {},
    })
    return response_payload.get("result", {})
