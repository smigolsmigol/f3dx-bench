---
title: Errors
---

# Error rate by provider, hour

```sql err_rate
SELECT
  provider,
  date_trunc('hour', CAST(ts AS TIMESTAMP)) AS hour,
  COUNT(*) AS n,
  SUM(CASE WHEN status_code >= 400 THEN 1 ELSE 0 END)::DOUBLE / COUNT(*) AS error_rate
FROM beacons
WHERE ts >= NOW() - INTERVAL 7 DAY
GROUP BY 1, 2
HAVING n >= 1  -- raised to 50 once real beacon volume lands
ORDER BY hour DESC, provider;
```

<LineChart data={err_rate} x="hour" y="error_rate" series="provider" yAxisTitle="error rate (0-1)" />

## Worst providers (last 24h)

```sql worst_providers
SELECT
  provider,
  COUNT(*) AS n,
  SUM(CASE WHEN status_code >= 400 THEN 1 ELSE 0 END) AS errors,
  ROUND(100.0 * SUM(CASE WHEN status_code >= 400 THEN 1 ELSE 0 END) / COUNT(*), 2) AS error_pct,
  SUM(CASE WHEN status_code = 429 THEN 1 ELSE 0 END) AS rate_limits,
  SUM(CASE WHEN status_code BETWEEN 500 AND 599 THEN 1 ELSE 0 END) AS server_errors
FROM beacons
WHERE ts >= NOW() - INTERVAL 1 DAY
GROUP BY 1
HAVING n >= 1  -- raised to 50 once real beacon volume lands
ORDER BY error_pct DESC;
```

<DataTable data={worst_providers} />
