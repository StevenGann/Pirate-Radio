# PiRate Radio — control API runbook

The optional FastAPI control plane (Phase 6, design §15 / D4). It exposes read-only status plus two
write actions (skip, regenerate) over HTTP. It is **off by default** and, when on, binds **loopback
only** and requires a bearer token. The broadcast never depends on it: the API task is
crash-isolated, so an API failure logs and dies while the stations keep transmitting (H-A5).

## Is it even on?

The API runs only if `config.json` has a `control` block with `enabled: true`. With no `control`
block (the default), the daemon runs **no control plane at all** — appropriate for a Pi 3 or a closed
deployment. Confirm at startup:

```
journalctl -u pirate-radio | grep -i 'control'    # a serve line iff the API is enabled
```

## Configuration

```jsonc
"control": {
  "enabled": true,
  "host": "127.0.0.1",        // loopback ONLY by default — never 0.0.0.0 without intent (below)
  "port": 8080,
  "token_env": "PIRATE_API_TOKEN",
  "log_ring_size": 2000        // GET /logs in-memory ring depth (see the caveat at the bottom)
}
```

- **`host` defaults to `127.0.0.1`.** The control plane is reachable only from the Pi itself. To
  administer it remotely, **use an SSH tunnel — do not bind to the LAN.** Binding `0.0.0.0` puts an
  authenticated-but-internet-adjacent socket on an always-on appliance; the safe default is loopback +
  tunnel.

  ```
  # from your workstation: forward local 8080 -> the Pi's loopback 8080
  ssh -N -L 8080:127.0.0.1:8080 pirate@your-pi
  # then hit http://127.0.0.1:8080 locally; nothing is exposed on the Pi's LAN interface
  ```

  If you *must* bind the LAN (`host: 0.0.0.0` or a specific LAN IP), that is an explicit operator
  choice: put a firewall in front of the port and treat the token as the only thing between the LAN
  and a skip/regenerate action.

- **`port` is the daemon's own listener** — it is NOT the systemd unit. No unit edit is needed to
  change it; edit `config.json` and `systemctl restart pirate-radio`. If you firewall the host, open
  this port for the tunnel/LAN path you chose.

## The token (H22 — by name, never by value)

The API authenticates every non-`/health` route with a bearer token. The daemon reads it **by
environment-variable name** (`token_env`); the value never appears in `config.json`, the unit file, or
any log. Put it in the same root-owned `0600` `EnvironmentFile` the unit already loads
(`/etc/pirate-radio/secrets.env`):

```
# generate a strong token and append it (read -s keeps it off your shell history + screen)
sudo sh -c 'printf "PIRATE_API_TOKEN=%s\n" "$(openssl rand -hex 32)" >> /etc/pirate-radio/secrets.env'
sudo chmod 0600 /etc/pirate-radio/secrets.env
sudo systemctl restart pirate-radio        # the daemon reads the var by name at startup
```

If `enabled: true` but the named variable is **unset**, the daemon fails fast at startup with a
`ConfigError` that names the missing variable (never its value) — it will not serve an unauthenticated
control plane.

### Token rotation

The token lives only in the `EnvironmentFile`, so rotation is: rewrite the line, restart, done.

```
sudo sed -i '/^PIRATE_API_TOKEN=/d' /etc/pirate-radio/secrets.env
sudo sh -c 'printf "PIRATE_API_TOKEN=%s\n" "$(openssl rand -hex 32)" >> /etc/pirate-radio/secrets.env'
sudo systemctl restart pirate-radio        # old token invalid the instant the daemon re-reads the file
```

The control plane drops for the ~second of the restart; the **broadcast is unaffected** (the daemon
restarts as a whole, stations resume from their schedules).

## Calling it without leaking the token

Never put the token in a command line (`ps`/shell history leak). Use one of these.

```
# read it into the environment once, then reference it (not echoed to the screen)
read -rs PIRATE_API_TOKEN          # paste the token; it is not displayed
export PIRATE_API_TOKEN
curl -s -H "Authorization: Bearer ${PIRATE_API_TOKEN}" http://127.0.0.1:8080/stations
```

```
# OR a curl config file (-K) so the header never hits the process list / history
umask 077; printf 'header = "Authorization: Bearer %s"\n' "$TOKEN" > ~/.pirate-curl
curl -s -K ~/.pirate-curl http://127.0.0.1:8080/stations
```

## Endpoints

All responses use the `{success, data, error}` envelope. `/health` is open; everything else needs the
bearer token (401 without it). Unknown station → 404; unknown/absent schedule date → 404.

| Method & path | Auth | Purpose |
|---|---|---|
| `GET /health` | open | Liveness probe; data-free `{success:true}`. |
| `GET /stations` | token | All stations + current state (config order). |
| `GET /stations/{name}/now` | token | Now-playing (item kind/block/offset/title/artist/next/gap). |
| `GET /stations/{name}/schedule?date=YYYY-MM-DD` | token | A day's schedule (defaults to today). |
| `POST /stations/{name}/regenerate` | token | **202** — force-rebuild the station's schedule on disk. |
| `POST /stations/{name}/skip` | token | **202** — drop the **next** segment at the upcoming boundary. |
| `GET /logs?station=&level=&since=&limit=` | token | Recent log records from the in-memory ring. |

### Skip is skip-at-next-boundary — NOT a mid-segment cut

`POST .../skip` sets a one-shot flag the player checks at the **top of its loop**, so it drops the
**next** buffered segment, not the one currently on the air. The airing segment always finishes (the
sink writes the whole buffer on its own thread; a mid-segment cut is not possible without surgery).
Expect the change at the next segment boundary, not instantly. 202 = accepted, not "already skipped".

### Regenerate is lock-serialized and effective at the next roll

`POST .../regenerate` rebuilds the on-disk schedule under the station's regen lock — the **same lock
the midnight day-roll holds** — so the two can never race. It returns **202** and writes to disk; the
**running player does not hot-swap** to the new schedule. The new schedule takes effect at the next
midnight day-roll or a `systemctl restart`. (Same semantics as the `--regenerate` CLI oneshot, just
triggered over HTTP against the live daemon.)

## The `/logs` ring — a known, ratified limitation (R8′ deviation)

`GET /logs` is served from a **bounded in-memory ring buffer** (`log_ring_size` records, default
2000), NOT from journald or a database. Consequences, by design for v1:

- **Lossy across restarts:** the ring is empty after every daemon restart — it holds only what the
  *current* process has logged since it started.
- **Shallow:** only the last `log_ring_size` records survive; older ones are overwritten.
- Secrets are scrubbed on the way in (Bearer/`sk-`/api-key/Basic/URL-userinfo/etc.), same as journald.

**journald remains the source of truth** for anything historical or forensic:

```
journalctl -u pirate-radio              # the durable, complete operator log
journalctl -u pirate-radio | grep -E 'backstop fired|render-poison'
```

Use `/logs` for a quick "what is this running process doing right now" over the tunnel; use
`journalctl` for "what happened last night / across the restart".
