---
title: Cost
---

# Cost per 1k tokens by model + token bucket

```sql cost_per_1k
WITH bucketed AS (
  SELECT
    model,
    CASE
      WHEN input_tokens + output_tokens < 100  THEN '0_100'
      WHEN input_tokens + output_tokens < 1000 THEN '100_1k'
      WHEN input_tokens + output_tokens < 10000 THEN '1k_10k'
      ELSE '10k_plus'
    END AS token_bucket,
    cost_usd_estimate,
    input_tokens + output_tokens AS total_tokens
  FROM beacons
  WHERE ts >= NOW() - INTERVAL 7 DAY
    AND cost_usd_estimate > 0
    AND status_code BETWEEN 200 AND 299
)
SELECT
  model,
  token_bucket,
  COUNT(*) AS n,
  ROUND(1000 * AVG(cost_usd_estimate) / NULLIF(AVG(total_tokens), 0), 5) AS avg_cost_per_1k_usd
FROM bucketed
GROUP BY 1, 2
HAVING n >= 50
ORDER BY model, token_bucket;
```

<DataTable data={cost_per_1k} />

## Total spend by provider (last 7d)

```sql provider_spend
SELECT
  provider,
  COUNT(*) AS requests,
  SUM(input_tokens) AS input_tokens,
  SUM(output_tokens) AS output_tokens,
  ROUND(SUM(cost_usd_estimate), 2) AS spend_usd
FROM beacons
WHERE ts >= NOW() - INTERVAL 7 DAY
GROUP BY 1
HAVING requests >= 50
ORDER BY spend_usd DESC;
```

<BarChart data={provider_spend} x="provider" y="spend_usd" />
