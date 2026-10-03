"""Distribution and module entry point checks for the web-only application."""

import subprocess
import sys
import tomllib
from pathlib import Path


def test_application_dependencies_include_web_backend() -> None:
    data = tomllib.loads((Path(__file__).resolve().parent.parent / "pyproject.toml").read_text())
    core = " ".join(data["project"]["dependencies"]).lower()
    for package in ("fastapi", "uvicorn", "itsdangerous", "ruamel.yaml", "pydantic"):
        assert package in core
    assert "server" not in data["project"].get("optional-dependencies", {})


def test_module_help_is_a_server_launcher() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "yt_dlp_emby", "--help"], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert "--host" in result.stdout
    assert "--data" in result.stdout
    assert "--manifest" not in result.stdout


def test_main_module_delegates() -> None:
    import yt_dlp_emby.__main__ as module

    assert callable(module.main)
