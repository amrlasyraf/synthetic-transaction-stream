"""Command line interface for the synthetic producer."""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from .generator import Config, Generator


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate entirely synthetic transaction data")
    parser.add_argument("--output", type=Path, default=Path("output"))
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--start-date", type=date.fromisoformat, default=date(2026, 1, 1))
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--users", type=int, default=250)
    parser.add_argument("--merchants", type=int, default=40)
    parser.add_argument("--partners", type=int, default=5)
    parser.add_argument("--transactions-per-day", type=int, default=200)
    parser.add_argument("--no-anomalies", action="store_true")
    args = parser.parse_args()
    config = Config(
        seed=args.seed,
        start_date=args.start_date,
        days=args.days,
        users=args.users,
        merchants=args.merchants,
        partners=args.partners,
        transactions_per_day=args.transactions_per_day,
        anomalies=not args.no_anomalies,
    )
    try:
        generator = Generator(config).generate()
    except ValueError as error:
        parser.error(str(error))
    generator.write(args.output)
    print(json.dumps({
        "output": str(args.output.resolve()),
        "transactions": len(generator.transactions),
        "events": len(generator.events),
        "scenario_transactions": len(generator.labels),
    }))


if __name__ == "__main__":
    main()
