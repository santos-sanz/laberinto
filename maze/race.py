from __future__ import annotations

import asyncio
import copy
import json
import uuid
from datetime import datetime
from typing import Any

from .config import GROUND_TRUTH_SOLUTION_MAX_CELLS, PUBLIC_VISITED_LIMIT, RESULTS_DIR
from .game import Maze, distance_map, generate_maze, shortest_path
from .models import RaceConfig, new_lane, now_iso
from .runners import HeuristicPolicy, policy_for_model, run_decisions_lane, run_text_lane

RACES_DIR = RESULTS_DIR / "races"


def analyse_maze(maze: Maze) -> dict[str, Any]:
    solution = shortest_path(maze)
    distances = distance_map(maze)
    include_solution = maze.cell_count <= GROUND_TRUTH_SOLUTION_MAX_CELLS
    return {
        "solvable": bool(solution),
        "solution": [list(cell) for cell in solution] if include_solution else None,
        "solution_omitted": not include_solution,
        "optimal_steps": len(solution) - 1 if solution else None,
        "reachable_cells": len(distances),
    }


def _public_lane(lane: dict[str, Any]) -> dict[str, Any]:
    trimmed = dict(lane)
    visited = trimmed.get("visited") or []
    if len(visited) > PUBLIC_VISITED_LIMIT:
        trimmed["visited"] = []
    public = copy.deepcopy(trimmed)
    public.pop("raw", None)
    if len(public.get("trail") or []) > 1200:
        public["trail"] = public["trail"][-1200:]
    public["trace"] = public.get("trace", [])[-100:]
    if isinstance(public.get("verification"), dict):
        public["verification"].pop("path", None)
    for attempt in public.get("attempts", []):
        attempt["content"] = (attempt.get("content") or "")[:4000]
        attempt["reasoning"] = (attempt.get("reasoning") or "")[:2000]
    return public


def _live_winner(race: dict[str, Any]) -> str | None:
    if race.get("winner"):
        return race["winner"]
    if race.get("status") in ("cancelled", "error"):
        return None
    eligible = [
        (key, lane)
        for key, lane in race["lanes"].items()
        if lane.get("kind") != "baseline"
        and lane.get("status") == "solved"
        and lane.get("elapsed_ms")
    ]
    if not eligible:
        return None
    eligible.sort(key=lambda item: item[1]["elapsed_ms"])
    if len(eligible) > 1 and abs(eligible[0][1]["elapsed_ms"] - eligible[1][1]["elapsed_ms"]) < 1:
        return "tie"
    return eligible[0][0]


def _public_race(race: dict[str, Any]) -> dict[str, Any]:
    public = copy.deepcopy({key: value for key, value in race.items() if key != "lanes"})
    public["lanes"] = {key: _public_lane(lane) for key, lane in race["lanes"].items()}
    public["winner"] = _live_winner(race)
    return public


def _summary(race: dict[str, Any]) -> dict[str, Any]:
    lanes = race["lanes"]
    lane_summaries = {}
    for key, lane in lanes.items():
        solution = lane.get("solution") or {}
        lane_summaries[key] = {
            "kind": lane.get("kind"),
            "label": lane.get("label") or key,
            "model": lane.get("model"),
            "status": lane.get("status"),
            "elapsed_ms": lane.get("elapsed_ms"),
            "steps": solution.get("steps"),
            "efficiency": solution.get("efficiency"),
            "rate_limited": bool((lane.get("stats") or {}).get("rate_limited")),
        }
    winner = race.get("winner")
    winner_label = "empate" if winner == "tie" else lane_summaries.get(winner, {}).get("label")
    winner_ms = lane_summaries.get(winner, {}).get("elapsed_ms") if winner else None

    solved = [
        (key, lane)
        for key, lane in lanes.items()
        if lane.get("kind") != "baseline"
        and lane.get("status") == "solved"
        and lane.get("elapsed_ms")
    ]
    solved.sort(key=lambda item: item[1]["elapsed_ms"])
    first_decisions = next(
        (lane for lane in lanes.values() if lane.get("kind") == "decisions"), {}
    )
    result: dict[str, Any] = {
        "winner": winner,
        "winner_label": winner_label,
        "winner_ms": winner_ms,
        "lanes": lane_summaries,
        "text_ms": lanes.get("text", {}).get("elapsed_ms"),
        "decisions_ms": first_decisions.get("elapsed_ms"),
        "baseline_ms": lanes.get("baseline", {}).get("elapsed_ms"),
        "text_status": lanes.get("text", {}).get("status"),
        "decisions_status": first_decisions.get("status"),
        "baseline_status": lanes.get("baseline", {}).get("status"),
        "delta_ms": None,
        "speedup": None,
    }
    if len(solved) >= 2:
        first, second = solved[0][1], solved[1][1]
        result["delta_ms"] = round(second["elapsed_ms"] - first["elapsed_ms"], 1)
        if second["elapsed_ms"] > 0:
            result["speedup"] = round(first["elapsed_ms"] / second["elapsed_ms"], 3)
    if winner == "tie" and solved:
        result["winner_ms"] = solved[0][1]["elapsed_ms"]
    return result


