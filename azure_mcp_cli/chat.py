import asyncio
import json
from datetime import datetime
from typing import Any, Dict, List, Optional
import types  # for dummy message on error

from openai import AsyncAzureOpenAI
from contextlib import AsyncExitStack

from azure_mcp_cli.config import ask_user, DEFAULT_SYSTEM_PROMPT, load_mcp_servers
from azure_mcp_cli.mcp_manager import MCPManager
from azure.identity import DefaultAzureCredential, get_bearer_token_provider


async def chat_loop(cfg: Dict[str, str], mcp: MCPManager, verbose: bool, chatlog: Optional[str] = None, batch_input: Optional[str] = None):
    # Initialize Azure OpenAI client using API key or Azure AD credential if API key is empty
    api_key = cfg.get("api_key", "")
    if api_key:
        client = AsyncAzureOpenAI(
            azure_endpoint=cfg["endpoint"],
            api_key=api_key,
            api_version=cfg["api_version"],
        )
    else:

        token_provider = get_bearer_token_provider(
            DefaultAzureCredential(), "https://cognitiveservices.azure.com/.default"
        )
        client = AsyncAzureOpenAI(
            azure_endpoint=cfg["endpoint"],
            azure_ad_token_provider=token_provider,
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
    # track disabled servers (default: all enabled) and auto-approve flag
    disabled_servers: set[str] = set()
    auto_approve: bool = False

    # helper to build LLM call kwargs with optional filtering and function_call
    def build_kwargs(func_call: Any = None, filter_disabled: bool = True) -> Dict[str, Any]:
        kw: Dict[str, Any] = {"model": deployment, "messages": messages}
        # Azure OpenAI optional params
        if "max_tokens" in cfg:
            try:
                kw["max_tokens"] = int(cfg["max_tokens"])
            except (ValueError, TypeError):
                pass
        if "temperature" in cfg:
            try:
                kw["temperature"] = float(cfg["temperature"])
            except (ValueError, TypeError):
                pass
        if "top_p" in cfg:
            try:
                kw["top_p"] = float(cfg["top_p"])
            except (ValueError, TypeError):
                pass
        # include functions
        if mcp.function_defs:
            funcs = mcp.function_defs
            if filter_disabled:
                # filter out disabled servers
                funcs = [f for f in funcs if mcp.session_to_server_name.get(mcp.tool_to_session.get(f["name"])) not in disabled_servers]
            if funcs:
                kw["functions"] = funcs
                # determine function call
                if func_call:
                    # explicit call by name
                    kw["function_call"] = {"type": "function", "name": func_call}
                else:
                    kw["function_call"] = "auto"
        return kw
    # helper to call LLM and extract message
    async def send_msg(func_call: Any = None, filter_disabled: bool = True):
        try:
            resp = await client.chat.completions.create(**build_kwargs(func_call, filter_disabled))
            return resp.choices[0].message
        except Exception as e:
            if verbose:
                print(f"❌ Error calling LLM: {e}")
            # Return dummy message to continue flow
            return types.SimpleNamespace(function_call=None, content=f"[Error] LLM call failed")
    # unified loop to process LLM, function calls, approval, logging, and final assistant message
    async def process_llm(batch_mode: bool, forced_call: Any = None) -> str:
        nonlocal auto_approve
        forced = forced_call
        while True:
            msg = await send_msg(func_call=forced, filter_disabled=not batch_mode)
            forced = None
            # tool call invoked by LLM
            if msg.function_call:
                fname = msg.function_call.name
                try:
                    fargs = json.loads(msg.function_call.arguments or "{}")
                except json.JSONDecodeError:
                    fargs = {}
                # approval logic
                approved = batch_mode or auto_approve
                if not batch_mode and not auto_approve:
                    while True:
                        choice = await asyncio.to_thread(ask_user, f"Execute tool 🔧 {fname}? (y=yes, n=no, a=always, s=show args) ")
                        choice = choice.strip().lower()
                        if choice == "a":
                            auto_approve = True
                            approved = True
                            break
                        if choice == "y":
                            approved = True
                            break
                        if choice == "n":
                            approved = False
                            break
                        if choice == "s":
                            print(f"Tool arguments: {fargs}")
                            continue
                        print("Invalid choice, please select y, n, a, or s.")
                # execute or skip
                if approved:
                    # tool execution print
                    if verbose:
                        print(f"🔧 Calling tool {fname} with args {fargs}")
                    else:
                        if not batch_mode:
                            print(f"🔧 Calling tool {fname}")
                    try:
                        result = await mcp.call_tool(fname, fargs)
                    except Exception as e:
                        result = {"error": str(e)}
                else:
                    if not batch_mode:
                        print(f"❌ Skipping tool {fname}")
                    result = {"error": "Tool execution skipped by user"}
                # serialize and append
                if isinstance(obj := result, str):
                    rtxt = obj
                else:
                    try:
                        rtxt = json.dumps(getattr(result, "output", getattr(result, "model_dump", result)), ensure_ascii=False, default=str)
                    except Exception:
                        rtxt = str(result)
                messages.append({"role": "function", "name": fname, "content": rtxt})
                if log_file:
                    log_file.write(json.dumps(messages[-1], ensure_ascii=False) + "\n")
                if verbose:
                    print(f"🛠️ Tool result: {rtxt}")
                continue
            # final assistant message
            content = msg.content
            if not batch_mode:
                print(f"🤖 AI> {content}")
            messages.append({"role": "assistant", "content": content})
            if log_file:
                log_file.write(json.dumps(messages[-1], ensure_ascii=False) + "\n")
            return content
    # batch mode: send single input and output final response
    if batch_input is not None:
        messages.append({"role": "user", "content": batch_input})
        if log_file:
            log_file.write(json.dumps(messages[-1], ensure_ascii=False) + "\n")
        # run LLM until final response (auto-approve all tools)
        content = await process_llm(batch_mode=True)
        print(content)
        if log_file:
            log_file.close()
        return

    print("\n📝 Starting AI agent chat — 'reset' to reset history, 'exit' to quit\n")
    while True:
        # read user input
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
         
        # append user message (forced or normal)
        user_msg = forced_user_message if forced_user_message is not None else user_in
        messages.append({"role": "user", "content": user_msg})
        if log_file:
            log_file.write(json.dumps(messages[-1], ensure_ascii=False) + "\n")
        # process LLM (including tool calls) and display interactive response
        await process_llm(batch_mode=False, forced_call=forced_tool_call)

    if log_file:
        log_file.close()
