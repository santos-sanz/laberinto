from __future__ import annotations

import asyncio
import math
import time
from dataclasses import dataclass, field
from typing import Any, Protocol, Sequence

from .clients import NamClient, OpenRouterDecisionsClient, ProviderError
from .config import HEURISTIC_MODEL, PUBLIC_VISITED_LIMIT, TEXT_MAX_CELLS, TEXT_MAX_TOKENS
from .game import (
    DIRECTION_LABEL,
    DIRECTIONS,
    Coord,
    Maze,
    MoveOption,
    Verification,
    distance_map,
    heuristic_order,
    legal_moves,
    verify_path,
)
from .models import RaceConfig, now_iso
from .prompts import build_decisions_request, build_text_messages, parse_path_response


def trace(lane: dict[str, Any], message: str, **data: Any) -> None:
    entry = {"at": now_iso(), "message": message}
    if data:
        entry["data"] = data
    lane["trace"].append(entry)
    if len(lane["trace"]) > 240:
        del lane["trace"][:-240]


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 1)


def _finish_lane(lane: dict[str, Any], started: float, status: str) -> None:
    lane["status"] = status
    lane["finished_at"] = now_iso()
    lane["elapsed_ms"] = _elapsed_ms(started)


def _accumulate(lane: dict[str, Any], prompt: int, completion: int, total: int, cost: float) -> None:
    lane["tokens"]["prompt"] += prompt
    lane["tokens"]["completion"] += completion
    lane["tokens"]["total"] += total
    lane["cost"] = round(lane["cost"] + cost, 8)


def _error_verification(message: str, optimal_steps: int | None) -> Verification:
    return Verification(False, message, [], 0, 0, 0, optimal_steps, None)


def _solution_payload(verification: Verification, source: str, extra: dict | None = None) -> dict[str, Any]:
    payload = {
        "path": [list(cell) for cell in verification.path],
        "steps": verification.steps,
        "unique_cells": verification.unique_cells,
        "repeated_cells": verification.repeated_cells,
        "optimal_steps": verification.optimal_steps,
        "efficiency": verification.efficiency,
        "source": source,
    }
    if extra:
        payload.update(extra)
    return payload


def _apply_solution(lane: dict[str, Any], verification: Verification) -> None:
    lane["verification"] = verification.to_dict()
    lane["path"] = [list(cell) for cell in verification.path]
    lane["trail"] = [list(cell) for cell in verification.path]
    lane["visited"] = [list(cell) for cell in dict.fromkeys(verification.path)]
    lane["position"] = list(verification.path[-1]) if verification.path else lane["position"]
    lane["stats"].update(
        {
            "steps": verification.steps,
            "unique_cells": verification.unique_cells,
            "optimal_steps": verification.optimal_steps,
            "path_length": verification.steps,
            "efficiency": verification.efficiency,
        }
    )


