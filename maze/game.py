from __future__ import annotations

import random
from collections import deque
from dataclasses import dataclass
from typing import Any, Iterable, Sequence

Coord = tuple[int, int]

DIRECTIONS = ("n", "e", "s", "w")
DELTAS: dict[str, tuple[int, int]] = {
    "n": (0, -1),
    "e": (1, 0),
    "s": (0, 1),
    "w": (-1, 0),
}
OPPOSITE = {"n": "s", "s": "n", "e": "w", "w": "e"}
WALL_BITS = {"n": 1, "e": 2, "s": 4, "w": 8}
DIRECTION_LABEL = {"n": "north", "e": "east", "s": "south", "w": "west"}


@dataclass(frozen=True)
class Maze:
    width: int
    height: int
    seed: int
    walls: tuple[int, ...]

    def __post_init__(self) -> None:
        if self.width < 2 or self.height < 2:
            raise ValueError("maze must be at least 2x2")
        if len(self.walls) != self.width * self.height:
            raise ValueError("walls length does not match maze size")

    @property
    def start(self) -> Coord:
        return (0, 0)

    @property
    def goal(self) -> Coord:
        return (self.width - 1, self.height - 1)

    @property
    def cell_count(self) -> int:
        return self.width * self.height

    def in_bounds(self, x: int, y: int) -> bool:
        return 0 <= x < self.width and 0 <= y < self.height

    def index(self, pos: Coord) -> int:
        return pos[1] * self.width + pos[0]

    def has_wall(self, x: int, y: int, direction: str) -> bool:
        if not self.in_bounds(x, y):
            return True
        return bool(self.walls[self.index((x, y))] & WALL_BITS[direction])

    def neighbor(self, pos: Coord, direction: str) -> Coord:
        dx, dy = DELTAS[direction]
        return (pos[0] + dx, pos[1] + dy)

    def can_move(self, pos: Coord, direction: str) -> bool:
        if direction not in DELTAS:
            return False
        target = self.neighbor(pos, direction)
        if not self.in_bounds(*target):
            return False
        return not self.has_wall(pos[0], pos[1], direction)

    def open_directions(self, pos: Coord) -> list[str]:
        return [direction for direction in DIRECTIONS if self.can_move(pos, direction)]

    def all_cells(self) -> Iterable[Coord]:
        for y in range(self.height):
            for x in range(self.width):
                yield (x, y)

    def to_ascii(self) -> str:
        lines: list[str] = []
        for y in range(self.height):
            top = "+"
            for x in range(self.width):
                top += "---+" if self.has_wall(x, y, "n") else "   +"
            lines.append(top)
            middle = ""
            for x in range(self.width):
                middle += "|" if self.has_wall(x, y, "w") else " "
                middle += "   "
            middle += "|"
            lines.append(middle)
        bottom = "+"
        for x in range(self.width):
            bottom += "---+" if self.has_wall(x, self.height - 1, "s") else "   +"
        lines.append(bottom)
        return "\n".join(lines)

    def to_dict(self, include_solution: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "width": self.width,
            "height": self.height,
            "seed": self.seed,
            "walls": list(self.walls),
            "start": list(self.start),
            "goal": list(self.goal),
            "ascii": self.to_ascii(),
            "cells": self.cell_count,
        }
        if include_solution:
            path = shortest_path(self)
            payload["solution"] = [list(cell) for cell in path]
            payload["optimal_steps"] = len(path) - 1
            payload["dead_ends"] = dead_end_count(self)
            payload["junctions"] = junction_count(self)
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Maze":
        return cls(
            width=int(data["width"]),
            height=int(data["height"]),
            seed=int(data.get("seed", 0)),
            walls=tuple(int(value) for value in data["walls"]),
        )


