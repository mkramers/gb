import sys
from dataclasses import dataclass
from pathlib import Path

import yaml


DEFAULT_CONFIG_PATH = Path.home() / ".config" / "gbb" / "config.yaml"


@dataclass
class Config:
    recent_days: int
    repos: list[Path]


def load_config(path: Path = DEFAULT_CONFIG_PATH) -> Config:
    if not path.exists():
        print(f"Config not found: {path}", file=sys.stderr)
        sys.exit(1)

    with open(path) as f:
        raw = yaml.safe_load(f)

    return Config(
        recent_days=raw.get("recent_days", 14),
        repos=[Path(p).expanduser() for p in raw["repos"]],
    )
