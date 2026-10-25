from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Sequence

from .game import DIRECTION_LABEL, Coord, Maze, MoveOption, moves_to_path


def _extract_json(text: str) -> Any | None:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char not in "[{":
            continue
        try:
            value, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        return value
    return None


def _adjacency_rows(maze: Maze) -> str:
    rows = []
    for y in range(maze.height):
        rows.append(
            " ".join(f"{x},{y}:" + "".join(maze.open_directions((x, y))) for x in range(maze.width))
        )
    return "\n".join(rows)


def build_text_messages(maze: Maze, feedback: str | None = None) -> list[dict[str, str]]:
    system = (
        "You solve perfect mazes. You must answer with a single JSON object and nothing else. "
        "No markdown, no code fences, no explanation."
    )
    user = f"""Maze size: {maze.width} columns x {maze.height} rows.
Coordinates are [x, y]. x grows to the right (0..{maze.width - 1}); y grows downward (0..{maze.height - 1}).
Start: {list(maze.start)}. Goal: {list(maze.goal)}.

Open exits are listed row by row. Every token is `x,y:dirs`, where dirs is a string of the open directions:
`n` = north (y-1), `e` = east (x+1), `s` = south (y+1), `w` = west (x-1).
This adjacency list is authoritative: there are no other openings.

{_adjacency_rows(maze)}

Rules:
- Return one valid walk from the start to the goal.
- Consecutive coordinates must differ by exactly one cell horizontally or vertically.
- Only move in a direction listed for the current cell.
- The first coordinate must be the start and the last coordinate must be the goal.
- Prefer the shortest path, without revisiting cells.

Return exactly this JSON shape:
{{"path": [[x, y], [x, y], ...]}}"""
    if feedback:
        user += f"\n\nYour previous answer was rejected: {feedback}\nReturn a corrected JSON object."
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


@dataclass
class ParsedPath:
    path: list[Coord] | None
    error: str | None
    payload: Any | None
    raw_content: str


def parse_path_response(content: str, maze: Maze) -> ParsedPath:
    if not content or not content.strip():
        return ParsedPath(None, "empty response", None, content)
    payload = _extract_json(content)
    if payload is None:
        return ParsedPath(None, "response is not valid JSON", None, content)

    if isinstance(payload, list):
        raw_path = payload
    elif isinstance(payload, dict):
        raw_path = payload.get("path")
        if raw_path is None and isinstance(payload.get("moves"), list):
            try:
                path = moves_to_path(maze.start, payload["moves"])
            except (TypeError, ValueError) as exc:
                return ParsedPath(None, f"invalid moves: {exc}", payload, content)
            return ParsedPath(path, None, payload, content)
    else:
        return ParsedPath(None, "response must be an object with a `path` array", payload, content)

    if not isinstance(raw_path, list):
        return ParsedPath(None, "response must contain a `path` array", payload, content)
    if not raw_path:
        return ParsedPath(None, "`path` is empty", payload, content)

    path: list[Coord] = []
    for index, item in enumerate(raw_path, start=1):
        try:
            if isinstance(item, dict):
                path.append((int(item["x"]), int(item["y"])))
            elif isinstance(item, str):
                parts = [part.strip() for part in item.replace("(", "").replace(")", "").split(",")]
                if len(parts) != 2:
                    raise ValueError(f"invalid coordinate {item!r}")
                path.append((int(parts[0]), int(parts[1])))
            elif isinstance(item, (list, tuple)) and len(item) >= 2:
                path.append((int(item[0]), int(item[1])))
            else:
                raise ValueError(f"invalid coordinate {item!r}")
        except (KeyError, TypeError, ValueError) as exc:
            return ParsedPath(None, f"step {index}: {exc}", payload, content)
    return ParsedPath(path, None, payload, content)


def build_decisions_request(
    model: str,
    maze: Maze,
    position: Coord,
    visited: Sequence[Coord],
    path: Sequence[Coord],
    moves: Sequence[MoveOption],
) -> dict[str, Any]:
    """One Decisions API request: rank the legal exits at a junction."""
    criteria = {
        move.direction: (
            f"{DIRECTION_LABEL[move.direction]} to ({move.pos[0]}, {move.pos[1]}), "
            f"{move.distance if move.distance is not None else '?'} steps to the goal"
        )
        for move in moves
    }
    return {
        "model": model,
        "state": {
            "game": "perfect maze race",
            "maze": {
                "width": maze.width,
                "height": maze.height,
                "start": list(maze.start),
                "goal": list(maze.goal),
            },
            "position": list(position),
            "visited_count": len(visited),
            "current_path_tail": [list(cell) for cell in path[-8:]],
            "legal_moves": [
                {
                    "direction": move.direction,
                    "to": list(move.pos),
                    "distance_to_goal": move.distance,
                }
                for move in moves
            ],
            "rules": {
                "coordinates": "[x, y], x grows right, y grows down",
                "only_legal_moves": [move.direction for move in moves],
                "distance_to_goal": "exact remaining shortest-path steps computed by the harness",
            },
            "instruction": (
                "You navigate a token inside a perfect maze. "
                "Choose the legal exit that minimizes the remaining distance to the goal. "
                "Dead ends force the harness to backtrack and lose time."
            ),
        },
        "questions": {
            "move": {
                "type": "choice",
                "instructions": (
                    "Pick the single best next direction. Every listed option is legal and unvisited. "
                    "The distance_to_goal field is the exact shortest-path distance from that exit to the goal; "
                    "prefer the smallest value."
                ),
                "criteria": criteria,
            }
        },
    }
