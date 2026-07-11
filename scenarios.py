"""Persistence helpers for saved input scenarios.

Scenarios are stored as JSON in `scenarios.json` at the project root:
{name: {widget_key: raw_widget_value, ...}, ...}
"""

import json
from pathlib import Path

SCENARIOS_FILE = Path(__file__).resolve().parent / "scenarios.json"


def load_scenarios(path: Path = SCENARIOS_FILE) -> dict:
    """Return all saved scenarios; a missing or corrupt file yields {}."""
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {name: vals for name, vals in data.items() if isinstance(vals, dict)}


def save_scenarios(data: dict, path: Path = SCENARIOS_FILE) -> None:
    """Write the full scenarios mapping to disk."""
    Path(path).write_text(json.dumps(data, indent=2) + "\n")


def save_scenario(name: str, values: dict, path: Path = SCENARIOS_FILE) -> None:
    """Save (or overwrite) a single named scenario."""
    data = load_scenarios(path)
    data[name] = values
    save_scenarios(data, path)


def delete_scenario(name: str, path: Path = SCENARIOS_FILE) -> None:
    """Delete a named scenario if it exists."""
    data = load_scenarios(path)
    if name in data:
        del data[name]
        save_scenarios(data, path)
