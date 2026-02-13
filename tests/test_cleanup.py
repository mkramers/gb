from pathlib import Path
from unittest.mock import patch, MagicMock

from gbb.cleanup import has_non_ignored_files, delete_branch, delete_worktree


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


def test_delete_branch_soft():
    with patch("gbb.cleanup.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        result = delete_branch(Path("/repo"), "feature", force=False)
        assert result is None
        mock_run.assert_called_once_with(
            ["git", "-C", "/repo", "branch", "-d", "feature"],
            capture_output=True, text=True,
        )


def test_delete_branch_force():
    with patch("gbb.cleanup.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        result = delete_branch(Path("/repo"), "feature", force=True)
        assert result is None
        mock_run.assert_called_once_with(
            ["git", "-C", "/repo", "branch", "-D", "feature"],
            capture_output=True, text=True,
        )


def test_delete_branch_error():
    with patch("gbb.cleanup.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stderr="error: not merged")
        result = delete_branch(Path("/repo"), "feature", force=False)
        assert "not merged" in result


def test_delete_worktree():
    with patch("gbb.cleanup.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        result = delete_worktree(Path("/repo"), Path("/worktree"))
        assert result is None
        mock_run.assert_called_once_with(
            ["git", "-C", "/repo", "worktree", "remove", "/worktree"],
            capture_output=True, text=True,
        )


def test_delete_worktree_error():
    with patch("gbb.cleanup.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stderr="fatal: is locked")
        result = delete_worktree(Path("/repo"), Path("/worktree"))
        assert "locked" in result
