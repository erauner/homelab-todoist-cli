"""Configuration management for Todoist CLI."""

import json
import os
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "todoist"
CONFIG_FILE = CONFIG_DIR / "config.json"


def get_config() -> dict:
    """Load configuration from config file."""
    if not CONFIG_FILE.exists():
        return {}
    with open(CONFIG_FILE) as f:
        return json.load(f)


def get_token() -> str | None:
    """Get API token from config or environment."""
    # Environment variable takes precedence
    if token := os.environ.get("TODOIST_API_TOKEN"):
        return token
    config = get_config()
    return config.get("token")


def save_config(config: dict) -> None:
    """Save configuration to config file."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)
    # Secure the config file (contains API token)
    CONFIG_FILE.chmod(0o600)


def require_token() -> str:
    """Get API token or raise an error with helpful message."""
    token = get_token()
    if not token:
        raise SystemExit(
            "No API token found.\n\n"
            "Set your token in one of these ways:\n"
            "  1. Environment variable: export TODOIST_API_TOKEN=your_token\n"
            "  2. Config file: ~/.config/todoist/config.json with {\"token\": \"your_token\"}\n\n"
            "Get your token from: Todoist Settings -> Integrations -> Developer -> API token"
        )
    return token
