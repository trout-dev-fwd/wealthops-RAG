import json
import os

CONFIG_DIR = os.path.expanduser("~/.wealthops")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")
KNOWLEDGE_DB_PATH = os.path.join(CONFIG_DIR, "wealthops.db")
CHATS_DB_PATH = os.path.join(CONFIG_DIR, "chats.db")
GITHUB_REPO = "username/wealthops-rag"
DEFAULT_MODEL = "claude-sonnet-4-20250514"

IRC_DEFAULTS = {
    "irc_server": "irc.greed.software",
    "irc_port": 6697,
    "irc_channel": "#wealthops",
    "irc_nick": "Barbara",
    "help_email": "trout.dev.fwd@gmail.com",
}


def load_config() -> dict:
    """Read config.json, creating the directory if missing. Returns empty dict if file missing."""
    os.makedirs(CONFIG_DIR, exist_ok=True)
    if not os.path.exists(CONFIG_FILE):
        return {}
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def save_config(config: dict) -> None:
    """Write config.json, creating the directory if missing."""
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=4)


def get_api_key() -> str | None:
    """Return the stored API key, or None if not set."""
    return load_config().get("api_key")
