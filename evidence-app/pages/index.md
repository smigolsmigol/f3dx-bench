---
title: f3dx-bench
---

# Real-prod-traffic LLM benchmark

Real prod traffic from f3dx + llmkit users who opt in. Last 7 days. Updated continuously.

```sql metrics
SELECT
  COUNT(*) AS beacons_24h,
  COUNT(DISTINCT install_id) AS active_installs,
  ROUND(AVG(latency_ms_total), 0) AS avg_latency_ms,
  ROUND(SUM(cost_usd_estimate), 2) AS spend_usd
FROM beacons
WHERE ts >= NOW() - INTERVAL 1 DAY;
```

<BigValue data={metrics} value="beacons_24h" title="Beacons (24h)" />
<BigValue data={metrics} value="active_installs" title="Active installs" />
<BigValue data={metrics} value="avg_latency_ms" title="Avg latency (ms)" />
<BigValue data={metrics} value="spend_usd" title="Total spend USD (24h)" />

## Detail pages

- [Latency](/latency) p99 / p95 / p50 by model + region + hour
- [Errors](/errors) error rate by provider + hour
- [Cost](/cost) cost per 1k tokens by model + token bucket

## What this is

Public dashboard of real LLM-request latency, error, and cost telemetry. Anonymized at the source. Read more:

- [Architecture](https://github.com/smigolsmigol/f3dx-bench/blob/main/docs/architecture.md)
- [Privacy contract](https://github.com/smigolsmigol/f3dx-bench/blob/main/docs/privacy.md)
- [HMAC attestation scheme](https://github.com/smigolsmigol/f3dx-bench/blob/main/docs/hmac-attestation.md)
