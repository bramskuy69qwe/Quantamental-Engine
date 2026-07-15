# Correlation log — reading cookbook (CL.T4, plan 4.2)

How to actually read `data/logs/correlation/corr-YYYY-MM-DD.jsonl`.
Envelope/taxonomy reference: [docs/design/correlation_log_spec.md](design/correlation_log_spec.md)
(§4 envelope, §5 categories, §9 recipes, **§15 as-built errata** — this
cookbook uses the as-built shapes, which is what the spec's §15 exists
to record). Tools: `scripts/corr_tail.py` (chains, tail, races, dups),
`jq` (ad-hoc slices), DuckDB (bulk SQL).

**The three reading rules:**

1. **Order = (`ts`, `seq`).** `seq` is allocated atomically at emit and
   is the truth within one engine run; it RESETS on restart — across
   runs (and across files), `ts` orders. `corr_tail.py` sorts this way
   for you; hand-rolled jq does not.
2. **The position-identity key is `terminal_position_id`** — everywhere:
   envelopes, DB columns, app state. The spec's `tpid` *shorthand* is
   prose, not a key; `select(.payload.tpid=="")` matches nothing
   (spec §15 **E23**). The attr identity tuple is
   `terminal_position_id` / `calc_id` / `exchange_order_id` /
   `lifecycle_id`, verbatim including `""` — with two caveats:
   two-party envelopes carry `parent_`/`child_`-prefixed order ids
   (HA-26), and enrich/drift/manual envelopes hardcode
   `lifecycle_id:""` (E27).
3. **Not every alarming-looking line is a bug.** The benign classes are
   listed at the end — check them before filing.

---

## corr_tail.py (the wrapped recipes)

```text
python scripts/corr_tail.py --corr-id wsu-1b9e04af        # one chain, true order
python scripts/corr_tail.py --calc-id <ID> --days 3       # an identity, cross-chain + cross-day
python scripts/corr_tail.py --symbol XAUUSDT --category "attr_*"
python scripts/corr_tail.py --since 2026-06-12T09:00 --until 2026-06-12T09:05
python scripts/corr_tail.py --interleave 4460 4490        # race view (spec §4.1)
python scripts/corr_tail.py --dups                        # repeated dedup_keys
python scripts/corr_tail.py --follow --category "attr_*"  # live tail, filtered
python scripts/corr_tail.py --raw --corr-id X | jq ...    # NDJSON passthrough
```

`--calc-id` is a raw-line **substring** match, so it works for ANY
identity string (calc_id, terminal_position_id, exchange_order_id,
dedup keys) — exact-key jq misses ids embedded in dedup tags and the
HA-26 prefixed keys. Prefer a distinctive id (`CALC-123`, `wsu-…`); a
bare number can match inside an unrelated `seq`/`ts`. `--dups` groups
per (category, dedup_key) and hides funding re-polls by default (see
benign classes; `--include-benign`).

---

## jq recipes (as-built keys)

One chain, everything for a ticker, attribution only:

```bash
jq -c 'select(.corr_id=="wsu-1b9e04af")'                       corr-2026-06-12.jsonl
jq -c 'select(.symbol=="XAUUSDT")'                             corr-2026-06-12.jsonl
jq -c 'select(.symbol=="XAUUSDT" and (.category|startswith("attr_")))' corr-2026-06-12.jsonl
```

Decisions that did NOT happen (the historical silent-skip bug class —
every attr invocation emits, including skips):

```bash
jq -c 'select(.payload.outcome=="SKIPPED") | {seq,category,reason:.payload.reason}' corr-*.jsonl
jq -c 'select(.category=="attr_match_attempt" and .payload.outcome=="NEEDS_MANUAL_REVIEW")' corr-*.jsonl
```

**Stranded identity** — the canonical race-damage query (E23: the real
key, not the spec's `tpid` shorthand):

```bash
jq -c 'select(.payload.terminal_position_id=="")' corr-2026-06-12.jsonl
```

**Did the close row actually land?** The predicate is
`payload.row_written`, NOT `outcome=="WRITTEN"` — a post-persist
exception reads `outcome:"ERROR"` with `row_written:true` (HA-32):

```bash
jq -c 'select(.category=="attr_close_build" and (.payload.row_written|not))' corr-*.jsonl
```

A trade's whole life by calc id (cross-cuts corr_ids; the grep-shaped
equivalent of `--calc-id`):

```bash
grep 'CALC-123' corr-*.jsonl | jq -c '{seq,ts,corr_id,category}'
```

