import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from rich.text import Text
from textual import events, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import DataTable, Footer, Header, Input, Static
from textual.worker import get_current_worker

from gbb.cleanup import delete_branch, delete_worktree, has_non_ignored_files
from gbb.config import Config
from gbb.git import BranchInfo, discover_repo, is_dirty

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
        Binding("d", "delete_branch", "Delete", show=True),
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

    #confirm-bar {
        dock: bottom;
        height: auto;
        min-height: 1;
        display: none;
        background: $surface;
    }

    #confirm-bar.visible {
        display: block;
    }
    """

    def __init__(
        self,
        config: Config,
        cwd: Path,
        show_all: bool = False,
    ):
        super().__init__()
        self._config = config
        self._cwd = cwd
        self._force_show_all = show_all
        self._pending_delete: tuple[str, Path, BranchInfo] | None = None
        self.filtering: bool = False
        self._repo_colors: dict[str, str] = {}
        self._all_rows: list[tuple[str, Path, BranchInfo]] = []
        self._group_indices: list[int] = []
        self.repo_data: list[tuple[str, Path, list[BranchInfo]]] = []
        self._current_repo: str | None = None
        self._show_all = show_all
        self._loading_others = False

    def compose(self) -> ComposeResult:
        yield Header()
        yield DataTable(cursor_type="row")
        yield Input(placeholder="/filter branches...", id="filter-bar")
        yield Static("", id="confirm-bar")
        yield Footer()

    def _rebuild_rows(self) -> None:
        self._all_rows = []
        self._repo_colors = {}
        for i, (name, path, branches) in enumerate(self.repo_data):
            self._repo_colors[name] = REPO_COLORS[i % len(REPO_COLORS)]
            for b in branches:
                self._all_rows.append((name, path, b))

    def _scoped_rows(self) -> list[tuple[str, Path, BranchInfo]]:
        if not self._show_all and self._current_repo:
            return [r for r in self._all_rows if r[0] == self._current_repo]
        return self._all_rows

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_columns(
            "Repo", "Branch", "Age", "Status", "HEAD±", "main±", "Path", "Commit",
            "Cleanup",
        )

        valid_repos = [p for p in self._config.repos if p.exists()]

        current_repo_path: Path | None = None
        for rp in valid_repos:
            try:
                self._cwd.relative_to(rp)
                current_repo_path = rp
                self._current_repo = rp.name
                break
            except ValueError:
                continue

        if not self._force_show_all:
            self._show_all = self._current_repo is None

        if current_repo_path and not self._force_show_all:
            branches = discover_repo(current_repo_path, self._config.recent_days, self._cwd)
            if branches:
                self.repo_data = [(current_repo_path.name, current_repo_path, branches)]
                self._rebuild_rows()
            self._populate(self._scoped_rows())
            other_repos = [rp for rp in valid_repos if rp != current_repo_path]
            if other_repos:
                self._loading_others = True
                self._discover_repos_background(other_repos)
        else:
            self._loading_others = True
            self._discover_repos_background(valid_repos)
            self.notify("Discovering repos...", timeout=3)

        self._update_scope_label()
        self.set_interval(5, self._refresh_tick)
        table.focus()

    @work(thread=True, exclusive=True, group="discovery")
    def _discover_repos_background(self, repos: list[Path]) -> None:
        worker = get_current_worker()
        with ThreadPoolExecutor() as pool:
            results = list(pool.map(
                lambda rp: (rp.name, rp, discover_repo(rp, self._config.recent_days, self._cwd)),
                repos,
            ))
        if worker.is_cancelled:
            return
        new_data = [(name, path, branches) for name, path, branches in results if branches]
        self.call_from_thread(self._merge_discovered, new_data)

    def _merge_discovered(self, new_data: list[tuple[str, Path, list[BranchInfo]]]) -> None:
        existing_names = {name for name, _, _ in self.repo_data}
        for name, path, branches in new_data:
            if name not in existing_names:
                self.repo_data.append((name, path, branches))
        self._rebuild_rows()
        self._loading_others = False
        if self._show_all or self._current_repo is None:
            self._populate(self._scoped_rows())

    def _refresh_tick(self) -> None:
        if self._pending_delete is not None:
            return
        if self._loading_others:
            return
        if not self.repo_data:
            return
        self._refresh_repos()

    @work(thread=True, exclusive=True, group="refresh")
    def _refresh_repos(self) -> None:
        worker = get_current_worker()
        repo_paths = [(name, path) for name, path, _ in self.repo_data]
        with ThreadPoolExecutor() as pool:
            results = list(pool.map(
                lambda item: (item[0], item[1], discover_repo(item[1], self._config.recent_days, self._cwd)),
                repo_paths,
            ))
        if worker.is_cancelled:
            return
        new_data = [(name, path, branches) for name, path, branches in results if branches]
        self.call_from_thread(self._apply_refresh, new_data)

    def _apply_refresh(self, new_data: list[tuple[str, Path, list[BranchInfo]]]) -> None:
        if self._pending_delete is not None:
            return

        table = self.query_one(DataTable)
        cursor_key: str | None = None
        cursor_row_idx = table.cursor_row
        if table.row_count > 0:
            row_keys = list(table.rows.keys())
            if cursor_row_idx < len(row_keys):
                cursor_key = str(row_keys[cursor_row_idx].value)

        self.repo_data = new_data
        self._rebuild_rows()

        for name, path, branches in self.repo_data:
            for b in branches:
                if b.is_current:
                    self._current_repo = name
                    break

        if self.filtering:
            query = self.query_one("#filter-bar", Input).value
            self._apply_filter(query)
        else:
            self._populate(self._scoped_rows())

        if cursor_key and table.row_count > 0:
            row_keys = list(table.rows.keys())
            for i, rk in enumerate(row_keys):
                if str(rk.value) == cursor_key:
                    table.move_cursor(row=i)
                    return
        if table.row_count > 0:
            table.move_cursor(row=min(cursor_row_idx, table.row_count - 1))

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

            path_str = shorten_path(b.worktree.path) if b.worktree else ""
            wt_path = str(b.worktree.path) if b.worktree else ""

            if b.deletable:
                repo_cell = Text(f"{tree}{repo_name}", style=f"dim {color}")
                branch_cell = Text(f"{prefix}{b.name}", style="dim")
                age_cell = Text(format_age(b.timestamp), style="dim")
                status_cell = Text(status.plain, style="dim")
                head_cell = Text(format_ahead_behind(b.ahead_upstream, b.behind_upstream).plain, style="dim")
                main_cell = Text(format_ahead_behind(b.ahead_main, b.behind_main).plain, style="dim")
                path_cell = Text(path_str, style="dim")
                commit_cell = Text(b.commit, style="dim")
                cleanup_cell = Text(b.delete_reason or "", style="dim")
            else:
                repo_cell = Text(f"{tree}{repo_name}", style=f"bold {color}")
                branch_cell = f"{prefix}{b.name}"
                age_cell = Text(format_age(b.timestamp), style="dim")
                status_cell = status
                head_cell = format_ahead_behind(b.ahead_upstream, b.behind_upstream)
                main_cell = format_ahead_behind(b.ahead_main, b.behind_main)
                path_cell = path_str
                commit_cell = b.commit
                cleanup_cell = Text("")

            table.add_row(
                repo_cell,
                branch_cell,
                age_cell,
                status_cell,
                head_cell,
                main_cell,
                path_cell,
                commit_cell,
                cleanup_cell,
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
        if self._show_all and self._loading_others:
            self.notify("Loading other repos...", timeout=2)
        if self.filtering:
            query = self.query_one("#filter-bar", Input).value
            self._apply_filter(query)
        else:
            self._populate(self._scoped_rows())

    def action_quit_app(self) -> None:
        self.workers.cancel_all()
        self.exit()

    def action_cancel(self) -> None:
        if self._pending_delete is not None:
            self._dismiss_confirm()
        elif self.filtering:
            self._close_filter()
        else:
            self.workers.cancel_all()
            self.exit()

    def _get_cursor_row_data(self) -> tuple[str, Path, BranchInfo] | None:
        table = self.query_one(DataTable)
        if table.row_count == 0:
            return None
        row_keys = list(table.rows.keys())
        key = str(row_keys[table.cursor_row].value)
        parts = key.split(":", 2)
        repo_name = parts[0]
        branch_name = parts[1]
        for rn, rp, b in self._all_rows:
            if rn == repo_name and b.name == branch_name:
                return (rn, rp, b)
        return None

    def action_delete_branch(self) -> None:
        if self.filtering or self._pending_delete is not None:
            return

        data = self._get_cursor_row_data()
        if not data:
            return

        repo_name, repo_path, branch = data

        if branch.is_current:
            self.notify("Cannot delete current branch", timeout=3)
            return

        for rn, rp, branches in self.repo_data:
            if rn == repo_name:
                for br in branches:
                    if br.name in ("main", "master") and branch.name == br.name:
                        self.notify("Cannot delete main branch", timeout=3)
                        return
                break

        if branch.deletable:
            self._try_delete(repo_name, repo_path, branch)
        else:
            self._pending_delete = (repo_name, repo_path, branch)
            self._show_confirm(
                f"'{branch.name}' not detected as merged. Force delete? [y/n]"
            )

    def _try_delete(self, repo_name: str, repo_path: Path, branch: BranchInfo) -> None:
        if branch.worktree:
            dirty = is_dirty(branch.worktree.path)
            has_files = has_non_ignored_files(
                branch.worktree.path, self._config.worktree_ignore
            )
            if dirty or has_files:
                self._pending_delete = (repo_name, repo_path, branch)
                reasons = []
                if dirty:
                    reasons.append("uncommitted changes")
                if has_files:
                    reasons.append("files outside ignore list")
                self._show_confirm(
                    f"Worktree has {' and '.join(reasons)}. Delete? [y/n]"
                )
                return

            err = delete_worktree(repo_path, branch.worktree.path)
            if err:
                self.notify(f"Error: {err}", timeout=5)
                return

        err = delete_branch(repo_path, branch.name, force=True)
        if err:
            self.notify(f"Error: {err}", timeout=5)
            return

        self._remove_row(repo_name, branch.name)
        self.notify(f"Deleted {branch.name}", timeout=3)

    def _show_confirm(self, message: str) -> None:
        bar = self.query_one("#confirm-bar", Static)
        bar.update(message)
        bar.add_class("visible")

    def _dismiss_confirm(self) -> None:
        self._pending_delete = None
        bar = self.query_one("#confirm-bar", Static)
        bar.remove_class("visible")
        bar.update("")

    def _remove_row(self, repo_name: str, branch_name: str) -> None:
        self._all_rows = [
            (rn, rp, b) for rn, rp, b in self._all_rows
            if not (rn == repo_name and b.name == branch_name)
        ]
        for i, (rn, rp, branches) in enumerate(self.repo_data):
            if rn == repo_name:
                self.repo_data[i] = (
                    rn, rp, [b for b in branches if b.name != branch_name]
                )
                break
        if self.filtering:
            query = self.query_one("#filter-bar", Input).value
            self._apply_filter(query)
        else:
            self._populate(self._scoped_rows())

    def on_key(self, event: events.Key) -> None:
        if self._pending_delete is not None:
            if event.key == "y":
                repo_name, repo_path, branch = self._pending_delete
                self._dismiss_confirm()
                if branch.worktree:
                    err = delete_worktree(repo_path, branch.worktree.path)
                    if err:
                        self.notify(f"Error: {err}", timeout=5)
                        return
                err = delete_branch(repo_path, branch.name, force=True)
                if err:
                    self.notify(f"Error: {err}", timeout=5)
                    return
                self._remove_row(repo_name, branch.name)
                self.notify(f"Deleted {branch.name}", timeout=3)
            elif event.key == "n" or event.key == "escape":
                self._dismiss_confirm()
            event.prevent_default()
            event.stop()

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
