from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .config import (
    DEFAULT_DECISION_CONTENDERS,
    DEFAULT_DECISIONS_MODEL,
    DEFAULT_HEIGHT,
    DEFAULT_MAX_JUNCTION_CALLS,
    DEFAULT_MODE,
    DEFAULT_SEED,
    DEFAULT_TEXT_ATTEMPTS,
    DEFAULT_TEXT_MODEL,
    DEFAULT_WIDTH,
    HEURISTIC_MODEL,
    MAX_MAZE_SIZE,
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class RaceConfig:
    width: int = DEFAULT_WIDTH
    height: int = DEFAULT_HEIGHT
    seed: int = DEFAULT_SEED
    mode: str = DEFAULT_MODE
    text_model: str = DEFAULT_TEXT_MODEL
    decisions_model: str = DEFAULT_DECISIONS_MODEL
    decisions_models: list[str] = field(default_factory=list)
    text_max_attempts: int = DEFAULT_TEXT_ATTEMPTS
    max_junction_calls: int = DEFAULT_MAX_JUNCTION_CALLS
    include_baseline: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RaceConfig":
        width = int(data.get("width", DEFAULT_WIDTH))
        height = int(data.get("height", DEFAULT_HEIGHT))
        if not (5 <= width <= MAX_MAZE_SIZE and 5 <= height <= MAX_MAZE_SIZE):
            raise ValueError(f"maze dimensions must be between 5 and {MAX_MAZE_SIZE}")
        mode = str(data.get("mode") or DEFAULT_MODE).strip().lower()
        if mode not in ("versus", "decisions"):
            raise ValueError("mode must be 'versus' or 'decisions'")
        attempts = int(data.get("text_max_attempts", DEFAULT_TEXT_ATTEMPTS))
        if not (1 <= attempts <= 5):
            raise ValueError("text_max_attempts must be between 1 and 5")
        budget = int(data.get("max_junction_calls", DEFAULT_MAX_JUNCTION_CALLS))
        if not (0 <= budget <= 500):
            raise ValueError("max_junction_calls must be between 0 and 500")
        decisions_model = str(data.get("decisions_model") or DEFAULT_DECISIONS_MODEL)
        raw_models = data.get("decisions_models")
        if raw_models is None:
            decisions_models = list(DEFAULT_DECISION_CONTENDERS)
        else:
            if not isinstance(raw_models, list):
                raise ValueError("decisions_models must be a list")
            decisions_models = [str(model).strip() for model in raw_models if str(model).strip()]
        if mode == "decisions":
            if not decisions_models:
                decisions_models = list(DEFAULT_DECISION_CONTENDERS)
            if not (2 <= len(decisions_models) <= 4):
                raise ValueError("decisions_models must contain between 2 and 4 models")
        else:
            decisions_models = [decisions_model]
        return cls(
            width=width,
            height=height,
            seed=int(data.get("seed", DEFAULT_SEED)),
            mode=mode,
            text_model=str(data.get("text_model") or DEFAULT_TEXT_MODEL),
            decisions_model=decisions_model,
            decisions_models=decisions_models,
            text_max_attempts=attempts,
            max_junction_calls=budget,
            include_baseline=bool(data.get("include_baseline", False)),
        )

    @property
    def max_steps(self) -> int:
        return self.width * self.height * 4

    def lane_specs(self) -> list[dict[str, Any]]:
        if self.mode == "decisions":
            specs = [
                {
                    "key": f"decisions_{index + 1}",
                    "kind": "decisions",
                    "label": f"Decisiones {index + 1}",
                    "model": model,
                    "provider": decisions_provider(model),
                }
                for index, model in enumerate(self.decisions_models)
            ]
            if self.include_baseline:
                specs.append(
                    {
                        "key": "baseline",
                        "kind": "baseline",
                        "label": "Control",
                        "model": HEURISTIC_MODEL,
                        "provider": "Harness",
                    }
                )
            return specs

        specs = [
            {
                "key": "text",
                "kind": "text",
                "label": "Texto",
                "model": self.text_model,
                "provider": "Nam",
            },
            {
                "key": "decisions",
                "kind": "decisions",
                "label": "Decisiones",
                "model": self.decisions_model,
                "provider": decisions_provider(self.decisions_model),
            },
        ]
        if self.include_baseline and self.decisions_model != HEURISTIC_MODEL:
            specs.append(
                {
                    "key": "baseline",
                    "kind": "baseline",
                    "label": "Control",
                    "model": HEURISTIC_MODEL,
                    "provider": "Harness",
                }
            )
        return specs

    def to_dict(self) -> dict[str, Any]:
        return {
            "width": self.width,
            "height": self.height,
            "seed": self.seed,
            "mode": self.mode,
            "text_model": self.text_model,
            "decisions_model": self.decisions_model,
            "decisions_models": self.decisions_models,
            "text_max_attempts": self.text_max_attempts,
            "max_junction_calls": self.max_junction_calls,
            "include_baseline": self.include_baseline,
        }

def new_lane(
    kind: str,
    model: str,
    provider: str,
    start: tuple[int, int],
    label: str | None = None,
) -> dict[str, Any]:
    return {
        "kind": kind,
        "label": label or kind,
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
            "rate_limited": False,
        },
        "verification": None,
        "solution": None,
    }


def decisions_provider(decisions_model: str) -> str:
    return "Harness" if decisions_model == HEURISTIC_MODEL else "OpenRouter"
