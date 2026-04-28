# Per-install HMAC attestation

## Why

A public, anonymous, opt-in telemetry endpoint is a flood magnet. If anyone can POST a beacon claiming to be from any install_id, the dashboard becomes a casino: cherry-picked synthetic traffic skews "p99 latency for groq" and the network-effect signal collapses.

We need an attack-resistant control without making users register an account, fill a form, or hold an API key. The HMAC scheme below is the answer.

## How

Each f3dx install does this on first run:

```
install_id  = uuid4()
secret_key  = secrets.token_bytes(32)
write_local({install_id, secret_key}, mode=0o600)
```

Both stay on the user's machine. Forever. There is no upload of `secret_key`.

For every beacon:

```
canonical = json_canonicalize(beacon, exclude="install_hmac")
beacon.install_hmac = hmac_sha256(secret_key, canonical).hex()
POST /v1/beacon  beacon
```

## Worker side

On first beacon for a given `install_id`, the Worker has no record. It does TOFU (trust-on-first-use):

```
stored = KV.get(install_id)
if stored is None:
    KV.put(install_id, beacon.install_hmac)  # accept, pin
    return 202
```

On every subsequent beacon, the Worker recomputes the HMAC the same way the client did, using the pinned secret, and rejects on mismatch:

```
stored = KV.get(install_id)
expected = hmac_sha256(stored, json_canonicalize(beacon, exclude="install_hmac")).hex()
if expected != beacon.install_hmac:
    return 401
```

## Why TOFU is good enough

A flooder who wants to impersonate install_id `X` after `X` has registered must produce a HMAC matching `X`'s pinned secret. The secret never left the legitimate machine. So the flooder can't match.

A flooder who wants to register many fresh install_ids and flood synthetic data is rate-limited per install_id (60 req/min) and bucket-suppressed at the dashboard layer (N>=50 per (model, provider, region, hour)). The flooder needs to stand up many distinct installs running for many real-time hours, against many different (model, provider, region) buckets, just to move one cell on the dashboard. The economics tilt against them.

A flooder who wants to amplify synthetic data through the legitimate install_id of someone else has to compromise that machine first. At that point the HMAC scheme is not the weakest link.

## What this is NOT

This is NOT cryptographic identity. install_id is anonymous and unverified. Anyone with shell access to the install file can rotate the secret and become a "new install" at will. We accept this; the goal is not authentication, it is rate-limited attribution to make flooding expensive.

This is NOT GDPR-grade pseudonymization. The HMAC is one-way but the install_id is stable, so a determined attacker with side-channel data could correlate. The forget endpoint exists for this reason.

## Future work

v0.0.2: replace TOFU with a proper registration handshake (challenge-response, install_id derived from HKDF over the secret_key so the Worker can verify install_id integrity without storing the secret in plaintext).

v0.1: per-tenant aggregated install_ids for llmkit (so llmkit-managed users get one tenant-scoped install_id rather than one per CLI invocation).
