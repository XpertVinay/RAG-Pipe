"""High-Performance Async Model Context Protocol (MCP) Client with Anonymous Proxying."""

import asyncio
import json
import time
import uuid
from typing import Any, Dict, List, Optional
import httpx

from app.core.logging import logger
from app.mcp.protocol import (
    CallToolResult,
    JSONRPCError,
    JSONRPCRequest,
    JSONRPCResponse,
    MCPClientConfig,
    MCPMethod,
    MCPTool,
    ToolContentItem,
)
from app.mcp.security import AnonymousScrubber, SSRFProtector


class MCPClientError(Exception):
    """Exception raised by MCP client interactions."""
    pass


class MCPClient:
    """Async Client for communicating with third-party MCP tool servers anonymously."""

    def __init__(self, config: MCPClientConfig):
        self.config = config
        self._tools_cache: Optional[List[MCPTool]] = None
        self._tools_cache_time: float = 0.0
        self._cache_ttl_seconds: float = 300.0  # 5 minutes
        self._failure_count: int = 0
        self._circuit_open_until: float = 0.0
        self._http_client: Optional[httpx.AsyncClient] = None

    async def get_http_client(self) -> httpx.AsyncClient:
        """Return or instantiate pooled HTTP client."""
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.config.timeout_seconds, connect=5.0),
                headers=self._build_headers(),
            )
        return self._http_client

    def _build_headers(self) -> Dict[str, str]:
        """Build headers with optional anonymous proxy tags."""
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "MCP-Agent-Client/1.0 (Anonymous)",
        }
        if self.config.auth_token and not self.config.anonymous:
            headers["Authorization"] = f"Bearer {self.config.auth_token}"
        elif self.config.anonymous:
            # Mask or supply anonymous task correlation token
            anon_token = AnonymousScrubber.generate_anonymous_session_id(self.config.provider_id)
            headers["X-Anonymous-Task-Id"] = anon_token

        headers.update(self.config.headers)
        return headers

    def _is_circuit_open(self) -> bool:
        """Check if circuit breaker is tripped due to repeated failures."""
        if time.time() < self._circuit_open_until:
            return True
        return False

    def _record_failure(self) -> None:
        """Record failure and trip circuit breaker if threshold is reached."""
        self._failure_count += 1
        if self._failure_count >= 3:
            self._circuit_open_until = time.time() + 60.0  # Open for 60 seconds
            logger.warning(
                f"MCP Client: Circuit breaker tripped for provider '{self.config.provider_id}' until {self._circuit_open_until}"
            )

    def _record_success(self) -> None:
        """Reset circuit breaker counters on successful request."""
        self._failure_count = 0
        self._circuit_open_until = 0.0

    async def _send_jsonrpc(self, method: str, params: Optional[Dict[str, Any]] = None) -> Any:
        """Send JSON-RPC request to external MCP server."""
        if not self.config.enabled:
            raise MCPClientError(f"MCP Provider '{self.config.provider_id}' is disabled.")

        if self._is_circuit_open():
            raise MCPClientError(
                f"MCP Provider '{self.config.provider_id}' circuit is open due to recent errors. Skipping."
            )

        if not SSRFProtector.validate_url(self.config.server_url):
            raise MCPClientError(f"Security Alert: Target URL '{self.config.server_url}' failed SSRF checks.")

        req_id = str(uuid.uuid4())
        rpc_req = JSONRPCRequest(id=req_id, method=method, params=params or {})
        client = await self.get_http_client()

        # Retry with exponential backoff (up to 2 retries)
        last_exception: Optional[Exception] = None
        for attempt in range(2):
            try:
                response = await client.post(
                    self.config.server_url,
                    json=rpc_req.model_dump(),
                )
                if response.status_code != 200:
                    raise MCPClientError(
                        f"MCP Server error HTTP {response.status_code}: {response.text[:200]}"
                    )

                data = response.json()
                rpc_resp = JSONRPCResponse(**data)

                if rpc_resp.error:
                    raise MCPClientError(
                        f"MCP JSON-RPC Error [{rpc_resp.error.code}]: {rpc_resp.error.message}"
                    )

                self._record_success()
                return rpc_resp.result

            except Exception as e:
                last_exception = e
                logger.warning(
                    f"MCP request to {self.config.provider_id} (attempt {attempt + 1}) failed: {e}"
                )
                await asyncio.sleep(0.5 * (2 ** attempt))

        self._record_failure()
        try:
            from app.services.audit_service import audit_service
            asyncio.create_task(
                audit_service.log_event(
                    domain_category="third_party_failure",
                    event_name="mcp_third_party_failure",
                    execution_status="failed",
                    error_type="MCPClientError",
                    error_message=f"External MCP server '{self.config.provider_id}' failed: {last_exception}",
                    metadata_payload={"provider": self.config.provider_id, "url": self.config.server_url, "method": method},
                )
            )
        except Exception:
            pass
        raise MCPClientError(f"MCP provider '{self.config.provider_id}' failed: {last_exception}")

    async def list_tools(self, force_refresh: bool = False) -> List[MCPTool]:
        """Discover available tools advertised by this MCP server."""
        now = time.time()
        if not force_refresh and self._tools_cache and (now - self._tools_cache_time) < self._cache_ttl_seconds:
            return self._tools_cache

        result = await self._send_jsonrpc(MCPMethod.TOOLS_LIST.value)
        tools_data = result.get("tools", []) if isinstance(result, dict) else []

        tools: List[MCPTool] = []
        for t in tools_data:
            tool = MCPTool(
                name=t.get("name", "unnamed_tool"),
                description=t.get("description", ""),
                inputSchema=t.get("inputSchema", {}),
                provider=self.config.provider_id,
                is_anonymous=self.config.anonymous,
            )
            tools.append(tool)

        self._tools_cache = tools
        self._tools_cache_time = now
        return tools

    async def call_tool(
        self,
        name: str,
        arguments: Dict[str, Any],
        anonymous: Optional[bool] = None,
    ) -> CallToolResult:
        """Call an MCP tool with optional anonymous scrubbing of arguments and parameters."""
        should_anonymize = self.config.anonymous if anonymous is None else anonymous

        # Scrub payload before it leaves the application perimeter
        safe_args = AnonymousScrubber.anonymize_payload(arguments) if should_anonymize else arguments

        params = {
            "name": name,
            "arguments": safe_args,
        }

        logger.info(
            f"Invoking MCP tool '{name}' on provider '{self.config.provider_id}' (Anonymous: {should_anonymize})"
        )

        try:
            raw_result = await self._send_jsonrpc(MCPMethod.TOOLS_CALL.value, params)
            if not isinstance(raw_result, dict):
                return CallToolResult(
                    content=[ToolContentItem(type="text", text=str(raw_result))],
                    isError=False,
                    metadata={"provider": self.config.provider_id, "anonymous": should_anonymize},
                )

            content_items: List[ToolContentItem] = []
            for item in raw_result.get("content", []):
                if isinstance(item, dict):
                    content_items.append(ToolContentItem(**item))
                else:
                    content_items.append(ToolContentItem(type="text", text=str(item)))

            return CallToolResult(
                content=content_items,
                isError=raw_result.get("isError", False),
                metadata={
                    "provider": self.config.provider_id,
                    "anonymous": should_anonymize,
                    "scrubbed_input": should_anonymize,
                },
            )

        except Exception as e:
            logger.error(f"Failed to execute MCP tool '{name}': {e}")
            return CallToolResult(
                content=[ToolContentItem(type="text", text=f"Error executing tool '{name}': {str(e)}")],
                isError=True,
                metadata={"provider": self.config.provider_id, "error": str(e)},
            )

    async def close(self) -> None:
        """Close connection pools."""
        if self._http_client and not self._http_client.is_closed:
            await self._http_client.aclose()
