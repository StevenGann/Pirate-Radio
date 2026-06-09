# PiRate Radio — grids & content layout

This is the radio's core content model: **what plays, when.** Two things must line up — your
**content folders** (the music, grouped) and your **grid files** (the daily schedule that references
those groups). The boot dry-run (`--regenerate`) fails loudly if they don't, so get this right first.

Each station has its own `content_dir` (the audio) and `schedule_dir` (the grid YAML files), both set
in `config.json`.

## 1. Content layout — folders become "groups"

The scanner turns each **top-level subfolder of `content_dir` into a group**, named after the folder.
A grid slot plays from a group by that exact name.

```
<content_dir>/
├── jazz/                 # group "jazz"
│   ├── miles.flac
│   └── coltrane.mp3
├── morning_talk/         # group "morning_talk"
│   └── intro.m4a
└── overnight/            # group "overnight"
    ├── ambient1.ogg
    └── deep/space.flac   # nested files collapse INTO their top-level group ("overnight")
```

- **Group name = top-level folder name.** Nested subfolders do **not** make new groups — their files
  belong to the top-level folder above them.
- **Accepted audio extensions:** `.mp3 .flac .ogg .oga .m4a .mp4 .wav .opus`. Anything else is
  skipped (and logged).
- A group must have **at least one readable audio file** to be usable. An empty folder is not a group.
- If `content_dir` yields no non-empty groups at all, boot fails with a `CatalogError`.

Tip: tag your files first (artist/title/duration) with the offline tagger — see
[`tagging.md`](tagging.md) — so the DJ has real metadata to talk about.

## 2. Grid files — the daily schedule

Grid files are **YAML**, one per resolution slot, in the station's `schedule_dir`. Each maps the day
into contiguous time **slots**, each bound to a content **group**.

### Filename & resolution order

For a given day the loader picks the **first** file that exists, in this order:

1. The exact weekday: `monday.yaml`, `tuesday.yaml`, … `sunday.yaml`
2. `weekday.yaml` (Mon–Fri) or `weekend.yaml` (Sat–Sun)
3. `default.yaml`

So a single `default.yaml` covers every day; add `weekend.yaml` to differ on weekends; add
`saturday.yaml` to special-case one day. If none of the three exist for a day, boot fails with a
`GridResolutionError`.

### Schema

A grid file is a mapping with a `slots:` list. Each slot:

| Key | Required | Meaning |
|---|---|---|
| `start` | yes | Slot start time `HH:MM` (24-hour). |
| `end` | yes | Slot end time `HH:MM`, **exclusive**. |
| `group` | yes | The content-folder group to play in this slot (must be non-empty). |
| `name` | yes | A human label for the block (shown in logs / the DJ context). |
| `tagline` | no | Optional short blurb for the block. |
| `description` | no | Optional longer description. |
| `name:` (top level) | no | Optional grid name; defaults to the filename stem. |

### The tiling rule (this is what trips people up)

The slots must **tile the whole day, 00:00 → 24:00, with no gaps and no overlaps**:

- The **first** slot must `start` at `00:00`.
- Each slot's `end` must equal the **next** slot's `start` (contiguous — no gaps, no overlaps).
- The **last** slot must `end` at `24:00`, which you write as **`00:00`** (`datetime` has no 24:00).
- `00:00` as an end is the "end of day" marker and is legal **only on the final slot**. A single
  slot `00:00 → 00:00` means "all day".
- Every slot needs `start < end` (no zero-length slots), except the final `… → 00:00`.

### Worked example — `default.yaml`

```yaml
name: "Everyday"
slots:
  - { start: "00:00", end: "06:00", group: "overnight",    name: "Overnight Ambient" }
  - { start: "06:00", end: "10:00", group: "morning_talk", name: "Morning Show",
      tagline: "Wake up with us" }
  - { start: "10:00", end: "18:00", group: "jazz",         name: "Daytime Jazz" }
  - { start: "18:00", end: "00:00", group: "overnight",    name: "Evening Wind-Down" }
```

This tiles 00:00→06:00→10:00→18:00→24:00 contiguously; the last slot ends at `00:00` (24:00). Every
`group` (`overnight`, `morning_talk`, `jazz`) must be a non-empty subfolder of that station's
`content_dir`.

> The generator drops a station ID at the first item of each new clock-hour. A slot boundary that
> falls mid-hour starts a new block whose first item lands in the *same* hour, so you may hear a
> second station ID that hour — expected and harmless (decision 0067 carry-forward).

An "all day, one group" grid is just:

```yaml
slots:
  - { start: "00:00", end: "00:00", group: "music", name: "All Day" }
```

## 3. Validate before you go live

The boot dry-run generates the day's schedule and fails loudly on any grid/content mismatch — run it
after every grid or content change (it does **not** start the daemon):

```
sudo -u pirate /opt/pirate-radio/.venv/bin/python -m pirate_radio \
    --config /etc/pirate-radio/config.json --regenerate
```

Common failures and what they mean:

- `first slot must start at 00:00` / `last slot must end at 24:00` — your slots don't cover the full
  day; fix the tiling.
- `gap/overlap between '<A>' (ends …) and '<B>' (starts …)` — a slot's `end` doesn't match the next
  slot's `start`.
- `only the final slot may end at 24:00 (00:00)` — a non-final slot has `end: "00:00"`; only the last
  one may.
- `slot groups with no non-empty content folder` / `CatalogError` — a slot's `group` has no matching
  non-empty subfolder under `content_dir` (typo, or the folder is empty / has no accepted audio).

Once `--regenerate` succeeds, the schedules are written under `state_dir/<station>/<date>.json` and the
daemon will pick them up. See [`first-boot.md`](first-boot.md) for the full bring-up.
