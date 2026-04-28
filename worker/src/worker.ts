/**
 * f3dx-bench ingest Worker.
 *
 * Routes:
 *   POST /v1/beacon  - one beacon JSON or NDJSON batch
 *   POST /v1/forget  - remove all rows for an install_id (HMAC-authed)
 *   GET  /v1/health  - 200 ok
 *
 * Validates schema, verifies HMAC against KV (install_id -> secret_key),
 * rate-limits per install (60 req/min via DurableObject token bucket
 * deferred to v0.0.2; this V0 just rejects above 60/min via in-memory
 * map per Worker isolate).
 *
 * Validated rows append to R2 as date-partitioned NDJSON. A separate
 * scheduled cron (in wrangler.toml) does the daily NDJSON -> Parquet
 * compaction.
 */
import { Hono } from "hono";

interface Env {
  BEACONS_R2: R2Bucket;
  INSTALL_KV: KVNamespace;
}

interface TraceBeacon {
  schema_version: "v1";
  ts: string;
  install_id: string;
  install_hmac: string;
  model: string;
  provider: string;
  region?: string;
  status_code: number;
  latency_ms_to_first_token?: number;
  latency_ms_total: number;
  input_tokens: number;
  output_tokens: number;
  cost_usd_estimate?: number;
}

const ALLOWED_PROVIDERS = new Set([
  "openai", "anthropic", "groq", "together", "fireworks",
  "deepseek", "openrouter", "mistral", "xai", "vllm", "llmkit", "other",
]);

const RATE_LIMIT_PER_MIN = 60;
const rateBucket = new Map<string, { count: number; resetAt: number }>();

function shapeError(msg: string): { ok: false; error: string } {
  return { ok: false, error: msg };
}

function validateBeacon(b: unknown): { ok: true; beacon: TraceBeacon } | { ok: false; error: string } {
  if (typeof b !== "object" || b === null) return shapeError("body must be a JSON object");
  const x = b as Record<string, unknown>;
  if (x.schema_version !== "v1") return shapeError("schema_version must be 'v1'");
  if (typeof x.ts !== "string") return shapeError("ts must be string");
  if (typeof x.install_id !== "string" || x.install_id.length < 8) return shapeError("install_id must be a UUID string");
  if (typeof x.install_hmac !== "string" || !/^[0-9a-f]{64}$/.test(x.install_hmac)) {
    return shapeError("install_hmac must be 64 hex chars");
  }
  if (typeof x.model !== "string" || x.model.length === 0) return shapeError("model required");
  if (typeof x.provider !== "string" || !ALLOWED_PROVIDERS.has(x.provider)) return shapeError("provider must be one of the allowed list");
  if (typeof x.status_code !== "number" || x.status_code < 100 || x.status_code > 599) return shapeError("status_code must be 100-599");
  if (typeof x.latency_ms_total !== "number" || x.latency_ms_total < 0) return shapeError("latency_ms_total must be a non-negative number");
  if (typeof x.input_tokens !== "number" || x.input_tokens < 0) return shapeError("input_tokens required");
  if (typeof x.output_tokens !== "number" || x.output_tokens < 0) return shapeError("output_tokens required");
  return { ok: true, beacon: x as unknown as TraceBeacon };
}

