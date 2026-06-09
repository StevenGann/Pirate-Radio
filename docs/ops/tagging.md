# Offline tagging runbook — `python -m pirate_radio.tagging`

A standalone, **offline** batch tool that enriches a station library's tags (title/artist/album/year)
so the catalog scanner and the DJ patter read clean metadata. Run it **ahead of time**, never during a
live broadcast. It uses Chromaprint (`fpcalc`) for fingerprints, AcoustID for lookup, and MusicBrainz
for metadata. No new Python packages are needed — only the `fpcalc` binary.

## 0. When to run it

- **Not during broadcast.** Fingerprinting is CPU-heavy; the tool drops itself to a low CPU/IO
  priority (`nice`/`ionice`), but on a 4-core Pi a large run still competes with the live stations.
  Tag when the daemon is stopped, or on another machine, or accept the de-prioritised contention.
- **Expect it to be slow.** `fpcalc` decodes ~120 s of each file; a 10k-file library is roughly
  **1–4 hours** of CPU just for fingerprinting (plus the ≤1 req/s MusicBrainz lookups for the files
  that need them). It is resumable — re-running skips files that already have BOTH title and artist.
- **A 1–4 h all-core decode run heats the Pi** — make sure active cooling is fitted (a passively
  cooled Pi will thermal-throttle and run even slower).
- **Each tagged file is rewritten in full.** The atomic write copies the whole file to a temp, writes
  the tags, then renames — so a tagged file costs ~2× its size in writes. That is why you run against
  the content drive, not the boot SD (below), and why `--dry-run`/`--limit` trials are cheap (no copy).
- **Partial tags re-fetch.** A file that ends up with a title but no artist does NOT pass the
  skip-gate, so a later run re-fingerprints it and re-queries the APIs (rate-limited). Fully-tagged
  files are skipped cheaply; expect repeat work only for the partially-matched stragglers.

## 1. Prerequisites

```
sudo apt install libchromaprint-tools   # provides `fpcalc`
fpcalc -version                          # verify
```

Get a free **AcoustID application API key** at <https://acoustid.org/new-application>, then set it as
an env var **without leaving it in your shell history**:

```
read -s -p "AcoustID key: " ACOUSTID_API_KEY && export ACOUSTID_API_KEY   # -s = no echo
```

(or put it in a root-owned `0600` env file you `source`). The tool reads the key **by env-var name**;
the value is never logged (it is scrubbed from any error, including the `?client=` URL).

## 2. Dry-run first (writes nothing)

Always preview before touching files. `--dry-run` logs the exact tag changes it *would* make:

```
python -m pirate_radio.tagging \
    --content-dir /srv/pirate/station1 \
    --user-agent "PiRate/1.0 ( you@example.com )" \
    --dry-run --limit 20
```

- `--user-agent` is **required** and must include contact info (MusicBrainz policy; a bad UA gets the
  IP throttled/banned).
- `--limit N` caps the run for a trial.

## 3. Run for real

```
python -m pirate_radio.tagging \
    --content-dir /srv/pirate/station1 \
    --user-agent "PiRate/1.0 ( you@example.com )"
```

- **Default is fill-not-overwrite:** only missing fields are written; a confident match below the
  score floor writes nothing. Existing good tags are never clobbered.
- **`--force`** overwrites existing tags with the matched metadata (still never erases a field the
  match doesn't have). Use only when you mean it; dry-run it first.
- Writes are **atomic** (same-dir temp + rename), so a power loss / Ctrl-C never corrupts a file.
- **Run against the content mount, not the boot SD card** (rewriting many files' tags is hard on SD;
  keep the library on the USB/SSD content drive — A6).

## 4. Read the summary + logs

The tool prints, per run, `N tagged, M skipped, K failed of T`, and per-file failures name the file
and the reason (scrubbed). A `skipped` file was already tagged or had no confident match; a `failed`
file hit a fingerprint/lookup error and was left untouched (the batch continues — one bad file never
aborts the run).

## 5. Pick up the new tags

The running radio reads tags fresh on its next catalog (re)scan — restart the daemon, or `touch` the
content directory to bump its mtime so the `CatalogCache` rescans:

```
touch /srv/pirate/station1 && sudo systemctl restart pirate-radio
```

## Flags reference

| flag | meaning |
|---|---|
| `--content-dir` (required) | library root to walk |
| `--user-agent` (required) | MusicBrainz UA with contact info |
| `--acoustid-key-env` | env var holding the key (default `ACOUSTID_API_KEY`) |
| `--dry-run` | log planned tags, write nothing |
| `--force` | overwrite existing tags (still never erases) |
| `--limit N` | tag at most N files (stable order) |
| `--min-score` | AcoustID confidence floor (default 0.85) |
| `--log-level` | default INFO |


---

**Related:** [`first-boot.md`](first-boot.md) (the full bring-up runbook) · [`config-reference.md`](config-reference.md) (every config key).