def generate_maze(width: int = 13, height: int = 13, seed: int | None = None) -> Maze:
    """Carve a perfect maze with randomized depth-first search."""
    if width < 2 or height < 2:
        raise ValueError("maze must be at least 2x2")
    if width > 41 or height > 41:
        raise ValueError("maze cannot be larger than 41x41")
    seed = random.randrange(0, 2**31) if seed is None else int(seed)
    rng = random.Random(seed)
    walls = [WALL_BITS["n"] | WALL_BITS["e"] | WALL_BITS["s"] | WALL_BITS["w"] for _ in range(width * height)]
    visited = {(0, 0)}
    stack: list[Coord] = [(0, 0)]

    def carve(a: Coord, b: Coord, direction: str) -> None:
        ai = a[1] * width + a[0]
        bi = b[1] * width + b[0]
        walls[ai] &= ~WALL_BITS[direction]
        walls[bi] &= ~WALL_BITS[OPPOSITE[direction]]

    while stack:
        x, y = stack[-1]
        options = []
        for direction in DIRECTIONS:
            dx, dy = DELTAS[direction]
            nx, ny = x + dx, y + dy
            if 0 <= nx < width and 0 <= ny < height and (nx, ny) not in visited:
                options.append((direction, (nx, ny)))
        if not options:
            stack.pop()
            continue
        direction, target = rng.choice(options)
        carve((x, y), target, direction)
        visited.add(target)
        stack.append(target)

    return Maze(width=width, height=height, seed=seed, walls=tuple(walls))


def shortest_path(maze: Maze, start: Coord | None = None, goal: Coord | None = None) -> list[Coord]:
    start = start or maze.start
    goal = goal or maze.goal
    frontier: deque[Coord] = deque([start])
    parents: dict[Coord, Coord | None] = {start: None}
    while frontier:
        current = frontier.popleft()
        if current == goal:
            break
        for direction in maze.open_directions(current):
            nxt = maze.neighbor(current, direction)
            if nxt not in parents:
                parents[nxt] = current
                frontier.append(nxt)
    if goal not in parents:
        return []
    path: list[Coord] = []
    node: Coord | None = goal
    while node is not None:
        path.append(node)
        node = parents[node]
    path.reverse()
    return path


def distance_map(maze: Maze, origin: Coord | None = None) -> dict[Coord, int]:
    origin = origin or maze.goal
    distances: dict[Coord, int] = {origin: 0}
    frontier: deque[Coord] = deque([origin])
    while frontier:
        current = frontier.popleft()
        for direction in maze.open_directions(current):
            nxt = maze.neighbor(current, direction)
            if nxt not in distances:
                distances[nxt] = distances[current] + 1
                frontier.append(nxt)
    return distances


def dead_end_count(maze: Maze) -> int:
    return sum(1 for cell in maze.all_cells() if len(maze.open_directions(cell)) == 1)


def junction_count(maze: Maze) -> int:
    return sum(1 for cell in maze.all_cells() if len(maze.open_directions(cell)) >= 3)


def direction_between(a: Coord, b: Coord) -> str | None:
    dx = b[0] - a[0]
    dy = b[1] - a[1]
    for direction, (ddx, ddy) in DELTAS.items():
        if (dx, dy) == (ddx, ddy):
            return direction
    return None


@dataclass(frozen=True)
class MoveOption:
    direction: str
    pos: Coord
    distance: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "direction": self.direction,
            "pos": list(self.pos),
            "distance_to_goal": self.distance,
        }


def legal_moves(
    maze: Maze,
    pos: Coord,
    visited: Iterable[Coord] | None = None,
    distances: dict[Coord, int] | None = None,
) -> list[MoveOption]:
    visited_set = set(visited or ())
    distances = distances if distances is not None else distance_map(maze)
    moves: list[MoveOption] = []
    for direction in maze.open_directions(pos):
        target = maze.neighbor(pos, direction)
        if target in visited_set:
            continue
        moves.append(MoveOption(direction, target, distances.get(target)))
    moves.sort(key=lambda move: (move.distance if move.distance is not None else 10**9, DIRECTIONS.index(move.direction)))
    return moves


