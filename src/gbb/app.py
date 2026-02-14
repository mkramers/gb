import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from rich.text import Text
from textual import events, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import DataTable, Footer, Header, Input, Static
from textual.worker import get_current_worker

from gbb.cleanup import delete_branch, delete_worktree, list_non_ignored_entries
from gbb.config import Config
from gbb.git import BranchInfo, discover_repo, fetch_repo, is_dirty
from gbb.kitty import (
    KittyError,
    KittyWindow,
    clear_idle_panes,
    create_workspace_tab,
    is_kitty,
    restart_claude_pane,
    switch_all_panes,
)
from gbb.pins import load_pins, pin_key, save_pins

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


class DeleteConfirmScreen(ModalScreen[bool]):
    CSS = """
    DeleteConfirmScreen {
        align: center middle;
    }
    #delete-dialog {
        width: 60;
        height: auto;
        max-height: 80%;
        border: thick $error;
        background: $surface;
        padding: 1 2;
    }
    """

    def __init__(
        self,
        branch_name: str,
        worktree_path: str,
        reasons: list[str],
        entries: list[str],
    ):
        super().__init__()
        self._branch_name = branch_name
        self._worktree_path = worktree_path
        self._reasons = reasons
        self._entries = entries

    def compose(self) -> ComposeResult:
        with Vertical(id="delete-dialog"):
            yield Static(self._build_content())

    def _build_content(self) -> str:
        lines = [f"[bold]Delete '{self._branch_name}'?[/bold]", ""]
        lines.append(self._worktree_path)
        if self._reasons:
            lines.append("")
            for reason in self._reasons:
                lines.append(f"[yellow]  {reason}[/yellow]")
        if self._entries:
            lines.append("")
            for entry in self._entries[:20]:
                lines.append(f"  {entry}")
            remaining = len(self._entries) - 20
            if remaining > 0:
                lines.append(f"  [dim]... and {remaining} more[/dim]")
        lines.append("")
        lines.append("[dim]y[/dim] delete  [dim]n[/dim] cancel")
        return "\n".join(lines)

    def on_key(self, event: events.Key) -> None:
        if event.key == "y":
            self.dismiss(True)
        elif event.key in ("n", "escape"):
            self.dismiss(False)
        event.prevent_default()
        event.stop()


class ClaudeConfirmScreen(ModalScreen[str]):
    """Returns 'continue', 'resume', or '' (cancel)."""

    CSS = """
    ClaudeConfirmScreen {
        align: center middle;
    }
    #claude-dialog {
        width: 50;
        height: auto;
        border: thick $warning;
        background: $surface;
        padding: 1 2;
    }
    """

    def __init__(self, count: int):
        super().__init__()
        self._count = count

    def compose(self) -> ComposeResult:
        with Vertical(id="claude-dialog"):
            s = "s" if self._count != 1 else ""
            yield Static(
                f"[bold]Claude running in {self._count} pane{s}[/bold]\n\n"
                f"Kill + restart?\n\n"
                f"[dim]c[/dim] --continue  [dim]r[/dim] --resume  [dim]n[/dim] skip"
            )

    def on_key(self, event: events.Key) -> None:
        if event.key == "c":
            self.dismiss("continue")
        elif event.key == "r":
            self.dismiss("resume")
        elif event.key in ("n", "escape"):
            self.dismiss("")
        event.prevent_default()
        event.stop()


