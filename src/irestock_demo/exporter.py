from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any


def safe_cell(value: Any) -> Any:
    if isinstance(value, (list, dict)):
        value = json.dumps(value, ensure_ascii=False)
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def write_result(result: dict, directory: Path, *, excel: bool = False) -> list[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    json_path = directory / "result.json"
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    paths = [json_path]
    tables = {name: rows for name, rows in result.items() if isinstance(rows, list)}
    for name, rows in tables.items():
        path = directory / f"{name}.csv"
        columns = list(dict.fromkeys(key for row in rows for key in row))
        with path.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=columns)
            writer.writeheader()
            writer.writerows({key: safe_cell(value) for key, value in row.items()} for row in rows)
        paths.append(path)
    if excel:
        from openpyxl import Workbook

        workbook = Workbook()
        workbook.remove(workbook.active)
        for name, rows in tables.items():
            sheet = workbook.create_sheet(name)
            columns = list(dict.fromkeys(key for row in rows for key in row))
            sheet.append(columns)
            for row in rows:
                sheet.append([safe_cell(row.get(column)) for column in columns])
            sheet.freeze_panes = "A2"
            sheet.auto_filter.ref = sheet.dimensions
        path = directory / "result.xlsx"
        workbook.save(path)
        paths.append(path)
    return paths
