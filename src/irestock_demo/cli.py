from __future__ import annotations

import argparse
import json
from pathlib import Path

from .allocation import replenish
from .domain import Dataset
from .exporter import write_result
from .transfer import transfer


def main() -> None:
    parser = argparse.ArgumentParser(description="Synthetic iRestock engineering demonstration")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--mode", choices=("replenishment", "transfer"), default="replenishment")
    parser.add_argument("--output", type=Path, default=Path("outputs/demo"))
    parser.add_argument("--excel", action="store_true", help="Requires the excel optional dependency")
    args = parser.parse_args()
    try:
        data = Dataset.from_dict(json.loads(args.input.read_text(encoding="utf-8")))
        result = replenish(data) if args.mode == "replenishment" else transfer(data)
        paths = write_result(result, args.output, excel=args.excel)
    except (ValueError, TypeError, KeyError, OSError) as error:
        parser.exit(2, f"Input rejected: {error}\n")
    for path in paths:
        print(path)


if __name__ == "__main__":
    main()
