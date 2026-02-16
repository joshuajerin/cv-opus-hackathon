"""
Config — centralized configuration with env overrides.

Loads API keys from OpenClaw's auth store. All pipeline parameters
are configurable via environment variables with sensible defaults.
"""
import json
import os
from pathlib import Path
from dataclasses import dataclass

AUTH_PROFILES_PATH = Path.home() / ".openclaw/agents/main/agent/auth-profiles.json"


@dataclass(frozen=True)
class PipelineConfig:
    """Immutable pipeline configuration. Env vars override defaults."""

    # Model
    model: str = os.getenv("HWB_MODEL", "claude-opus-4-6")
    max_tokens_requirements: int = int(os.getenv("HWB_TOKENS_REQ", "2000"))
    max_tokens_parts: int = int(os.getenv("HWB_TOKENS_PARTS", "8192"))
    max_tokens_pcb: int = int(os.getenv("HWB_TOKENS_PCB", "8192"))
    max_tokens_cad: int = int(os.getenv("HWB_TOKENS_CAD", "5000"))
    max_tokens_assembly: int = int(os.getenv("HWB_TOKENS_ASM", "8192"))

    # Retry
    max_retries: int = int(os.getenv("HWB_MAX_RETRIES", "3"))
    retry_base_ms: int = int(os.getenv("HWB_RETRY_BASE_MS", "1000"))

    # Cache
    cache_dir: str = os.getenv("HWB_CACHE_DIR", "/tmp/hwb_cache")
    cache_ttl_s: int = int(os.getenv("HWB_CACHE_TTL", "3600"))

    # Search
    fts_max_candidates: int = int(os.getenv("HWB_FTS_MAX", "2000"))
    bom_max_parts: int = int(os.getenv("HWB_BOM_MAX", "50"))

    # Pricing
    inr_to_usd: float = float(os.getenv("HWB_INR_USD", "0.012"))

    # Server
    host: str = os.getenv("HWB_HOST", "0.0.0.0")
    port: int = int(os.getenv("HWB_PORT", "8000"))

    # Output
    output_dir: str = os.getenv("HWB_OUTPUT_DIR", "output")


# Singleton
CONFIG = PipelineConfig()


def load_anthropic_key() -> str | None:
    """Load Anthropic API key from env or OpenClaw auth profiles."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key:
        return key
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
