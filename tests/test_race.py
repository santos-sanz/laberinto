from __future__ import annotations

import asyncio
import json

import pytest

from maze.clients import TextCall
from maze.game import generate_maze, shortest_path
from maze.race import manager


class FakeNamClient:
    def __init__(self, *args, **kwargs):
        self.maze = generate_maze(9, 9, 42)

    async def complete(self, model, messages, **kwargs):
        content = json.dumps({"path": [list(cell) for cell in shortest_path(self.maze)]})
        return TextCall(
            model=model,
            content=content,
            reasoning=None,
            latency_ms=4.0,
            prompt_tokens=220,
            completion_tokens=35,
            total_tokens=255,
            cost=0.0,
            raw={"choices": [{"message": {"content": content}}]},
        )


@pytest.mark.asyncio
async def test_full_race_with_heuristic_decisions(monkeypatch) -> None:
    monkeypatch.setattr("maze.runners.NamClient", FakeNamClient)
    manager.races.clear()
    race = manager.create(
        {
            "width": 9,
            "height": 9,
            "seed": 42,
            "decisions_model": "harness/heuristic",
            "text_model": "fake-text",
            "text_max_attempts": 1,
            "max_junction_calls": 40,
            "include_baseline": False,
        }
    )
    manager.start(race["id"])
    result = None
    for _ in range(500):
        await asyncio.sleep(0.02)
        result = manager.get(race["id"])
        if result and result["status"] in ("done", "error", "cancelled"):
            break
    assert result is not None
    assert result["status"] == "done"
    assert result["lanes"]["text"]["status"] == "solved"
    assert result["lanes"]["decisions"]["status"] == "solved"
    assert result["lanes"]["text"]["solution"]["steps"] > 0
    assert result["lanes"]["decisions"]["solution"]["steps"] > 0
    assert result["winner"] in ("text", "decisions", "tie")
    assert result["summary"] is not None
    assert result["ground_truth"]["optimal_steps"] > 0
