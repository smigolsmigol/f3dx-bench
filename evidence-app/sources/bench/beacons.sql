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
FROM read_parquet('https://pub-13d8fca488d741aa901d2dae08ba80bf.r2.dev/parquet/latest.parquet')
WHERE ts >= NOW() - INTERVAL 30 DAY;
