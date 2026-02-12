import time
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.widgets import DataTable, Header, Input, Label

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


def populate_table(
    table: DataTable,
    repo_name: str,
    branches: list[BranchInfo],
) -> None:
    table.clear(columns=True)
    table.add_columns(
        "Branch", "Status", "HEAD±", "main±", "Path", "Commit", "Age"
    )
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
            key=f"{b.name}:{wt_path}",
        )


class RepoSection(Vertical):
    def __init__(self, repo_name: str, repo_path: Path, branches: list[BranchInfo]):
        super().__init__(id=f"repo-{repo_name}")
        self.repo_name = repo_name
        self.repo_path = repo_path
        self.branches = branches

    def compose(self) -> ComposeResult:
        yield Label(f" {self.repo_name} ", classes="repo-header")
        table = DataTable(cursor_type="row", id=f"table-{self.repo_name}")
        yield table

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        populate_table(table, self.repo_name, self.branches)


class GbbApp(App):
    TITLE = "gbb"

    BINDINGS = [
        Binding("q", "quit_app", "Quit"),
        Binding("enter", "select_branch", "Select"),
        Binding("j", "cursor_down", "Down", show=False),
        Binding("k", "cursor_up", "Up", show=False),
        Binding("alt+up", "prev_table", "Prev repo", show=False),
        Binding("alt+down", "next_table", "Next repo", show=False),
        Binding("slash", "start_filter", "Filter", show=False),
        Binding("escape", "cancel", "Cancel"),
    ]

    CSS = """
    VerticalScroll {
        height: 1fr;
    }

    RepoSection {
        height: auto;
        margin-bottom: 1;
    }

    .repo-header {
        background: $primary-background;
        color: $text;
        text-style: bold;
        width: 100%;
        padding: 0 1;
    }

    DataTable {
        height: auto;
        max-height: 20;
    }

    #filter-bar {
        dock: bottom;
        height: 1;
        display: none;
    }

    #filter-bar.visible {
        display: block;
    }
    """

    def __init__(self, repo_data: list[tuple[str, Path, list[BranchInfo]]]):
        super().__init__()
        self.repo_data = repo_data
        self.selected_path: str | None = None
        self.selected_branch: str | None = None
        self.selected_has_worktree: bool = False
        self.filtering: bool = False

    def compose(self) -> ComposeResult:
        yield Header()
        with VerticalScroll():
            for repo_name, repo_path, branches in self.repo_data:
                yield RepoSection(repo_name, repo_path, branches)
        yield Input(placeholder="/filter branches...", id="filter-bar")

    def _visible_tables(self) -> list[DataTable]:
        return [
            section.query_one(DataTable)
            for section in self.query(RepoSection)
            if section.display
        ]

    def _focused_table(self) -> DataTable | None:
        focused = self.focused
        if isinstance(focused, DataTable):
            return focused
        return None

    def on_mount(self) -> None:
        tables = self._visible_tables()
        if tables:
            tables[0].focus()

    def action_quit_app(self) -> None:
        self.exit()

    def action_cancel(self) -> None:
        if self.filtering:
            self._close_filter()
        else:
            self.exit()

    def action_select_branch(self) -> None:
        table = self._focused_table()
        if not table:
            return

        if table.row_count == 0:
            return

        key = str(table.ordered_rows[table.cursor_row].key)
        # key format: "{branch_name}:{wt_path}"
        parts = key.split(":", 1)
        branch_name = parts[0]
        wt_path = parts[1] if len(parts) > 1 else ""

        section = table.parent
        if not isinstance(section, RepoSection):
            return

        self.selected_branch = branch_name
        self.selected_has_worktree = bool(wt_path)
        if wt_path:
            self.selected_path = wt_path
        else:
            self.selected_path = str(section.repo_path)

        self.exit()

    def action_cursor_down(self) -> None:
        table = self._focused_table()
        if table:
            table.action_cursor_down()

    def action_cursor_up(self) -> None:
        table = self._focused_table()
        if table:
            table.action_cursor_up()

    def action_prev_table(self) -> None:
        tables = self._visible_tables()
        current = self._focused_table()
        if not tables or not current:
            return
        try:
            idx = tables.index(current)
        except ValueError:
            return
        if idx > 0:
            tables[idx - 1].focus()
            tables[idx - 1].move_cursor(row=0)

    def action_next_table(self) -> None:
        tables = self._visible_tables()
        current = self._focused_table()
        if not tables or not current:
            return
        try:
            idx = tables.index(current)
        except ValueError:
            return
        if idx < len(tables) - 1:
            tables[idx + 1].focus()
            tables[idx + 1].move_cursor(row=0)

    def action_start_filter(self) -> None:
        if self.filtering:
            return
        self.filtering = True
        filter_bar = self.query_one("#filter-bar", Input)
        filter_bar.add_class("visible")
        filter_bar.value = ""
        filter_bar.focus()

    def _close_filter(self) -> None:
        self.filtering = False
        filter_bar = self.query_one("#filter-bar", Input)
        filter_bar.remove_class("visible")
        filter_bar.value = ""
        self._apply_filter("")
        tables = self._visible_tables()
        if tables:
            tables[0].focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "filter-bar":
            self._apply_filter(event.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "filter-bar":
            self.filtering = False
            filter_bar = self.query_one("#filter-bar", Input)
            filter_bar.remove_class("visible")
            tables = self._visible_tables()
            if tables:
                tables[0].focus()

    def _apply_filter(self, query: str) -> None:
        query = query.lower()
        for section in self.query(RepoSection):
            table = section.query_one(DataTable)
            if query:
                filtered = [
                    b for b in section.branches
                    if query in b.name.lower()
                ]
            else:
                filtered = section.branches

            if not filtered and query:
                section.display = False
            else:
                section.display = True
                populate_table(table, section.repo_name, filtered)

        tables = self._visible_tables()
        if tables and not self._focused_table():
            tables[0].focus()
