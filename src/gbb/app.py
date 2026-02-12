import time
from pathlib import Path

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import DataTable, Footer, Header, Input

from gbb.git import BranchInfo

REPO_COLORS = [
    "#50fa7b",
    "#8be9fd",
    "#ff79c6",
    "#ffb86c",
    "#bd93f9",
    "#f1fa8c",
    "#ff5555",
    "#6272a4",
]


def format_age(timestamp: int) -> str:
    delta = int(time.time()) - timestamp
    if delta < 3600:
        return f"{delta // 60}m"
    if delta < 86400:
        return f"{delta // 3600}h"
    if delta < 604800:
        return f"{delta // 86400}d"
    return f"{delta // 604800}w"


def format_ahead_behind(ahead: int, behind: int) -> Text:
    if not ahead and not behind:
        return Text("")
    result = Text()
    if ahead:
        result.append(f"↑{ahead}", style="#50fa7b")
    if behind:
        result.append(f"↓{behind}", style="#ff5555")
    return result


def shorten_path(path: Path) -> str:
    home = Path.home()
    try:
        return "~/" + str(path.relative_to(home))
    except ValueError:
        return str(path)


class GbbApp(App):
    TITLE = "gbb"

    BINDINGS = [
        Binding("q", "quit_app", "Quit", show=True),
        Binding("down", "cursor_down", "Down", show=False, priority=True),
        Binding("j", "cursor_down", "Down", show=False),
        Binding("up", "cursor_up", "Up", show=False, priority=True),
        Binding("k", "cursor_up", "Up", show=False),
        Binding("alt+up", "prev_group", "Prev repo", show=False),
        Binding("alt+down", "next_group", "Next repo", show=False),
        Binding("slash", "start_filter", "Filter", show=True),
        Binding("a", "toggle_scope", "All repos", show=True),
        Binding("escape", "cancel", "Cancel", show=True),
    ]

    CSS = """
    DataTable {
        height: 1fr;
    }

    DataTable > .datatable--header {
        text-style: bold;
    }

    #filter-bar {
        dock: bottom;
        height: auto;
        min-height: 1;
        display: none;
    }

    #filter-bar.visible {
        display: block;
    }
    """

    def __init__(
        self,
        repo_data: list[tuple[str, Path, list[BranchInfo]]],
        current_repo: str | None = None,
    ):
        super().__init__()
        self.repo_data = repo_data
        self._current_repo = current_repo
        self._show_all = current_repo is None
        self.filtering: bool = False
        self._repo_colors: dict[str, str] = {}
        for i, (name, _, _) in enumerate(repo_data):
            self._repo_colors[name] = REPO_COLORS[i % len(REPO_COLORS)]
        self._all_rows: list[tuple[str, Path, BranchInfo]] = []
        for repo_name, repo_path, branches in repo_data:
            for b in branches:
                self._all_rows.append((repo_name, repo_path, b))
        self._group_indices: list[int] = []

    def compose(self) -> ComposeResult:
        yield Header()
        yield DataTable(cursor_type="row")
        yield Input(placeholder="/filter branches...", id="filter-bar")
        yield Footer()

    def _scoped_rows(self) -> list[tuple[str, Path, BranchInfo]]:
        if not self._show_all and self._current_repo:
            return [r for r in self._all_rows if r[0] == self._current_repo]
        return self._all_rows

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_columns(
            "Repo", "Branch", "Age", "Status", "HEAD±", "main±", "Path", "Commit"
        )
        self._populate(self._scoped_rows())
        self._update_scope_label()
        table.focus()

    def _populate(self, rows: list[tuple[str, Path, BranchInfo]]) -> None:
        table = self.query_one(DataTable)
        table.clear()
        self._group_indices = []
        last_repo = None

        for i, (repo_name, repo_path, b) in enumerate(rows):
            if repo_name != last_repo:
                self._group_indices.append(i)
                last_repo = repo_name

            color = self._repo_colors[repo_name]
            tree = "⎇ " if b.worktree else "  "
            repo_cell = Text(f"{tree}{repo_name}", style=f"bold {color}")

            if b.is_current:
                prefix = "@ "
            elif b.worktree:
                prefix = "+ "
            else:
                prefix = "  "

            if b.worktree:
                status = Text("*", style="#ffb86c") if b.dirty else Text(" ")
            else:
                status = Text("—", style="dim")

            path = shorten_path(b.worktree.path) if b.worktree else ""
            wt_path = str(b.worktree.path) if b.worktree else ""

            table.add_row(
                repo_cell,
                f"{prefix}{b.name}",
                Text(format_age(b.timestamp), style="dim"),
                status,
                format_ahead_behind(b.ahead_upstream, b.behind_upstream),
                format_ahead_behind(b.ahead_main, b.behind_main),
                path,
                b.commit,
                key=f"{repo_name}:{b.name}:{wt_path}",
            )

    def _update_scope_label(self) -> None:
        label = "This repo" if self._show_all else "All repos"
        self._bindings.key_to_bindings["a"] = [
            Binding("a", "toggle_scope", label, show=True)
        ]
        self.refresh_bindings()

    def action_toggle_scope(self) -> None:
        if self._current_repo is None:
            return
        self._show_all = not self._show_all
        self._update_scope_label()
        if self.filtering:
            query = self.query_one("#filter-bar", Input).value
            self._apply_filter(query)
        else:
            self._populate(self._scoped_rows())

    def action_quit_app(self) -> None:
        self.exit()

    def action_cancel(self) -> None:
        if self.filtering:
            self._close_filter()
        else:
            self.exit()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        key = str(event.row_key.value)
        # key format: "{repo_name}:{branch_name}:{wt_path}"
        parts = key.split(":", 2)
        repo_name = parts[0] if len(parts) > 0 else ""
        branch_name = parts[1] if len(parts) > 1 else ""
        wt_path = parts[2] if len(parts) > 2 else ""

        has_worktree = bool(wt_path)
        if wt_path:
            path = wt_path
        else:
            path = ""
            for name, repo_path, _ in self.repo_data:
                if name == repo_name:
                    path = str(repo_path)
                    break

        self.exit((path, branch_name, has_worktree))

    def action_cursor_down(self) -> None:
        table = self.query_one(DataTable)
        if table.row_count == 0:
            return
        if table.cursor_row >= table.row_count - 1:
            table.move_cursor(row=0)
        else:
            table.action_cursor_down()

    def action_cursor_up(self) -> None:
        table = self.query_one(DataTable)
        if table.row_count == 0:
            return
        if table.cursor_row <= 0:
            table.move_cursor(row=table.row_count - 1)
        else:
            table.action_cursor_up()

    def action_prev_group(self) -> None:
        table = self.query_one(DataTable)
        current = table.cursor_row
        for idx in reversed(self._group_indices):
            if idx < current:
                table.move_cursor(row=idx)
                return
        if self._group_indices:
            table.move_cursor(row=self._group_indices[-1])

    def action_next_group(self) -> None:
        table = self.query_one(DataTable)
        current = table.cursor_row
        for idx in self._group_indices:
            if idx > current:
                table.move_cursor(row=idx)
                return
        if self._group_indices:
            table.move_cursor(row=self._group_indices[0])

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
        self._populate(self._scoped_rows())
        table = self.query_one(DataTable)
        table.focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "filter-bar":
            self._apply_filter(event.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "filter-bar":
            self.filtering = False
            filter_bar = self.query_one("#filter-bar", Input)
            filter_bar.remove_class("visible")
            table = self.query_one(DataTable)
            table.focus()

    def _apply_filter(self, query: str) -> None:
        rows = self._scoped_rows()
        query = query.lower()
        if query:
            filtered = [
                row for row in rows
                if query in row[2].name.lower() or query in row[0].lower()
            ]
        else:
            filtered = rows
        self._populate(filtered)
