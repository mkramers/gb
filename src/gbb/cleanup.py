import subprocess
from pathlib import Path


def delete_branch(repo: Path, branch: str, force: bool = False) -> str | None:
    flag = "-D" if force else "-d"
    result = subprocess.run(
        ["git", "-C", str(repo), "branch", flag, branch],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return result.stderr.strip()
    return None


def delete_worktree(repo: Path, worktree_path: Path) -> str | None:
    result = subprocess.run(
        ["git", "-C", str(repo), "worktree", "remove", str(worktree_path)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return result.stderr.strip()
    return None


def has_non_ignored_files(worktree: Path, ignore_patterns: list[str]) -> bool:
    ignore = {".git"} | set(ignore_patterns)
    for entry in worktree.iterdir():
        if entry.name in ignore:
            continue
        return True
    return False


def list_non_ignored_entries(worktree: Path, ignore_patterns: list[str]) -> list[str]:
    result = subprocess.run(
        ["git", "-C", str(worktree), "ls-files", "--others", "--exclude-standard"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return []
    ignore = set(ignore_patterns)
    entries = []
    for line in result.stdout.strip().splitlines():
        if not line:
            continue
        top_level = line.split("/")[0]
        if top_level in ignore:
            continue
        entries.append(line)
    return entries
