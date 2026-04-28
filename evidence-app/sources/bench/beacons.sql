SELECT
  ts,
  CAST(ts AS DATE) AS date,
  date_trunc('hour', CAST(ts AS TIMESTAMP)) AS hour,
  model,
  provider,
  region,
  status_code,
  latency_ms_to_first_token,
  latency_ms_total,
  input_tokens,
  output_tokens,
  cost_usd_estimate,
  install_id
FROM beacons
WHERE ts >= NOW() - INTERVAL 7 DAY;
