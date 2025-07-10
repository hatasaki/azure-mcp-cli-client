from __future__ import annotations

import asyncio
import json
import os
import sys
from contextlib import AsyncExitStack
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from openai import AsyncAzureOpenAI  # NOTE: async client!
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamablehttp_client
from mcp.client.sse import sse_client

# ---------------------------------------------------------------------------
# Paths & Defaults
# ---------------------------------------------------------------------------
HOME = Path.home()
CONF_DIR = HOME / ".azuremcpcli"
AZURE_CONF_PATH = CONF_DIR / "AzureOpenAI.json"
MCP_CONF_PATH = CONF_DIR / "mcp.json"

# Default system prompt: instruct the agent to analyze user intent, set goals, execute necessary tools until goals are met, and return the final response
DEFAULT_SYSTEM_PROMPT = (
    "Based on the user's instructions, analyze the user's intent, define goals to achieve that intent, "
    "invoke and execute necessary tools until the goals are accomplished, and finally return the response to the user."
)

# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def ask_user(prompt: str) -> str:  # blocking wrapper (used via to_thread)
    return input(prompt)


def ensure_conf_dir() -> None:
    CONF_DIR.mkdir(parents=True, exist_ok=True)


def load_or_create_azure_conf() -> Dict[str, str]:
    ensure_conf_dir()
    if AZURE_CONF_PATH.exists():
        return json.loads(AZURE_CONF_PATH.read_text("utf-8"))

    print("⚙️  Please enter Azure OpenAI connection information (first run only)")
    cfg = {
        "endpoint": ask_user("Azure OpenAI endpoint URL: ").strip(),
        "api_key": ask_user("Azure OpenAI API key: ").strip(),
        "api_version": ask_user("API version (e.g., 2024-02-15-preview): ").strip(),
        "deployment": ask_user("Model deployment name: ").strip(),
        "system_prompt": DEFAULT_SYSTEM_PROMPT,
        "created": datetime.utcnow().isoformat() + "Z",
    }
    AZURE_CONF_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), "utf-8")
    print(f"✅ Configuration saved to {AZURE_CONF_PATH}")
    return cfg


def load_mcp_servers() -> List[Dict[str, Any]]:
    if MCP_CONF_PATH.is_file():
        data = json.loads(MCP_CONF_PATH.read_text("utf-8"))
        # wrapper format: { "servers": { name: config, ... } } or list
        if isinstance(data, dict) and "servers" in data:
            srv_data = data["servers"]
            # list of server dicts
            if isinstance(srv_data, list):
                return srv_data
            # dict of named configs
            if isinstance(srv_data, dict):
                servers = []
                for name, cfg in srv_data.items():
                    srv = {"name": name}
                    t = cfg.get("type", "")
                    srv.update({
                        "transport": t,
                        "command": cfg.get("command", ""),
                        "args": cfg.get("args", []),
                        "env": cfg.get("env", {}),
                        "url": cfg.get("url", ""),
                        "headers": cfg.get("headers", {}),
                    })
                    servers.append(srv)
                return servers
        # template format: top-level name:config
        if isinstance(data, dict) and all(isinstance(v, dict) for v in data.values()):
            servers = []
            for name, cfg in data.items():
                srv = {"name": name}
                t = cfg.get("type", "")
                srv.update({
                    "transport": t,
                    "command": cfg.get("command", ""),
                    "args": cfg.get("args", []),
                    "env": cfg.get("env", {}),
                    "url": cfg.get("url", ""),
                    "headers": cfg.get("headers", {}),
                })
                servers.append(srv)
            return servers
        # fallback: raw list
        if isinstance(data, list):
            return data
    return []

