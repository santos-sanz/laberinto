from __future__ import annotations

import json

import pytest

from maze.clients import DecisionsCall, TextCall
from maze.game import distance_map, generate_maze, shortest_path
from maze.models import RaceConfig, new_lane
from maze.runners import HeuristicPolicy, OpenRouterPolicy, run_decisions_lane, run_text_lane


class FakeNamClient:
    def __init__(self, maze):
        self.maze = maze

    async def complete(self, model, messages, **kwargs):
        content = json.dumps({"path": [list(cell) for cell in shortest_path(self.maze)]})
        return TextCall(
            model=model,
            content=content,
            reasoning=None,
            latency_ms=5.0,
            prompt_tokens=300,
            completion_tokens=40,
            total_tokens=340,
            cost=0.0,
            raw={"choices": [{"message": {"content": content}}]},
        )


class MischievousDecisionsClient:
    """Picks the worst exit once, then plays optimally; the harness must backtrack."""

    def __init__(self, maze):
        self.distances = distance_map(maze)
        self.calls = 0

    async def decide(self, payload, timeout=180.0):
        self.calls += 1
        state = payload["state"]
        options = state["legal_moves"]
        if self.calls == 1:
            chosen = max(options, key=lambda option: self.distances[tuple(option["to"])])
        else:
            chosen = min(options, key=lambda option: self.distances[tuple(option["to"])])
        probabilities = {option["direction"]: 0.02 for option in options}
        probabilities[chosen["direction"]] = 0.95
        answers = {
            "move": {
                "type": "choice",
                "choice": chosen["direction"],
                "probabilities": probabilities,
                "confidence": 0.8,
            }
        }
        return DecisionsCall(
            model=payload["model"],
            answers=answers,
            provider="fake",
            latency_ms=5.0,
            prompt_tokens=700,
            completion_tokens=0,
            total_tokens=700,
            cost=0.0,
            raw={"answers": answers},
        )


class OracleDecisionsClient:
    def __init__(self, maze):
        self.maze = maze
        self.distances = distance_map(maze)
        self.calls = 0

    async def decide(self, payload, timeout=180.0):
        self.calls += 1
        state = payload["state"]
        position = tuple(state["position"])
        options = state["legal_moves"]
        best = min(options, key=lambda option: self.distances[tuple(option["to"])])
        probabilities = {option["direction"]: 0.01 for option in options}
        probabilities[best["direction"]] = 0.97
        answers = {
            "move": {
                "type": "choice",
                "choice": best["direction"],
                "probabilities": probabilities,
                "confidence": 0.9,
            }
        }
        return DecisionsCall(
            model=payload["model"],
            answers=answers,
            provider="fake",
            latency_ms=8.0,
            prompt_tokens=800,
            completion_tokens=0,
            total_tokens=800,
            cost=0.0,
            raw={"answers": answers},
        )


@pytest.mark.asyncio
async def test_text_lane_solves_with_full_path(monkeypatch) -> None:
    maze = generate_maze(9, 9, 42)
    monkeypatch.setattr("maze.runners.NamClient", lambda: FakeNamClient(maze))
    config = RaceConfig.from_dict({"width": 9, "height": 9, "seed": 42, "text_max_attempts": 1})
    lane = new_lane("text", config.text_model, "Nam", maze.start)
    await run_text_lane(config, maze, lane, len(shortest_path(maze)) - 1)
    assert lane["status"] == "solved", lane.get("error") or lane.get("verification")
    assert lane["verification"]["ok"] is True
    assert lane["solution"]["efficiency"] == 1.0
    assert lane["position"] == list(maze.goal)
    assert lane["calls"] == 1


@pytest.mark.asyncio
async def test_decisions_lane_solves_with_oracle_policy() -> None:
    maze = generate_maze(9, 9, 42)
    config = RaceConfig.from_dict(
        {"width": 9, "height": 9, "seed": 42, "decisions_model": "fake/decisions"}
    )
    policy = OpenRouterPolicy("fake/decisions")
    client = OracleDecisionsClient(maze)
    policy.client = client
    lane = new_lane("decisions", config.decisions_model, "OpenRouter", maze.start)
    await run_decisions_lane(config, maze, lane, policy, source="decisions")
    assert lane["status"] == "solved", lane.get("error") or lane.get("verification")
    assert lane["verification"]["ok"] is True
    assert lane["solution"]["efficiency"] == 1.0
    assert lane["calls"] == client.calls
    assert lane["position"] == list(maze.goal)
    assert client.calls > 0


@pytest.mark.asyncio
async def test_decisions_lane_backtracks_out_of_a_wrong_turn() -> None:
    maze = generate_maze(9, 9, 42)
    config = RaceConfig.from_dict(
        {"width": 9, "height": 9, "seed": 42, "decisions_model": "fake/mischief"}
    )
    policy = OpenRouterPolicy("fake/mischief")
    client = MischievousDecisionsClient(maze)
    policy.client = client
    lane = new_lane("decisions", config.decisions_model, "OpenRouter", maze.start)
    await run_decisions_lane(config, maze, lane, policy, source="decisions")
    assert lane["status"] == "solved", lane.get("error") or lane.get("verification")
    assert lane["verification"]["ok"] is True
    assert lane["stats"]["dead_ends_hit"] > 0
    assert lane["stats"]["backtracks"] > 0
    assert client.calls >= 3
    assert lane["solution"]["efficiency"] == 1.0


@pytest.mark.asyncio
async def test_heuristic_baseline_solves_without_calls() -> None:
    maze = generate_maze(9, 9, 42)
    config = RaceConfig.from_dict(
        {"width": 9, "height": 9, "seed": 42, "decisions_model": "harness/heuristic"}
    )
    lane = new_lane("baseline", config.decisions_model, "Harness", maze.start)
    await run_decisions_lane(config, maze, lane, HeuristicPolicy(), source="baseline")
    assert lane["status"] == "solved", lane.get("error") or lane.get("verification")
    assert lane["calls"] == 0
    assert lane["solution"]["efficiency"] == 1.0
