from pathlib import Path

from gbb.config import load_config, Config


def test_load_config(tmp_path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        "recent_days: 7\n"
        "repos:\n"
        "  - ~/projects/app\n"
        "  - ~/work/api\n"
    )
    config = load_config(config_file)
    assert config.recent_days == 7
    assert len(config.repos) == 2
    assert config.repos[0] == Path.home() / "projects" / "app"


def test_load_config_defaults(tmp_path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text("repos:\n  - ~/projects/app\n")
    config = load_config(config_file)
    assert config.recent_days == 14


def test_load_config_missing():
    import pytest

    with pytest.raises(SystemExit):
        load_config(Path("/nonexistent/config.yaml"))
