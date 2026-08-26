"""Measure pandas reading the full 1.02 GB DLD transactions CSV, two ways.

Run A (naive)   : pd.read_csv(path)            -- everything in RAM, inferred dtypes
Run B (streamed): chunksize + usecols + dtype  -- bounded memory

Both compute the SAME aggregation so the numbers are comparable with the PySpark run:
    group by area_name_en, year, quarter -> count, sum(actual_worth), avg(meter_sale_price)

Usage: python bench_pandas.py <naive|chunked> <csv_path>
"""

import resource
import sys
import time

import pandas as pd

USECOLS = [
    "transaction_id",
    "instance_date",
    "area_name_en",
    "actual_worth",
    "meter_sale_price",
]

DTYPES = {
    "transaction_id": "string",
    "area_name_en": "category",
    "actual_worth": "float64",
    "meter_sale_price": "float64",
}

CHUNK = 100_000


def peak_rss_mb() -> float:
    # Linux reports ru_maxrss in kilobytes
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


def aggregate(df: pd.DataFrame) -> pd.DataFrame:
    df = df[df["actual_worth"].notna() & (df["actual_worth"] > 0)]
    # dd-MM-yyyy, stated explicitly: format="mixed" infers per element, which silently
    # reads an ambiguous 03-04-2019 as month-first. Same format string as the Spark job.
    d = pd.to_datetime(df["instance_date"], errors="coerce", format="%d-%m-%Y")
    df = df.assign(year=d.dt.year, quarter=d.dt.quarter)
    df = df[df["year"].notna()]
    return df.groupby(["area_name_en", "year", "quarter"], observed=True).agg(
        n=("actual_worth", "size"),
        total=("actual_worth", "sum"),
        sum_sqm=("meter_sale_price", "sum"),
        cnt_sqm=("meter_sale_price", "count"),
    )


def run_naive(path: str):
    """Everything at once. No usecols, no dtypes -- object dtype for every text column."""
    t0 = time.perf_counter()
    df = pd.read_csv(path, low_memory=False)
    t_read = time.perf_counter() - t0
    rss_after_read = peak_rss_mb()
    mem_df = df.memory_usage(deep=True).sum() / 1024**2
    print(f"  columns loaded      : {len(df.columns)}")
    print(f"  rows                : {len(df):,}")
    print(f"  read wall time      : {t_read:6.1f} s")
    print(f"  DataFrame in memory : {mem_df:8.1f} MB  (deep)")
    print(f"  peak RSS after read : {rss_after_read:8.1f} MB")

    t1 = time.perf_counter()
    agg = aggregate(df)
    t_agg = time.perf_counter() - t1
    print(f"  aggregate wall time : {t_agg:6.1f} s")
    print(f"  groups              : {len(agg):,}")
    print(f"  TOTAL wall time     : {t_read + t_agg:6.1f} s")
    print(f"  PEAK RSS            : {peak_rss_mb():8.1f} MB")
    return agg


def run_chunked(path: str):
    """Streamed. Only the columns we need, dtypes declared, partial aggregates merged."""
    t0 = time.perf_counter()
    parts = []
    rows = 0
    nchunks = 0
    reader = pd.read_csv(
        path, usecols=USECOLS, dtype=DTYPES, chunksize=CHUNK, low_memory=False
    )
    for chunk in reader:
        nchunks += 1
        rows += len(chunk)
        parts.append(aggregate(chunk))
    combined = (
        pd.concat(parts)
        .groupby(level=[0, 1, 2], observed=True)
        .agg({"n": "sum", "total": "sum", "sum_sqm": "sum", "cnt_sqm": "sum"})
    )
    total = time.perf_counter() - t0
    print(f"  columns loaded      : {len(USECOLS)}  (of 46)")
    print(f"  rows                : {rows:,}")
    print(f"  chunks              : {nchunks}  @ {CHUNK:,}")
    print(f"  TOTAL wall time     : {total:6.1f} s")
    print(f"  groups              : {len(combined):,}")
    print(f"  PEAK RSS            : {peak_rss_mb():8.1f} MB")
    return combined


if __name__ == "__main__":
    mode, path = sys.argv[1], sys.argv[2]
    print(f"=== pandas {pd.__version__} · mode={mode} · {path}")
    agg = run_naive(path) if mode == "naive" else run_chunked(path)
    # checksum so all three runs can be proven to agree
    print(f"  CHECK rows={int(agg['n'].sum()):,} total={agg['total'].sum():.0f}")