# ---------------------------------------------------------------------------
# MCP handling
# ---------------------------------------------------------------------------
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

    # ---- connection helpers ------------------------------------------------
    async def _connect_all(self):
        for srv in self._servers_conf:
            name = srv.get("name", "Unnamed MCP Server")
            transport = srv.get("transport", "http").lower()
            try:
                if transport == "stdio":
                    await self._connect_stdio(name, srv)
                elif transport in {"http", "streamable", "streamable-http", "stream", "streamable_http"}:
                    await self._connect_streamable_http(name, srv)
                elif transport == "sse":
                    await self._connect_sse(name, srv)
                else:
                    print(f"⚠️ Unsupported transport: {transport} ({name}) — skipping")
            except Exception as e:  # noqa: BLE001
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
        # record mapping of session to server name
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
        # record mapping of session to server name
        self.session_to_server_name[session] = name
        tool_count = await self._register_session(session)
        print(f"✅ Connected to {name} (streamable-http) — {tool_count} tools")

    async def _connect_sse(self, name: str, cfg: Dict[str, Any]):
        url = cfg.get("url")
        if not url:
            raise ValueError("url not set")
        read, write = await self._stack.enter_async_context(sse_client(url, headers=cfg.get("headers") or None))
        session = await self._stack.enter_async_context(ClientSession(read, write))
        # record mapping of session to server name
        self.session_to_server_name[session] = name
        tool_count = await self._register_session(session)
        print(f"✅ Connected to {name} (SSE) — {tool_count} tools — recommended: Streamable HTTP")

    # ---- tool execution ----------------------------------------------------
    async def call_tool(self, name: str, args: Dict[str, Any] | None):
        if name not in self.tool_to_session:
            raise KeyError(f"Tool '{name}' not registered")
        return await self.tool_to_session[name].call_tool(name, args or {})

