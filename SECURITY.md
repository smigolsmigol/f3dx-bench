# Security policy

## Reporting a vulnerability

Email: smigolsmigol@protonmail.com

Acknowledgment SLA: 48 hours.
Critical-fix SLA: 7 days.

## Supported versions

| Version | Supported |
|---------|-----------|
| latest  | Yes       |

## Architecture surface

f3dx-bench is a public-internet ingest endpoint. The threat model:

- The Worker is publicly callable. Controls: rate-limit per install_id (60/min), HMAC verification per beacon, schema validation, payload size cap, per-install KV write-once TOFU.
- The R2 bucket is publicly READ-able for the parquet path so duckdb-wasm in the dashboard can query directly with zero egress fee. NDJSON path is internal.
- No prompt content, no response content, no API keys, no headers ever flow to the Worker. See `docs/privacy.md` for the full data contract.
- HMAC scheme documented at `docs/hmac-attestation.md` including TOFU caveat.

## Out of scope

- The local install file (`~/.config/f3dx/install`) is the user's responsibility. We document its read-perm 600 expectation and sensible storage path, but compromise of the local machine compromises the install_id and we don't claim otherwise.
- The Evidence.dev dashboard is static + browser-rendered. There is no auth surface to attack server-side.

## Scope

In scope: the Worker code in `worker/`, the schema validation, the HMAC scheme. Anything that lets an attacker insert false beacons, exfiltrate other installs' data, or break the public dashboard.

Out of scope: Cloudflare's R2/Workers/KV implementation, third-party deps in the dashboard build, browser bugs in duckdb-wasm.
