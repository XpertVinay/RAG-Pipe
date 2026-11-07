"""Model Context Protocol (MCP) data specifications and JSON-RPC 2.0 types."""

from enum import Enum
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field


class MCPMethod(str, Enum):
    """Standard Model Context Protocol JSON-RPC methods."""
    INITIALIZE = "initialize"
    PING = "ping"
    TOOLS_LIST = "tools/list"
    TOOLS_CALL = "tools/call"
    RESOURCES_LIST = "resources/list"
    RESOURCES_READ = "resources/read"
    PROMPTS_LIST = "prompts/list"
    PROMPTS_GET = "prompts/get"


class ToolInputSchema(BaseModel):
    """JSON Schema defining arguments for an MCP tool."""
    type: str = "object"
    properties: Dict[str, Any] = Field(default_factory=dict)
    required: Optional[List[str]] = Field(default_factory=list)


class MCPTool(BaseModel):
    """Definition of an MCP tool advertised by a server."""
    name: str
    description: str
    inputSchema: ToolInputSchema = Field(default_factory=ToolInputSchema)
    provider: Optional[str] = "native"
    is_anonymous: bool = True


class ToolContentItem(BaseModel):
    """A content block returned by an MCP tool invocation."""
    type: str = "text"
    text: Optional[str] = None
    data: Optional[Any] = None
    mimeType: Optional[str] = None


class CallToolResult(BaseModel):
    """Standard result structure returned from tools/call."""
    content: List[ToolContentItem] = Field(default_factory=list)
    isError: bool = False
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def get_text(self) -> str:
        """Convenience method to join all text contents."""
        return "\n".join(item.text for item in self.content if item.text)


class JSONRPCError(BaseModel):
    """Standard JSON-RPC 2.0 Error object."""
    code: int
    message: str
    data: Optional[Any] = None


class JSONRPCRequest(BaseModel):
    """Standard JSON-RPC 2.0 Request."""
    jsonrpc: str = "2.0"
    id: Union[str, int]
    method: str
    params: Optional[Dict[str, Any]] = Field(default_factory=dict)


class JSONRPCResponse(BaseModel):
    """Standard JSON-RPC 2.0 Response."""
    jsonrpc: str = "2.0"
    id: Union[str, int]
    result: Optional[Any] = None
    error: Optional[JSONRPCError] = None


class MCPClientConfig(BaseModel):
    """Configuration for connecting to an external MCP server."""
    provider_id: str
    name: str
    server_url: str
    transport: str = "sse"  # "sse", "http", or "stdio"
    auth_token: Optional[str] = None
    anonymous: bool = True
    timeout_seconds: float = 20.0
    enabled: bool = True
    headers: Dict[str, str] = Field(default_factory=dict)
