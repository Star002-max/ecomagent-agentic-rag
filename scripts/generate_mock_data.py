"""Generate four reproducible, related CSV datasets for EcomAgent V1.

Run from the project root: python -m scripts.generate_mock_data
Only synthetic data is produced. No model, agent, or external service is used.
"""

import argparse
import json
import random
from datetime import date, timedelta
from pathlib import Path
from typing import Dict

import pandas as pd

from scripts.validate_mock_data import validate_tables


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_END_DATE = date(2026, 9, 22)
DAYS = 180
DEFAULT_SEED = 42
CATALOG = [
    ("桌面收纳盒", "家居", 3990),
    ("保温杯", "日用", 6990),
    ("笔记本", "文具", 1990),
    ("手机支架", "数码配件", 2990),
    ("帆布袋", "日用", 3590),
    ("书签套装", "文具", 1290),
    ("鼠标垫", "数码配件", 2490),
    ("文件夹", "文具", 1590),
    ("毛巾", "日用", 2290),
    ("收纳篮", "家居", 4590),
    ("便签纸", "文具", 990),
    ("数据线收纳扣", "数码配件", 1690),
    ("杯垫", "家居", 1890),
    ("旅行洗漱包", "日用", 4990),
    ("阅读灯", "数码配件", 7990),
]


def build_tables(seed: int, end_date: date) -> Dict[str, pd.DataFrame]:
    """Build data in memory; integer cents avoid monetary accumulation errors."""
    sales_rows = []
    inventory_rows = []
    review_rows = []
    product_rows = []
    start_date = end_date - timedelta(days=DAYS - 1)

    for number, (name, category, price_cents) in enumerate(CATALOG, start=1):
        sku = f"SKU{number:03d}"
        rng = random.Random(seed + number)
        sku_sales = []
        sku_ratings = []
        base_sessions = 900 + number * 35
        base_conversion = 0.055 + (number % 4) * 0.005

        for index in range(DAYS):
            day = start_date + timedelta(days=index)
            recent = index >= DAYS - 30
            # A repeating 30-day pattern and small noise create normal variation.
            seasonal = 1 + ((index % 30) - 14.5) * 0.003
            traffic_factor = 0.65 if recent and number == 1 else 1.0
            if recent and number == 4:
                traffic_factor = 1.35
            conversion_factor = 0.60 if recent and number in (2, 5) else 1.0
            sessions = round(
                base_sessions * seasonal * rng.uniform(0.97, 1.03)
                * traffic_factor
            )
            target_conversion = (
                base_conversion * conversion_factor * rng.uniform(0.98, 1.02)
            )
            orders = round(sessions * target_conversion)
            # Some orders contain two units; conversion uses orders, not units.
            extra_units = round(orders * rng.uniform(0.08, 0.12))
            units = orders + extra_units
            row = {
                "date": day.isoformat(), "sku": sku,
                "orders": orders, "units": units,
                "revenue": units * price_cents / 100,
                "sessions": sessions,
                "conversion_rate": round(orders / sessions, 10),
            }
            sku_sales.append(row)
            # Two review events per product/day, not one pre-averaged rating.
            for _ in range(2):
                rating = rng.choice([1, 2, 2, 3] if recent and number == 5
                                    else [4, 4, 5, 5, 5])
                sku_ratings.append(rating)
                review_rows.append({
                    "date": day.isoformat(), "sku": sku, "rating": rating,
                    "review_text": (
                        "使用后发现做工问题，希望改善质量。" if rating <= 2
                        else "体验一般，细节仍有改善空间。" if rating == 3
                        else "与描述一致，日常使用满意。"
                    ),
                })

        # SKU003 receives no replenishment and ends with exactly 50 units.
        # Other SKUs are replenished to a target before that day's shipments.
        target_stock = 1800 + number * 30
        stock = (sum(row["units"] for row in sku_sales) + 50
                 if number == 3 else target_stock)
        for row in sku_sales:
            if number != 3 and stock - row["units"] < 1000:
                stock = target_stock
            stock -= row["units"]
            inventory_rows.append({
                "date": row["date"], "sku": sku, "inventory": stock,
            })

        sales_rows.extend(sku_sales)
        product_rows.append({
            "sku": sku, "product_name": name, "category": category,
            "price": price_cents / 100,
            "rating": round(sum(sku_ratings) / len(sku_ratings), 4),
            "review_count": len(sku_ratings),
        })

    return {
        "products": pd.DataFrame(product_rows),
        "sales": pd.DataFrame(sales_rows),
        "inventory": pd.DataFrame(inventory_rows),
        "reviews": pd.DataFrame(review_rows),
    }


def generate(output_dir: Path, seed: int, end_date: date,
             overwrite: bool = False) -> None:
    """Validate before writing; require explicit consent to replace data files."""
    targets = [output_dir / f"{name}.csv" for name in
               ("products", "sales", "inventory", "reviews")]
    targets.append(output_dir / "dataset_manifest.json")
    if not overwrite and any(path.exists() for path in targets):
        raise FileExistsError("数据文件已存在；确认需要重建后添加 --overwrite。")
    tables = build_tables(seed, end_date)
    validate_tables(tables, end_date)
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, frame in tables.items():
        frame.to_csv(output_dir / f"{name}.csv", index=False, encoding="utf-8")
    manifest = {
        "schema_version": 1, "synthetic": True, "seed": seed,
        "start_date": (end_date - timedelta(days=DAYS - 1)).isoformat(),
        "end_date": end_date.isoformat(), "days": DAYS, "sku_count": 15,
        "recent_days": 30, "currency": "CNY", "pandas_version": pd.__version__,
        "rows": {name: len(frame) for name, frame in tables.items()},
    }
    targets[-1].write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"已生成并通过内存校验：{output_dir.resolve()}")
    for name, frame in tables.items():
        print(f"  {name}.csv: {len(frame)} 行")


def main() -> None:
    """Parse reproducibility settings and generate the dataset."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "data")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--end-date", type=date.fromisoformat,
                        default=DEFAULT_END_DATE)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    try:
        generate(args.output_dir, args.seed, args.end_date, args.overwrite)
    except (ValueError, OSError) as exc:
        parser.exit(1, f"生成失败：{exc}\n")


if __name__ == "__main__":
    main()
