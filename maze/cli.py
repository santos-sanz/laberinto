from __future__ import annotations

import argparse
import asyncio
import json

from . import __version__, config
from .game import dead_end_count, generate_maze, junction_count, shortest_path


def cmd_generate(args: argparse.Namespace) -> int:
    maze = generate_maze(args.width, args.height, args.seed)
    path = shortest_path(maze)
    print(f"seed={maze.seed} size={maze.width}x{maze.height} cells={maze.cell_count}")
    if maze.cell_count <= 2601 or args.ascii:
        print(maze.to_ascii())
    else:
        print("(ASCII omitido para laberintos grandes; usa --ascii para imprimirlo)")
    print(f"optimal steps: {len(path) - 1}")
    print(f"dead ends: {dead_end_count(maze)}  junctions: {junction_count(maze)}")
    if args.show_path:
        print("path:", json.dumps([list(cell) for cell in path]))
    return 0


async def _run_race(args: argparse.Namespace) -> int:
    from .models import RaceConfig
    from .race import manager

    config_data = {
        "width": args.width,
        "height": args.height,
        "seed": args.seed,
        "mode": args.mode,
        "text_model": args.text_model,
        "text_max_attempts": args.text_max_attempts,
        "max_junction_calls": args.max_junction_calls,
        "include_baseline": args.include_baseline,
    }
    if args.mode == "decisions":
        config_data["decisions_models"] = [
            model.strip() for model in args.decisions_models.split(",") if model.strip()
        ]
    else:
        config_data["decisions_model"] = args.decisions_model
    RaceConfig.from_dict(config_data)
    race = manager.create(config_data)
    manager.start(race["id"])
    loop = asyncio.get_running_loop()
    deadline = loop.time() + args.timeout
    result = race
    while loop.time() < deadline:
        await asyncio.sleep(0.25)
        current = manager.get(race["id"])
        if current is not None:
            result = current
            if current["status"] in ("done", "error", "cancelled"):
                break
    else:
        manager.cancel(race["id"])
        print(f"race timed out after {args.timeout}s")
        return 1

    gt = result["ground_truth"]
    print(
        f"race {result['id']} seed={result['config']['seed']} "
        f"{result['config']['width']}x{result['config']['height']} optimal={gt['optimal_steps']}"
    )
    for kind, lane in result["lanes"].items():
        solution = lane.get("solution") or {}
        print(
            f"  {kind:9s} {lane['status']:9s} {str(lane.get('elapsed_ms')):>9s} ms  "
            f"calls={lane['calls']} steps={solution.get('steps')} "
            f"efficiency={solution.get('efficiency')} "
            f"tokens={lane['tokens']['total']}"
        )
        if lane.get("error"):
            print(f"            error: {lane['error']}")
    print(f"winner: {result.get('winner') or 'none'}")
    return 0


def cmd_race(args: argparse.Namespace) -> int:
    return asyncio.run(_run_race(args))


def cmd_serve(args: argparse.Namespace) -> int:
    from .server import run

    run(host=args.host, port=args.port, reload=args.reload)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="maze", description="Text vs decisions model race through a perfect maze"
    )
    parser.add_argument("--version", action="version", version=f"maze {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="start the live race control web app")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8050)
    serve.add_argument("--reload", action="store_true")
    serve.set_defaults(func=cmd_serve)

    generate = sub.add_parser("generate", help="print a maze and its optimal solution")
    generate.add_argument("--width", type=int, default=config.DEFAULT_WIDTH)
    generate.add_argument("--height", type=int, default=config.DEFAULT_HEIGHT)
    generate.add_argument("--seed", type=int, default=config.DEFAULT_SEED)
    generate.add_argument("--show-path", action="store_true")
    generate.add_argument("--ascii", action="store_true", help="print the full ASCII maze even when it is huge")
    generate.set_defaults(func=cmd_generate)

    race = sub.add_parser("race", help="run one race headlessly")
    race.add_argument("--width", type=int, default=config.DEFAULT_WIDTH)
    race.add_argument("--height", type=int, default=config.DEFAULT_HEIGHT)
    race.add_argument("--seed", type=int, default=config.DEFAULT_SEED)
    race.add_argument("--mode", choices=["decisions", "versus"], default=config.DEFAULT_MODE)
    race.add_argument("--text-model", default=config.DEFAULT_TEXT_MODEL)
    race.add_argument("--decisions-model", default=config.DEFAULT_DECISIONS_MODEL)
    race.add_argument(
        "--decisions-models",
        default=",".join(config.DEFAULT_DECISION_CONTENDERS),
        help="comma-separated models for decisions mode",
    )
    race.add_argument("--text-max-attempts", type=int, default=config.DEFAULT_TEXT_ATTEMPTS)
    race.add_argument("--max-junction-calls", type=int, default=config.DEFAULT_MAX_JUNCTION_CALLS)
    race.add_argument("--include-baseline", action="store_true")
    race.add_argument("--timeout", type=int, default=600)
    race.set_defaults(func=cmd_race)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
