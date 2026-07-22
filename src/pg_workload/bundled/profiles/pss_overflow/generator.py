from __future__ import annotations

import argparse
import math
import os
import subprocess


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate scaled pg_stat_statements churn tables")
    parser.add_argument("--scale", type=float, required=True)
    args = parser.parse_args()
    if not math.isfinite(args.scale) or args.scale <= 0:
        parser.error("--scale must be a finite number greater than zero")

    table_count = max(50, round(1_000 * args.scale))
    sql = f"""
        DO $$
        DECLARE
            i integer;
        BEGIN
            FOR i IN 1..{table_count} LOOP
                EXECUTE format(
                    'CREATE TABLE pss_overflow.table_%s (id integer PRIMARY KEY, value text)',
                    i
                );
                EXECUTE format(
                    'INSERT INTO pss_overflow.table_%s (id, value) VALUES (1, ''test'')',
                    i
                );
            END LOOP;
        END
        $$;
        INSERT INTO pss_overflow.profile_config (table_count) VALUES ({table_count});
    """
    subprocess.run(
        [os.environ.get("PG_WORKLOAD_PSQL", "psql"), "-X", "-q", "-v", "ON_ERROR_STOP=1"],
        input=sql,
        text=True,
        check=True,
    )
    print(f"Generated pss_overflow: tables={table_count}")


if __name__ == "__main__":
    main()
