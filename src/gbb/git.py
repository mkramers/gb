from dataclasses import dataclass
from pathlib import Path


@dataclass
class Worktree:
    path: Path
    head: str
    branch: str


@dataclass
class BranchInfo:
    name: str
    commit: str
    timestamp: int
    worktree: Worktree | None = None
    is_current: bool = False
    dirty: bool = False
    ahead_upstream: int = 0
    behind_upstream: int = 0
    ahead_main: int = 0
    behind_main: int = 0


def parse_worktrees(output: str) -> dict[str, Worktree]:
    worktrees = {}
    current: dict[str, str] = {}

    for line in output.splitlines():
        if not line.strip():
            if "branch" in current and not current["branch"].startswith("("):
                branch = current["branch"].removeprefix("refs/heads/")
                worktrees[branch] = Worktree(
                    path=Path(current["worktree"]),
                    head=current["HEAD"][:7],
                    branch=branch,
                )
            current = {}
            continue

        key, _, value = line.partition(" ")
        current[key] = value

    return worktrees
