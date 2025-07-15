# Azure MCP CLI Client
https://github.com/hatasaki/azure-mcp-cli-client

## Description

This CLI application integrates Azure OpenAI's function calling with Model Context Protocol (MCP) tools, enabling an interactive agent chat from the terminal. It loads Azure OpenAI configuration, connects to configured MCP servers, registers available tools, and orchestrates tool calls based on LLM responses.

![scrrenshot](/assets/Azure-MCP-CLI-Client-screenshot.png)

## Download

Pre-built binaries are available in GitHub Releases for:

- **Windows**: `azuremcpcli-windows-<version>.zip` (contains `mcpcli.exe`)
- **Linux**: `azuremcpcli-linux-<version>.tar.gz` (contains `mcpcli`)
- **macOS**: `azuremcpcli-macos-<version>.tar.gz` (contains `mcpcli`)

Download and extract the archive, then add the extraction directory to your PATH environment variable.

## Usage

### Release Binaries

After downloading and extracting the release binaries, add the extraction directory to your PATH.

```bash
# interactive mode
mcpcli

# batch mode
mcpcli --batch "<user input>"
```

### From Source

If you prefer to run from source, follow these steps:

```bash
# Clone the repository
git clone https://github.com/hatasaki/azure-mcp-cli-client

# Install dependencies
pip install -r requirements.txt

# Run the chat CLI
# interactive mode
python mcp_chat_cli.py

# batch mode
python mcp_chat_cli.py --batch "<user input>"
```

### Initial setup
   - When launching for the first time, you need to enter the Azure OpenAI endpoint, API key, API version, and deployment name. When the API key is blank, authenticate using Entra ID (you must be logged in via `az login` in your desktop environment)
   - To register the MCP server, you must create a mcp.json file and save it in .azuremcpcli directory under your user home folder(`C:\Users\<username>\.azuremcpcli` for Windows, `~/.azuremcpcli` for Linux). Copy mcp.json.sample to .azuremcpcli/mcp.json for fast start. For more details, refer to MCP Server Registration section.

### Options
- Command options:
   - `--reset`: Delete saved configurations and saved MCP server list.
   - `--verbose`: Enable verbose mode: display detailed tool input/output.
   - `--chatlog <file path>`: Append all conversation history including tool calls to the file
   - `--batch <user input>`: Run a single user input in batch mode. Sends the specified input once, auto-approves all tool calls, and prints only the final response. Use `--verbose` to show connection and tool logs. Example:
      ``` powershell
      mcpcli --batch "List up the latest MCP related features in Azure" 
      ```
   - `--azureconfig <file>`: Specify a custom Azure OpenAI configuration file instead of the default (AzureOpenAI.json).
   - `--mcpconfig <file>`: Specify a custom MCP server configuration file instead of the default (mcp.json).

- Chat options:
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
# default MCP server configuratiom file (~/.azuremcpcli/mcp.json)
mcpcli

# Specify custom MCP server configuration file
mcpcli --mcpconfig <MCP config file>
```
to automatically connect to your registered MCP servers.

## Azure OpenAI Configuration

After lunching for first time, Azure OpenAI configuration file automatically created at `~/.azuremcpcli/AzureOpenAI.json`. You also create your own configuration and specify to use it with `--azureconfig` option.

   ```json
   {
     "endpoint": "https://<your-endpoint>.openai.azure.com/",
     "api_key": "<your-api-key-or-blank>", // blank for using Entra ID authentication
     "api_version": "2025-04-01-preview",
     "deployment": "<your-deployment-name>",
     "max_tokens": 32768, // integer number for max tokens
     "temperature": 0.7, // float number for temperature
     "top_p": 1.0, // float number for top_p
     "system_message": "You are a helpful assistant..." // system prompt for the agent
   }
   ```

## Multi Agentic chaining
By using the `--batch` option, you can chain multiple commands with different types of Azure OpenAI service and MCP server configurations, enabling more complex integrations between agents and tools. Similarly, this tool can be linked with various applications. The use cases are entirely up to you!
### Example:
Run first command with GPT-4.1(aoai_gpt41.json) and Microsoft Docs MCP server(mcp_mslear.json), then summrize with o3 model(default config).
-  Windows (powershell)
```powershell
mcpcli --batch "Summarize 100 words: $(mcpcli --batch "List up the latest MCP related features in Azure"  --azureconfig aoai_gpt41.json --mcpconfig mcp_mslearn.json --raw)"
```
- Linux/MacOS (bash)
```bash
mcpcli --batch "Summarize 100 words: $(mcpcli --batch 'List up the latest MCP related features in Azure' --azureconfig aoai_gpt41.json --mcpconfig mcp_mslearn.json --raw)"
```

## Disclaimer
This application is a sample app and has been developed for testing, evaluation, and demonstration purposes. It is not intended for use in a production environment. If you choose to use this application, please do so at your own risk. Additionally, this application is not affiliated with or endorsed by the organization to which the developer belongs.

## Contributing
This project has adopted the [Microsoft Open Source Code of Conduct](https://opensource.microsoft.com/codeofconduct/). For more information see the [Code of Conduct FAQ](https://opensource.microsoft.com/codeofconduct/faq/) or contact [opencode@microsoft.com](mailto:opencode@microsoft.com) with any additional questions or comments.

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.