def moves_to_path(start: Coord, moves: Sequence[str]) -> list[Coord]:
    path = [start]
    current = start
    for raw in moves:
        direction = str(raw).strip().lower()
        aliases = {
            "up": "n",
            "down": "s",
            "left": "w",
            "right": "e",
            "north": "n",
            "east": "e",
            "south": "s",
            "west": "w",
            "^": "n",
            "v": "s",
            "<": "w",
            ">": "e",
        }
        direction = aliases.get(direction, direction)
        if direction not in DELTAS:
            raise ValueError(f"unknown move {raw!r}")
        dx, dy = DELTAS[direction]
        current = (current[0] + dx, current[1] + dy)
        path.append(current)
    return path


def normalise_coord(raw: Any) -> Coord:
    if isinstance(raw, dict):
        return (int(raw["x"]), int(raw["y"]))
    if isinstance(raw, str):
        parts = [part.strip() for part in raw.replace("(", "").replace(")", "").split(",")]
        if len(parts) != 2:
            raise ValueError(f"invalid coordinate {raw!r}")
        return (int(parts[0]), int(parts[1]))
    if isinstance(raw, (list, tuple)) and len(raw) >= 2:
        return (int(raw[0]), int(raw[1]))
    raise ValueError(f"invalid coordinate {raw!r}")


@dataclass
class Verification:
    ok: bool
    error: str | None
    path: list[Coord]
    steps: int
    unique_cells: int
    repeated_cells: int
    optimal_steps: int | None
    efficiency: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "error": self.error,
            "path": [list(cell) for cell in self.path],
            "steps": self.steps,
            "unique_cells": self.unique_cells,
            "repeated_cells": self.repeated_cells,
            "optimal_steps": self.optimal_steps,
            "efficiency": self.efficiency,
        }


def verify_path(
    maze: Maze,
    raw_path: Sequence[Any],
    optimal_steps: int | None = None,
) -> Verification:
    if optimal_steps is None:
        reference = shortest_path(maze)
        optimal_steps = len(reference) - 1 if reference else None
    if not raw_path:
        return Verification(False, "path is empty", [], 0, 0, 0, optimal_steps, None)
    try:
        path = [normalise_coord(item) for item in raw_path]
    except (KeyError, TypeError, ValueError) as exc:
        return Verification(False, f"malformed coordinate: {exc}", [], 0, 0, 0, optimal_steps, None)
    if path[0] != maze.start:
        return Verification(False, f"path starts at {path[0]} instead of {maze.start}", path, 0, 0, 0, optimal_steps, None)
    for index in range(1, len(path)):
        previous, current = path[index - 1], path[index]
        if not maze.in_bounds(*current):
            return Verification(False, f"step {index}: {current} is outside the maze", path[: index + 1], index, len(set(path[: index + 1])), 0, optimal_steps, None)
        if abs(previous[0] - current[0]) + abs(previous[1] - current[1]) != 1:
            return Verification(False, f"step {index}: {previous} -> {current} is not a single-cell move", path[: index + 1], index, len(set(path[: index + 1])), 0, optimal_steps, None)
        direction = direction_between(previous, current)
        if direction is None or not maze.can_move(previous, direction):
            return Verification(False, f"step {index}: a wall blocks {previous} -> {current}", path[: index + 1], index, len(set(path[: index + 1])), 0, optimal_steps, None)
    if path[-1] != maze.goal:
        return Verification(False, f"path ends at {path[-1]} instead of {maze.goal}", path, len(path) - 1, len(set(path)), 0, optimal_steps, None)
    steps = len(path) - 1
    unique_cells = len(set(path))
    repeated = steps + 1 - unique_cells
    efficiency = round(optimal_steps / steps, 3) if steps and optimal_steps else None
    return Verification(True, None, path, steps, unique_cells, repeated, optimal_steps, efficiency)


def solve_maze(maze: Maze) -> list[Coord]:
    return shortest_path(maze)


def heuristic_order(maze: Maze, moves: Sequence[MoveOption]) -> list[MoveOption]:
    return sorted(moves, key=lambda move: (move.distance if move.distance is not None else 10**9, DIRECTIONS.index(move.direction)))
