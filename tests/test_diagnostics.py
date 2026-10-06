from __future__ import annotations

import sqlite3
from pathlib import Path

from yt_dlp_emby.server.diagnostics import diagnostics


def test_paths_diagnostics_do_not_create_missing_library_or_reveal_secrets(
    tmp_path: Path,
) -> None:
    missing_library = tmp_path / "nas" / "library"
    secret = "diagnostic-secret-value"
    result = diagnostics(
        tmp_path / "app-data",
        {
            "YT_DLP_EMBY_LIBRARY": str(missing_library),
            "SONARR_API_KEY": secret,
        },
        ["paths", "worker"],
    )

    assert result["ok"] is False
    paths = result["checks"][0]["paths"]
    assert paths[0]["status"] == "missing"
    assert not missing_library.exists()
    assert secret not in repr(result)


def test_database_diagnostic_opens_existing_database_read_only(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    path = data_dir / "jobs.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE sample(value TEXT)")
        connection.execute("INSERT INTO sample VALUES ('preserve')")
    before = path.read_bytes()

    result = diagnostics(data_dir, {}, ["database"])

    assert result["ok"] is True
    assert result["checks"][0]["status"] == "ok"
    assert path.read_bytes() == before
