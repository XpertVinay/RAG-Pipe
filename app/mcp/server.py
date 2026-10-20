"""Model Context Protocol (MCP) Server implementation exposing RAG & Multi-Agent tools."""

import json
from typing import Any, Dict, List, Optional
from app.core.logging import logger
from app.mcp.protocol import (
    CallToolResult,
    JSONRPCError,
    JSONRPCRequest,
    JSONRPCResponse,
    MCPMethod,
    MCPTool,
)
from app.mcp.registry import mcp_registry


class MCPServer:
    """Standard Model Context Protocol Server implementation."""

    def __init__(self, server_name: str = "rag-agent-mcp-server", version: str = "1.0.0"):
        self.server_name = server_name
        self.version = version

    async def handle_request(self, request_payload: Dict[str, Any]) -> Dict[str, Any]:
        """Process incoming JSON-RPC 2.0 MCP request and return response dict."""
        try:
            req = JSONRPCRequest(**request_payload)
        except Exception as e:
            err = JSONRPCError(code=-32700, message=f"Parse error: {str(e)}")
            return JSONRPCResponse(id="null", error=err).model_dump()

        try:
            if req.method == MCPMethod.INITIALIZE.value:
                result = {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {
                        "tools": {"listChanged": False},
                        "resources": {"subscribe": False, "listChanged": False},
                        "prompts": {"listChanged": False},
                    },
                    "serverInfo": {
                        "name": self.server_name,
                        "version": self.version,
                    },
                }
                return JSONRPCResponse(id=req.id, result=result).model_dump()

            elif req.method == MCPMethod.PING.value:
                return JSONRPCResponse(id=req.id, result={}).model_dump()

            elif req.method == MCPMethod.TOOLS_LIST.value:
                tools = await mcp_registry.list_all_tools()
                result = {
                    "tools": [t.model_dump() for t in tools]
                }
                return JSONRPCResponse(id=req.id, result=result).model_dump()

            elif req.method == MCPMethod.TOOLS_CALL.value:
                params = req.params or {}
                tool_name = params.get("name")
                arguments = params.get("arguments", {})

                if not tool_name:
                    err = JSONRPCError(code=-32602, message="Invalid params: 'name' is required for tools/call")
                    return JSONRPCResponse(id=req.id, error=err).model_dump()

                call_result: CallToolResult = await mcp_registry.execute_tool(
                    tool_name=tool_name,
                    arguments=arguments,
                    anonymous=True,
                )
                return JSONRPCResponse(id=req.id, result=call_result.model_dump()).model_dump()

            else:
                err = JSONRPCError(code=-32601, message=f"Method '{req.method}' not found")
                return JSONRPCResponse(id=req.id, error=err).model_dump()

        except Exception as e:
            logger.error(f"Internal MCP server error during '{req.method}': {e}")
            err = JSONRPCError(code=-32603, message=f"Internal error: {str(e)}")
            return JSONRPCResponse(id=req.id, error=err).model_dump()


# Global MCP Server instance
mcp_server = MCPServer()