async function verifyHmac(env: Env, beacon: TraceBeacon): Promise<boolean> {
  const stored = await env.INSTALL_KV.get(beacon.install_id);
  let secret: string;
  if (stored === null) {
    // First beacon from this install. The install_hmac IS the secret derivation:
    // we accept it on first contact and pin it. Subsequent beacons must match
    // an HMAC computed with this same secret. For V0 we treat the first hmac
    // value itself as the install secret (TOFU). v0.0.2 will replace this with
    // a registration handshake that uses the install_id as key derivation input.
    await env.INSTALL_KV.put(beacon.install_id, beacon.install_hmac, { expirationTtl: 60 * 60 * 24 * 365 });
    return true;
  }
  secret = stored;
  // Recompute HMAC over the beacon canonical form (sorted keys, excluding
  // install_hmac itself) using the stored secret.
  const canonical = canonicalJson({ ...beacon, install_hmac: undefined });
  const enc = new TextEncoder();
  const key = await crypto.subtle.importKey(
    "raw",
    enc.encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const sigBuf = await crypto.subtle.sign("HMAC", key, enc.encode(canonical));
  const sig = Array.from(new Uint8Array(sigBuf), (b) => b.toString(16).padStart(2, "0")).join("");
  return sig === beacon.install_hmac;
}

function canonicalJson(obj: Record<string, unknown>): string {
  const filtered = Object.fromEntries(
    Object.entries(obj).filter(([_, v]) => v !== undefined),
  );
  const keys = Object.keys(filtered).sort();
  const sorted: Record<string, unknown> = {};
  for (const k of keys) sorted[k] = filtered[k];
  return JSON.stringify(sorted);
}

function checkRateLimit(installId: string): boolean {
  const now = Date.now();
  const entry = rateBucket.get(installId);
  if (entry === undefined || entry.resetAt < now) {
    rateBucket.set(installId, { count: 1, resetAt: now + 60_000 });
    return true;
  }
  if (entry.count >= RATE_LIMIT_PER_MIN) return false;
  entry.count += 1;
  return true;
}

function partitionPath(beacon: TraceBeacon): string {
  const ts = new Date(beacon.ts);
  const yyyy = String(ts.getUTCFullYear());
  const mm = String(ts.getUTCMonth() + 1).padStart(2, "0");
  const dd = String(ts.getUTCDate()).padStart(2, "0");
  const hour = String(ts.getUTCHours()).padStart(2, "0");
  const installShort = beacon.install_id.slice(0, 8);
  return `beacons/yyyy=${yyyy}/mm=${mm}/dd=${dd}/hour=${hour}/install_${installShort}.ndjson`;
}

async function appendBeacon(env: Env, beacon: TraceBeacon): Promise<void> {
  const path = partitionPath(beacon);
  const existing = await env.BEACONS_R2.get(path);
  const existingText = existing === null ? "" : await existing.text();
  const newText = existingText + JSON.stringify(beacon) + "\n";
  await env.BEACONS_R2.put(path, newText);
}

const app = new Hono<{ Bindings: Env }>();

app.get("/v1/health", (c) => c.json({ ok: true, service: "f3dx-bench", schema: "v1" }));

app.post("/v1/beacon", async (c) => {
  const ct = c.req.header("content-type") ?? "";
  let beacons: TraceBeacon[];
  if (ct.includes("application/x-ndjson")) {
    const text = await c.req.text();
    const lines = text.split("\n").filter((l) => l.trim().length > 0);
    if (lines.length > 100) return c.json(shapeError("batch too large (max 100)"), 413);
    const parsed: TraceBeacon[] = [];
    for (const line of lines) {
      let obj: unknown;
      try {
        obj = JSON.parse(line);
      } catch {
        return c.json(shapeError(`invalid JSON in batch line: ${line.slice(0, 80)}`), 400);
      }
      const result = validateBeacon(obj);
      if (!result.ok) return c.json(result, 400);
      parsed.push(result.beacon);
    }
    beacons = parsed;
  } else {
    let obj: unknown;
    try {
      obj = await c.req.json();
    } catch {
      return c.json(shapeError("invalid JSON body"), 400);
    }
    const result = validateBeacon(obj);
    if (!result.ok) return c.json(result, 400);
    beacons = [result.beacon];
  }

  for (const b of beacons) {
    if (!checkRateLimit(b.install_id)) return c.json(shapeError("rate limit exceeded for install_id"), 429);
    if (!(await verifyHmac(c.env, b))) return c.json(shapeError("invalid HMAC for install_id"), 401);
    await appendBeacon(c.env, b);
  }
  return c.json({ ok: true, count: beacons.length }, 202);
});

app.post("/v1/forget", async (c) => {
  let body: { install_id?: string; install_hmac?: string };
  try {
    body = await c.req.json();
  } catch {
    return c.json(shapeError("invalid JSON body"), 400);
  }
  if (typeof body.install_id !== "string" || typeof body.install_hmac !== "string") {
    return c.json(shapeError("install_id + install_hmac required"), 400);
  }
  const stored = await c.env.INSTALL_KV.get(body.install_id);
  if (stored === null || stored !== body.install_hmac) {
    return c.json(shapeError("install_id not registered or hmac mismatch"), 401);
  }
  // Forget queued: actual R2 row deletion happens in the scheduled job
  // (we mark the install_id in a forget set; the daily compaction skips it).
  await c.env.INSTALL_KV.put(`forget:${body.install_id}`, "1", { expirationTtl: 60 * 60 * 24 * 30 });
  return c.json({ ok: true, queued: true }, 202);
});

app.notFound((c) => c.json(shapeError("not found"), 404));

export default app;
