#!/usr/bin/env python3
"""Preflight for buildPages: did the latest nightly aggregation run cleanly?

sp_run_agg_step records a failed step in agg_pipeline_log and moves on, so a
broken aggregate would otherwise ship as yesterday's numbers with nothing
flagging it. This fails the build when the latest pipeline run has a step that
errored, or when no run started within --max-age-hours.

A run that is still in progress is reported but does not fail: every aggregate
swaps in atomically, so a build reading mid-run sees consistent tables.
"""
import argparse
import os
import sys

import databaseConnector


def _summary(text):
    print(text)
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(text + "\n")


def latest_run():
    conn = databaseConnector.get_connection()
    try:
        cur = conn.cursor()
        databaseConnector.configure_read_session(conn, cur)
        steps = databaseConnector.fetch_latest_agg_run(conn, cur)
        cur.close()
    finally:
        conn.close()
    return steps


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-age-hours", type=float, default=36,
                        help="Fail when the latest run started longer ago than this")
    args = parser.parse_args()

    databaseConnector.init_connection_pool(
        os.environ["DATABASE_HOST"],
        os.environ["DATABASE_USER"],
        os.environ["DATABASE_PASSWORD"],
        os.environ["DATABASE_NAME"],
        os.environ["DATABASE_PORT"],
        pool_size=2,
    )

    steps = latest_run()
    if not steps:
        _summary("Aggregation pipeline has never run (agg_pipeline_log is empty).")
        sys.exit(1)

    age_hours = steps[0]["age_seconds"] / 3600
    # sp_run_agg_step writes '[ok after N attempts]' into error for a retried success
    failed = [s for s in steps if s["error"] and not s["error"].startswith("[ok after")]
    running = [s for s in steps if s["finished_at"] is None]

    if failed:
        _summary(f"Aggregation run from {steps[0]['started_at']} has {len(failed)} failed step(s):")
        for s in failed:
            _summary(f"- `{s['step']}`: {s['error']}")
        sys.exit(1)
    if age_hours > args.max_age_hours:
        _summary(
            f"Latest aggregation run started {age_hours:.1f}h ago "
            f"(limit {args.max_age_hours:g}h). The nightly event is not running."
        )
        sys.exit(1)
    if running:
        _summary(
            f"Aggregation run from {steps[0]['started_at']} is still in progress "
            f"(at `{running[-1]['step']}`). Building against the tables swapped in so far."
        )
    else:
        _summary(
            f"Aggregation run from {steps[0]['started_at']} finished cleanly "
            f"({len(steps)} steps, {age_hours:.1f}h ago)."
        )


if __name__ == "__main__":
    main()
