# azure-mcp-cli-client

## Description

This CLI application integrates Azure OpenAI's function calling with Model Context Protocol (MCP) tools, enabling an interactive agent chat from the terminal. It loads Azure OpenAI configuration, connects to configured MCP servers, registers available tools, and orchestrates tool calls based on LLM responses.

## Usage

1. Install dependencies:
   pip install -r requirements.txt

2. Run the chat CLI:
   python mcp_chat_cli.py

3. Command options:
   --reset    Delete saved configurations and saved MCP server list.
   reset      Reset chat history during a session.
   exit/quit  Exit the chat application.

## Build
"""mcp_cli.py
Async CLI that orchestrates Azure OpenAI function calling with Model Context Protocol (MCP) tools.
Tested with
    * openai   >= 1.13.3  (uses **AsyncAzureOpenAI**)
    * mcp      >= 1.10.1
    * Python   >= 3.10 (3.13 ready)

Build single-file exe (PowerShell):
    py -m pip install pyinstaller
    pyinstaller -F -n mcpcli mcp_cli.py
"""

## Contributing
This project has adopted the [Microsoft Open Source Code of Conduct](https://opensource.microsoft.com/codeofconduct/). For more information see the [Code of Conduct FAQ](https://opensource.microsoft.com/codeofconduct/faq/) or contact [opencode@microsoft.com](mailto:opencode@microsoft.com) with any additional questions or comments.