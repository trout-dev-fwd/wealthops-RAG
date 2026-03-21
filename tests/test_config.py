import json
import os
import sys

import pytest

# Patch CONFIG_DIR before importing so tests use a temp directory
@pytest.fixture(autouse=True)
def temp_config(tmp_path, monkeypatch):
    import app.config as cfg
    new_dir = str(tmp_path / ".wealthops")
    new_file = os.path.join(new_dir, "config.json")
    monkeypatch.setattr(cfg, "CONFIG_DIR", new_dir)
    monkeypatch.setattr(cfg, "CONFIG_FILE", new_file)
    yield new_dir, new_file


def test_load_config_creates_dir(tmp_path, monkeypatch):
    import app.config as cfg
    assert not os.path.exists(cfg.CONFIG_DIR)
    result = cfg.load_config()
    assert result == {}
    assert os.path.isdir(cfg.CONFIG_DIR)


def test_load_config_missing_file_returns_empty():
    import app.config as cfg
    result = cfg.load_config()
    assert result == {}


def test_save_and_load_config():
    import app.config as cfg
    data = {"api_key": "sk-ant-test123", "some_setting": 42}
    cfg.save_config(data)
    loaded = cfg.load_config()
    assert loaded == data


def test_save_creates_directory(tmp_path, monkeypatch):
    import app.config as cfg
    # Directory doesn't exist yet (fixture creates a fresh one each time)
    cfg.save_config({"api_key": "sk-ant-xyz"})
    assert os.path.isdir(cfg.CONFIG_DIR)
    assert os.path.exists(cfg.CONFIG_FILE)


def test_get_api_key_returns_none_when_missing():
    import app.config as cfg
    assert cfg.get_api_key() is None


def test_get_api_key_returns_value():
    import app.config as cfg
    cfg.save_config({"api_key": "sk-ant-abc"})
    assert cfg.get_api_key() == "sk-ant-abc"


def test_load_config_handles_corrupt_file():
    import app.config as cfg
    cfg.save_config({"ok": True})
    with open(cfg.CONFIG_FILE, "w") as f:
        f.write("not valid json{{{")
    result = cfg.load_config()
    assert result == {}


def test_constants_defined():
    import app.config as cfg
    assert cfg.CONFIG_DIR.endswith(".wealthops")
    assert cfg.KNOWLEDGE_DB_PATH.endswith("wealthops.db")
    assert cfg.CHATS_DB_PATH.endswith("chats.db")
    assert isinstance(cfg.GITHUB_REPO, str)


