from __future__ import annotations

import argparse
import math
import os
import subprocess


def scaled(base: int, scale: float, minimum: int) -> int:
    return max(minimum, round(base * scale))


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate synthetic jsonb_docs data")
    parser.add_argument("--scale", type=float, required=True)
    args = parser.parse_args()
    if not math.isfinite(args.scale) or args.scale <= 0:
        parser.error("--scale must be a finite number greater than zero")

    doc_count = scaled(50_000, args.scale, 1_000)

    sql = f"""
        SELECT setseed(0.73051984);

        INSERT INTO jsonb_docs.documents (doc_type, doc, created_at)
        SELECT
            (ARRAY['order', 'invoice', 'ticket', 'profile'])[1 + floor(random() * 4)::integer],
            jsonb_build_object(
                'status', (ARRAY['new', 'open', 'closed'])[1 + floor(random() * 3)::integer],
                'customer_id', 1 + floor(power(random(), 2) * 10000)::integer,
                'amount', round((power(random(), 1.5) * 1000)::numeric, 2),
                'priority', floor(random() * 5)::integer,
                'tags', (
                    SELECT jsonb_agg('tag-' || t)
                    FROM (SELECT DISTINCT floor(random() * 50)::integer AS t
                          FROM generate_series(1, 1 + floor(random() * 4)::integer)) AS s
                ),
                'comment', 'Synthetic document ' || g
            ),
            now() - (random() * interval '7 days')
        FROM generate_series(1, {doc_count}) AS g;

        ANALYZE jsonb_docs.documents;
    """
    subprocess.run(
        [os.environ.get("PG_WORKLOAD_PSQL", "psql"), "-X", "-q", "-v", "ON_ERROR_STOP=1"],
        input=sql,
        text=True,
        check=True,
    )

    print(f"Generated jsonb_docs: documents={doc_count}")


if __name__ == "__main__":
    main()
