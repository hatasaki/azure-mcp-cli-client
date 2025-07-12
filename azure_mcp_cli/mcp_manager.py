from contextlib import AsyncExitStack
from typing import Any, Dict, List

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamablehttp_client
from mcp.client.sse import sse_client


class MCPManager:
    """Connects to configured MCP servers and exposes their tools."""

    def __init__(self, servers: List[Dict[str, Any]]):
        self._servers_conf = servers
        self._stack: AsyncExitStack | None = None
        self.tool_to_session: Dict[str, ClientSession] = {}
        self.function_defs: List[Dict[str, Any]] = []
        # map each ClientSession to its server name
        self.session_to_server_name: Dict[ClientSession, str] = {}

    async def __aenter__(self):
        self._stack = AsyncExitStack()
        await self._stack.__aenter__()
        await self._connect_all()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if self._stack:
            await self._stack.__aexit__(exc_type, exc, tb)

    async def _connect_all(self):
        for srv in self._servers_conf:
            name = srv.get("name", "Unnamed MCP Server")
            transport = srv.get("transport", "http").lower()
            print(f"🔗 Connecting to {name} ({transport})...")
            try:
                if transport == "stdio":
                    await self._connect_stdio(name, srv)
                elif transport in {"http", "streamable", "streamable-http", "stream", "streamable_http"}:
                    await self._connect_streamable_http(name, srv)
                elif transport == "sse":
                    await self._connect_sse(name, srv)
                else:
                    print(f"⚠️ Unsupported transport: {transport} ({name}) — skipping")
            except Exception as e:
                print(f"❌ Connection to {name} failed: {e}")

    async def _register_session(self, session: ClientSession):
        await session.initialize()
        tool_list = await session.list_tools()
        for t in tool_list.tools:
            if t.name in self.tool_to_session:
                continue  # already registered
            self.tool_to_session[t.name] = session
            self.function_defs.append({
                "name": t.name,
                "description": getattr(t, "description", ""),
                "parameters": getattr(t, "inputSchema", {"type": "object", "properties": {}}),
            })
        return len(tool_list.tools)

    async def _connect_stdio(self, name: str, cfg: Dict[str, Any]):
        cmd = cfg.get("command")
        if not cmd:
            raise ValueError("command not set")
        params = StdioServerParameters(command=cmd, args=cfg.get("args", []), env=cfg.get("env"))
        read, write = await self._stack.enter_async_context(stdio_client(params))
        session = await self._stack.enter_async_context(ClientSession(read, write))
        self.session_to_server_name[session] = name
        tool_count = await self._register_session(session)
        print(f"✅ Connected to {name} (stdio) — {tool_count} tools")

    async def _connect_streamable_http(self, name: str, cfg: Dict[str, Any]):
        url = cfg.get("url")
        if not url:
            raise ValueError("url not set")
        read, write, _ = await self._stack.enter_async_context(
            streamablehttp_client(url, headers=cfg.get("headers") or None)
        )
        session = await self._stack.enter_async_context(ClientSession(read, write))
        self.session_to_server_name[session] = name
        tool_count = await self._register_session(session)
        print(f"✅ Connected to {name} (streamable-http) — {tool_count} tools")

    async def _connect_sse(self, name: str, cfg: Dict[str, Any]):
        url = cfg.get("url")
        if not url:
            raise ValueError("url not set")
        read, write = await self._stack.enter_async_context(
            sse_client(url, headers=cfg.get("headers") or None)
        )
        session = await self._stack.enter_async_context(ClientSession(read, write))
        self.session_to_server_name[session] = name
        tool_count = await self._register_session(session)
        print(f"✅ Connected to {name} (SSE) — {tool_count} tools — recommended: Streamable HTTP")

    async def call_tool(self, name: str, args: Dict[str, Any] | None):
        if name not in self.tool_to_session:
            raise KeyError(f"Tool '{name}' not registered")
        return await self.tool_to_session[name].call_tool(name, args or {})