class RaceManager:
    def __init__(self) -> None:
        self.races: dict[str, dict[str, Any]] = {}
        self.tasks: dict[str, asyncio.Task] = {}
        RACES_DIR.mkdir(parents=True, exist_ok=True)

    def create(self, raw_config: dict[str, Any]) -> dict[str, Any]:
        config = RaceConfig.from_dict(raw_config)
        maze = generate_maze(config.width, config.height, config.seed)
        ground_truth = analyse_maze(maze)
        race_id = uuid.uuid4().hex[:12]
        race: dict[str, Any] = {
            "id": race_id,
            "status": "created",
            "created_at": now_iso(),
            "started_at": None,
            "finished_at": None,
            "config": config.to_dict(),
            "maze": maze.to_dict(include_solution=False),
            "ground_truth": ground_truth,
            "lanes": {
                spec["key"]: new_lane(
                    spec["kind"], spec["model"], spec["provider"], maze.start, spec["label"]
                )
                for spec in config.lane_specs()
            },
            "winner": None,
            "events": [],
            "summary": None,
        }
        self.races[race_id] = race
        return _public_race(race)

    def start(self, race_id: str) -> None:
        race = self.races[race_id]
        if race["status"] != "created":
            return
        task = asyncio.create_task(self._run(race_id))
        self.tasks[race_id] = task
        task.add_done_callback(lambda _: self.tasks.pop(race_id, None))

    def cancel(self, race_id: str) -> bool:
        task = self.tasks.get(race_id)
        if task is None:
            return False
        task.cancel()
        race = self.races.get(race_id)
        if race:
            race["status"] = "cancelled"
            race["finished_at"] = now_iso()
            for lane in race["lanes"].values():
                if lane["status"] in ("waiting", "running"):
                    lane["status"] = "cancelled"
        return True

    async def _run(self, race_id: str) -> None:
        race = self.races[race_id]
        race["status"] = "running"
        race["started_at"] = now_iso()
        race["events"].append({"at": race["started_at"], "message": "carrera iniciada"})
        config = RaceConfig.from_dict(race["config"])
        maze = generate_maze(config.width, config.height, config.seed)
        solution = shortest_path(maze)
        optimal_steps = len(solution) - 1
        lanes = race["lanes"]

        tasks = []
        for key, lane in lanes.items():
            if lane["kind"] == "text":
                tasks.append(run_text_lane(config, maze, lane, optimal_steps))
            elif lane["kind"] == "decisions":
                tasks.append(
                    run_decisions_lane(
                        config,
                        maze,
                        lane,
                        policy_for_model(lane["model"]),
                        source=key,
                    )
                )
            elif lane["kind"] == "baseline":
                tasks.append(
                    run_decisions_lane(
                        config,
                        maze,
                        lane,
                        HeuristicPolicy(),
                        source=key,
                    )
                )
        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            race["status"] = "cancelled"
            race["finished_at"] = now_iso()
            self._save(race)
            raise
        except Exception as exc:  # pragma: no cover - defensive
            race["status"] = "error"
            race["error"] = str(exc)
            race["finished_at"] = now_iso()
            self._save(race)
            return

        eligible = [
            (key, lane)
            for key, lane in lanes.items()
            if lane["kind"] != "baseline"
            and lane["status"] == "solved"
            and lane["elapsed_ms"]
        ]
        if eligible:
            fastest_key, fastest = min(eligible, key=lambda item: item[1]["elapsed_ms"])
            race["winner"] = fastest_key
            if len(eligible) > 1:
                first, second = sorted(eligible, key=lambda item: item[1]["elapsed_ms"])[:2]
                if abs(first[1]["elapsed_ms"] - second[1]["elapsed_ms"]) < 1:
                    race["winner"] = "tie"
        race["status"] = "done"
        race["finished_at"] = now_iso()
        race["summary"] = _summary(race)
        race["events"].append(
            {
                "at": race["finished_at"],
                "message": f"carrera terminada: {race['summary'].get('winner_label') or 'sin ganador'}",
            }
        )
        self._save(race)

    def _save(self, race: dict[str, Any]) -> None:
        path = RACES_DIR / f"{race['id']}.json"
        path.write_text(json.dumps(race, indent=2, ensure_ascii=False), encoding="utf-8")

    def get(self, race_id: str) -> dict[str, Any] | None:
        race = self.races.get(race_id)
        if race is not None:
            return _public_race(race)
        path = RACES_DIR / f"{race_id}.json"
        if path.exists():
            return _public_race(json.loads(path.read_text(encoding="utf-8")))
        return None

    def history(self, limit: int = 20) -> list[dict[str, Any]]:
        summaries: dict[str, dict[str, Any]] = {}
        for race in self.races.values():
            summaries[race["id"]] = {
                "id": race["id"],
                "status": race["status"],
                "created_at": race["created_at"],
                "started_at": race["started_at"],
                "finished_at": race["finished_at"],
                "winner": race.get("winner") or _live_winner(race),
                "config": race["config"],
                "summary": race.get("summary"),
            }
        if RACES_DIR.exists():
            for path in RACES_DIR.glob("*.json"):
                if path.stem in summaries:
                    continue
                try:
                    race = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                summaries[race["id"]] = {
                    "id": race["id"],
                    "status": race.get("status"),
                    "created_at": race.get("created_at"),
                    "started_at": race.get("started_at"),
                    "finished_at": race.get("finished_at"),
                    "winner": race.get("winner"),
                    "config": race.get("config"),
                    "summary": race.get("summary"),
                }
        ordered = sorted(
            summaries.values(),
            key=lambda item: item.get("started_at") or item.get("created_at") or "",
            reverse=True,
        )
        return ordered[:limit]


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


manager = RaceManager()
