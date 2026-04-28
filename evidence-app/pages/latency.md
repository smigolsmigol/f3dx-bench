---
title: Latency
---

# Latency by model, region, hour

```sql latency_pct
SELECT
  model,
  COALESCE(region, 'unknown') AS region,
  date_trunc('hour', CAST(ts AS TIMESTAMP)) AS hour,
  COUNT(*) AS n,
  PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY latency_ms_total) AS p50_ms,
  PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY latency_ms_total) AS p95_ms,
  PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY latency_ms_total) AS p99_ms
FROM beacons
WHERE ts >= NOW() - INTERVAL 7 DAY
  AND status_code BETWEEN 200 AND 299
GROUP BY 1, 2, 3
HAVING n >= 50  -- k-anonymity bucket suppression
ORDER BY hour DESC, model, region;
```

<LineChart data={latency_pct} x="hour" y="p99_ms" series="model" yAxisTitle="p99 latency (ms)" />

## p95 vs p50 by model (last 24h)

```sql model_pct_24h
SELECT
  model,
  COUNT(*) AS n,
  PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY latency_ms_total) AS p50_ms,
  PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY latency_ms_total) AS p95_ms,
  PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY latency_ms_total) AS p99_ms
FROM beacons
WHERE ts >= NOW() - INTERVAL 1 DAY
  AND status_code BETWEEN 200 AND 299
GROUP BY 1
HAVING n >= 50
ORDER BY p99_ms DESC;
```

<DataTable data={model_pct_24h} />
