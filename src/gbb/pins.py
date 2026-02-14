import json
from pathlib import Path

PINS_PATH = Path.home() / ".local" / "share" / "gbb" / "pins.json"


def pin_key(repo_name: str, branch_name: str) -> str:
    return f"{repo_name}:{branch_name}"


def load_pins() -> set[str]:
    if not PINS_PATH.exists():
        return set()
    with open(PINS_PATH) as f:
        return set(json.load(f))


def save_pins(pins: set[str]) -> None:
    PINS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(PINS_PATH, "w") as f:
        json.dump(sorted(pins), f, indent=2)
