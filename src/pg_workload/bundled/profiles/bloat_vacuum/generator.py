from __future__ import annotations

import argparse
import math
import os
import subprocess


def scaled(base: int, scale: float, minimum: int) -> int:
    return max(minimum, round(base * scale))


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate synthetic bloat_vacuum data")
    parser.add_argument("--scale", type=float, required=True)
    args = parser.parse_args()
    if not math.isfinite(args.scale) or args.scale <= 0:
        parser.error("--scale must be a finite number greater than zero")

    account_count = scaled(100_000, args.scale, 1_000)

    sql = f"""
        SELECT setseed(0.90731255);

        INSERT INTO bloat_vacuum.accounts (owner_name, balance, status, updated_at, filler)
        SELECT
            'account owner ' || g,
            round((power(random(), 1.7) * 50000)::numeric, 2),
            (ARRAY['active', 'active', 'active', 'suspended', 'closed'])[1 + floor(random() * 5)::integer],
            now() - (random() * interval '30 days'),
            md5(g::text) || repeat('x', 40)
        FROM generate_series(1, {account_count}) AS g;

        -- Pre-bloat: one non-HOT update round over a tenth of the table, so the
        -- first report already shows dead tuples.
        UPDATE bloat_vacuum.accounts
        SET balance = balance + 1,
            updated_at = clock_timestamp(),
            filler = md5(random()::text) || repeat('x', 40)
        WHERE id % 10 = 0;

        ANALYZE bloat_vacuum.accounts;
    """
    subprocess.run(
        [os.environ.get("PG_WORKLOAD_PSQL", "psql"), "-X", "-q", "-v", "ON_ERROR_STOP=1"],
        input=sql,
        text=True,
        check=True,
    )

    print(f"Generated bloat_vacuum: accounts={account_count}")


if __name__ == "__main__":
    main()
