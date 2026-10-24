from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .config import (
    DEFAULT_DECISIONS_MODEL,
    DEFAULT_HEIGHT,
    DEFAULT_MAX_JUNCTION_CALLS,
    DEFAULT_SEED,
    DEFAULT_TEXT_ATTEMPTS,
    DEFAULT_TEXT_MODEL,
    DEFAULT_WIDTH,
    HEURISTIC_MODEL,
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class RaceConfig:
    width: int = DEFAULT_WIDTH
    height: int = DEFAULT_HEIGHT
    seed: int = DEFAULT_SEED
    text_model: str = DEFAULT_TEXT_MODEL
    decisions_model: str = DEFAULT_DECISIONS_MODEL
    text_max_attempts: int = DEFAULT_TEXT_ATTEMPTS
    max_junction_calls: int = DEFAULT_MAX_JUNCTION_CALLS
    include_baseline: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RaceConfig":
        width = int(data.get("width", DEFAULT_WIDTH))
        height = int(data.get("height", DEFAULT_HEIGHT))
        if not (5 <= width <= 31 and 5 <= height <= 31):
            raise ValueError("maze dimensions must be between 5 and 31")
        attempts = int(data.get("text_max_attempts", DEFAULT_TEXT_ATTEMPTS))
        if not (1 <= attempts <= 5):
            raise ValueError("text_max_attempts must be between 1 and 5")
        budget = int(data.get("max_junction_calls", DEFAULT_MAX_JUNCTION_CALLS))
        if not (0 <= budget <= 500):
            raise ValueError("max_junction_calls must be between 0 and 500")
        return cls(
            width=width,
            height=height,
            seed=int(data.get("seed", DEFAULT_SEED)),
            text_model=str(data.get("text_model") or DEFAULT_TEXT_MODEL),
            decisions_model=str(data.get("decisions_model") or DEFAULT_DECISIONS_MODEL),
            text_max_attempts=attempts,
            max_junction_calls=budget,
            include_baseline=bool(data.get("include_baseline", False)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "width": self.width,
            "height": self.height,
            "seed": self.seed,
            "text_model": self.text_model,
            "decisions_model": self.decisions_model,
            "text_max_attempts": self.text_max_attempts,
            "max_junction_calls": self.max_junction_calls,
            "include_baseline": self.include_baseline,
        }

    @property
    def max_steps(self) -> int:
        return self.width * self.height * 4


def new_lane(kind: str, model: str, provider: str, start: tuple[int, int]) -> dict[str, Any]:
    return {
        "kind": kind,
        "model": model,
        "provider": provider,
        "status": "waiting",
        "started_at": None,
        "finished_at": None,
        "elapsed_ms": None,
        "calls": 0,
        "tokens": {"prompt": 0, "completion": 0, "total": 0},
        "cost": 0.0,
        "error": None,
        "attempts": [],
        "trace": [],
        "raw": [],
        "position": list(start),
        "path": [list(start)],
        "trail": [list(start)],
        "visited": [list(start)],
        "stats": {
            "steps": 0,
            "backtracks": 0,
            "junctions": 0,
            "dead_ends_hit": 0,
            "unique_cells": 1,
            "optimal_steps": None,
            "path_length": None,
            "efficiency": None,
        },
        "verification": None,
        "solution": None,
    }


def decisions_provider(decisions_model: str) -> str:
    return "Harness" if decisions_model == HEURISTIC_MODEL else "OpenRouter"