async def run_text_lane(
    config: RaceConfig,
    maze: Maze,
    lane: dict[str, Any],
    optimal_steps: int,
) -> None:
    client = NamClient()
    started = time.perf_counter()
    lane["started_at"] = now_iso()
    lane["status"] = "running"

    if maze.cell_count > TEXT_MAX_CELLS:
        message = (
            f"laberinto {maze.width}×{maze.height} ({maze.cell_count} celdas): "
            f"el carril de texto solo admite hasta {TEXT_MAX_CELLS} celdas. "
            "Usa el modo decisiones o un laberinto más pequeño."
        )
        lane["verification"] = _error_verification(message, optimal_steps).to_dict()
        trace(lane, message)
        _finish_lane(lane, started, "unsolved")
        return

    trace(lane, f"abriendo carril de texto con {config.text_model}")

    feedback: str | None = None
    for attempt in range(1, config.text_max_attempts + 1):
        messages = build_text_messages(maze, feedback)
        trace(lane, f"intento {attempt}/{config.text_max_attempts}: pidiendo la ruta completa")
        try:
            call = await client.complete(config.text_model, messages, max_tokens=TEXT_MAX_TOKENS)
        except ProviderError as exc:
            lane["error"] = str(exc)
            trace(lane, f"error del proveedor: {exc}")
            _finish_lane(lane, started, "error")
            return
        except Exception as exc:  # pragma: no cover - defensive
            lane["error"] = f"unexpected error: {exc}"
            trace(lane, lane["error"])
            _finish_lane(lane, started, "error")
            return

        lane["calls"] += 1
        _accumulate(lane, call.prompt_tokens, call.completion_tokens, call.total_tokens, call.cost)
        lane["raw"].append(
            {
                "attempt": attempt,
                "request": {"model": config.text_model, "messages": messages},
                "response": call.raw,
            }
        )

        response_text = call.content or ""
        used_reasoning = False
        if not response_text.strip() and call.reasoning:
            response_text = call.reasoning
            used_reasoning = True
        parsed = parse_path_response(response_text, maze)
        if parsed.error or parsed.path is None:
            verification = _error_verification(parsed.error or "invalid path", optimal_steps)
        else:
            verification = verify_path(maze, parsed.path, optimal_steps)

        lane["verification"] = verification.to_dict()
        lane["attempts"].append(
            {
                "attempt": attempt,
                "latency_ms": round(call.latency_ms, 1),
                "tokens": call.total_tokens,
                "ok": verification.ok,
                "error": verification.error,
                "content": call.content[:6000],
                "reasoning": (call.reasoning or "")[:3000],
                "used_reasoning": used_reasoning,
            }
        )

        if verification.ok:
            _apply_solution(lane, verification)
            lane["solution"] = _solution_payload(
                verification,
                source="text",
                extra={"attempt": attempt, "model_latency_ms": round(call.latency_ms, 1)},
            )
            trace(
                lane,
                f"resuelto en {round((time.perf_counter() - started) * 1000)} ms",
                attempt=attempt,
                steps=verification.steps,
            )
            _finish_lane(lane, started, "solved")
            return

        feedback = verification.error or parsed.error or "invalid path"
        if not call.content.strip() and call.reasoning:
            feedback = f"{feedback}. Your message content was empty; put the JSON object in the final answer."
        trace(lane, f"intento {attempt} rechazado: {feedback}")

    lane["verification"] = _error_verification(
        f"no valid path after {config.text_max_attempts} attempts", optimal_steps
    ).to_dict()
    trace(lane, "sin solución válida tras agotar los intentos")
    _finish_lane(lane, started, "unsolved")


@dataclass
class Selection:
    probabilities: dict[str, float] = field(default_factory=dict)
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost: float = 0.0
    latency_ms: float = 0.0
    raw: dict[str, Any] | None = None


class MovePolicy(Protocol):
    async def select(
        self,
        maze: Maze,
        position: Coord,
        visited: Sequence[Coord],
        path: Sequence[Coord],
        moves: Sequence[MoveOption],
    ) -> Selection: ...


def _normalise(values: dict[str, float]) -> dict[str, float]:
    cleaned = {key: max(0.0, value) for key, value in values.items() if math.isfinite(value)}
    total = sum(cleaned.values())
    if total <= 0:
        if not cleaned:
            return {}
        share = 1.0 / len(cleaned)
        return {key: share for key in cleaned}
    return {key: value / total for key, value in cleaned.items()}


def _choice_to_direction(raw: Any, moves: Sequence[MoveOption]) -> str | None:
    if not isinstance(raw, str):
        return None
    text = raw.strip().lower()
    valid = {move.direction for move in moves}
    if text in valid:
        return text
    for move in moves:
        if text == DIRECTION_LABEL[move.direction]:
            return move.direction
        if text == f"{DIRECTION_LABEL[move.direction]} to ({move.pos[0]}, {move.pos[1]})".lower():
            return move.direction
        if text.startswith(f"{move.direction} ") or text.startswith(f"{DIRECTION_LABEL[move.direction]} "):
            return move.direction
    return None


