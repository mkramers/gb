from pathlib import Path


def has_non_ignored_files(worktree: Path, ignore_patterns: list[str]) -> bool:
    ignore = {".git"} | set(ignore_patterns)
    for entry in worktree.iterdir():
        if entry.name in ignore:
            continue
        return True
    return False
