"""Unit tests for the desktop launcher helpers (no server is started)."""

from __future__ import annotations

import os
import socket

from desktop import launcher


def test_user_data_dir_ends_with_app_name():
    path = launcher.user_data_dir("RagIndex")
    assert path.name == "RagIndex"
    assert path.is_absolute()


def test_user_data_dir_respects_localappdata_on_windows(monkeypatch):
    import sys

    if not sys.platform.startswith("win"):
        return  # convention differs per-OS; only assert the Windows base here
    monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\example\AppData\Local")
    path = launcher.user_data_dir("RagIndex")
    assert str(path).endswith(r"AppData\Local\RagIndex")


def test_find_free_port_returns_valid_port():
    port = launcher.find_free_port(preferred=None)
    assert 1024 <= port <= 65535


def test_find_free_port_prefers_available_port():
    free = launcher.find_free_port(preferred=None)
    # Nothing is bound to `free` right now, so the preferred port should be honored.
    assert launcher.find_free_port(preferred=free) == free


def test_find_free_port_falls_back_when_taken():
    host = "127.0.0.1"
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as held:
        held.bind((host, 0))
        taken = held.getsockname()[1]
        held.listen(1)
        # Preferred port is occupied -> launcher must return a different, free one.
        chosen = launcher.find_free_port(preferred=taken, host=host)
        assert chosen != taken
        assert 1024 <= chosen <= 65535


def test_configure_runtime_sets_env_and_creates_dirs(tmp_path, monkeypatch):
    monkeypatch.delenv("RAGINDEX_DATA_DIR", raising=False)
    monkeypatch.delenv("RAGINDEX_INCOMING_DIR", raising=False)
    target = tmp_path / "RagIndex"

    resolved = launcher.configure_runtime(target)

    assert resolved == target
    assert target.is_dir()
    assert (target / "incoming").is_dir()
    assert os.environ["RAGINDEX_DATA_DIR"] == str(target)
    assert os.environ["RAGINDEX_INCOMING_DIR"] == str(target / "incoming")


def test_configure_runtime_does_not_override_explicit_env(tmp_path, monkeypatch):
    preset = str(tmp_path / "preset")
    monkeypatch.setenv("RAGINDEX_DATA_DIR", preset)
    monkeypatch.delenv("RAGINDEX_INCOMING_DIR", raising=False)

    launcher.configure_runtime(tmp_path / "other")

    # setdefault must keep the explicitly provided value.
    assert os.environ["RAGINDEX_DATA_DIR"] == preset


def test_ollama_available_false_when_nothing_listening():
    # Point at a free (closed) port so the probe fails fast and returns False.
    closed = launcher.find_free_port(preferred=None)
    assert launcher.ollama_available(host=f"http://127.0.0.1:{closed}", timeout=0.5) is False
