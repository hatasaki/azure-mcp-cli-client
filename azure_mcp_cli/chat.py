import asyncio
import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from openai import AsyncAzureOpenAI
from contextlib import AsyncExitStack

from azure_mcp_cli.config import ask_user, DEFAULT_SYSTEM_PROMPT, load_mcp_servers
from azure_mcp_cli.mcp_manager import MCPManager


async def chat_loop(cfg: Dict[str, str], mcp: MCPManager, verbose: bool, chatlog: Optional[str] = None):
    client = AsyncAzureOpenAI(
        azure_endpoint=cfg["endpoint"],
        api_key=cfg["api_key"],
        api_version=cfg["api_version"],
    )
    deployment = cfg["deployment"]
    system_prompt = cfg.get("system_prompt", DEFAULT_SYSTEM_PROMPT)
    # Append current date to system prompt
    current_date = datetime.now().strftime("%Y-%m-%d")
    system_prompt = f"{system_prompt}\nCurrent date: {current_date}"  
    messages: List[Dict[str, Any]] = [{"role": "system", "content": system_prompt}]
    # open log file for appending if path provided
    log_file = open(chatlog, 'a', encoding='utf-8') if chatlog else None
    if log_file:
        log_file.write(json.dumps(messages[0], ensure_ascii=False) + "\n")
    print("\n📝 Starting AI agent chat — 'reset' to reset history, 'exit' to quit\n")
    # track disabled servers (default: all enabled)
    disabled_servers: set[str] = set()
    # auto-approve flag: if set, automatically approve all tool executions until reset
    auto_approve: bool = False

    while True:
        raw = await asyncio.to_thread(ask_user, "👤 User> ")  # blocking input
        user_in = raw.strip()
        # detect forced tool call via '#tool_name [message]'
        forced_tool_call: Optional[str] = None
        forced_user_message: Optional[str] = None
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
                # reset auto-approve on history reset
                auto_approve = False
                if log_file:
                    log_file.write(json.dumps({"role": "system", "content": "History reset"}, ensure_ascii=False) + "\n")
                    log_file.write(json.dumps(messages[0], ensure_ascii=False) + "\n")
                continue
            # reset all MCP server connections and reload configuration
            if user_in.lower() == "tools reset":
                # close existing MCP connections
                if mcp._stack:
                    await mcp._stack.__aexit__(None, None, None)
                # clear tool mappings and server names
                mcp.tool_to_session.clear()
                mcp.function_defs.clear()
                mcp.session_to_server_name.clear()
                # reload server definitions and reconnect
                servers = load_mcp_servers()
                mcp._servers_conf = servers
                mcp._stack = AsyncExitStack()
                await mcp._stack.__aenter__()
                await mcp._connect_all()
                # reset disable/enable flags
                disabled_servers.clear()
                print("🔄 Tools reset: reloaded configuration and reconnected to MCP servers")
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
                for tname, sess in mcp.tool_to_session.items():
                    srv = mcp.session_to_server_name.get(sess, "Unknown")
                    server_tools.setdefault(srv, []).append(tname)
                print("🛠️ Connected MCP servers and their tools (status):")
                for srv, tools in server_tools.items():
                    status = "disabled" if srv in disabled_servers else "enabled"
                    print(f"🧰 {srv} [{status}]: {', '.join(tools)}")
                continue
            # show tools descriptions for a specific server
            if user_in.lower().startswith("tools describe "):
                srv_name = user_in[len("tools describe "):].strip()
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
        if log_file:
            log_file.write(json.dumps(messages[-1], ensure_ascii=False) + "\n")

        while True:
            # prepare LLM call, filtering out tools from disabled servers and applying forced tool choice
            kwargs: Dict[str, Any] = {"model": deployment, "messages": messages}
            # include optional Azure OpenAI parameters if defined in AzureOpenAI.json
            if "max_tokens" in cfg:
                try:
                    kwargs["max_tokens"] = int(cfg["max_tokens"])
                except (ValueError, TypeError):
                    pass
            if "temperature" in cfg:
                try:
                    kwargs["temperature"] = float(cfg["temperature"])
                except (ValueError, TypeError):
                    pass
            if "top_p" in cfg:
                try:
                    kwargs["top_p"] = float(cfg["top_p"])
                except (ValueError, TypeError):
                    pass
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
                # Approval before executing the tool
                approved: bool = True
                if not auto_approve:
                    while True:
                        choice = await asyncio.to_thread(ask_user, f"Execute tool 🔧 {fname}? (y=yes, n=no, a=always, s=show args) ")
                        choice = choice.strip().lower()
                        if choice == "a":
                            auto_approve = True
                            approved = True
                            break
                        elif choice == "y":
                            approved = True
                            break
                        elif choice == "n":
                            approved = False
                            break
                        elif choice == "s":
                            print(f"Tool arguments: {fargs}")
                            continue
                        else:
                            print("Invalid choice, please select y, n, a, or s.")
                if approved:
                    if verbose:
                        print(f"🔧 Calling tool {fname} with args {fargs}")
                    else:
                        print(f"🔧 Calling tool {fname}")
                    try:
                        result = await mcp.call_tool(fname, fargs)
                    except Exception as e:
                        result = {"error": str(e)}
                else:
                    print(f"❌ Skipping tool {fname}")
                    result = {"error": "Tool execution skipped by user"}
                rtxt = _serialize_result(result)
                messages.append({"role": "function", "name": fname, "content": rtxt})
                if log_file:
                    log_file.write(json.dumps(messages[-1], ensure_ascii=False) + "\n")
                if verbose:
                    print(f"🛠️ Tool result: {rtxt}")
                continue  # ask LLM again with new function-result

            # ---- Final assistant message -----------------------------------
            print(f"🤖 AI> {msg.content}")
            messages.append({"role": "assistant", "content": msg.content})
            if log_file:
                log_file.write(json.dumps(messages[-1], ensure_ascii=False) + "\n")
            break

    if log_file:
        log_file.close()
