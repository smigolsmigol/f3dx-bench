# Architecture

## System diagram

```
                                      f3d1_user runs an agent
                                                |
              +-------------------+              v
              | f3dx (Python)     |   beacon = build_beacon(request, response)
              | f3dx-cache        |   payload bound: ~200 bytes
              | f3dx-router       |   no prompt content, no response content
              | llmkit (TS SDK)   |   no API keys, no headers
              +-------------------+
                                      |
                                      | HTTPS POST /v1/beacon
                                      | (NDJSON batch up to 100 rows)
                                      v
                                +-----------------+
                                | CF Worker       |
                                |  Hono router    |
                                |  schema validate|
                                |  HMAC verify    |
                                |  rate-limit 60/m|
                                +-----------------+
                                      |
                              ndjson append           install_id -> secret
                                      v                      |
                              +---------------+      +---------------+
                              | R2 bucket     |      | KV namespace  |
                              | beacons/      |      | (TOFU keys +  |
                              |   yyyy=/mm=/  |      |  forget set)  |
                              |   dd=/hour=/  |      +---------------+
                              +---------------+
                                      |
                              daily cron (v0.0.2)
                                      v
                              +---------------+
                              | parquet/      |    public R2 read URL
                              |   yyyy=/mm=/  +-----+
                              |   dd=/        |     |
                              +---------------+     |
                                                    v
                                           +------------------+
                                           | Evidence.dev     |
                                           |  duckdb-wasm     |
                                           |  in browser      |
                                           |  reads parquet   |
                                           +------------------+
                                                    |
                                                    v
                                          bench.f3d1.dev (CDN)
```

## Retention

- **Raw NDJSON**: 90 days in R2 under `beacons/`. After 90 days, lifecycle rule deletes.
- **Compacted Parquet**: 1 year in R2 under `parquet/`. Append-only; old files stay.
- **Aggregated views**: forever. The dashboard queries only aggregates with N>=50 bucket suppression, so individual rows never leak even from cached browser state.
- **Forget request**: install_id is added to a forget set in KV; the daily compaction job skips its rows when writing parquet, so within 24h the install is invisible to the dashboard.

## Schema versioning

`schema_version` is on every beacon. v1 is the only one accepted today. v2 (planned) will add per-token timing for streaming. The Worker rejects unknown versions with 400.

## Why Cloudflare R2 + Workers + Pages

- R2: zero egress fee, so duckdb-wasm in the browser can pull parquet without burning $.
- Workers: edge-distributed ingest, so the latency budget is dominated by the user's own network, not our hop.
- Pages: static deploy of the Evidence.dev build. No backend, no servers, no scaling story.

Total ops cost at 100M beacons/day: under $10/mo (R2 storage + Workers requests + KV reads).
