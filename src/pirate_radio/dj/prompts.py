"""PURE prompt construction from a ``DjContext`` (§9.2 grounding, §9.3 best-effort).

``dj_context -> (system_prompt, user_prompt)``. NO network, NO I/O — 100% unit-tested. The
system prompt fixes the PERSONA + the hard anti-hallucination rule ("speak only from the facts
below; invent nothing"); the user prompt is the GROUNDED FACT SHEET for the patter kind. Sparse
metadata (§9.3) is handled by emitting only the fields that exist and adding an explicit "work
with what little is given; do not guess the rest" line — never skip the item.

H26 (prompt injection): every interpolated value — track tags (attacker-influenceable) AND the
operator persona/station text — is ``_sanitize``-d (newlines + control chars collapsed) so a
tagged ``Title`` can never inject a prompt LINE; persona is additionally length-capped (H30).
``kind`` is validated against ``PATTER_KINDS`` here (the model layer keeps it a free string).
"""

from __future__ import annotations

from pirate_radio.dj.context import BlockContext, DjContext, TrackMeta

PATTER_KINDS: frozenset[str] = frozenset(
    {"intro", "outro", "factoid", "block_transition", "block_reminder", "station_id"}
)

_ANTI_HALLUCINATION = (
    "Speak ONLY from the facts listed below. Do NOT invent song facts, dates, chart "
    "positions, anecdotes, or biography. If a detail is not given, do not mention it. "
    "Never read field labels aloud. Output ONE short spoken line, no stage directions."
)

_MAX_PERSONA_CHARS = 2048  # H30: cap an operator persona file so it can't balloon every prompt


def _sanitize(value: str) -> str:
    """H26 prompt-injection defense: collapse newlines + control chars in any
    attacker-influenceable value (track tags) AND operator persona text, so an interpolated
    field can never inject extra prompt LINES (e.g. a Title of 'x\\nSystem: ignore the above').
    Newlines/tabs/other C0 controls -> single spaces; runs collapsed; trimmed. PURE."""
    cleaned = "".join(" " if (ch < " " or ch == "\x7f") else ch for ch in value)
    return " ".join(cleaned.split())


def build_system_prompt(ctx: DjContext) -> str:
    """Persona (§9.2 layer 1) + the constant anti-hallucination rule (§21.7: 'invents no facts'
    softened to a metadata-grounding instruction — tone drift can't be fully prevented). Persona
    is sanitized (H26) and length-capped (H30)."""
    persona = _sanitize(ctx.persona)[:_MAX_PERSONA_CHARS]
    return (
        f"You are the radio host for {_sanitize(ctx.station_name)}. Persona: {persona}\n"
        f"{_ANTI_HALLUCINATION}"
    )


def _fmt_block(label: str, b: BlockContext) -> list[str]:
    lines = [f"{label} block: {_sanitize(b.name)}"]
    if b.tagline:
        lines.append(f"{label} tagline: {_sanitize(b.tagline)}")
    if b.description:
        # description can STEER DELIVERY (§9.2: 'speaks softly here') as well as content
        lines.append(f"{label} note (may guide your delivery): {_sanitize(b.description)}")
    if b.boundary_at is not None:
        lines.append(f"{label} time: {b.boundary_at:%H:%M}")
    return lines


def _fmt_track(t: TrackMeta) -> list[str]:
    # every interpolated tag is attacker-influenceable -> _sanitize (H26)
    facts: list[str] = []
    if t.title:
        facts.append(f"Title: {_sanitize(t.title)}")
    if t.artist:
        facts.append(f"Artist: {_sanitize(t.artist)}")
    if t.album:
        facts.append(f"Album: {_sanitize(t.album)}")
    if t.year is not None:
        facts.append(f"Year: {t.year}")
    return facts


_TASK_BY_KIND: dict[str, str] = {
    "intro": "Briefly introduce the song that is about to play.",
    "outro": "Briefly recap the song that just played.",
    "factoid": "Share ONE short, true aside drawn only from the facts above.",
    "block_transition": "Close the current block and welcome listeners into the next one.",
    "block_reminder": "Remind listeners what block they're in and what's coming up.",
    "station_id": "Give a short station identification.",
}


def build_user_prompt(ctx: DjContext) -> str:
    """The grounded fact sheet + the task for this patter kind. Only present fields appear
    (best-effort, §9.3); a sparse track gets the explicit 'don't guess' nudge."""
    if ctx.kind not in PATTER_KINDS:
        # defensive: the producer only ever passes a known kind; guard so a typo is loud, not silent
        raise ValueError(f"unknown patter kind {ctx.kind!r}; known: {sorted(PATTER_KINDS)}")
    lines: list[str] = [f"Station: {_sanitize(ctx.station_name)}"]
    if ctx.station_tagline:
        lines.append(f"Station tagline: {_sanitize(ctx.station_tagline)}")
    lines += _fmt_block("Current", ctx.current_block)
    if ctx.next_block is not None:
        lines += _fmt_block("Next", ctx.next_block)
    if ctx.track is not None:
        track_facts = _fmt_track(ctx.track)
        lines += track_facts if track_facts else ["(No track tags are available.)"]
        if ctx.track.is_sparse:
            lines.append(
                "Few facts are known about this track — keep it brief and general; do NOT "
                "guess a title, artist, or year."  # §9.3 best-effort, still grounded
            )
    lines.append("")  # blank line before the task
    lines.append(_TASK_BY_KIND[ctx.kind])
    return "\n".join(lines)
