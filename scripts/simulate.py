"""Prints score curves for typical voting patterns, to calibrate K and d (M9).

python scripts/simulate.py --k 0.5 --d 0.95 --cadence weekly --periods 26
"""

import argparse
from collections.abc import Callable, Sequence

from app.domain.scoring import ScoreParams, default_params, simulate, validate
from app.domain.types import Cadence

# Net value per period index for each pattern.
PATTERNS: dict[str, Callable[[int], float]] = {
    "immer top": lambda _: 1.0,
    "meist gut": lambda _: 0.5,
    "gemischt": lambda i: 1.0 if i % 2 else -1.0,
    "top, dann still": lambda i: 1.0 if i < 8 else 0.0,
    "absturz": lambda i: 1.0 if i < 8 else -1.0,
}
SAMPLE_EVERY = 2


def curves(params: ScoreParams, periods: int) -> dict[str, list[float]]:
    return {
        name: simulate(params, [net(i) for i in range(periods)]) for name, net in PATTERNS.items()
    }


def format_table(data: dict[str, list[float]], every: int = SAMPLE_EVERY) -> str:
    periods = len(next(iter(data.values()), []))
    columns = list(range(every - 1, periods, every))
    width = max(len(name) for name in data)
    header = " " * width + "".join(f"{i + 1:>6}" for i in columns)
    rows = [
        f"{name:<{width}}" + "".join(f"{s[i]:6.1f}" for i in columns) for name, s in data.items()
    ]
    return "\n".join([header, *rows])


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cadence", choices=[c.value for c in Cadence], default="weekly")
    parser.add_argument("--k", type=float)
    parser.add_argument("--d", type=float)
    parser.add_argument("--periods", type=int, default=26)
    args = parser.parse_args(argv)

    cadence = Cadence(args.cadence)
    defaults = default_params(cadence)
    params = ScoreParams(
        k=defaults.k if args.k is None else args.k,
        d=defaults.d if args.d is None else args.d,
    )
    invalid = validate(params, cadence)
    if invalid:
        print(f"Warnung: außerhalb der Grenzen: {', '.join(sorted(invalid))}")
    print(f"K = {params.k:.4g}, d = {params.d:.4g}, Takt = {cadence.value}")
    print(format_table(curves(params, args.periods)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
