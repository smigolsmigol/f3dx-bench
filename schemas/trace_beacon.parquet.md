# TraceBeacon Parquet column layout

The daily compaction job (CF Worker scheduled cron, lands in v0.0.2) reads NDJSON files from `r2://beacons/yyyy=*/mm=*/dd=*/hour=*/*.ndjson` and emits Parquet files to `r2://parquet/yyyy=*/mm=*/dd=*/`.

Schema:

| Column | Parquet type | Required | Notes |
|--------|--------------|----------|-------|
| `schema_version` | STRING | Yes | Always `v1` for this version |
| `ts` | TIMESTAMP_MILLIS | Yes | UTC, from `ts` ISO 8601 |
| `install_id` | STRING | Yes | UUID, low cardinality per partition |
| `model` | STRING | Yes | Dictionary-encoded |
| `provider` | STRING | Yes | Dictionary-encoded |
| `region` | STRING | No | Dictionary-encoded; null when unknown |
| `status_code` | INT32 | Yes | 100-599 |
| `latency_ms_to_first_token` | INT64 | No | Null for non-streaming |
| `latency_ms_total` | INT64 | Yes | |
| `input_tokens` | INT64 | Yes | |
| `output_tokens` | INT64 | Yes | |
| `cost_usd_estimate` | DOUBLE | No | Null when client doesn't compute it |

Notes:

- `install_hmac` is NOT in parquet. It's only used by the Worker for verification at ingest, then discarded. The dashboard never needs it.
- Compression: SNAPPY. Row group size: 128 MB. Page size: 1 MB.
- Partitioning: yyyy/mm/dd (Hive style) so duckdb can prune by date.
- Dictionary-encoded columns (model, provider, region) typically dominate file size; ~30 distinct providers + ~200 distinct models + ~25 regions means dict overhead is negligible.
- Estimated bytes per row after compression: ~30. At 100M rows/day -> ~3GB/day -> ~1TB/year. R2 storage cost: under $20/year at this scale.
