from __future__ import annotations

import argparse
import math
import os
import subprocess
from datetime import date, timedelta

DAYS_BACK = 30
DAYS_AHEAD = 2


def scaled(base: int, scale: float, minimum: int) -> int:
    return max(minimum, round(base * scale))


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate synthetic partition_aging data")
    parser.add_argument("--scale", type=float, required=True)
    args = parser.parse_args()
    if not math.isfinite(args.scale) or args.scale <= 0:
        parser.error("--scale must be a finite number greater than zero")

    row_count = scaled(200_000, args.scale, 2_000)

    today = date.today()
    partitions = []
    for offset in range(-DAYS_BACK, DAYS_AHEAD + 1):
        day = today + timedelta(days=offset)
        nxt = day + timedelta(days=1)
        partitions.append(
            f"CREATE TABLE partition_aging.events_{day:%Y_%m_%d} "
            "PARTITION OF partition_aging.events "
            f"FOR VALUES FROM ('{day.isoformat()}') TO ('{nxt.isoformat()}');"
        )

    sql = (
        "\n".join(partitions)
        + f"""

        SELECT setseed(0.55083122);

        -- Skewed toward recent days; the 30-day span matches the retention window
        -- exactly and never crosses the oldest partition boundary.
        INSERT INTO partition_aging.events (ts, kind, payload)
        SELECT
            now() - (power(random(), 2) * interval '30 days'),
            (ARRAY['click', 'view', 'purchase', 'signup', 'error'])[1 + floor(random() * 5)::integer],
            'event ' || g || ' session=' || floor(power(random(), 2) * 100000)::integer
        FROM generate_series(1, {row_count}) AS g;
    """
    )
    subprocess.run(
        [os.environ.get("PG_WORKLOAD_PSQL", "psql"), "-X", "-q", "-v", "ON_ERROR_STOP=1"],
        input=sql,
        text=True,
        check=True,
    )

    print(f"Generated partition_aging: partitions={len(partitions)}, events={row_count}")


if __name__ == "__main__":
    main()
