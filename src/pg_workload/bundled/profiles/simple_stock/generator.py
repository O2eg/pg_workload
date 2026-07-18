from __future__ import annotations

import argparse
import math
import os
import subprocess


def scaled(base: int, scale: float, minimum: int) -> int:
    return max(minimum, round(base * scale))


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate synthetic simple_stock data")
    parser.add_argument("--scale", type=float, required=True)
    args = parser.parse_args()
    if not math.isfinite(args.scale) or args.scale <= 0:
        parser.error("--scale must be a finite number greater than zero")

    order_1_count = scaled(150_000, args.scale, 100)
    order_2_count = scaled(1_000_000, args.scale, 1_000)
    stock_count = scaled(1_000_000, args.scale, 1_000)

    sql = f"""
        SELECT setseed(0.31051984);

        INSERT INTO simple_stock.order_items_1 (name)
        SELECT 'Product group ' || g
        FROM generate_series(1, {order_1_count}) AS g;

        INSERT INTO simple_stock.order_items_2 (name)
        SELECT 'SKU ' || g
        FROM generate_series(1, {order_2_count}) AS g;

        INSERT INTO simple_stock.stock_items
            (order_items_1_id, order_items_2_id, amount, optcounter, descr)
        SELECT
            1 + floor(power(random(), 2.2) * {order_1_count})::integer,
            1 + ((g - 1) % {order_2_count}),
            round((power(random(), 1.7) * 500)::numeric, 4),
            floor(random() * 20000)::smallint,
            CASE
                WHEN g % 20 = 0 THEN NULL
                ELSE 'Synthetic stock item ' || g || ' distribution=' || (g % 97)
            END
        FROM generate_series(1, {stock_count}) AS g;
    """
    subprocess.run(
        [os.environ.get("PG_WORKLOAD_PSQL", "psql"), "-X", "-q", "-v", "ON_ERROR_STOP=1"],
        input=sql,
        text=True,
        check=True,
    )

    print(
        "Generated simple_stock: "
        f"order_items_1={order_1_count}, order_items_2={order_2_count}, stock_items={stock_count}"
    )


if __name__ == "__main__":
    main()
