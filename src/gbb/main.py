import os
import sys
from pathlib import Path

import typer

from gbb.config import load_config

RESULT_FILE = Path(f"/tmp/gbb-{os.getuid()}-result")

app = typer.Typer(add_completion=False)


@app.command()
def main(
    show_all: bool = typer.Option(False, "--all", "-a", help="Show all repos"),
):
    config = load_config()
    cwd = Path.cwd()

    from gbb.app import GbbApp

    RESULT_FILE.unlink(missing_ok=True)

    gbb_app = GbbApp(config=config, cwd=cwd, show_all=show_all)
    result = gbb_app.run()

    if result:
        selected_path, branch_name, has_worktree = result
        if selected_path:
            RESULT_FILE.write_text(selected_path)
            if not has_worktree and branch_name:
                print(
                    f"hint: git checkout {branch_name}",
                    file=sys.stderr,
                )