class GbbApp(App):
    TITLE = "gbb"

    BINDINGS = [
        Binding("q", "quit_app", "Close", show=True, key_display="q/esc"),
        Binding("down", "cursor_down", "Down", show=False, priority=True),
        Binding("j", "cursor_down", "Down", show=False),
        Binding("up", "cursor_up", "Up", show=False, priority=True),
        Binding("k", "cursor_up", "Up", show=False),
        Binding("alt+up", "prev_group", "Prev repo", show=False),
        Binding("alt+down", "next_group", "Next repo", show=False),
        Binding("slash", "start_filter", "Filter", show=True),
        Binding("a", "toggle_scope", "All repos", show=True),
        Binding("escape", "cancel", "", show=False),
        Binding("d", "delete_branch", "Delete", show=True),
        Binding("o", "open_root", "Open", show=True),
        Binding("p", "toggle_pin", "Pin", show=True),
        Binding("K", "clear_panes", "Clear", show=True),
        Binding("T", "new_workspace", "Workspace", show=True),
    ]

    CSS = """
    DataTable {
        height: 1fr;
        scrollbar-size: 0 0;
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
        self._footer_timer = None
        self._pins = load_pins()
        self._kitty_mode = is_kitty()
        self._active_branch_key: str | None = None
        self._pending_claude_windows: list[KittyWindow] = []
        self._pending_switch_path: Path | None = None
        self._pending_checkout_branch: str | None = None

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

    def _pinned_branches(self, repo_name: str) -> set[str]:
        prefix = f"{repo_name}:"
        return {key[len(prefix):] for key in self._pins if key.startswith(prefix)}

    def _scoped_rows(self) -> list[tuple[str, Path, BranchInfo]]:
        if not self._show_all and self._current_repo:
            rows = [r for r in self._all_rows if r[0] == self._current_repo]
        else:
            rows = list(self._all_rows)
        pinned = [r for r in rows if pin_key(r[0], r[2].name) in self._pins]
        unpinned = [r for r in rows if pin_key(r[0], r[2].name) not in self._pins]
        return pinned + unpinned

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_columns(
            "", "Repo", "Branch", "Age", "Status", "HEAD±", "main±", "Path", "Commit",
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
            branches = discover_repo(
                current_repo_path, self._config.recent_days, self._cwd,
                pinned=self._pinned_branches(current_repo_path.name),
            )
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

        self._update_scope_label()
        self.set_interval(5, self._refresh_tick)
        self._footer_timer = self.set_timer(3, self._hide_footer)
        self._fetch_repos_background(valid_repos)
        table.focus()

    @work(thread=True, exclusive=True, group="discovery")
    def _discover_repos_background(self, repos: list[Path]) -> None:
        worker = get_current_worker()
        with ThreadPoolExecutor() as pool:
            results = list(pool.map(
                lambda rp: (rp.name, rp, discover_repo(
                    rp, self._config.recent_days, self._cwd,
                    pinned=self._pinned_branches(rp.name),
                )),
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

    @work(thread=True, exclusive=True, group="fetch")
    def _fetch_repos_background(self, repos: list[Path]) -> None:
        worker = get_current_worker()
        with ThreadPoolExecutor() as pool:
            list(pool.map(fetch_repo, repos))
        if not worker.is_cancelled:
            self.call_from_thread(self._post_fetch_refresh)

    def _post_fetch_refresh(self) -> None:
        if self._pending_delete is not None or self._loading_others:
            return
        self._refresh_repos()

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
                lambda item: (item[0], item[1], discover_repo(
                    item[1], self._config.recent_days, self._cwd,
                    pinned=self._pinned_branches(item[0]),
                )),
                repo_paths,
            ))
        if worker.is_cancelled:
            return
        new_data = [(name, path, branches) for name, path, branches in results if branches]
        self.call_from_thread(self._apply_refresh, new_data)

    @staticmethod
    def _data_fingerprint(data: list[tuple[str, Path, list["BranchInfo"]]]) -> tuple:
        rows = []
        for name, _, branches in data:
            for b in branches:
                rows.append((
                    name, b.name, b.timestamp, b.dirty,
                    b.ahead_upstream, b.behind_upstream,
                    b.ahead_main, b.behind_main,
                    b.deletable, b.delete_reason,
                    str(b.worktree.path) if b.worktree else "",
                    b.commit,
                ))
        return tuple(rows)

    def _apply_refresh(self, new_data: list[tuple[str, Path, list[BranchInfo]]]) -> None:
        if self._pending_delete is not None:
            return

        if self._data_fingerprint(new_data) == self._data_fingerprint(self.repo_data):

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

            is_pinned = pin_key(repo_name, b.name) in self._pins
            is_active = (
                self._kitty_mode
                and self._active_branch_key == f"{repo_name}:{b.name}"
            )
            if is_active and is_pinned:
                pin_cell = Text("►⚑", style="#50fa7b")
            elif is_active:
                pin_cell = Text("►", style="#50fa7b")
            elif is_pinned:
                pin_cell = Text("⚑", style="#f1fa8c")
            else:
                pin_cell = Text("")

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
                pin_cell,
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

        if branch.worktree:
            self._pending_delete = (repo_name, repo_path, branch)
            self._prepare_worktree_delete(repo_name, repo_path, branch)
        elif branch.deletable:
            self._execute_delete(repo_name, repo_path, branch)
        else:
            self._pending_delete = (repo_name, repo_path, branch)
            self._show_confirm(
                f"'{branch.name}' not detected as merged. Force delete? [y/n]"
            )

    def action_clear_panes(self) -> None:
        if not self._kitty_mode:
            return
        self._do_clear_panes()

    @work(thread=True, exclusive=True, group="kitty-clear")
    def _do_clear_panes(self) -> None:
        try:
            cleared = clear_idle_panes()
        except KittyError:
            return
        if cleared:
            self.call_from_thread(
                self.notify,
                f"Cleared {cleared} pane{'s' if cleared != 1 else ''}",
                timeout=2,
            )

    def action_new_workspace(self) -> None:
        if not self._kitty_mode:
            return
        data = self._get_cursor_row_data()
        if not data:
            return
        repo_name, repo_path, branch = data
        if branch.worktree:
            selected_dir = branch.worktree.path
            checkout_branch = None
        else:
            selected_dir = repo_path
            checkout_branch = branch.name
        self._do_create_workspace(repo_name, repo_path, selected_dir, checkout_branch)

    @work(thread=True, exclusive=True, group="kitty-workspace")
    def _do_create_workspace(
        self, repo_name: str, repo_path: Path, selected_dir: Path, checkout_branch: str | None,
    ) -> None:
        try:
            create_workspace_tab(repo_name, repo_path, selected_dir, checkout_branch)
        except KittyError as e:
            self.call_from_thread(self.notify, f"Workspace failed: {e}", timeout=5)
            return
        self.call_from_thread(
            self.notify, f"Workspace opened for {repo_name}", timeout=3,
        )

    def action_open_root(self) -> None:
        data = self._get_cursor_row_data()
        if not data:
            return
        repo_name, repo_path, branch = data
        path = branch.worktree.path if branch.worktree else repo_path
        subprocess.Popen(
            ["subl", str(path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def action_toggle_pin(self) -> None:
        if self.filtering or self._pending_delete is not None:
            return
        data = self._get_cursor_row_data()
        if not data:
            return
        repo_name, repo_path, branch = data
        key = pin_key(repo_name, branch.name)
        if key in self._pins:
            self._pins.discard(key)
        else:
            self._pins.add(key)
        save_pins(self._pins)
        if self.filtering:
            query = self.query_one("#filter-bar", Input).value
            self._apply_filter(query)
        else:
            self._populate(self._scoped_rows())

    @work(thread=True, exclusive=True, group="delete-check")
    def _prepare_worktree_delete(
        self, repo_name: str, repo_path: Path, branch: BranchInfo
    ) -> None:
        dirty = is_dirty(branch.worktree.path)
        entries = list_non_ignored_entries(
            branch.worktree.path, self._config.worktree_ignore
        )
        self.call_from_thread(
            self._show_delete_dialog, repo_name, repo_path, branch, dirty, entries
        )

    def _show_delete_dialog(
        self,
        repo_name: str,
        repo_path: Path,
        branch: BranchInfo,
        dirty: bool,
        entries: list[str],
    ) -> None:
        reasons: list[str] = []
        if dirty:
            reasons.append("uncommitted changes")
        if entries:
            reasons.append("untracked files")
        if not branch.deletable:
            reasons.append("not detected as merged")

        if not reasons:
            self._execute_delete(repo_name, repo_path, branch)
            return

        def on_result(confirmed: bool) -> None:
            self._pending_delete = None
            if confirmed:
                self._execute_delete(repo_name, repo_path, branch)

        self.push_screen(
            DeleteConfirmScreen(
                branch.name,
                shorten_path(branch.worktree.path),
                reasons,
                entries,
            ),
            on_result,
        )

    def _execute_delete(
        self, repo_name: str, repo_path: Path, branch: BranchInfo
    ) -> None:
        self._pending_delete = None
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

    def _show_footer_briefly(self) -> None:
        footer = self.query_one(Footer)
        footer.display = True
        if self._footer_timer is not None:
            self._footer_timer.stop()
        self._footer_timer = self.set_timer(3, self._hide_footer)

    def _hide_footer(self) -> None:
        self.query_one(Footer).display = False
        self._footer_timer = None

    def on_key(self, event: events.Key) -> None:
        self._show_footer_briefly()
        if self._pending_delete is not None:
            bar = self.query_one("#confirm-bar", Static)
            if not bar.has_class("visible"):
                return
            if event.key == "y":
                repo_name, repo_path, branch = self._pending_delete
                self._dismiss_confirm()
                self._execute_delete(repo_name, repo_path, branch)
            elif event.key in ("n", "escape"):
                self._dismiss_confirm()
            event.prevent_default()
            event.stop()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        key = str(event.row_key.value)
        parts = key.split(":", 2)
        repo_name = parts[0] if len(parts) > 0 else ""
        branch_name = parts[1] if len(parts) > 1 else ""
        wt_path = parts[2] if len(parts) > 2 else ""

        has_worktree = bool(wt_path)

        if self._kitty_mode:
            self._active_branch_key = f"{repo_name}:{branch_name}"
            self._repopulate()
            if has_worktree:
                self._do_kitty_switch(Path(wt_path))
            else:
                repo_path = None
                for name, rp, _ in self.repo_data:
                    if name == repo_name:
                        repo_path = rp
                        break
                if repo_path:
                    self._do_kitty_switch(repo_path, checkout_branch=branch_name)
            return

        if wt_path:
            path = wt_path
        else:
            path = ""
            for name, repo_path, _ in self.repo_data:
                if name == repo_name:
                    path = str(repo_path)
                    break

        self.exit((path, branch_name, has_worktree))

    def _repopulate(self) -> None:
        table = self.query_one(DataTable)
        cursor_row = table.cursor_row
        if self.filtering:
            query = self.query_one("#filter-bar", Input).value
            self._apply_filter(query)
        else:
            self._populate(self._scoped_rows())
        if table.row_count > 0:
            table.move_cursor(row=min(cursor_row, table.row_count - 1))

    @work(thread=True, exclusive=True, group="kitty-switch")
    def _do_kitty_switch(self, target_path: Path, checkout_branch: str | None = None) -> None:
        try:
            result = switch_all_panes(target_path, checkout_branch)
        except KittyError as e:
            self.call_from_thread(self.notify, str(e), timeout=5)
            return
        self.call_from_thread(self._handle_switch_result, result, target_path, checkout_branch)

    def _handle_switch_result(self, result, target_path: Path, checkout_branch: str | None = None) -> None:
        parts = []
        if result.switched:
            n = result.switched
            parts.append(f"Switched {n} pane{'s' if n != 1 else ''}")
        if result.skipped:
            parts.append(f"Skipped: {', '.join(result.skipped)}")
        if parts:
            self.notify(". ".join(parts), timeout=3)

        if result.claude_windows:
            self._pending_claude_windows = result.claude_windows
            self._pending_switch_path = target_path
            self._pending_checkout_branch = checkout_branch

            def on_claude_confirm(choice: str) -> None:
                if choice:
                    self._restart_claude_panes(claude_flag=choice)
                else:
                    self._pending_claude_windows = []
                    self._pending_switch_path = None
                    self._pending_checkout_branch = None

            self.push_screen(
                ClaudeConfirmScreen(len(result.claude_windows)),
                on_claude_confirm,
            )

    @work(thread=True, exclusive=True, group="kitty-claude")
    def _restart_claude_panes(self, claude_flag: str = "continue") -> None:
        windows = list(self._pending_claude_windows)
        path = self._pending_switch_path
        checkout = self._pending_checkout_branch
        self._pending_claude_windows = []
        self._pending_switch_path = None
        self._pending_checkout_branch = None
        restarted = 0
        for w in windows:
            if restart_claude_pane(w, path, checkout, claude_flag=claude_flag):
                restarted += 1
        if restarted:
            self.call_from_thread(
                self.notify,
                f"Restarted claude --{claude_flag} in {restarted} pane{'s' if restarted != 1 else ''}",
                timeout=3,
            )

    def action_cursor_down(self) -> None:
        self._show_footer_briefly()
        table = self.query_one(DataTable)
        if table.row_count == 0:
            return
        if table.cursor_row >= table.row_count - 1:
            table.move_cursor(row=0)
        else:
            table.action_cursor_down()

    def action_cursor_up(self) -> None:
        self._show_footer_briefly()
        table = self.query_one(DataTable)
        if table.row_count == 0:
            return
        if table.cursor_row <= 0:
            table.move_cursor(row=table.row_count - 1)
        else:
            table.action_cursor_up()

    def action_prev_group(self) -> None:
        self._show_footer_briefly()
        table = self.query_one(DataTable)
        current = table.cursor_row
        for idx in reversed(self._group_indices):
            if idx < current:
                table.move_cursor(row=idx)
                return
        if self._group_indices:
            table.move_cursor(row=self._group_indices[-1])

    def action_next_group(self) -> None:
        self._show_footer_briefly()
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
