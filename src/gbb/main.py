import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from gbb.config import load_config
from gbb.git import BranchInfo, discover_repo

RESULT_FILE = Path(f"/tmp/gbb-{os.getuid()}-result")


def _import_app():
    from gbb.app import GbbApp
    return GbbApp


def main():
    config = load_config()
    cwd = Path.cwd()

    valid_repos = [p for p in config.repos if p.exists()]
    for p in config.repos:
        if not p.exists():
            print(f"Skipping missing repo: {p}", file=sys.stderr)

    with ThreadPoolExecutor() as pool:
        app_future = pool.submit(_import_app)
        results = list(pool.map(
            lambda rp: (rp.name, rp, discover_repo(rp, config.recent_days, cwd)),
            valid_repos,
        ))

    GbbApp = app_future.result()

    repo_data: list[tuple[str, Path, list[BranchInfo]]] = [
        (name, path, branches) for name, path, branches in results if branches
    ]

    if not repo_data:
        print("No repos with branches found.", file=sys.stderr)
        sys.exit(1)

    current_repo_name: str | None = None
    for name, repo_path, _ in repo_data:
        try:
            cwd.relative_to(repo_path)
            current_repo_name = name
            break
        except ValueError:
            continue

    RESULT_FILE.unlink(missing_ok=True)

    app = GbbApp(repo_data, current_repo=current_repo_name)
    result = app.run()

    if result:
        selected_path, branch_name, has_worktree = result
        if selected_path:
            RESULT_FILE.write_text(selected_path)
            if not has_worktree and branch_name:
                print(
                    f"hint: git checkout {branch_name}",
                    file=sys.stderr,
                )
