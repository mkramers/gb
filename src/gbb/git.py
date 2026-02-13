import subprocess
import time
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
    deletable: bool = False
    delete_reason: str | None = None


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


def parse_branches(output: str) -> dict[str, BranchInfo]:
    branches = {}
    for line in output.strip().splitlines():
        parts = line.split()
        if len(parts) >= 3:
            name, commit, timestamp = parts[0], parts[1], int(parts[2])
            branches[name] = BranchInfo(
                name=name, commit=commit, timestamp=timestamp
            )
    return branches


def parse_tracking_status(output: str) -> dict[str, bool]:
    gone = {}
    for line in output.strip().splitlines():
        parts = line.split(None, 1)
        if len(parts) == 2:
            name, track = parts
            gone[name] = "[gone]" in track
        elif len(parts) == 1:
            gone[parts[0]] = False
    return gone


def run_git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True
    )
    return result.stdout


def detect_main_branch(repo: Path) -> str | None:
    # Try the remote HEAD symref first (e.g. origin/HEAD -> origin/main)
    ref = run_git(repo, "symbolic-ref", "refs/remotes/origin/HEAD").strip()
    if ref:
        return ref.removeprefix("refs/remotes/origin/")

    for name in ("main", "master"):
        result = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--verify", f"refs/heads/{name}"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return name
    return None


def is_dirty(path: Path) -> bool:
    output = run_git(path, "status", "--porcelain")
    return bool(output.strip())


def ahead_behind(repo: Path, branch: str, upstream: str) -> tuple[int, int]:
    output = run_git(
        repo, "rev-list", "--left-right", "--count", f"{branch}...{upstream}"
    )
    parts = output.strip().split()
    if len(parts) == 2:
        return int(parts[0]), int(parts[1])
    return 0, 0


def is_squash_merged(repo: Path, branch: str, main: str) -> bool:
    output = run_git(repo, "cherry", main, branch).strip()
    if not output:
        return False
    return all(line.startswith("-") for line in output.splitlines())


def is_ancestor(repo: Path, branch: str, ancestor: str) -> bool:
    result = subprocess.run(
        ["git", "-C", str(repo), "merge-base", "--is-ancestor", branch, ancestor],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def discover_repo(
    repo: Path, recent_days: int, cwd: Path
) -> list[BranchInfo]:
    wt_output = run_git(repo, "worktree", "list", "--porcelain")
    worktrees = parse_worktrees(wt_output)

    ref_output = run_git(
        repo,
        "for-each-ref",
        "refs/heads/",
        "--format=%(refname:short) %(objectname:short) %(committerdate:unix)",
    )
    branches = parse_branches(ref_output)

    tracking_output = run_git(
        repo,
        "for-each-ref",
        "refs/heads/",
        "--format=%(refname:short) %(upstream:track)",
    )
    gone_branches = parse_tracking_status(tracking_output)

    main_branch = detect_main_branch(repo)
    cutoff = time.time() - (recent_days * 86400)

    result = []
    for name, info in branches.items():
        if name in worktrees:
            wt = worktrees[name]
            info.worktree = wt
            info.commit = wt.head
            info.is_current = cwd == wt.path or str(cwd).startswith(
                str(wt.path) + "/"
            )
            info.dirty = is_dirty(wt.path)
        elif info.timestamp < cutoff:
            continue

        if main_branch and name != main_branch:
            info.ahead_main, info.behind_main = ahead_behind(
                repo, name, main_branch
            )

        if info.worktree:
            upstream = run_git(
                repo,
                "for-each-ref",
                "--format=%(upstream:short)",
                f"refs/heads/{name}",
            ).strip()
            if upstream:
                info.ahead_upstream, info.behind_upstream = ahead_behind(
                    repo, name, upstream
                )

        if name != main_branch and not info.is_current:
            if gone_branches.get(name):
                info.deletable = True
                info.delete_reason = "upstream gone"
            elif main_branch and is_ancestor(repo, name, main_branch):
                info.deletable = True
                info.delete_reason = "merged"
            elif main_branch and is_squash_merged(repo, name, main_branch):
                info.deletable = True
                info.delete_reason = "squash-merged"

        result.append(info)

    return result
