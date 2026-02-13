from pathlib import Path
from gbb.cleanup import has_non_ignored_files


def test_empty_dir_has_no_files(tmp_path):
    (tmp_path / ".git").mkdir()
    assert has_non_ignored_files(tmp_path, []) is False


def test_dir_with_only_ignored_files(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "foo.js").write_text("x")
    (tmp_path / "__pycache__").mkdir()
    assert has_non_ignored_files(tmp_path, ["node_modules", "__pycache__"]) is False


def test_dir_with_real_files(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('hi')")
    assert has_non_ignored_files(tmp_path, ["node_modules"]) is True


def test_dir_with_only_dot_git(tmp_path):
    (tmp_path / ".git").mkdir()
    assert has_non_ignored_files(tmp_path, []) is False
