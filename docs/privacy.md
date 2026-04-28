# Privacy contract

## Opt-in mechanics

The default is OFF. f3dx-bench only collects beacons when the user explicitly turns it on:

- **f3dx Python SDK**: env var `F3DX_BENCH_OPTIN=1` or `f3dx.configure_bench(opt_in=True)`
- **llmkit hosted dashboard**: settings -> "Contribute anonymized telemetry to f3dx-bench" toggle
- **f3dx-cache / f3dx-router**: same env var, both libraries respect it

There is no first-run prompt, no "anonymous statistics" dialog, no implied consent.

## What's collected

Exactly the 12 fields in `schemas/trace_beacon.schema.json`:

- `schema_version`, `ts`, `install_id`, `install_hmac`
- `model`, `provider`, `region` (region only when known)
- `status_code`, `latency_ms_to_first_token` (when streaming), `latency_ms_total`
- `input_tokens`, `output_tokens`, `cost_usd_estimate`

That's it. Wire size ~200 bytes per beacon.

## What's NOT collected

- Prompt content (no `messages`, no system prompt, no user content)
- Response content (no completion text, no tool-call args, no streamed tokens)
- API keys (the Worker never sees your provider creds)
- HTTP headers (no `User-Agent`, no `Authorization`, no `X-Anything`)
- IP address (Worker uses Cloudflare's automatic stripping; the install_id is the only stable identifier)
- Hostnames or any data that could reveal the deploying org

## install_id and HMAC

The install_id is a UUID generated locally on first run, stored in:

- `~/.config/f3dx/install` (Linux)
- `~/Library/Application Support/f3dx/install` (macOS)
- `%APPDATA%\f3dx\install` (Windows)

The install file has read perms 600 and contains `{install_id, secret_key}`. The secret never leaves the machine; the HMAC computed over each beacon does.

The install_id is NOT joinable to your github account, your llmkit tenant, or any other identity. Two installs running on the same laptop produce two distinct install_ids.

## k-anonymity

Every public dashboard query suppresses any (model, provider, region, hour) bucket where N < 50. This is enforced in the SQL `HAVING n >= 50` clauses, which means you cannot derive single-install behavior from the dashboard even if you knew which install_id was yours.

## Data removal (forget request)

POST `/v1/forget` with body `{install_id, install_hmac}`:

```
curl -X POST https://bench-ingest.f3d1.dev/v1/forget \
  -H 'content-type: application/json' \
  -d '{"install_id": "<your-uuid>", "install_hmac": "<hmac>"}'
```

The Worker verifies the HMAC matches the registered secret for that install_id, then queues the install_id for skipping in the next daily compaction. Within 24h all rows from that install are absent from the parquet that the dashboard reads.

Raw NDJSON in R2 has its 90-day lifecycle; we don't expedite that delete because the raw is not publicly readable and stays under the same retention policy as everything else.

## Reproducibility

Every dashboard query is published in `evidence-app/pages/*.md` as plain SQL. Anyone can clone the repo, point at their own f3dx-bench mirror, and re-run.

## Contact

For privacy questions or removal requests outside the API: smigolsmigol@protonmail.com.
