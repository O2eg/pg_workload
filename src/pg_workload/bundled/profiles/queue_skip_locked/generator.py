from __future__ import annotations

import argparse
import math
import os
import subprocess


def scaled(base: int, scale: float, minimum: int) -> int:
    return max(minimum, round(base * scale))


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate synthetic queue_skip_locked data")
    parser.add_argument("--scale", type=float, required=True)
    args = parser.parse_args()
    if not math.isfinite(args.scale) or args.scale <= 0:
        parser.error("--scale must be a finite number greater than zero")

    pending_count = scaled(20_000, args.scale, 500)
    done_count = scaled(5_000, args.scale, 100)

    sql = f"""
        SELECT setseed(0.41202610);

        INSERT INTO queue_skip_locked.tasks (payload, status, priority, created_at)
        SELECT
            'seed task ' || g,
            'pending',
            floor(power(random(), 2) * 10)::integer,
            now() - (random() * interval '1 hour')
        FROM generate_series(1, {pending_count}) AS g;

        INSERT INTO queue_skip_locked.tasks
            (payload, status, priority, created_at, started_at, finished_at, attempts)
        SELECT
            'history task ' || g,
            'done',
            floor(power(random(), 2) * 10)::integer,
            now() - ((1 + random() * 23) * interval '1 hour'),
            now() - ((1 + random() * 23) * interval '1 hour') + interval '1 minute',
            now() - ((1 + random() * 23) * interval '1 hour') + interval '2 minutes',
            1
        FROM generate_series(1, {done_count}) AS g;

        ANALYZE queue_skip_locked.tasks;
    """
    subprocess.run(
        [os.environ.get("PG_WORKLOAD_PSQL", "psql"), "-X", "-q", "-v", "ON_ERROR_STOP=1"],
        input=sql,
        text=True,
        check=True,
    )

    print(f"Generated queue_skip_locked: pending={pending_count}, done={done_count}")


if __name__ == "__main__":
    main()
