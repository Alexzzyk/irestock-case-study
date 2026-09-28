from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from pathlib import Path
import sqlite3
from typing import Iterator
from uuid import uuid4


class RunRepository:
    """Persist a result and its rule evidence in a single transaction."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    mode TEXT NOT NULL CHECK(mode IN ('replenishment', 'transfer')),
                    input_sha256 TEXT NOT NULL,
                    result_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS decisions (
                    run_id TEXT NOT NULL REFERENCES runs(id),
                    sequence INTEGER NOT NULL,
                    sku TEXT NOT NULL,
                    store TEXT NOT NULL,
                    rule_id TEXT NOT NULL,
                    evidence_json TEXT NOT NULL,
                    PRIMARY KEY(run_id, sequence)
                );
                CREATE INDEX IF NOT EXISTS decisions_lookup ON decisions(run_id, sku, store);
            """)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def save(self, payload: dict, result: dict) -> dict:
        canonical_input = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        fingerprint = hashlib.sha256(canonical_input.encode()).hexdigest()
        run_id = uuid4().hex
        evidence = [
            (row["sku"], row["store"], decision["rule_id"], json.dumps(decision, ensure_ascii=False))
            for row in result["audit"] for decision in row.get("trace", [])
        ]
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO runs(id, mode, input_sha256, result_json) VALUES (?, ?, ?, ?)",
                (run_id, result["mode"], fingerprint, json.dumps(result, ensure_ascii=False)),
            )
            connection.executemany(
                "INSERT INTO decisions VALUES (?, ?, ?, ?, ?, ?)",
                [(run_id, index, *row) for index, row in enumerate(evidence)],
            )
        return {"run_id": run_id, "input_sha256": fingerprint, "result": result}

    def get(self, run_id: str) -> dict | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT input_sha256, result_json FROM runs WHERE id = ?", (run_id,),
            ).fetchone()
        if row is None:
            return None
        return {"run_id": run_id, "input_sha256": row[0], "result": json.loads(row[1])}
