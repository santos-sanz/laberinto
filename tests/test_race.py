from __future__ import annotations

import asyncio
import json

import pytest

from maze.clients import TextCall
from maze.game import generate_maze, shortest_path
from maze.models import RaceConfig
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


def test_default_config_is_a_255_decisions_duel() -> None:
    config = RaceConfig.from_dict({})
    assert config.width == 255
    assert config.height == 255
    assert config.mode == "decisions"
    assert len(config.decisions_models) == 2
    assert [spec["key"] for spec in config.lane_specs()] == ["decisions_1", "decisions_2"]


def test_decisions_mode_lane_specs() -> None:
    config = RaceConfig.from_dict(
        {
            "mode": "decisions",
            "decisions_models": ["baseten/mammoth-1:free", "baseten/elephant-1:free"],
            "include_baseline": True,
        }
    )
    specs = config.lane_specs()
    assert [spec["key"] for spec in specs] == ["decisions_1", "decisions_2", "baseline"]
    assert specs[0]["label"] == "Decisiones 1"
    assert specs[0]["kind"] == "decisions"
    assert specs[2]["kind"] == "baseline"


@pytest.mark.asyncio
async def test_decisions_duel_races_two_control_lanes(monkeypatch) -> None:
    manager.races.clear()
    race = manager.create(
        {
            "width": 9,
            "height": 9,
            "seed": 42,
            "mode": "decisions",
            "decisions_models": ["harness/heuristic", "harness/heuristic"],
            "max_junction_calls": 20,
        }
    )
    assert list(race["lanes"]) == ["decisions_1", "decisions_2"]
    manager.start(race["id"])
    result = None
    for _ in range(500):
        await asyncio.sleep(0.02)
        result = manager.get(race["id"])
        if result and result["status"] in ("done", "error", "cancelled"):
            break
    assert result is not None
    assert result["status"] == "done"
    assert result["lanes"]["decisions_1"]["status"] == "solved"
    assert result["lanes"]["decisions_2"]["status"] == "solved"
    assert result["winner"] in ("decisions_1", "decisions_2", "tie")
    assert result["summary"]["lanes"]["decisions_1"]["steps"] == 40
    assert result["summary"]["lanes"]["decisions_2"]["steps"] == 40


@pytest.mark.asyncio
async def test_full_race_with_heuristic_decisions(monkeypatch) -> None:
    monkeypatch.setattr("maze.runners.NamClient", FakeNamClient)
    manager.races.clear()
    race = manager.create(
        {
            "width": 9,
            "height": 9,
            "seed": 42,
            "mode": "versus",
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
