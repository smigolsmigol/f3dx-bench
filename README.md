# f3dx-bench

The first prod-traffic latency dashboard for LLMs. Artificial Analysis runs synthetic probes from a fixed test bench. lm-arena measures judge-quality. Nothing measures real prod latency on real traffic across providers, hours, regions. f3dx-bench does, by sitting downstream of f3dx and llmkit users who opt in.

The differentiator is structural: AA cannot collect this data without becoming a runtime, and they aren't. llmkit already sits in the request path of every llmkit user, so the data plane lights up on day 1 instead of needing a flywheel from zero.

```bash
# in your f3dx app:
F3DX_BENCH_OPTIN=1 python my_agent.py
# or in your llmkit dashboard, toggle "Contribute to f3dx-bench"
```

Three live charts at https://bench.f3d1.dev (placeholder URL until deploy):
- **latency.md** - p99 / p95 / p50 latency by model + region + hour, last 7 days
- **errors.md** - error-rate by provider + hour, last 7 days
- **cost.md** - cost-per-1k tokens by token bucket, by model

## Architecture

Three components, one repo:

1. **`schemas/`** - canonical TraceBeacon row (12 fields, ~200 bytes wire). NO prompt content, NO response content, NO API keys. install_id is per-install UUID; install_hmac is HMAC-SHA256 over the canonical beacon JSON. k-anonymity bucket suppression at N>=50 on every aggregation that hits the public dashboard.

2. **`worker/`** - Cloudflare Worker (Hono) at the ingest edge. POST `/v1/beacon` with single beacon or NDJSON batch. Validates schema, verifies HMAC against KV-stored install secret, rate-limits per install (60 req/min), appends validated rows to R2 as date-partitioned NDJSON. Daily scheduled job converts NDJSON to Parquet for the dashboard's duckdb-wasm reader.

3. **`evidence-app/`** - Evidence.dev frontend. SQL queries against duckdb-wasm reading the public R2 parquet directly in the browser. Static deploy (Cloudflare Pages or any CDN). No backend. Charts render client-side.

## Privacy contract

Read `docs/privacy.md` for the full policy. Short version:

- Opt-in only (env var, dashboard toggle, or first-run prompt). No silent telemetry.
- 12-field beacon shape only. No prompt content, no response content, no API keys, no headers.
- Install-keyed HMAC blocks synthetic-traffic flooding without requiring registration.
- Aggregations that go to the public dashboard suppress any (model, provider, region, hour) bucket where N < 50.
- Forget request: `POST /v1/forget {install_id, hmac}` removes all rows for that install_id within 24h.

## Layout

```
f3dx-bench/
  schemas/
    trace_beacon.schema.json     JSON Schema for the wire format
    trace_beacon.parquet.md      Parquet column layout for R2
  worker/
    src/worker.ts                CF Worker (Hono): /v1/beacon + /v1/health + /v1/forget
    wrangler.toml                CF deploy config (placeholders for R2 bucket + KV namespace)
    package.json                 deps: hono only; dev: wrangler + biome
    tsconfig.json
  evidence-app/
    pages/{index,latency,errors,cost}.md
    sources/bench/{connection.yaml,beacons.sql}
    package.json
    evidence.settings.json
  docs/
    architecture.md              system diagram + retention policy
    privacy.md                   opt-in mechanics, k-anonymity, forget flow
    hmac-attestation.md          per-install HMAC scheme + reasoning
  .github/
    workflows/{ci,scorecard,security}.yml
    dependabot.yml
  README.md / LICENSE / CODEOWNERS / SECURITY.md / .gitignore
```

## What's missing

- Schema versioning (v1 only; v2 will add streaming-specific timing)
- Beacon batching client SDK (Python + TypeScript, lands in f3dx[bench] + @f3d1/llmkit-sdk)
- Public R2 deploy (Federico holds the wrangler creds)
- Evidence.dev hosted at bench.f3d1.dev (CF Pages step after R2)

## Sibling projects

- [f3dx](https://github.com/smigolsmigol/f3dx) - the runtime that emits beacons
- [llmkit](https://github.com/smigolsmigol/llmkit) - the hosted gateway that emits beacons too
- [f3dx-cache](https://github.com/smigolsmigol/f3dx-cache) - cache hits also emit beacons (zero-cost, but useful for tracking which models get cached most)
- [f3dx-router](https://github.com/smigolsmigol/f3dx-router) - routing decisions emit beacons (which provider won the hedged race)

## License

MIT.
