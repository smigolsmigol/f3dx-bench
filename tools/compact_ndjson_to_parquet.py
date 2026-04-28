"""Compact f3dx-bench NDJSON beacons in R2 into date-partitioned parquet.

Reads `beacons/yyyy=*/mm=*/dd=*/hour=*/install_*.ndjson` from the R2 bucket
specified in the f3dx-bench wrangler config, parses each line as a TraceBeacon
row, and writes one parquet file per (yyyy, mm, dd) partition under
`parquet/yyyy=*/mm=*/dd=*/all.parquet` in the same bucket.

Per-day files keep duckdb-wasm queries narrow when the dashboard hits the
public R2 URL; partition pruning by date is the dominant query pattern.

V0 reads ALL ndjson + rewrites every parquet partition that's covered by the
input. V0.1 will track per-day high-watermarks in KV so we only rewrite
the partitions touched since the last run.

Usage:
    export R2_ACCOUNT_ID=...
    export R2_ACCESS_KEY_ID=...
    export R2_SECRET_ACCESS_KEY=...
    python tools/compact_ndjson_to_parquet.py \\
        --bucket f3dx-bench-beacons \\
        --suppress-below 50          # k-anonymity guard: drop rows when
                                     # (model, provider, region, hour) bucket
                                     # has fewer than N samples in the day

Anything fancier (incremental compaction, parallel partitions, distributed
state) waits until volume justifies it.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
from collections import defaultdict
from collections.abc import Iterator
from datetime import datetime, timezone

import boto3
import pyarrow as pa
import pyarrow.parquet as pq
from botocore.config import Config
from dotenv import load_dotenv

# Pick up R2 credentials from tools/.env if present (gitignored). Falls
# through to existing env vars when .env is absent (CI / containers).
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))


# Canonical schema. Mirror of schemas/trace_beacon.parquet.md, kept in sync
# manually until v0.1 introduces a generated artifact. Order matters: pyarrow
# uses field order for column layout.
_SCHEMA = pa.schema([
    pa.field("schema_version", pa.string(), nullable=False),
    pa.field("ts", pa.timestamp("ms", tz="UTC"), nullable=False),
    pa.field("install_id", pa.string(), nullable=False),
    pa.field("model", pa.string(), nullable=False),
    pa.field("provider", pa.string(), nullable=False),
    pa.field("region", pa.string(), nullable=True),
    pa.field("status_code", pa.int32(), nullable=False),
    pa.field("latency_ms_to_first_token", pa.int64(), nullable=True),
    pa.field("latency_ms_total", pa.int64(), nullable=False),
    pa.field("input_tokens", pa.int64(), nullable=False),
    pa.field("output_tokens", pa.int64(), nullable=False),
    pa.field("cost_usd_estimate", pa.float64(), nullable=True),
])


_NDJSON_PREFIX = "beacons/"
_PARQUET_PREFIX = "parquet/"
_PARTITION_RE = re.compile(
    r"^beacons/yyyy=(?P<yyyy>\d{4})/mm=(?P<mm>\d{2})/dd=(?P<dd>\d{2})/hour=(?P<hour>\d{2})/"
)


def s3_client() -> "boto3.client":
    account = os.environ.get("R2_ACCOUNT_ID")
    if not account:
        sys.exit("R2_ACCOUNT_ID env var required")
    access = os.environ.get("R2_ACCESS_KEY_ID")
    secret = os.environ.get("R2_SECRET_ACCESS_KEY")
    if not access or not secret:
        sys.exit("R2_ACCESS_KEY_ID + R2_SECRET_ACCESS_KEY env vars required")
    return boto3.client(
        "s3",
        endpoint_url=f"https://{account}.r2.cloudflarestorage.com",
        aws_access_key_id=access,
        aws_secret_access_key=secret,
        region_name="auto",
        config=Config(signature_version="s3v4"),
    )


def list_ndjson_keys(s3, bucket: str) -> Iterator[str]:
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=_NDJSON_PREFIX):
        for obj in page.get("Contents", []):
            if obj["Key"].endswith(".ndjson"):
                yield obj["Key"]


def parse_ndjson(body: bytes) -> Iterator[dict]:
    for line in body.decode("utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        # Drop install_hmac before going into parquet; it's only used by the
        # Worker for verification at ingest, never queryable from the dashboard.
        row.pop("install_hmac", None)
        yield row


def coerce_row(row: dict) -> dict | None:
    """Return a dict aligned with _SCHEMA, or None if a required field is missing."""
    try:
        ts = datetime.fromisoformat(row["ts"].replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return {
            "schema_version": str(row.get("schema_version", "v1")),
            "ts": ts,
            "install_id": str(row["install_id"]),
            "model": str(row["model"]),
            "provider": str(row["provider"]),
            "region": row.get("region") or None,
            "status_code": int(row["status_code"]),
            "latency_ms_to_first_token": (
                int(row["latency_ms_to_first_token"])
                if row.get("latency_ms_to_first_token") is not None
                else None
            ),
            "latency_ms_total": int(row["latency_ms_total"]),
            "input_tokens": int(row["input_tokens"]),
            "output_tokens": int(row["output_tokens"]),
            "cost_usd_estimate": (
                float(row["cost_usd_estimate"])
                if row.get("cost_usd_estimate") is not None
                else None
            ),
        }
    except (KeyError, ValueError, TypeError):
        return None


def apply_k_anon(rows: list[dict], threshold: int) -> list[dict]:
    """Suppress rows in (model, provider, region, hour) buckets below threshold."""
    if threshold <= 1:
        return rows
    counts: dict[tuple, int] = defaultdict(int)
    for r in rows:
        bucket = (
            r["model"],
            r["provider"],
            r["region"] or "",
            r["ts"].replace(minute=0, second=0, microsecond=0),
        )
        counts[bucket] += 1
    out = []
    for r in rows:
        bucket = (
            r["model"],
            r["provider"],
            r["region"] or "",
            r["ts"].replace(minute=0, second=0, microsecond=0),
        )
        if counts[bucket] >= threshold:
            out.append(r)
    return out


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    p.add_argument("--bucket", required=True, help="R2 bucket name (e.g. f3dx-bench-beacons)")
    p.add_argument(
        "--suppress-below",
        type=int,
        default=1,
        help="k-anonymity threshold; rows in (model,provider,region,hour) buckets "
        "smaller than N are dropped. Default 1 (no suppression).",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Read + parse + count rows, do NOT write parquet to R2.",
    )
    args = p.parse_args()

    s3 = s3_client()

    by_day: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    raw_count = 0
    skipped_count = 0
    for key in list_ndjson_keys(s3, args.bucket):
        m = _PARTITION_RE.match(key)
        if not m:
            continue
        body = s3.get_object(Bucket=args.bucket, Key=key)["Body"].read()
        for row in parse_ndjson(body):
            raw_count += 1
            coerced = coerce_row(row)
            if coerced is None:
                skipped_count += 1
                continue
            day_key = (m["yyyy"], m["mm"], m["dd"])
            by_day[day_key].append(coerced)

    print(f"read {raw_count} ndjson rows ({skipped_count} skipped) across {len(by_day)} day partitions")

    written = 0
    for (yyyy, mm, dd), rows in sorted(by_day.items()):
        rows = apply_k_anon(rows, args.suppress_below)
        if not rows:
            print(f"  yyyy={yyyy}/mm={mm}/dd={dd}: 0 rows after k-anon, skipping")
            continue
        # Build a column-oriented Arrow table from the row dicts
        cols: dict[str, list] = {field.name: [] for field in _SCHEMA}
        for r in rows:
            for field in _SCHEMA:
                cols[field.name].append(r[field.name])
        table = pa.table(cols, schema=_SCHEMA)

        buf = io.BytesIO()
        pq.write_table(table, buf, compression="snappy")
        body = buf.getvalue()

        out_key = f"{_PARQUET_PREFIX}yyyy={yyyy}/mm={mm}/dd={dd}/all.parquet"
        if args.dry_run:
            print(f"  DRY RUN yyyy={yyyy}/mm={mm}/dd={dd}: {len(rows)} rows -> {len(body)} bytes (would write {out_key})")
        else:
            s3.put_object(
                Bucket=args.bucket,
                Key=out_key,
                Body=body,
                ContentType="application/vnd.apache.parquet",
            )
            print(f"  wrote {out_key}: {len(rows)} rows -> {len(body)} bytes")
            written += 1

    if not args.dry_run:
        print(f"\nDONE: wrote {written} parquet partitions to s3://{args.bucket}/{_PARQUET_PREFIX}")

    # Emit a consolidated latest.parquet so the dashboard reads one stable
    # URL regardless of how partitions slice. Cheap at our row counts; if
    # this gets expensive we'll switch the dashboard to a manifest pattern.
    all_rows: list[dict] = []
    for rows in by_day.values():
        all_rows.extend(apply_k_anon(rows, args.suppress_below))
    if not all_rows:
        print("no rows for latest.parquet, skipping")
        return
    cols: dict[str, list] = {field.name: [] for field in _SCHEMA}
    for r in all_rows:
        for field in _SCHEMA:
            cols[field.name].append(r[field.name])
    table = pa.table(cols, schema=_SCHEMA)
    buf = io.BytesIO()
    pq.write_table(table, buf, compression="snappy")
    body = buf.getvalue()
    out_key = f"{_PARQUET_PREFIX}latest.parquet"
    if args.dry_run:
        print(f"DRY RUN latest.parquet: {len(all_rows)} rows -> {len(body)} bytes (would write {out_key})")
    else:
        s3.put_object(
            Bucket=args.bucket,
            Key=out_key,
            Body=body,
            ContentType="application/vnd.apache.parquet",
        )
        print(f"wrote {out_key}: {len(all_rows)} rows -> {len(body)} bytes")


if __name__ == "__main__":
    main()
