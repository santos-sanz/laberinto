from __future__ import annotations

import asyncio
import json
import random
import re
from typing import Any, AsyncIterator

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import __version__, config
from .clients import list_decision_models, list_nam_models, provider_status
from .game import generate_maze
from .race import manager

RACE_ID_PATTERN = re.compile(r"^[a-f0-9]{12}$")

FALLBACK_TEXT_MODELS = [
    "deepseek-v4-flash",
    "qwen3.6",
    "gemma4",
    "qwen3.8-flash",
    "glm5.3-flash",
    "mimo-v2.6-flash",
]


class RaceRequest(BaseModel):
    width: int = config.DEFAULT_WIDTH
    height: int = config.DEFAULT_HEIGHT
    seed: int = config.DEFAULT_SEED
    mode: str = config.DEFAULT_MODE
    text_model: str = config.DEFAULT_TEXT_MODEL
    decisions_model: str = config.DEFAULT_DECISIONS_MODEL
    decisions_models: list[str] = Field(default_factory=list)
    text_max_attempts: int = config.DEFAULT_TEXT_ATTEMPTS
    max_junction_calls: int = config.DEFAULT_MAX_JUNCTION_CALLS
    include_baseline: bool = False

    def to_config(self) -> dict[str, Any]:
        return self.model_dump()


app = FastAPI(title="Laberinto Race Control", version=__version__)
app.mount("/static", StaticFiles(directory=str(config.WEB_DIR)), name="static")


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(config.WEB_DIR / "index.html")


@app.get("/api/health")
async def health() -> dict[str, Any]:
    return {"ok": True, "version": __version__}


@app.get("/api/bootstrap")
async def bootstrap() -> dict[str, Any]:
    status, nam_result, decisions_result = await asyncio.gather(
        provider_status(), list_nam_models(), list_decision_models(), return_exceptions=True
    )

    if isinstance(status, Exception):
        status = {
            "nam": {"ok": False, "detail": str(status)},
            "openrouter": {"ok": False, "detail": str(status)},
        }
    if isinstance(nam_result, Exception):
        nam_models = [{"id": model, "owned_by": ""} for model in FALLBACK_TEXT_MODELS]
        nam_error = str(nam_result)
    else:
        nam_models = nam_result or [{"id": model, "owned_by": ""} for model in FALLBACK_TEXT_MODELS]
        nam_error = None
    if isinstance(decisions_result, Exception):
        decision_models, decision_error = [], str(decisions_result)
    else:
        decision_models, decision_error = decisions_result

    return {
        "version": __version__,
        "keys": status,
        "nam_models": nam_models,
        "nam_error": nam_error,
        "decision_models": decision_models,
        "decision_error": decision_error,
        "heuristic_model": config.HEURISTIC_MODEL,
        "defaults": {
            "width": config.DEFAULT_WIDTH,
            "height": config.DEFAULT_HEIGHT,
            "seed": config.DEFAULT_SEED,
            "mode": config.DEFAULT_MODE,
            "text_model": config.DEFAULT_TEXT_MODEL,
            "decisions_model": config.DEFAULT_DECISIONS_MODEL,
            "decisions_models": list(config.DEFAULT_DECISION_CONTENDERS),
            "text_max_attempts": config.DEFAULT_TEXT_ATTEMPTS,
            "max_junction_calls": config.DEFAULT_MAX_JUNCTION_CALLS,
            "include_baseline": False,
        },
    }


@app.get("/api/maze")
async def get_maze(
    width: int = Query(default=config.DEFAULT_WIDTH, ge=5, le=config.MAX_MAZE_SIZE),
    height: int = Query(default=config.DEFAULT_HEIGHT, ge=5, le=config.MAX_MAZE_SIZE),
    seed: int | None = None,
) -> dict[str, Any]:
    actual_seed = random.randrange(0, 2**31) if seed is None else int(seed)
    maze = generate_maze(width, height, actual_seed)
    return maze.to_dict(include_solution=True)


@app.post("/api/races")
async def create_race(request: RaceRequest) -> dict[str, Any]:
    try:
        race = manager.create(request.to_config())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    manager.start(race["id"])
    return manager.get(race["id"]) or race


@app.get("/api/races")
async def list_races(limit: int = Query(default=20, ge=1, le=100)) -> dict[str, Any]:
    return {"races": manager.history(limit)}


def _check_race_id(race_id: str) -> str:
    if not RACE_ID_PATTERN.fullmatch(race_id):
        raise HTTPException(status_code=404, detail="race not found")
    return race_id


@app.get("/api/races/{race_id}")
async def get_race(race_id: str) -> dict[str, Any]:
    race = manager.get(_check_race_id(race_id))
    if race is None:
        raise HTTPException(status_code=404, detail="race not found")
    return race


@app.post("/api/races/{race_id}/cancel")
async def cancel_race(race_id: str) -> dict[str, Any]:
    _check_race_id(race_id)
    if race_id not in manager.races:
        raise HTTPException(status_code=404, detail="race not found")
    cancelled = manager.cancel(race_id)
    return {"cancelled": cancelled, "race": manager.get(race_id)}


@app.get("/api/races/{race_id}/stream")
async def stream_race(race_id: str, request: Request) -> StreamingResponse:
    _check_race_id(race_id)
    if manager.get(race_id) is None:
        raise HTTPException(status_code=404, detail="race not found")

    async def events() -> AsyncIterator[str]:
        last: str | None = None
        while True:
            if await request.is_disconnected():
                break
            race = manager.get(race_id)
            if race is None:
                yield 'event: gone\ndata: {"detail": "race not found"}\n\n'
                break
            payload = json.dumps(race, ensure_ascii=False, separators=(",", ":"), default=str)
            if payload != last:
                yield f"data: {payload}\n\n"
                last = payload
            if race.get("status") in ("done", "error", "cancelled"):
                break
            await asyncio.sleep(0.18)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/export/{race_id}")
async def export_race(race_id: str) -> FileResponse:
    _check_race_id(race_id)
    path = config.RESULTS_DIR / "races" / f"{race_id}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="saved race not found")
    return FileResponse(path, media_type="application/json", filename=f"laberinto-race-{race_id}.json")


def run(host: str = "127.0.0.1", port: int = 8050, reload: bool = False) -> None:
    import uvicorn

    uvicorn.run("maze.server:app", host=host, port=port, reload=reload)


if __name__ == "__main__":
    run()
