from __future__ import annotations

import json

from maze.game import generate_maze, shortest_path
from maze.prompts import build_text_messages, parse_path_response


def test_text_prompt_contains_adjacency_and_json_contract() -> None:
    maze = generate_maze(7, 7, 11)
    messages = build_text_messages(maze)
    user = messages[1]["content"]
    assert "0,0:" in user
    assert '"path"' in user
    assert f"Start: {list(maze.start)}" in user
    assert f"Goal: {list(maze.goal)}" in user
    assert "This adjacency list is authoritative" in user


def test_parse_optimal_path() -> None:
    maze = generate_maze(7, 7, 11)
    path = shortest_path(maze)
    content = json.dumps({"path": [list(cell) for cell in path]})
    parsed = parse_path_response(content, maze)
    assert parsed.error is None
    assert parsed.path == path


def test_parse_fenced_json_and_moves() -> None:
    maze = generate_maze(7, 7, 11)
    fenced = "```json\n" + json.dumps({"path": [list(cell) for cell in shortest_path(maze)]}) + "\n```"
    assert parse_path_response(fenced, maze).path == shortest_path(maze)

    moves = "east south east".split()
    parsed = parse_path_response(json.dumps({"moves": moves}), maze)
    assert parsed.path is not None
    assert parsed.path[0] == maze.start
    assert len(parsed.path) == len(moves) + 1


def test_parse_rejects_garbage() -> None:
    maze = generate_maze(6, 6, 1)
    assert parse_path_response("not json", maze).error
    assert parse_path_response(json.dumps({"path": "nope"}), maze).error
    assert parse_path_response(json.dumps({"path": []}), maze).error
    assert parse_path_response(json.dumps({"path": [["x", 1]]}), maze).error
