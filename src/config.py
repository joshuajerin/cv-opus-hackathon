"""
Config — loads API keys from OpenClaw's auth store.
"""
import json
import os
from pathlib import Path

AUTH_PROFILES_PATH = Path.home() / ".openclaw/agents/main/agent/auth-profiles.json"


def load_anthropic_key() -> str | None:
    """Load Anthropic API key from env or OpenClaw auth profiles."""
    # Check env first
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key:
        return key

    # Pull from OpenClaw auth store
    if AUTH_PROFILES_PATH.exists():
        try:
            data = json.loads(AUTH_PROFILES_PATH.read_text())
            profiles = data.get("profiles", data)
            for name, profile in profiles.items():
                if "anthropic" in name.lower() and profile.get("key"):
                    return profile["key"]
        except Exception:
            pass

    return None


def ensure_anthropic_key():
    """Set ANTHROPIC_API_KEY in env if not already set."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        key = load_anthropic_key()
        if key:
            os.environ["ANTHROPIC_API_KEY"] = key
        else:
            raise RuntimeError(
                "No Anthropic API key found. Set ANTHROPIC_API_KEY or configure via OpenClaw."
            )


# Auto-load on import
ensure_anthropic_key()
