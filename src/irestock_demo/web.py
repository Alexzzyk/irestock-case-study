from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException

from . import __version__
from .allocation import replenish
from .domain import Dataset
from .storage import RunRepository
from .transfer import transfer


def create_app(database: Path | None = None) -> FastAPI:
    app = FastAPI(title="iRestock synthetic engineering demo", version=__version__)
    repository = RunRepository(database or Path(os.getenv("IRESTOCK_DEMO_DB", "outputs/demo.sqlite3")))

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "version": __version__, "data": "synthetic only"}

    @app.post("/api/run/{mode}")
    def run(mode: Literal["replenishment", "transfer"], payload: dict) -> dict:
        try:
            data = Dataset.from_dict(payload)
            result = replenish(data) if mode == "replenishment" else transfer(data)
        except (ValueError, TypeError, KeyError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return repository.save(payload, result)

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: str) -> dict:
        result = repository.get(run_id)
        if result is None:
            raise HTTPException(status_code=404, detail="Run not found")
        return result

    return app


def serve() -> None:
    import uvicorn

    uvicorn.run("irestock_demo.web:create_app", factory=True, host="127.0.0.1", port=8001)
