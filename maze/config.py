from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = ROOT / "web"
DATA_DIR = ROOT / "data"
RESULTS_DIR = ROOT / "results"

load_dotenv(ROOT / ".env")


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


NAN_API_KEY = _env("NAN_API_KEY")
NAN_BASE_URL = _env("NAN_BASE_URL", "https://api.nan.builders/v1").rstrip("/")
OPENROUTER_API_KEY = _env("OPENROUTER_API_KEY")
OPENROUTER_BASE_URL = _env("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/")
OPENROUTER_DECISIONS_URL = "https://openrouter.ai/api/alpha/decisions"

MAX_MAZE_SIZE = 255
DEFAULT_WIDTH = MAX_MAZE_SIZE
DEFAULT_HEIGHT = MAX_MAZE_SIZE
DEFAULT_SEED = 42
DEFAULT_MODE = "decisions"
DEFAULT_TEXT_MODEL = "deepseek-v4-flash"
DEFAULT_DECISIONS_MODEL = "baseten/mammoth-1:free"
DEFAULT_DECISION_CONTENDERS = [DEFAULT_DECISIONS_MODEL, "baseten/elephant-1:free"]
DEFAULT_TEXT_ATTEMPTS = 2
DEFAULT_MAX_JUNCTION_CALLS = 12
DEFAULT_MAX_STEPS = 900
TEXT_MAX_TOKENS = 16384
TEXT_MAX_CELLS = 400
MAZE_ASCII_MAX_CELLS = 4225
GROUND_TRUTH_SOLUTION_MAX_CELLS = 10000
PUBLIC_VISITED_LIMIT = 4000
HEURISTIC_MODEL = "harness/heuristic"

NON_CHAT_MARKERS = (
    "whisper",
    "rerank",
    "embedding",
    "embed",
    "tts",
    "image",
    "flux",
    "kokoro",
)


def mask_key(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:5]}…{value[-4:]}"