# ---------------------------------------------------------------------------
# Chat loop
# ---------------------------------------------------------------------------
async def chat_loop(cfg: Dict[str, str], mcp: MCPManager, verbose: bool):
    client = AsyncAzureOpenAI(
        azure_endpoint=cfg["endpoint"],
        api_key=cfg["api_key"],
        api_version=cfg["api_version"],
    )
    deployment = cfg["deployment"]
    system_prompt = cfg.get("system_prompt", DEFAULT_SYSTEM_PROMPT)

    messages: List[Dict[str, Any]] = [{"role": "system", "content": system_prompt}]
    print("\n📝 Starting AI agent chat — 'reset' to reset history, 'exit' to quit\n")
    # track disabled servers (default: all enabled)
    disabled_servers: set[str] = set()

    while True:
        raw = await asyncio.to_thread(ask_user, "User> ")  # blocking input
        user_in = raw.strip()
        # detect forced tool call via '#tool_name [message]'
        forced_tool_call: str | None = None
        forced_user_message: str | None = None
        if user_in.startswith("#"):
            # extract tool name up to first space, rest is message
            txt = user_in[1:].lstrip()
            parts = txt.split(None, 1)
            tool_name = parts[0]
            forced_user_message = parts[1] if len(parts) > 1 else ""
            # verify tool exists
            if tool_name not in mcp.tool_to_session:
                print(f"⚠️ No such tool: {tool_name}")
                continue
            # verify tool's server is enabled
            srv = mcp.session_to_server_name.get(mcp.tool_to_session[tool_name])
            if srv in disabled_servers:
                print(f"⚠️ Tool '{tool_name}' is disabled on server: {srv}")
                continue
            # force this tool for next LLM call
            forced_tool_call = tool_name
        else:
            # existing user commands
            if not user_in:
                continue
            if user_in.lower() in {"exit", "quit"}:
                print("👋  Goodbye!")
                break
            if user_in.lower() == "reset":
                messages = [{"role": "system", "content": system_prompt}]
                print("🔄 History reset")
                continue
            # disable all tools for a server
            if user_in.lower().startswith("tools disable "):
                srv_name = user_in[len("tools disable "):].strip()
                # verify server exists
                if srv_name not in mcp.session_to_server_name.values():
                    print(f"⚠️ No such server: {srv_name}")
                else:
                    disabled_servers.add(srv_name)
                    print(f"🔒 Disabled all tools for server: {srv_name}")
                continue
            # enable all tools for a server
            if user_in.lower().startswith("tools enable "):
                srv_name = user_in[len("tools enable "):].strip()
                # verify server exists
                if srv_name not in mcp.session_to_server_name.values():
                    print(f"⚠️ No such server: {srv_name}")
                else:
                    disabled_servers.discard(srv_name)
                    print(f"🔓 Enabled all tools for server: {srv_name}")
                continue
            # show connected servers and their tools
            if user_in.lower() == "tools":
                server_tools: Dict[str, List[str]] = {}
                for tool_name, sess in mcp.tool_to_session.items():
                    srv = mcp.session_to_server_name.get(sess, "Unknown")
                    server_tools.setdefault(srv, []).append(tool_name)
                print("🛠️ Connected MCP servers and their tools (status):")
                for srv, tools in server_tools.items():
                    status = "disabled" if srv in disabled_servers else "enabled"
                    print(f"{srv} [{status}]: {', '.join(tools)}")
                continue
            # show tools descriptions for a specific server
            if user_in.lower().startswith("tools "):
                srv_name = user_in[6:].strip()
                # map tool name to description
                desc_map = {f['name']: f['description'] for f in mcp.function_defs}
                # filter tools for this server
                tools = [name for name, sess in mcp.tool_to_session.items() if mcp.session_to_server_name.get(sess) == srv_name]
                if not tools:
                    print(f"⚠️ No tools found for server: {srv_name}")
                else:
                    print(f"📝 Tools for server '{srv_name}':")
                    for name in tools:
                        print(f"- {name}: {desc_map.get(name, 'No description')}")
                continue
         
        # append user message, use forced message if provided
        content_to_send = forced_user_message if forced_user_message is not None else user_in
        messages.append({"role": "user", "content": content_to_send})

        while True:
            # prepare LLM call, filtering out tools from disabled servers and applying forced tool choice
            kwargs: Dict[str, Any] = {"model": deployment, "messages": messages}
            if mcp.function_defs:
                # include only functions whose server is enabled
                filtered = []
                for f in mcp.function_defs:
                    sess = mcp.tool_to_session.get(f["name"])
                    srv = mcp.session_to_server_name.get(sess)
                    if srv and srv not in disabled_servers:
                        filtered.append(f)
                if filtered:
                    kwargs["functions"] = filtered
                    # apply forced tool call if requested
                    if forced_tool_call:
                        kwargs["function_call"] = {"type": "function", "name": forced_tool_call}
                    else:
                        kwargs["function_call"] = "auto"
            # only force tool call on first request
            forced_tool_call = None

            resp = await client.chat.completions.create(**kwargs)
            msg = resp.choices[0].message

            # ---- Tool call -------------------------------------------------
            def _serialize_result(obj: Any) -> str:
                """Return JSON-serializable string for tool result."""
                if isinstance(obj, str):
                    return obj
                # mcp.CallToolResult → .output (dict)
                if hasattr(obj, "output"):
                    obj = getattr(obj, "output")
                # Pydantic BaseModel (e.g., CallToolResult) → model_dump()
                elif hasattr(obj, "model_dump"):
                    obj = obj.model_dump()
                try:
                    return json.dumps(obj, ensure_ascii=False, default=str)
                except TypeError:
                    # last resort – convert whole object to str
                    return str(obj)

            if msg.function_call is not None:
                fname = msg.function_call.name
                try:
                    fargs = json.loads(msg.function_call.arguments or "{}")
                except json.JSONDecodeError:
                    fargs = {}
                if verbose:
                    print(f"🔧 Calling tool {fname} with args {fargs}")
                else:
                    print(f"🔧 Calling tool {fname}")
                try:
                    result = await mcp.call_tool(fname, fargs)
                except Exception as e:  # noqa: BLE001
                    result = {"error": str(e)}
                rtxt = _serialize_result(result)
                messages.append({"role": "function", "name": fname, "content": rtxt})
                if verbose:
                    print(f"🛠️ Tool result: {rtxt}")
                continue  # ask LLM again with new function‑result

            # ---- Final assistant message -----------------------------------
            print(f"AI> {msg.content}")
            messages.append({"role": "assistant", "content": msg.content})
            break

# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------
async def main():
    if "--reset" in sys.argv:
        for p in (AZURE_CONF_PATH, MCP_CONF_PATH):
            if p.exists():
                p.unlink()
        print("🗑️ Configuration files deleted")
        return

    azure_cfg = load_or_create_azure_conf()
    # Warn if MCP configuration file is missing
    if not MCP_CONF_PATH.is_file():
        print(f"⚠️ MCP configuration file not found at {MCP_CONF_PATH}. Please create mcp.json file.")
    servers = load_mcp_servers()
    # Determine verbose mode
    verbose = "--verbose" in sys.argv
    if verbose:
        print("🔍 Verbose mode enabled")

    async with MCPManager(servers) as mcp:
        if not mcp.tool_to_session:
            print("⚠️ No MCP tools found — please check your configuration")
        await chat_loop(azure_cfg, mcp, verbose)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n⏹️ Interrupted.")
