# azure-mcp-cli-client

## Description

This CLI application integrates Azure OpenAI's function calling with Model Context Protocol (MCP) tools, enabling an interactive agent chat from the terminal. It loads Azure OpenAI configuration, connects to configured MCP servers, registers available tools, and orchestrates tool calls based on LLM responses.

## Usage

1. Install dependencies:
   pip install -r requirements.txt

2. Run the chat CLI:
   python mcp_chat_cli.py
   - When launching for the first time, you need to enter the Azure OpenAI endpoint, API key, API version, and deployment name.
   - To register the MCP server, you must create a mcp.json file and save it in .azuremcpcli directory under your user home folder(C:\Users\\\<username>\\.azuremcpcli for Windows, ~/.azuremcpcli for Linux). Copy mcp.json.sample to .azuremcpcli/mcp.json for fast start. For more details, refer to MCP Server Registration section.
   - You can build single exe file for Windows. See Build section.

3. Command options:
   - `--reset`: Delete saved configurations and saved MCP server list.
   - `--verbose`: Enable verbose mode: display detailed tool input/output.
   - `--chatlog <path>`: Append all conversation history, including tool calls

4. Chat options:
   - `reset`: Reset chat history during a session.
   - `exit`/`quit`: Exit the chat application.
   - `tools`: List connected MCP servers and their available tools.
   - `tools describe <server>`: Show descriptions for each tool on the specified server.
   - `tools disable <server>`: Disable all tools for the specified server.
   - `tools enable <server>`: Enable all tools for the specified server.
   - `tools reset`: Reconnect all MCP servers with reloading mcp.json configuration.
   - `#<tool_name> <message>`: Force invocation of a specific tool with the given message. Example: `#microsoft_docs_search What is MCP?`

## MCP Server Registration

Before starting the CLI, create your MCP server configuration based on `mcp.json.template` and save it as `~/.azuremcpcli/mcp.json`.

### Steps
1. Create the configuration directory (if it does not exist):
   ```bash
   mkdir -p ~/.azuremcpcli
   ```
2. Copy the template to create `mcp.json`:
   - macOS/Linux
     ```bash
     cp mcp.json.template ~/.azuremcpcli/mcp.json
     ```
   - Windows PowerShell
     ```powershell
     Copy-Item .\mcp.json.template -Destination $HOME\.azuremcpcli\mcp.json
     ```
3. Open `~/.azuremcpcli/mcp.json` and register your server entries according to the `mcp.json.template` format:
   ```json
   {
     "servers": {
       "My MCP Server": {
         "type": "stdio",
         "command": "python",
         "args": ["server.py", "--port", "3000"],
         "env": { "API_KEY": "your key" }
       },
       "Remote MCP": {
         "type": "http",
         "url": "http://localhost:4000",
         "headers": { "X-API-KEY": "your key" }
       }
     }
   }
   ```
4. The `"servers"` format is compatible with VS Code’s [MCP servers configuration](https://code.visualstudio.com/docs/copilot/chat/mcp-servers).

After configuring, run:
```bash
python mcp_chat_cli.py
```
to automatically connect to your registered MCP servers.

## Build
- mcp_cli.py
Async CLI that orchestrates Azure OpenAI function calling with Model Context Protocol (MCP) tools.
Tested with
    * openai   >= 1.13.3  (uses **AsyncAzureOpenAI**)
    * mcp      >= 1.10.1
    * Python   >= 3.10 (3.13 ready)

- Build single-file exe (PowerShell):
    * python -m pip install pyinstaller
    * pyinstaller -F -n mcpcli mcp_chat_cli.py
    * ./dist/mcpcli.exe

## Disclaimer
This application is a sample app and has been developed for testing, evaluation, and demonstration purposes. It is not intended for use in a production environment. If you choose to use this application, please do so at your own risk. Additionally, this application is not affiliated with or endorsed by the organization to which the developer belongs.

## Contributing
This project has adopted the [Microsoft Open Source Code of Conduct](https://opensource.microsoft.com/codeofconduct/). For more information see the [Code of Conduct FAQ](https://opensource.microsoft.com/codeofconduct/faq/) or contact [opencode@microsoft.com](mailto:opencode@microsoft.com) with any additional questions or comments.