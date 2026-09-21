import pytest

pytest.importorskip("fastapi")

pytestmark = pytest.mark.web


def test_platform_put_preserves_imports(authed_client, tmp_path) -> None:
    root = tmp_path / "dropout.yaml"
    old_lib = tmp_path / "old"
    old_lib.mkdir()
    new_lib = tmp_path / "new" / "lib"
    new_lib.mkdir(parents=True)
    root.write_text(
        f'imports:\n  - shows/x.yaml\nlibrary: "{old_lib}"\nseries: []\n',
        encoding="utf-8",
    )
    client = authed_client
    # Use tmp_path dirs: absolute non-existent paths like /new/lib are
    # validated by the server (created 0700 or rejected), not blindly saved.
    response = client.put(
        "/api/platform/dropout",
        json={"library": str(new_lib), "old_dir": "", "cookies": ""},
    )
    assert response.status_code == 200, response.text
    text = root.read_text(encoding="utf-8")
    assert "shows/x.yaml" in text
    assert str(new_lib) in text


def test_platform_get(authed_client, tmp_path) -> None:
    (tmp_path / "youtube.yaml").write_text(
        'library: "/yt"\nold_dir: "/old"\n',
        encoding="utf-8",
    )
    client = authed_client
    body = client.get("/api/platform/youtube").json()
    assert body["library"] == "/yt"
    assert body["old_dir"] == "/old"
