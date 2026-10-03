from io import StringIO

from ruamel.yaml import YAML

from yt_dlp_emby.server.yaml_merge import merge_round_trip


def test_mapping_save_retains_nested_comments_and_quotes() -> None:
    yaml = YAML()
    yaml.preserve_quotes = True
    existing = yaml.load(
        '# show note\nseries:\n  - name: "Example" # name note\n'
        "    seasons:\n      - dropout: 28\n        to_season: 27 # custom mapping\n"
        '        title: "Campaign" # custom title\n'
    )
    replacement = {
        "series": [
            {"name": "Example", "seasons": [{"dropout": 28, "to_season": 26, "title": "New title"}]}
        ]
    }
    output = StringIO()
    yaml.dump(merge_round_trip(existing, replacement), output)
    text = output.getvalue()
    assert "# show note" in text
    assert "# name note" in text
    assert "26 # custom mapping" in " ".join(text.split())
    assert '"New title" # custom title' in " ".join(text.split())


def test_discovery_reordering_preserves_existing_season_annotations_and_explicit_clear() -> None:
    yaml = YAML()
    existing = yaml.load(
        "seasons:\n  - dropout: 28\n    to_season: 27 # keep mapping note\n"
        "    title: Campaign\n  - dropout: 29\n    enabled: false\n"
    )
    replacement = {
        "seasons": [
            {"dropout": 29, "enabled": False},
            {"dropout": 28, "to_season": 27},
            {"dropout": 30, "enabled": False},
        ]
    }
    output = StringIO()
    yaml.dump(merge_round_trip(existing, replacement), output)
    text = output.getvalue()
    assert "# keep mapping note" in text
    assert "title:" not in text
    assert [row["dropout"] for row in yaml.load(text)["seasons"]] == [29, 28, 30]
