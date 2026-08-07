"""Environment-backed settings, validated once at startup."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

from dotenv import load_dotenv


class ConfigError(RuntimeError):
    """Raised when the environment cannot produce a usable Config."""


@dataclass(frozen=True)
class Config:
    token: str
    db_url: str
    logging_level: str
    guild_id: int | None
    admin_role_id: int | None
    answer_cooldown_hours: float
    max_attempts: int


def _optional_int(env: Mapping[str, str], key: str) -> int | None:
    raw = env.get(key, "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        raise ConfigError(f"{key} must be a whole number, got {raw!r}") from None


def _positive_number(env: Mapping[str, str], key: str, default: float) -> float:
    raw = env.get(key, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        raise ConfigError(f"{key} must be a number, got {raw!r}") from None
    if value <= 0:
        raise ConfigError(f"{key} must be greater than zero, got {value}")
    return value


def _async_db_url(raw: str) -> str:
    # aiosqlite is required; a plain sqlite:// URL would silently give us a
    # synchronous driver that blocks the event loop.
    if raw.startswith("sqlite:///"):
        return raw.replace("sqlite:///", "sqlite+aiosqlite:///", 1)
    return raw


def load_config(env: Mapping[str, str] | None = None) -> Config:
    """Build a Config, raising ConfigError with an actionable message."""
    if env is None:
        load_dotenv()
        env = os.environ

    token = env.get("DISCORD_TOKEN", "").strip()
    if not token:
        raise ConfigError(
            "DISCORD_TOKEN is missing or empty. Copy .env.example to .env and "
            "paste your bot token from the Discord Developer Portal."
        )

    max_attempts = int(_positive_number(env, "MAX_ATTEMPTS", 3))

    return Config(
        token=token,
        db_url=_async_db_url(env.get("DB_URL", "").strip() or "sqlite:///app.db"),
        logging_level=env.get("LOGGING_LEVEL", "").strip() or "INFO",
        guild_id=_optional_int(env, "GUILD_ID"),
        admin_role_id=_optional_int(env, "ADMIN_ROLE_ID"),
        answer_cooldown_hours=_positive_number(env, "ANSWER_COOLDOWN_HOURS", 24.0),
        max_attempts=max_attempts,
    )
