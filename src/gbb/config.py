import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml


DEFAULT_CONFIG_PATH = Path.home() / ".config" / "gbb" / "config.yaml"

DEFAULT_WORKTREE_IGNORE = [
    "node_modules", ".venv", "venv", "__pycache__", ".tox",
    ".mypy_cache", ".pytest_cache", ".ruff_cache",
    "target", "dist", "build", ".next", ".nuxt",
    ".claude",
]


@dataclass
class WorkspaceConfig:
    start_claude: bool = True


@dataclass
class Config:
    recent_days: int
    repos: list[Path]
    worktree_ignore: list[str]
    workspace: WorkspaceConfig = field(default_factory=WorkspaceConfig)
    _path: Path = field(default=DEFAULT_CONFIG_PATH, repr=False)
    _raw: dict = field(default_factory=dict, repr=False)

    def save_workspace(self) -> None:
        self._raw["workspace"] = {"start_claude": self.workspace.start_claude}
        with open(self._path, "w") as f:
            yaml.dump(self._raw, f, default_flow_style=False, sort_keys=False)


def load_config(path: Path = DEFAULT_CONFIG_PATH) -> Config:
    if not path.exists():
        print(f"Config not found: {path}", file=sys.stderr)
        sys.exit(1)

    with open(path) as f:
        raw = yaml.safe_load(f)

    ws_raw = raw.get("workspace", {})
    workspace = WorkspaceConfig(
        start_claude=ws_raw.get("start_claude", True),
    )

    return Config(
        recent_days=raw.get("recent_days", 14),
        repos=[Path(p).expanduser() for p in raw["repos"]],
        worktree_ignore=DEFAULT_WORKTREE_IGNORE + raw.get("worktree_ignore", []),
        workspace=workspace,
        _path=path,
        _raw=raw,
    )
