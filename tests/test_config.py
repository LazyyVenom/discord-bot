import pytest

from champak.config import Config, ConfigError, load_config

BASE = {"DISCORD_TOKEN": "abc123"}


def test_loads_token():
    cfg = load_config(BASE)
    assert cfg.token == "abc123"


def test_missing_token_raises():
    with pytest.raises(ConfigError, match="DISCORD_TOKEN"):
        load_config({})


def test_blank_token_raises():
    with pytest.raises(ConfigError, match="DISCORD_TOKEN"):
        load_config({"DISCORD_TOKEN": "   "})


def test_defaults():
    cfg = load_config(BASE)
    assert cfg.db_url == "sqlite+aiosqlite:///app.db"
    assert cfg.logging_level == "INFO"
    assert cfg.guild_id is None
    assert cfg.admin_role_id is None
    assert cfg.answer_cooldown_hours == 24.0
    assert cfg.max_attempts == 3


def test_optional_ints_parsed():
    cfg = load_config({**BASE, "GUILD_ID": "42", "ADMIN_ROLE_ID": "7"})
    assert cfg.guild_id == 42
    assert cfg.admin_role_id == 7


def test_non_numeric_guild_id_raises():
    with pytest.raises(ConfigError, match="GUILD_ID"):
        load_config({**BASE, "GUILD_ID": "not-a-number"})


def test_sync_sqlite_url_is_upgraded_to_async():
    cfg = load_config({**BASE, "DB_URL": "sqlite:///app.db"})
    assert cfg.db_url == "sqlite+aiosqlite:///app.db"


def test_config_is_frozen():
    cfg = load_config(BASE)
    with pytest.raises(Exception):
        cfg.token = "other"
