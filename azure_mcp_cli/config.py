import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

# Paths & Defaults
HOME = Path.home()
CONF_DIR = HOME / ".azuremcpcli"
AZURE_CONF_PATH = CONF_DIR / "AzureOpenAI.json"
MCP_CONF_PATH = CONF_DIR / "mcp.json"

DEFAULT_SYSTEM_PROMPT = (
    "Based on the user's instructions, analyze the user's intent, define goals to achieve that intent, "
    "invoke and execute necessary tools until the goals are accomplished, and finally return the response to the user."
)


def ask_user(prompt: str) -> str:
    """Blocking prompt to the user (used via to_thread)."""
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
        "api_key": ask_user("Azure OpenAI API key (blank to use EntraID authentication): ").strip(),
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