class OpenRouterPolicy:
    def __init__(self, model: str):
        self.model = model
        self.client = OpenRouterDecisionsClient()

    async def select(
        self,
        maze: Maze,
        position: Coord,
        visited: Sequence[Coord],
        path: Sequence[Coord],
        moves: Sequence[MoveOption],
    ) -> Selection:
        payload = build_decisions_request(self.model, maze, position, visited, path, moves)
        call = await self.client.decide(payload)
        answer = call.answers.get("move")
        if not isinstance(answer, dict):
            answer = next((value for value in call.answers.values() if isinstance(value, dict)), {})

        probabilities: dict[str, float] = {}
        raw_probabilities = answer.get("probabilities")
        if isinstance(raw_probabilities, dict):
            for key, value in raw_probabilities.items():
                direction = _choice_to_direction(key, moves)
                if direction is None:
                    continue
                try:
                    probabilities[direction] = float(value)
                except (TypeError, ValueError):
                    continue

        choice = _choice_to_direction(answer.get("choice"), moves)
        if choice is not None and choice not in probabilities:
            probabilities[choice] = max(probabilities.values(), default=1.0)

        return Selection(
            probabilities=_normalise(probabilities),
            calls=1,
            prompt_tokens=call.prompt_tokens,
            completion_tokens=call.completion_tokens,
            total_tokens=call.total_tokens,
            cost=call.cost,
            latency_ms=call.latency_ms,
            raw={"request": payload, "response": call.raw},
        )


class HeuristicPolicy:
    """Solver-free control: prefer exits with the smallest remaining BFS distance."""

    async def select(
        self,
        maze: Maze,
        position: Coord,
        visited: Sequence[Coord],
        path: Sequence[Coord],
        moves: Sequence[MoveOption],
    ) -> Selection:
        distances = [move.distance if move.distance is not None else 10**9 for move in moves]
        peak = max(distances)
        weights = {
            move.direction: math.exp(-(distance - peak) / 2.0)
            for move, distance in zip(moves, distances)
        }
        return Selection(probabilities=_normalise(weights))


def policy_for_model(model: str) -> MovePolicy:
    if model == HEURISTIC_MODEL:
        return HeuristicPolicy()
    return OpenRouterPolicy(model)


def policy_for(config: RaceConfig) -> MovePolicy:
    return policy_for_model(config.decisions_model)


def _ranked_moves(
    moves: Sequence[MoveOption],
    probabilities: dict[str, float],
) -> list[MoveOption]:
    return sorted(
        moves,
        key=lambda move: (
            -float(probabilities.get(move.direction, 0.0)),
            move.distance if move.distance is not None else 10**9,
            DIRECTIONS.index(move.direction),
        ),
    )


