from __future__ import annotations

import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
TRADING_ROOT = ROOT / "trading_code_ml"
if str(TRADING_ROOT) not in sys.path:
    sys.path.insert(0, str(TRADING_ROOT))

from src.config import load_settings  # noqa: E402


def get_value(data: dict[str, Any], dotted_key: str) -> Any:
    value: Any = data
    for part in dotted_key.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple)):
        return ",".join(str(item) for item in value)
    return str(value)


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: config_value.py <config-path> <dotted-key>", file=sys.stderr)
        return 2
    print(stringify(get_value(load_settings(Path(sys.argv[1])), sys.argv[2])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