Interleave window / what rows did this chain write:

```bash
jq -c 'select(.seq>=4470 and .seq<=4480) | {seq,corr_id,task,category}' corr-2026-06-12.jsonl
jq -c 'select(.corr_id=="wsu-7c91" and .category=="db_write")'          corr-2026-06-12.jsonl
```

Duplicates by hand (prefer `--dups`, which pairs key+category — HA-32):

```bash
jq -r '[.category, .payload.dedup_key // empty] | @tsv' corr-*.jsonl | sort | uniq -d
```

**Subscription leak** (historical bug #4): a `calc_symbol_change` with
no later `ws_stream_rebuild`, or a `ws_connect` stream list still
containing the old symbol:

```bash
jq -c 'select(.category=="calc_symbol_change" or .category=="ws_stream_rebuild")' corr-*.jsonl
jq -c 'select(.category=="ws_connect" and (.payload.streams|tostring|contains("OLDSYMBOL")))' corr-*.jsonl
```

**LINKED with no link write** (HA-35 — the one known envelope-less seam
on the entry side: the matcher emits LINKED, then the raw
`orders.calc_id` UPDATE runs with no `db_write` tap, inside
`auto_classify`, which emits `link_transition` only AFTER that UPDATE
succeeds — so a stamp that raises leaves the LINKED decision with no
following `link_transition`). Detection is a join-absence on the chain:

```bash
# chains that decided LINKED
jq -r 'select(.category=="attr_match_attempt" and .payload.outcome=="LINKED") | .corr_id' corr-*.jsonl | sort -u > /tmp/linked
# chains that recorded the transition
jq -r 'select(.category=="link_transition") | .corr_id' corr-*.jsonl | sort -u > /tmp/wrote
comm -23 /tmp/linked /tmp/wrote     # LINKED but never transitioned → investigate
```

The empty-corr tripwire (a fallback `rest-*` pair or `corr_id:""` means
an entry point is missing a scope — itself a finding):

```bash
jq -c 'select(.corr_id=="")' corr-*.jsonl
jq -c 'select(.corr_id|startswith("rest-"))' corr-*.jsonl
```

---

## DuckDB (bulk slicing — reads NDJSON natively)

```sql
-- category volume profile for a day
SELECT category, count(*) FROM 'corr-2026-06-12.jsonl' GROUP BY 1 ORDER BY 2 DESC;

-- chain spans: longest chains first
SELECT corr_id, count(*) n, min(seq) s0, max(seq) s1
FROM 'corr-2026-06-12.jsonl' GROUP BY 1 ORDER BY n DESC LIMIT 20;

-- every attribution outcome for a symbol across the whole window
SELECT ts, seq, corr_id, category, payload->>'outcome' AS outcome
FROM 'corr-*.jsonl'
WHERE symbol='XAUUSDT' AND category LIKE 'attr_%' ORDER BY ts, seq;
```

---

## dedup_key styles (HA-32 — do NOT assume one shape)

Tag styles are heterogeneous **by design**; treat keys as opaque
strings and compare only within a category (verified against code,
2026-06-13):

| category | key shape |
|---|---|
| `ws_order_update` / `ws_algo_update` | `{exchangeOrderId}:{status}:{qty}` (omitted when the id is missing; ALGO frames key on `aid`) |
| `order_status_applied` | `{exchangeOrderId}:{normalized_status}:{qty}` (E21: NORMALIZED, not the raw frame's; bulk reconcile/stale lines have none) |
| `platform_fill` | `qt:{trade_id}` |
| `ws_news` | `bwe:{ext_id}` |
| `attr_match_attempt` | triggering-order key (see `calc_correlation.py`) |
| `attr_tpid_resolve` | `{fill_id}:tpid_resolve` |
| `attr_close_build` | `close:{fill_id}` |
| `attr_junction_form` | `junction:{fill_id}`, replay path `replay:{exchange_order_id}`, seal `seal:{terminal_position_id}:{sealed_ts}` (E36) |
| `attr_bracket_inherit` | `{leg_exchange_order_id}:inherit:{src_calc_id}` |
| `attr_reenrich_trigger` | `{exchange_order_id}:reenrich_fill` |
| manual link/unplanned (`attr_match_attempt` via link_actions) | `manual:{order_id}:{calc_id}` / `manual:{order_id}:unplanned` |
| `attr_funding_assign` | bare `venue_event_id` |

Enrich/drift lines carry **no** dedup_key (refresh-driven, no
triggering frame — E27).

---

## Benign classes — check BEFORE filing a finding

- **Funding re-polls** (HA-33): `attr_funding_assign` re-emits the SAME
  `venue_event_id` on every poll that re-sees a settlement —
  `inserted:false` disambiguates a routine re-poll from a genuine
  double-insert (two `inserted:true`). `--dups` hides these by default
  and reports the hidden count. Related: `inserted:false` also covers a
  swallowed write failure BY DESIGN — the paired `db_write` twin on the
  same chain distinguishes (E28).
- **Terminal replays** (HA-34): a venue redelivery of a terminal frame
  (`filled→filled`) bypasses the SR-1 gate BY DESIGN and is decided by
  the DB ON-CONFLICT guard — the discriminator is the paired `db_write`
  with `rowcount: 0`. Two `ws_order_update`/`order_status_applied`
  lines with one key + a rowcount-0 write = redelivery handled, not a
  double-process.
- **Cancelled deferred close-build** (HA-38): a close-build task
  cancelled mid-build (e.g. shutdown) emits
  `attr_close_build outcome:"ERROR", reason:"build_incomplete"` — a
  line, not a bug (mandate-1: absences must be lines; the label is
  accepted as-built).
- **`order_status_applied` is INTENT, `db_write` is truth** (E21,
  HA-25): the ws line records the gate-passed intent; whether the row
  changed is the paired `db_write` `rowcount`.
- **Unmatched out-taps at shutdown** (E15): task cancellation emits
  `rest_call`/`http_out_call` but never the return tap. Pair-join
  readers must tolerate widowed out-taps near shutdown.
- **REJECTED applies emit nothing** (E20): WS-priority snapshot
  rejects, SR-1 order-gate rejects, raced calc/link transitions — no
  envelope by design (CL.T5 may revisit).
- **SSE routes**: `http_response.duration_ms` of hours is normal — it
  fires at stream close (spec §5.1).
- **`attr_match_attempt` criteria are summarized** (E24): capped
  per-candidate failed-criteria summary; the FULL per-criterion rows
  are in the `calc_match_audit` DB table on the same chain.
- **Profile blind spots** (E13/HA-13): the `linkage` profile drops the
  whole `outbound` group (incl. webhook POST taps) AND `http`;
  `pubsub_publish` is unsampled at `full` (E14). Default profile is
  `full`. Pending the CL.T5 volume pass.
- **Nothing-to-do attr lines** (HA-28): per-update
  `attr_junction_form via:"post_link_replay" outcome:"SKIPPED"
  reason:"junction_exists"` and steady bracket SKIPPED lines are the
  normal idle chatter of a linked order at `full` — volume, not signal;
  the CL.T5 volume pass owns the dedup decision.
- **Reconciler outcomes on `attr_junction_form`** (E36, reconciler
  R2–R4): `MIGRATED` (junction row re-keyed/merged to the canonical
  tpid), `RECONCILED` (contributed_qty delta-reconciled to the order's
  true opening SUM; carries old/new qty), `SEALED` (lifecycle sealed at
  the final close). All three are on-change/actionable — one line per
  actual mutation, never idle chatter; an ENDLESSLY repeating
  MIGRATED/RECONCILED across events is a finding (caveats: one fill
  migrating ≥2 stale rows legitimately emits multiple same-key
  MIGRATED lines in ONE pass — `old_key` differs; and builder lines
  reached via the replay lane carry NO dedup_key, the synth fill has
  no fill id). Owner-emitted attr lines
  (`attr_tpid_resolve` close-fill lane, `attr_junction_form`) carry
  `component:"position_identity"` since reconciler R1 (the
  snapshot-recovery `attr_tpid_resolve` lane stays `order_manager` —
  E36) — filter by category as always; component is informational.

---

## Reading a race (spec §4.1 worked example)

1. Find the suspicious chain: `corr_tail.py --calc-id <id>` or
   `--symbol X --category "attr_*"`.
2. Note the seq range around the bad decision (say 4471–4476).
3. `corr_tail.py --interleave 4460 4490` — different `task` values in
   the same window genuinely ran concurrently; (`ts`,`seq`) gives true
   order. The classic shape: a scheduler chain's
   `position_snapshot_applied` (`closes_detected=[...]`) landing one
   line before a WS chain's `attr_tpid_resolve` falls back from
   live-position to entry-order — the §4.1 close-tpid race, readable.
4. `--corr-id` each participant for its full story; `db_write` lines
   answer what each chain persisted (`rowcount` is the truth).
