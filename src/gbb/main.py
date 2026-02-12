import os
import sys
from pathlib import Path

from gbb.app import GbbApp
from gbb.config import load_config
from gbb.git import BranchInfo, discover_repo


def main():
    config = load_config()
    cwd = Path.cwd()

    repo_data: list[tuple[str, Path, list[BranchInfo]]] = []
    for repo_path in config.repos:
        if not repo_path.exists():
            print(f"Skipping missing repo: {repo_path}", file=sys.stderr)
            continue

        branches = discover_repo(repo_path, config.recent_days, cwd)
        if branches:
            repo_data.append((repo_path.name, repo_path, branches))

    if not repo_data:
        print("No repos with branches found.", file=sys.stderr)
        sys.exit(1)

    # Save original stdout fd before Textual takes over
    stdout_fd = os.dup(1)

    app = GbbApp(repo_data)
    app.run()

    # Write to the original stdout fd directly
    if app.selected_path:
        os.write(stdout_fd, f"{app.selected_path}\n".encode())
        if not app.selected_has_worktree and app.selected_branch:
            print(
                f"hint: git checkout {app.selected_branch}",
                file=sys.stderr,
            )
    os.close(stdout_fd)
