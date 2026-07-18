from __future__ import annotations

import argparse
import math
import os
import subprocess


def scaled(base: int, scale: float, minimum: int) -> int:
    return max(minimum, round(base * scale))


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate synthetic special-identifier stock data")
    parser.add_argument("--scale", type=float, required=True)
    args = parser.parse_args()
    if not math.isfinite(args.scale) or args.scale <= 0:
        parser.error("--scale must be a finite number greater than zero")

    order_1_count = scaled(150_000, args.scale, 100)
    order_2_count = scaled(1_000_000, args.scale, 1_000)
    stock_count = scaled(1_000_000, args.scale, 1_000)

    sql = rf'''
        SET search_path = "simple_stock_spec_symbols";
        SELECT setseed(0.27182818);

        INSERT INTO "Aufträge_1" (""".Name""$#@&")
        SELECT 'Gruppe ' || g || ' <script>alert("synthetic");</script>'
        FROM generate_series(1, {order_1_count}) AS g;

        INSERT INTO "Aufträge_2" (""".Name""$#@&")
        SELECT 'Artikel ' || g || ' OR 1=1; --'
        FROM generate_series(1, {order_2_count}) AS g;

        INSERT INTO "Stock_$#@.&\n\r_items"
            ("order_items_1_µ", "order_items_2_µ", amount, optcounter,
             "<b>Beschreibung</b>$#@&\n", "Preis<script>alert('XSS');</script>$#@&",
             "Menge\tTab$#@&", "Bewertung漢字$#@&", "Prozentsatz😊$#@&",
             "Kleinster_Wert<style>*{{color:red;}}</style>$#@&",
             "Groesster_Wert!@#$%^&*()_+{{}}[]|\:;'<>,.?/~`""$#@&",
             "Genauigkeit\nNewLine", "Fließkomma\r\nCRLF$#@&",
             "ThisIsAVeryLongFieldNameThatWillBreakTheLayoutIfNotHandledPrope")
        SELECT
            1 + floor(power(random(), 2.2) * {order_1_count})::integer,
            1 + ((g - 1) % {order_2_count}),
            round((power(random(), 1.7) * 500)::numeric, 4),
            floor(random() * 20000)::smallint,
            'Beschreibung ' || g || ' <script>alert("XSS");</script> OR 1=1; --',
            round((random() * 10000)::numeric, 4),
            CASE WHEN g % 31 = 0 THEN 'NaN'::float8
                 WHEN g % 37 = 0 THEN 'Infinity'::float8
                 WHEN g % 41 = 0 THEN '-Infinity'::float8
                 ELSE random() * 1e12 END,
            CASE WHEN g % 29 = 0 THEN 'NaN'::real ELSE (random() * 100)::real END,
            round((random() * 100)::numeric, 2),
            ((g * 97) % 32767)::smallint,
            ((g::bigint * 982451653) % 9223372036854770000)::bigint,
            round((random() * 100)::numeric, 10),
            CASE WHEN g % 43 = 0 THEN 'NaN'::float8 ELSE random() * 1e15 END,
            'Synthetic description ' || g || ' <!-- parser edge case -->'
        FROM generate_series(1, {stock_count}) AS g;
    '''
    subprocess.run(
        [os.environ.get("PG_WORKLOAD_PSQL", "psql"), "-X", "-q", "-v", "ON_ERROR_STOP=1"],
        input=sql,
        text=True,
        check=True,
    )

    print(
        "Generated simple_stock_spec_symbols: "
        f"order_items_1={order_1_count}, order_items_2={order_2_count}, stock_items={stock_count}"
    )


if __name__ == "__main__":
    main()
