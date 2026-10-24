from __future__ import annotations

from collections import deque

from maze.game import (
    DELTAS,
    OPPOSITE,
    WALL_BITS,
    generate_maze,
    moves_to_path,
    shortest_path,
    verify_path,
)


def test_maze_is_deterministic_and_connected() -> None:
    maze = generate_maze(9, 9, 123)
    again = generate_maze(9, 9, 123)
    assert maze == again

    seen = {maze.start}
    queue = deque([maze.start])
    while queue:
        current = queue.popleft()
        for direction in maze.open_directions(current):
            nxt = maze.neighbor(current, direction)
            if nxt not in seen:
                seen.add(nxt)
                queue.append(nxt)
    assert seen == set(maze.all_cells())


def test_walls_are_symmetric() -> None:
    maze = generate_maze(8, 11, 5)
    for x, y in maze.all_cells():
        for direction, (dx, dy) in DELTAS.items():
            nx, ny = x + dx, y + dy
            if not maze.in_bounds(nx, ny):
                continue
            assert maze.has_wall(x, y, direction) == maze.has_wall(nx, ny, OPPOSITE[direction])
            assert maze.walls[maze.index((x, y))] & WALL_BITS[direction] == (
                WALL_BITS[direction] if maze.has_wall(x, y, direction) else 0
            )


def test_shortest_path_is_valid_and_optimal_length() -> None:
    maze = generate_maze(13, 13, 42)
    path = shortest_path(maze)
    assert path[0] == maze.start
    assert path[-1] == maze.goal
    verification = verify_path(maze, path)
    assert verification.ok, verification.error
    assert verification.steps == len(path) - 1
    assert verification.efficiency == 1.0
    assert verification.unique_cells == len(path)


def test_verify_rejects_wall_crossing() -> None:
    maze = generate_maze(7, 7, 3)
    blocked = None
    for x, y in maze.all_cells():
        for direction, (dx, dy) in DELTAS.items():
            if maze.has_wall(x, y, direction) and maze.in_bounds(x + dx, y + dy):
                blocked = [(x, y), (x + dx, y + dy)]
                break
        if blocked:
            break
    assert blocked is not None
    verification = verify_path(maze, blocked)
    assert not verification.ok
    assert "wall" in (verification.error or "")


def test_verify_rejects_bad_start_goal_and_jump() -> None:
    maze = generate_maze(6, 6, 9)
    assert not verify_path(maze, [[1, 1], list(maze.goal)]).ok
    assert not verify_path(maze, [[0, 0], [0, 0]]).ok
    assert not verify_path(maze, [[0, 0]]).ok
    assert not verify_path(maze, [[0, 0], [5, 5]]).ok


def test_moves_to_path_supports_words_and_symbols() -> None:
    start = (2, 3)
    assert moves_to_path(start, ["east", "s", "left", "up"]) == [
        (2, 3),
        (3, 3),
        (3, 4),
        (2, 4),
        (2, 3),
    ]
