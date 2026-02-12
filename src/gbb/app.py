import time
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import DataTable, Header

from gbb.git import BranchInfo


def format_age(timestamp: int) -> str:
    delta = int(time.time()) - timestamp
    if delta < 3600:
        return f"{delta // 60}m"
    if delta < 86400:
        return f"{delta // 3600}h"
    if delta < 604800:
        return f"{delta // 86400}d"
    return f"{delta // 604800}w"


def format_ahead_behind(ahead: int, behind: int) -> str:
    if not ahead and not behind:
        return ""
    parts = []
    if ahead:
        parts.append(f"+{ahead}")
    if behind:
        parts.append(f"-{behind}")
    return "".join(parts)


def shorten_path(path: Path) -> str:
    home = Path.home()
    try:
        return "~/" + str(path.relative_to(home))
    except ValueError:
        return str(path)


class GbbApp(App):
    TITLE = "gbb"

    BINDINGS = [
        Binding("q", "quit_app", "Quit"),
        Binding("escape", "quit_app", "Quit"),
        Binding("enter", "select_branch", "Select"),
        Binding("j", "cursor_down", "Down", show=False),
        Binding("k", "cursor_up", "Up", show=False),
        Binding("alt+up", "prev_group", "Prev repo", show=False),
        Binding("alt+down", "next_group", "Next repo", show=False),
    ]

    CSS = """
    DataTable {
        height: 1fr;
    }
    DataTable > .datatable--header {
        text-style: bold;
    }
    """

    def __init__(self, repo_data: list[tuple[str, "Path", list[BranchInfo]]]):
        super().__init__()
        self.repo_data = repo_data
        self.selected_path: str | None = None
        self.selected_branch: str | None = None
        self.selected_has_worktree: bool = False
        self.group_rows: list[int] = []

    def compose(self) -> ComposeResult:
        yield Header()
        yield DataTable(cursor_type="row")

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_columns(
            "Branch", "Status", "HEAD±", "main±", "Path", "Commit", "Age"
        )

        row_index = 0
        for repo_name, repo_path, branches in self.repo_data:
            table.add_row(
                f"── {repo_name} ──", "", "", "", "", "", "",
                key=f"group:{repo_path}",
            )
            self.group_rows.append(row_index)
            row_index += 1

            for b in branches:
                if b.is_current:
                    prefix = "@ "
                elif b.worktree:
                    prefix = "+ "
                else:
                    prefix = "  "

                if b.worktree:
                    status = "*" if b.dirty else " "
                else:
                    status = "—"

                path = shorten_path(b.worktree.path) if b.worktree else ""
                wt_path = str(b.worktree.path) if b.worktree else ""

                table.add_row(
                    f"{prefix}{b.name}",
                    status,
                    format_ahead_behind(b.ahead_upstream, b.behind_upstream),
                    format_ahead_behind(b.ahead_main, b.behind_main),
                    path,
                    b.commit,
                    format_age(b.timestamp),
                    key=f"branch:{b.name}:{wt_path}",
                )
                row_index += 1

    def action_quit_app(self) -> None:
        self.exit()

    def action_select_branch(self) -> None:
        table = self.query_one(DataTable)
        key = str(table.ordered_rows[table.cursor_row].key)

        if key.startswith("group:"):
            return

        parts = key.split(":", 2)
        branch_name = parts[1] if len(parts) > 1 else ""
        wt_path = parts[2] if len(parts) > 2 else ""

        self.selected_branch = branch_name
        self.selected_has_worktree = bool(wt_path)
        if wt_path:
            self.selected_path = wt_path
        else:
            for _, repo_path, branches in self.repo_data:
                for b in branches:
                    if b.name == branch_name:
                        self.selected_path = str(repo_path)
                        break

        self.exit()

    def action_cursor_down(self) -> None:
        table = self.query_one(DataTable)
        table.action_cursor_down()

    def action_cursor_up(self) -> None:
        table = self.query_one(DataTable)
        table.action_cursor_up()

    def action_prev_group(self) -> None:
        table = self.query_one(DataTable)
        current = table.cursor_row
        for row in reversed(self.group_rows):
            if row < current:
                table.move_cursor(row=row)
                return

    def action_next_group(self) -> None:
        table = self.query_one(DataTable)
        current = table.cursor_row
        for row in self.group_rows:
            if row > current:
                table.move_cursor(row=row)
                return
