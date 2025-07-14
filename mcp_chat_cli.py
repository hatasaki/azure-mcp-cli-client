#!/usr/bin/env python3
"""
Entrypoint for Azure MCP CLI Client.
"""
from __future__ import annotations

import asyncio
import sys
import azure_mcp_cli.config as config
from pathlib import Path

from azure_mcp_cli.config import load_or_create_azure_conf, load_mcp_servers
from azure_mcp_cli.mcp_manager import MCPManager
from azure_mcp_cli.chat import chat_loop


async def main():
    """Main entrypoint: load configuration, connect MCP, and start chat."""
    # parse chat log option
    chatlog: str | None = None
    if "--chatlog" in sys.argv:
        idx = sys.argv.index("--chatlog")
        if idx + 1 < len(sys.argv):
            chatlog = sys.argv[idx + 1]

    # reset configuration
    if "--reset" in sys.argv:
        for p in (config.AZURE_CONF_PATH, config.MCP_CONF_PATH):
            if p.exists():
                p.unlink()
        print("🗑️ Configuration files deleted")
        return

    # load Azure OpenAI and MCP server configurations
    if "--azureconfig" in sys.argv:
        idx = sys.argv.index("--azureconfig")
        if idx + 1 < len(sys.argv):
            config.AZURE_CONF_PATH = Path(sys.argv[idx + 1])
    if "--mcpconfig" in sys.argv:
        idx = sys.argv.index("--mcpconfig")
        if idx + 1 < len(sys.argv):
            config.MCP_CONF_PATH = Path(sys.argv[idx + 1])
    azure_cfg = load_or_create_azure_conf()
    if not config.MCP_CONF_PATH.is_file():
        print(f"⚠️ MCP configuration file not found at {config.MCP_CONF_PATH}. Please create mcp.json file.")
    servers = load_mcp_servers()

    # determine verbose mode
    verbose = "--verbose" in sys.argv
    if verbose:
        print("🔍 Verbose mode enabled")
    # determine batch mode: single input and auto-approve tools
    batch_input: str | None = None
    if "--batch" in sys.argv:
        idx = sys.argv.index("--batch")
        if idx + 1 < len(sys.argv):
            batch_input = sys.argv[idx + 1]

    # connect to MCP servers, suppressing connection prints in batch mode
    import builtins
    _orig_print = builtins.print
    suppress = False
    if batch_input and not verbose:
        suppress = True
        builtins.print = lambda *args, **kwargs: None
    async with MCPManager(servers) as mcp:
        if not mcp.tool_to_session and (verbose or not batch_input):
            print("⚠️ No MCP tools found — please check your configuration")
        # restore print before chat loop so final output is visible
        if suppress:
            builtins.print = _orig_print
        await chat_loop(azure_cfg, mcp, verbose, chatlog, batch_input)
    # ensure print restored
    if suppress:
        builtins.print = _orig_print


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n⏹️ Interrupted.")