async def run_decisions_lane(
    config: RaceConfig,
    maze: Maze,
    lane: dict[str, Any],
    policy: MovePolicy,
    source: str = "decisions",
) -> None:
    """Step-by-step navigator with harness-driven backtracking.

    At every junction the Decisions model ranks the legal exits. Corridors are
    followed without a model call. Dead ends are popped by the harness, which
    keeps the lane guaranteed to terminate on a perfect maze while the model
    decides how much wandering happens along the way.
    """
    started = time.perf_counter()
    lane["started_at"] = now_iso()
    lane["status"] = "running"
    trace(lane, f"abriendo carril {lane.get('label') or source} con {lane['model']}")

    distances = distance_map(maze)
    position = maze.start
    visited: set[Coord] = {maze.start}
    path: list[Coord] = [maze.start]
    trail: list[Coord] = [maze.start]
    stats = lane["stats"]
    stats["optimal_steps"] = None
    calls = 0
    rate_limited = False
    steps = 0
    last_trace_step = 0
    last_published_step = -1
    publish_interval = 1 if maze.cell_count <= PUBLIC_VISITED_LIMIT else 25
    baseline_pace = 0.012 if maze.cell_count <= PUBLIC_VISITED_LIMIT else 0.0

    def publish(force: bool = False) -> None:
        nonlocal last_published_step
        lane["position"] = list(position)
        stats["steps"] = steps
        stats["unique_cells"] = len(visited)
        stats["backtracks"] = max(0, len(trail) - len(path))
        stats["path_length"] = max(0, len(path) - 1)
        if not force and steps - last_published_step < publish_interval:
            return
        lane["path"] = [list(cell) for cell in path]
        lane["trail"] = [list(cell) for cell in trail[-1200:]]
        lane["visited"] = (
            [list(cell) for cell in visited] if len(visited) <= PUBLIC_VISITED_LIMIT else []
        )
        last_published_step = steps

    while position != maze.goal:
        if steps >= config.max_steps:
            break
        options = legal_moves(maze, position, visited, distances)
        if not options:
            if len(path) <= 1:
                break
            path.pop()
            position = path[-1]
            trail.append(position)
            steps += 1
            stats["dead_ends_hit"] += 1
            stats["backtracks"] += 1
            publish()
            if steps - last_trace_step >= 3:
                trace(lane, f"callejón sin salida, retrocedo a {list(position)}")
                last_trace_step = steps
            if source == "baseline" and baseline_pace:
                await asyncio.sleep(baseline_pace)
            continue

        if len(options) == 1:
            chosen = options[0]
        else:
            stats["junctions"] += 1
            if rate_limited:
                chosen = heuristic_order(maze, options)[0]
            elif calls >= config.max_junction_calls:
                chosen = heuristic_order(maze, options)[0]
                trace(lane, f"presupuesto de decisiones agotado en {list(position)}; uso la heurística")
            else:
                selection = None
                try:
                    selection = await policy.select(maze, position, visited, path, options)
                except ProviderError as exc:
                    if exc.status == 429:
                        rate_limited = True
                        stats["rate_limited"] = True
                        chosen = heuristic_order(maze, options)[0]
                        trace(
                            lane,
                            "límite de peticiones del proveedor (429); continúo con la heurística",
                        )
                    else:
                        lane["error"] = str(exc)
                        trace(lane, f"error del proveedor: {exc}")
                        _finish_lane(lane, started, "error")
                        return
                except Exception as exc:  # pragma: no cover - defensive
                    lane["error"] = f"unexpected error: {exc}"
                    trace(lane, lane["error"])
                    _finish_lane(lane, started, "error")
                    return

                if selection is not None:
                    if selection.calls:
                        lane["calls"] += selection.calls
                        calls += selection.calls
                        _accumulate(
                            lane,
                            selection.prompt_tokens,
                            selection.completion_tokens,
                            selection.total_tokens,
                            selection.cost,
                        )
                        if selection.raw is not None:
                            lane["raw"].append(
                                {
                                    "position": list(position),
                                    "step": steps,
                                    "request": selection.raw.get("request"),
                                    "response": selection.raw.get("response"),
                                }
                            )
                        trace(
                            lane,
                            f"decisión en {list(position)} en {round(selection.latency_ms)} ms",
                            prompt_tokens=selection.prompt_tokens,
                            options=len(options),
                        )

                    ranked = _ranked_moves(options, selection.probabilities)
                    chosen = ranked[0]
                    if selection.probabilities:
                        trace(
                            lane,
                            f"modelo elige {chosen.direction} desde {list(position)}",
                            probabilities={key: round(value, 3) for key, value in selection.probabilities.items()},
                        )
                    else:
                        trace(lane, "respuesta sin probabilidades; uso el orden heurístico")

        position = chosen.pos
        visited.add(position)
        path.append(position)
        trail.append(position)
        steps += 1
        publish()
        if source == "baseline" and baseline_pace:
            await asyncio.sleep(baseline_pace)
        if steps % 400 == 0:
            await asyncio.sleep(0)

    if position == maze.goal:
        publish(force=True)
        reference = distance_map(maze)
        optimal_steps = reference.get(maze.start, 0)
        verification = verify_path(maze, path, optimal_steps)
        stats["dead_ends_hit"] = stats.get("dead_ends_hit", 0)
        if verification.ok:
            _apply_solution(lane, verification)
            lane["stats"].update(
                {
                    "backtracks": max(0, len(trail) - len(path)),
                    "junctions": stats.get("junctions", 0),
                    "dead_ends_hit": stats.get("dead_ends_hit", 0),
                    "calls": calls,
                }
            )
            lane["solution"] = _solution_payload(
                verification,
                source=source,
                extra={
                    "model_calls": calls,
                    "junctions": stats.get("junctions", 0),
                    "dead_ends_hit": stats.get("dead_ends_hit", 0),
                    "rate_limited": stats.get("rate_limited", False),
                },
            )
            trace(
                lane,
                f"resuelto: {verification.steps} pasos, {len(path)} celdas en la ruta, "
                f"{stats.get('dead_ends_hit', 0)} callejones, {calls} llamadas",
            )
            _finish_lane(lane, started, "solved")
            return
        trace(lane, f"la búsqueda produjo una ruta inválida: {verification.error}")

    optimal = distance_map(maze).get(maze.start)
    lane["verification"] = _error_verification(
        f"no verified path within {config.max_steps} moves", optimal
    ).to_dict()
    trace(lane, f"búsqueda agotada: {steps} movimientos, {calls} llamadas")
    _finish_lane(lane, started, "unsolved")
