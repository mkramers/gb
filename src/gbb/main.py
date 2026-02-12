import os
import sys
import tempfile
from pathlib import Path

from gbb.app import GbbApp
from gbb.config import load_config
from gbb.git import BranchInfo, discover_repo

RESULT_FILE = Path(tempfile.gettempdir()) / f"gbb-{os.getuid()}-result"


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

    # Clear any previous result
    RESULT_FILE.unlink(missing_ok=True)

    app = GbbApp(repo_data)
    app.run()

    if app.selected_path:
        RESULT_FILE.write_text(app.selected_path)
        if not app.selected_has_worktree and app.selected_branch:
            print(
                f"hint: git checkout {app.selected_branch}",
                file=sys.stderr,
            )
