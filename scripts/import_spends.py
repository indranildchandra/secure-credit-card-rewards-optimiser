#!/usr/bin/env python3
"""
Import a transactions CSV into the spend tracker — entirely on-device.

    python scripts/import_spends.py --csv statement.csv
    python scripts/import_spends.py --csv statement.csv --user user --dry-run

The CSV needs an amount column and (ideally) a category/merchant column; a
card and a date column are used if present. Aggregated totals are written to the
same ADK user-scoped state the optimiser reads, so caps/milestones update
without manually logging each purchase.

Note: the ADK Web UI keys state by (app_name, user_id). Pass --user/--app to
match the identity your UI uses if the imported data doesn't show up.
"""

import argparse
import asyncio
import os
import sys

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from tools.spend_import import parse_spends_csv, import_rows  # noqa: E402


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="Import a spends CSV on-device.")
    parser.add_argument("--csv", required=True, help="Path to the CSV file.")
    parser.add_argument("--app", default="optimizer", help="ADK app name.")
    parser.add_argument("--user", default="user", help="ADK user id.")
    parser.add_argument(
        "--db",
        default=os.path.join(_ROOT, "db", "optimizer_sessions.db"),
        help="SQLite session DB (defaults to run.sh's db/optimizer_sessions.db).",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Parse and report only; don't write."
    )
    args = parser.parse_args(argv)

    with open(args.csv, encoding="utf-8") as f:
        parsed = parse_spends_csv(f.read())
    rows, skipped = parsed["rows"], parsed["skipped"]
    print(f"Parsed {len(rows)} rows ({skipped} skipped for bad/missing amount).")

    if args.dry_run:
        for r in rows[:10]:
            print("  ", r)
        if len(rows) > 10:
            print(f"   ... and {len(rows) - 10} more")
        return
    if not rows:
        print("Nothing to import.")
        return

    from google.adk.sessions import DatabaseSessionService

    os.makedirs(os.path.dirname(args.db), exist_ok=True)
    svc = DatabaseSessionService(db_url=f"sqlite:///{args.db}")
    summary = asyncio.run(import_rows(svc, args.app, args.user, rows))
    print(
        f"Imported {summary['imported']} transactions "
        f"(Rs.{summary['total_amount']:,.0f}) across months {summary['months']} "
        f"for user '{args.user}'. Restart ./run.sh to see updated caps."
    )


if __name__ == "__main__":
    main()
