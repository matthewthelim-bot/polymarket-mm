"""
Credential loading for Polymarket live trading.

Loads all secrets from environment variables only — never from hardcoded values.
Searches for a .env file in the project root and its parent directories.

SECURITY: Never log, print, or expose any credential values.
The credential fields must not appear in tracebacks, repr output, or logs.
"""

from __future__ import annotations
import os
from dataclasses import dataclass, field
from pathlib import Path


# Sentinel to detect missing fields without exposing the value
_MISSING = object()


def _load_env_file() -> None:
    """
    Try to load a .env file, searching from CWD upward.
    Uses python-dotenv if available; otherwise parses manually.
    """
    search = Path.cwd()
    for _ in range(5):  # search up to 5 levels
        candidate = search / ".env"
        if candidate.exists():
            _parse_env_file(candidate)
            return
        parent = search.parent
        if parent == search:
            break
        search = parent


def _parse_env_file(path: Path) -> None:
    """Parse a simple KEY=VALUE .env file into os.environ (no overwrite)."""
    try:
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = value
    except OSError:
        pass


@dataclass
class Credentials:
    """
    Holds Polymarket credentials loaded from environment.

    SECURITY: __repr__ and __str__ are intentionally omitted to prevent
    accidental credential exposure in logs or tracebacks.
    """
    poly_address: str
    poly_api_key: str
    poly_api_secret: str
    poly_api_passphrase: str
    private_key: str

    def __repr__(self) -> str:
        return "Credentials(<redacted>)"

    def __str__(self) -> str:
        return "Credentials(<redacted>)"


class CredentialError(Exception):
    """Raised when required credentials cannot be loaded."""


def load_credentials() -> Credentials:
    """
    Load Polymarket credentials from environment variables.

    Searches for a .env file in CWD and parent directories before reading
    environment variables. Variables already set in the environment take
    precedence over .env file values.

    Returns:
        Credentials with all five required fields populated.

    Raises:
        CredentialError: if any required variable is missing.
    """
    _load_env_file()

    required = {
        "POLY_ADDRESS": "poly_address",
        "POLY_API_KEY": "poly_api_key",
        "POLY_API_SECRET": "poly_api_secret",
        "POLY_API_PASSPHRASE": "poly_api_passphrase",
        "PRIVATE_KEY": "private_key",
    }

    values: dict[str, str] = {}
    missing: list[str] = []

    for env_var, field_name in required.items():
        val = os.environ.get(env_var, "")
        if not val:
            missing.append(env_var)
        else:
            values[field_name] = val

    if missing:
        raise CredentialError(
            f"Missing required environment variables: {', '.join(missing)}. "
            "Set them in a .env file or export them before running."
        )

    return Credentials(**values)
