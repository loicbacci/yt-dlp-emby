"""find_node(): PATH fast-path vs nvm probing (extract.py)."""

from __future__ import annotations

from pathlib import Path

import pytest

from yt_dlp_emby.extract import find_node


def _nvm_node(home: Path, version: str, *, executable: bool = True) -> Path:
    node = home / ".nvm" / "versions" / "node" / version / "bin" / "node"
    node.parent.mkdir(parents=True, exist_ok=True)
    node.write_text("#!/bin/sh\n", encoding="utf-8")
    node.chmod(0o755 if executable else 0o644)
    return node


def test_path_hit_wins_over_nvm(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    _nvm_node(tmp_path, "v20.1.0")
    monkeypatch.setattr("yt_dlp_emby.extract.shutil.which", lambda _name: "/usr/bin/node")
    assert find_node() == "/usr/bin/node"


def test_nvm_numeric_sort_beats_lexicographic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr("yt_dlp_emby.extract.shutil.which", lambda _name: None)
    _nvm_node(tmp_path, "v9.11.2")
    newest = _nvm_node(tmp_path, "v20.1.0")
    assert find_node() == str(newest)


def test_no_node_anywhere_returns_none(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr("yt_dlp_emby.extract.shutil.which", lambda _name: None)
    assert find_node() is None


def test_nvm_non_executable_ignored(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr("yt_dlp_emby.extract.shutil.which", lambda _name: None)
    _nvm_node(tmp_path, "v20.1.0", executable=False)
    assert find_node() is None
