"""corr_tail.py — reader for the correlation log (CL.T4, plan 4.1).

Reads the engine's NDJSON correlation log (``corr-YYYY-MM-DD.jsonl``,
spec docs/design/correlation_log_spec.md §4/§9) and answers the
debugging questions the envelope was shaped for:

    # one chain, in true emission order
    python scripts/corr_tail.py --corr-id wsu-1b9e04af

    # a trade's whole life — cross-cuts corr_ids AND days
    python scripts/corr_tail.py --calc-id CALC-123 --days 3

    # every attribution decision for a ticker
    python scripts/corr_tail.py --symbol XAUUSDT --category "attr_*"

    # race forensics: every chain in a seq window, side by side (spec §4.1)
    python scripts/corr_tail.py --interleave 4460 4490

    # duplicate detection: dedup_keys seen more than once (spec §4.1)
    python scripts/corr_tail.py --dups

    # tail the live file (filters apply)
    python scripts/corr_tail.py --follow --category "attr_*"

    # raw NDJSON passthrough for jq pipelines
    python scripts/corr_tail.py --raw --corr-id wsu-1b9e04af | jq .payload

Recipes + caveats (benign duplicate classes, identity-key names, reading
gotchas): docs/correlation_log_cookbook.md.

Design notes (deviations named per the deviation discipline):

- ``--calc-id`` is a RAW-LINE SUBSTRING match instead of a
  ``payload.calc_id`` equality test because identity keys are
  heterogeneous across envelopes (HA-26 two-party ``parent_``/``child_``
  prefixes; ids embedded in dedup tags like ``manual:{oid}:{calc}``) —
  an exact-key match would silently miss real references. It therefore
  works for ANY identity string: calc_id, terminal_position_id,
  exchange_order_id, lifecycle_id, dedup keys. NB the envelope key for
  position identity is ``terminal_position_id`` — the spec's ``tpid``
  shorthand does not exist in envelopes (spec §15 E23).
- ``--dups`` groups by (category, dedup_key) instead of bare key
  because tag styles are heterogeneous by design (HA-32) and the
  duplicate question is "did the SAME site process this twice"; the
  same id appearing under two categories is chain pairing, not a dup.
  Funding re-polls (``attr_funding_assign`` with ``inserted: false``)
  are routine benign repeats (HA-33) — hidden by default, shown with
  ``--include-benign``; the hidden count is always reported (no silent
  caps).
- Output is sorted by (``ts``, ``seq``) — the spec §4 total-order rule
  (``seq`` resets per engine restart; ``ts`` orders across runs).
- Unknown envelope fields and unknown categories are tolerated
  (forward compat across the 7-day window — plan 4.1); unparseable
  lines are skipped and COUNTED to stderr.
- Scan mode holds matches in memory to sort them. For whole-day bulk
  slicing use the cookbook's DuckDB recipes instead.

Stdlib-only at module level; ``config`` / ``core.correlation_log`` are
imported lazily and best-effort (default sink dir + category-typo
warnings degrade gracefully if unavailable).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Iterator, List, Optional, Sequence, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# A parsed line: (envelope dict, raw line). The raw line rides along for
# --raw passthrough and the substring --calc-id match.
Parsed = Tuple[Dict[str, Any], str]

GIST_MAX_INTERLEAVE = 72


def _default_dir() -> Optional[str]:
    """The engine's sink dir (config.CORR_LOG_DIR), best-effort.

    Relative values are anchored at the repo root (the engine runs from
    there; this script may not).
    """
    try:
        import config  # noqa: PLC0415 — lazy: explicit-path usage must not require config
        d = config.CORR_LOG_DIR
    except Exception:
        return None
    if not os.path.isabs(d):
        d = os.path.join(ROOT, d)
    return d


def _known_categories() -> Optional[set]:
    """The category registry, best-effort (typo warnings only)."""
    try:
        from core import correlation_log  # noqa: PLC0415 — lazy, optional
        return set(correlation_log.registry())
    except Exception:
        return None


def _today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _day_path(dir_: str, date_str: str) -> str:
    return os.path.join(dir_, f"corr-{date_str}.jsonl")


def resolve_files(files: Sequence[str], dir_: Optional[str],
                  date: Optional[str], days: int) -> List[str]:
    """Explicit paths win; else the last ``days`` daily files ending at
    ``date`` (default today UTC) that exist in the sink dir.

    Raises FileNotFoundError when nothing resolves (the caller reports).
    """
    if files:
        missing = [f for f in files if not os.path.exists(f)]
        if missing:
            raise FileNotFoundError(f"no such file: {', '.join(missing)}")
        return list(files)
    if dir_ is None:
        dir_ = _default_dir()
    if dir_ is None:
        raise FileNotFoundError(
            "could not resolve the correlation-log dir (config import failed); "
            "pass file paths or --dir"
        )
    end_str = date or _today_utc()
    try:
        end = datetime.strptime(end_str, "%Y-%m-%d")
    except ValueError:
        raise FileNotFoundError(f"--date must be YYYY-MM-DD, got {end_str!r}")
    candidates = [
        _day_path(dir_, (end - timedelta(days=i)).strftime("%Y-%m-%d"))
        for i in range(max(1, days) - 1, -1, -1)  # oldest → newest
    ]
    existing = [p for p in candidates if os.path.exists(p)]
    if not existing:
        raise FileNotFoundError(
            f"no correlation files found ({candidates[-1]}"
            + (f" … back {days} day(s)" if days > 1 else "") + ")"
        )
    return existing


def parse_envelope(line: str) -> Optional[Dict[str, Any]]:
    """One NDJSON line → envelope dict; None for anything unparseable.

    Tolerant by mandate (plan 4.1): unknown fields, unknown categories,
    and missing fields all pass through — only non-JSON / non-object
    lines are rejected (and counted by the caller).
    """
    line = line.strip()
    if not line:
        return None
    try:
        obj = json.loads(line)
    except (json.JSONDecodeError, ValueError):
        return None
    return obj if isinstance(obj, dict) else None


def _norm_ts(s: str) -> str:
    """Normalize a user timestamp for lexicographic compare against the
    envelope's fixed-format ISO-UTC ``ts``: ``2026-06-10T13:27:45.123456Z``.

    Prefix compares give half-open [--since, --until) semantics at the
    given precision; trailing ``Z`` is stripped so a full ``…45Z`` input
    means "from second 45 inclusive".
    """
    return s.strip().replace(" ", "T").rstrip("Zz")


def category_matches(category: str, pattern: str) -> bool:
    """Exact name, or prefix when the pattern ends with ``*``."""
    if pattern.endswith("*"):
        return category.startswith(pattern[:-1])
    return category == pattern


class Filters:
    """The plan-4.1 filter set: corr_id / calc_id / symbol / category /
    time-window. All compose (AND)."""

    def __init__(self, corr_id: Optional[str] = None, calc_id: Optional[str] = None,
                 symbol: Optional[str] = None, categories: Optional[List[str]] = None,
                 since: Optional[str] = None, until: Optional[str] = None) -> None:
        self.corr_id = corr_id
        self.calc_id = calc_id
        self.symbol = symbol
        self.categories = categories or []
        self.since = _norm_ts(since) if since else None
        self.until = _norm_ts(until) if until else None

    def matches(self, env: Dict[str, Any], raw: str) -> bool:
        if self.corr_id is not None and env.get("corr_id") != self.corr_id:
            return False
        if self.symbol is not None and env.get("symbol") != self.symbol:
            return False
        if self.calc_id is not None and self.calc_id not in raw:
            return False
        if self.categories:
            cat = env.get("category") or ""
            if not any(category_matches(cat, p) for p in self.categories):
                return False
        if self.since or self.until:
            ts = env.get("ts")
            if not isinstance(ts, str) or not ts:
                return False  # no parseable ts → cannot place in a window
            if self.since and ts < self.since:
                return False
            if self.until and ts >= self.until:
                return False
        return True


def sort_key(env: Dict[str, Any]) -> Tuple[str, int]:
    """Spec §4 exact total order: (ts, seq). seq resets per process run;
    ts orders across restarts (spec §7.5)."""
    ts = env.get("ts")
    seq = env.get("seq")
    return (ts if isinstance(ts, str) else "",
            seq if isinstance(seq, int) else 0)


def scan(paths: Sequence[str], filters: Filters) -> Tuple[List[Parsed], int]:
    """All matching (envelope, raw) pairs across ``paths`` + the count of
    unparseable lines seen (reported, never silently dropped)."""
    matches: List[Parsed] = []
    malformed = 0
    for path in paths:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                env = parse_envelope(line)
                if env is None:
                    if line.strip():
                        malformed += 1
                    continue
                if filters.matches(env, line):
                    matches.append((env, line.rstrip("\n")))
    return matches, malformed


def _compact(obj: Any) -> str:
    # ensure_ascii (default) keeps output safe on legacy Windows consoles.
    return json.dumps(obj, separators=(",", ":"), default=str)


def format_line(env: Dict[str, Any], gist_max: int = 0) -> str:
    """One envelope → one aligned human line.

    Columns: seq, ts, corr_id, task, component/category, symbol, payload.
    direction/peer/account_id are deliberately omitted (category implies
    them in practice) — use --raw when they matter.
    """
    seq = env.get("seq", "-")
    ts = env.get("ts") or "-"
    corr = env.get("corr_id") or "-"
    task = env.get("task") or "-"
    comp = env.get("component") or "-"
    cat = env.get("category") or "-"
    sym = env.get("symbol") or "-"
    payload = env.get("payload")
    gist = _compact(payload) if payload is not None else ""
    if gist_max and len(gist) > gist_max:
        gist = gist[: gist_max - 3] + "..."
    return f"{seq!s:>8}  {ts}  {corr:<14}  {task:<16}  {comp}/{cat}  {sym}  {gist}"


def is_benign_repeat(env: Dict[str, Any]) -> bool:
    """HA-33: funding re-polls re-emit the same ``venue_event_id`` with
    ``inserted: false`` — routine, not a double-process."""
    if env.get("category") != "attr_funding_assign":
        return False
    payload = env.get("payload")
    return isinstance(payload, dict) and payload.get("inserted") is False


def find_dups(parsed: Sequence[Parsed], include_benign: bool = False
              ) -> Tuple[List[Tuple[str, str, List[int]]], int]:
    """Duplicate dedup_keys, grouped by (category, dedup_key) — HA-32:
    tag styles are heterogeneous and only a same-category repeat means
    "the same site saw this twice"; keys are treated as opaque strings.

    Returns (groups, hidden_benign_lines): groups as
    (category, dedup_key, seqs) with >1 counted line, sorted by count
    desc; benign funding re-poll lines (HA-33) are excluded from the
    count unless ``include_benign`` — a group that stays >1 without them
    (a genuine double-insert) still surfaces.
    """
    groups: Dict[Tuple[str, str], List[int]] = {}
    hidden = 0
    for env, _raw in parsed:
        payload = env.get("payload")
        if not isinstance(payload, dict):
            continue
        key = payload.get("dedup_key")
        if not isinstance(key, str) or not key:
            continue
        if not include_benign and is_benign_repeat(env):
            hidden += 1
            continue
        cat = str(env.get("category") or "-")
        seq = env.get("seq")
        groups.setdefault((cat, key), []).append(seq if isinstance(seq, int) else 0)
    dups = [(cat, key, sorted(seqs)) for (cat, key), seqs in groups.items()
            if len(seqs) > 1]
    dups.sort(key=lambda g: (-len(g[2]), g[0], g[1]))
    return dups, hidden


def follow_stream(path_fn: Callable[[], str], initial_offsets: Dict[str, int],
                  poll: float = 0.5,
                  should_stop: Optional[Callable[[], bool]] = None,
                  ) -> Iterator[str]:
    """Yield complete NEW lines appended to the file named by ``path_fn``.

    ``path_fn`` is re-evaluated each poll so a UTC-day rollover switches
    to the new file (after draining the old one to EOF). Files are read
    in binary and split on ``\\n`` — a partial tail line is buffered
    until its newline arrives (the sink writes whole lines per batch,
    but a poll can land mid-write). ``initial_offsets`` carries the
    byte position already consumed per path (the scan's EOF), so
    already-printed lines are not re-emitted.
    """
    current = path_fn()
    offsets = dict(initial_offsets)
    buf = b""

    def _read_new(path: str) -> Iterator[str]:
        nonlocal buf
        try:
            size = os.path.getsize(path)
        except OSError:
            return
        pos = offsets.get(path, 0)
        # The sink is append-only with new-filename rollover and NO rename
        # (core/correlation_log.py): a day file only grows. A file that
        # shrank below our offset (an operator truncating it mid-follow) is
        # out of contract — we wait for it to grow past the stale offset
        # rather than re-read from 0.
        if size <= pos:
            return
        with open(path, "rb") as fh:
            fh.seek(pos)
            data = fh.read()
        offsets[path] = pos + len(data)
        buf += data
        while True:
            nl = buf.find(b"\n")
            if nl < 0:
                break
            line = buf[:nl]
            buf = buf[nl + 1:]
            yield line.decode("utf-8", errors="replace")

    while True:
        target = path_fn()
        if target != current:
            yield from _read_new(current)  # drain the closing day file
            buf = b""  # a torn tail line at rollover cannot complete
            current = target
        yield from _read_new(current)
        if should_stop is not None and should_stop():
            return
        time.sleep(poll)


def _warn_unknown_categories(patterns: Sequence[str]) -> None:
    known = _known_categories()
    if not known:
        return
    for p in patterns:
        if not p.endswith("*") and p not in known:
            print(f"warning: category {p!r} is not in the registry (typo? "
                  f"see core/correlation_log.py)", file=sys.stderr)


def run_scan(paths: Sequence[str], filters: Filters, raw: bool,
             out=None) -> int:
    out = out or sys.stdout
    matches, malformed = scan(paths, filters)
    matches.sort(key=lambda pr: sort_key(pr[0]))
    for env, raw_line in matches:
        print(raw_line if raw else format_line(env), file=out)
    if malformed:
        print(f"note: skipped {malformed} unparseable line(s)", file=sys.stderr)
    if not matches:
        print("0 lines matched", file=sys.stderr)
    return 0


def run_interleave(paths: Sequence[str], filters: Filters,
                   seq_from: int, seq_to: int, raw: bool, out=None) -> int:
    """Spec §4.1 race view: every chain in [seq_from, seq_to], corr_id +
    task side by side, payload gisted (drill into a chain for detail)."""
    out = out or sys.stdout
    matches, malformed = scan(paths, filters)
    window = [(e, r) for e, r in matches
              if isinstance(e.get("seq"), int) and seq_from <= e["seq"] <= seq_to]
    window.sort(key=lambda pr: sort_key(pr[0]))
    for env, raw_line in window:
        print(raw_line if raw else format_line(env, gist_max=GIST_MAX_INTERLEAVE),
              file=out)
    if malformed:
        print(f"note: skipped {malformed} unparseable line(s)", file=sys.stderr)
    if not window:
        print("0 lines matched", file=sys.stderr)
    return 0


def run_dups(paths: Sequence[str], filters: Filters,
             include_benign: bool, out=None) -> int:
    out = out or sys.stdout
    matches, malformed = scan(paths, filters)
    dups, hidden = find_dups(matches, include_benign=include_benign)
    for cat, key, seqs in dups:
        shown = ",".join(str(s) for s in seqs[:10])
        more = f" +{len(seqs) - 10} more" if len(seqs) > 10 else ""
        print(f"{len(seqs)}x  {cat}  {key}  seqs={shown}{more}", file=out)
    if hidden:
        print(f"note: {hidden} benign funding re-poll line(s) hidden "
              f"(attr_funding_assign inserted:false — HA-33); "
              f"--include-benign to count them", file=sys.stderr)
    if malformed:
        print(f"note: skipped {malformed} unparseable line(s)", file=sys.stderr)
    if not dups:
        print("no duplicate dedup_keys found", file=sys.stderr)
    else:
        print("note: not every repeat is a bug — see "
              "docs/correlation_log_cookbook.md (benign duplicate classes: "
              "funding re-polls, terminal replays discriminated by paired "
              "db_write rowcount=0)", file=sys.stderr)
    return 0


def run_follow(paths: Sequence[str], filters: Filters, raw: bool,
               dir_mode_dir: Optional[str], poll: float = 0.5,
               should_stop: Optional[Callable[[], bool]] = None,
               out=None) -> int:
    """Scan + print (sorted), then tail. In dir mode the target re-resolves
    to today's file each poll (UTC rollover-aware); with explicit files the
    last one is followed."""
    out = out or sys.stdout
    run_scan(paths, filters, raw, out=out)
    offsets = {p: os.path.getsize(p) for p in paths if os.path.exists(p)}
    if dir_mode_dir is not None:
        path_fn = lambda: _day_path(dir_mode_dir, _today_utc())  # noqa: E731
    else:
        last = paths[-1]
        path_fn = lambda: last  # noqa: E731
    try:
        for line in follow_stream(path_fn, offsets, poll=poll,
                                  should_stop=should_stop):
            env = parse_envelope(line)
            if env is None:
                continue
            if filters.matches(env, line):
                print(line if raw else format_line(env), file=out, flush=True)
    except KeyboardInterrupt:
        pass
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="corr_tail.py",
        description="Read the correlation log (corr-YYYY-MM-DD.jsonl): filter, "
                    "pretty-print chains in seq order, tail, race-interleave, "
                    "find duplicate dedup_keys.",
        epilog=__doc__.split("Design notes")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("files", nargs="*",
                   help="explicit .jsonl file(s); default: the engine sink dir")
    p.add_argument("--dir", default=None,
                   help="sink dir (default: config.CORR_LOG_DIR)")
    p.add_argument("--date", default=None, metavar="YYYY-MM-DD",
                   help="day file to read (UTC; default today)")
    p.add_argument("--days", type=int, default=1, metavar="N",
                   help="scan the N daily files ending at --date (default 1)")
    p.add_argument("--corr-id", help="one chain")
    p.add_argument("--calc-id", metavar="ID",
                   help="any identity string — substring match on the raw line "
                        "(calc_id, terminal_position_id, exchange_order_id, "
                        "lifecycle_id, dedup keys); cross-cuts corr_ids")
    p.add_argument("--symbol", help="top-level ticker slice (exact)")
    p.add_argument("--category", action="append", default=[], metavar="CAT",
                   help="exact category, or prefix with trailing '*' "
                        "(e.g. \"attr_*\"); repeatable (OR)")
    p.add_argument("--since", metavar="ISO_TS",
                   help="inclusive lower ts bound (UTC; prefix ok, e.g. "
                        "2026-06-12T09:00)")
    p.add_argument("--until", metavar="ISO_TS",
                   help="exclusive upper ts bound (UTC; prefix ok)")
    p.add_argument("--interleave", nargs=2, type=int,
                   metavar=("FROM_SEQ", "TO_SEQ"),
                   help="race view: every chain with seq in [FROM, TO], "
                        "corr_id + task columns, payloads gisted (spec §4.1)")
    p.add_argument("--dups", action="store_true",
                   help="dedup_keys seen >1x within one category (HA-32)")
    p.add_argument("--include-benign", action="store_true",
                   help="with --dups: also count funding re-poll repeats "
                        "(inserted:false — HA-33)")
    p.add_argument("--follow", action="store_true",
                   help="after the scan, tail the newest file live "
                        "(rollover-aware in dir mode)")
    p.add_argument("--raw", action="store_true",
                   help="print original NDJSON lines (for jq pipelines)")
    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    # Arbitrary payload content meets legacy Windows console encodings —
    # never die on a print.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except Exception:
            pass
    parser = build_parser()
    args = parser.parse_args(argv)

    modes = [bool(args.interleave), args.dups, args.follow]
    if sum(modes) > 1:
        parser.error("--interleave, --dups and --follow are mutually exclusive")
    if args.include_benign and not args.dups:
        parser.error("--include-benign only applies to --dups")
    if args.days < 1:
        parser.error("--days must be >= 1")

    _warn_unknown_categories(args.category)
    filters = Filters(corr_id=args.corr_id, calc_id=args.calc_id,
                      symbol=args.symbol, categories=args.category,
                      since=args.since, until=args.until)
    try:
        paths = resolve_files(args.files, args.dir, args.date, args.days)
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    if args.interleave:
        return run_interleave(paths, filters, args.interleave[0],
                              args.interleave[1], args.raw)
    if args.dups:
        return run_dups(paths, filters, args.include_benign)
    if args.follow:
        # dir mode (no explicit files) follows today's file across rollover
        dir_mode_dir = None
        if not args.files:
            dir_mode_dir = args.dir or _default_dir()
        return run_follow(paths, filters, args.raw, dir_mode_dir)
    return run_scan(paths, filters, args.raw)


if __name__ == "__main__":
    sys.exit(main())
