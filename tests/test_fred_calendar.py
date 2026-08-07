"""FRED-backed economic calendar + the calendar pane's honesty fix (2026-08-07).

WHY THIS EXISTS. Finnhub's /calendar/economic answers
`403 {"error":"You don't have access to this resource."}` on this account's
plan — OBSERVED against the live endpoint, not inferred from the log. Calendar
writes stopped 2026-06-09; the table kept 6,278 rows whose newest event was
2026-06-16; the pane queries a ±30d window, so it rendered ZERO rows for two
months under the literal message "no calendar events stored" — while 6,278
WERE stored. An affirmative wrong signal, which DESIGN.md ranks as worse than
no signal, and which was only caught because the operator happened to know an
NFP print was due that night.

The replacement is FRED's release calendar. Two facts about it are load-bearing
and are pinned here because both were found by EXECUTING the API, not reading
docs:

1. The BULK endpoint cannot see today. `/fred/releases/dates` returned only
   ['2026-09-04'] for release 50 over a ±40d window, while the per-release
   `/fred/release/dates?release_id=50` returned
   ['2026-07-02', '2026-08-07', '2026-09-04']. The bulk endpoint omits
   same-day and past dates — it would have hidden an NFP happening THAT DAY
   and emptied the entire backward half of the window.
2. FRED publishes NO TIMES (0 of 1000 sampled records carried one), so the
   clock times are curated constants. That is why writes REBUILD the window
   instead of upserting: correcting a curated time would otherwise mint a
   duplicate under UNIQUE(event_time, country, event_name) and leave two
   contradictory rows for one event.

No test here touches the network or the live DB.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import core.news_fetcher as nf  # noqa: E402
from core.news_fetcher import (  # noqa: E402
    _FRED_EXCLUDED,
    _FRED_RELEASES,
    _fred_event_time,
    _redact,
    FredCalendarFetcher,
)
from tests._srcpin import code as _code  # noqa: E402

_ROOT = Path(__file__).parent.parent


# ── the curated table ───────────────────────────────────────────────────────

class TestCuratedReleaseTable:
    def test_shape_and_impact_vocabulary(self):
        """`impact` is compared with exact strings in SQL (`impact IN (?,?)`)
        and keyed by the pane's impact pill — a typo silently un-filters."""
        assert _FRED_RELEASES, "the curated table is empty"
        for rid, entry in _FRED_RELEASES.items():
            assert isinstance(rid, int)
            name, impact, hh, mm, cap = entry
            assert name and isinstance(name, str)
            assert impact in ("high", "medium", "low"), (rid, impact)
            assert 0 <= hh <= 23 and 0 <= mm <= 59, (rid, hh, mm)
            assert cap >= 1

    def test_the_headline_releases_are_present_and_high(self):
        """NFP/CPI/GDP/PCE are the reason this feature exists. Pinned BY ID —
        the first draft looped over only CPI and GDP, so release 54 (PCE)
        could be downgraded or deleted with every test green."""
        assert _FRED_RELEASES[50][0].startswith("Nonfarm Payrolls")
        for rid in (50, 10, 53, 54):          # NFP, CPI, GDP, PCE
            assert rid in _FRED_RELEASES, rid
            assert _FRED_RELEASES[rid][1] == "high", rid
        # NFP and CPI are 08:30 ET releases — the single most consequential
        # constant in the table.
        assert _FRED_RELEASES[50][2:4] == (8, 30)
        assert _FRED_RELEASES[10][2:4] == (8, 30)

    def test_display_names_are_unique(self):
        """event_name is part of UNIQUE(event_time, country, event_name); two
        releases sharing a name on the same date would collide and one would
        vanish."""
        names = [v[0] for v in _FRED_RELEASES.values()]
        assert len(names) == len(set(names))

    def test_the_known_bad_releases_stay_excluded(self):
        """Each would put a WRONG row on a risk console — see the module
        comment. 101 (FOMC) is the sharpest: measured 38 release dates in a
        45-day window, so its dates cannot locate a meeting."""
        for rid in (101, 95, 27, 91):
            assert rid in _FRED_EXCLUDED
            assert rid not in _FRED_RELEASES


# ── the ET → UTC conversion (the curated-time half) ─────────────────────────

class TestEventTimeConversion:
    def test_dst_is_honoured_not_a_fixed_offset(self):
        """US releases are on an Eastern WALL CLOCK. The same 08:30 ET is
        12:30Z in summer and 13:30Z in winter; a hardcoded offset is an hour
        wrong for half the year, and any ±30d window in Mar/Nov spans it."""
        assert _fred_event_time("2026-08-07", 8, 30) == "2026-08-07T12:30:00+00:00"
        assert _fred_event_time("2026-12-04", 8, 30) == "2026-12-04T13:30:00+00:00"

    def test_format_matches_the_stored_convention_exactly(self):
        """event_time is a UNIQUE-key participant compared as a STRING. 'Z'
        instead of '+00:00', or a date-only value, mints duplicates rather
        than updating in place."""
        v = _fred_event_time("2026-08-07", 8, 30)
        assert v.endswith("+00:00") and not v.endswith("Z")
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00", v)

    def test_a_late_et_release_can_roll_into_the_next_utc_day(self):
        """16:30 ET is 20:30Z — same day. The guard is that we convert at all;
        a naive `day + 'T' + clock + 'Z'` would be 4 hours wrong."""
        assert _fred_event_time("2026-08-07", 16, 30) == "2026-08-07T20:30:00+00:00"


# ── credential hygiene ──────────────────────────────────────────────────────

class TestRedaction:
    def test_both_provider_credential_params_are_scrubbed(self):
        """FRED passes `api_key=`, Finnhub `token=` — the same leak path via
        httpx.HTTPStatusError embedding the full request URL. The original
        regex only knew `token=`, so the FIRST FRED failure would have written
        the key into risk_engine.jsonl in cleartext."""
        msg = ("GET https://api.stlouisfed.org/fred/release/dates"
               "?api_key=abcdef0123456789&file_type=json")
        out = _redact(Exception(msg))
        assert "abcdef0123456789" not in out
        assert "api_key=***" in out
        tok = _redact(Exception("https://finnhub.io/x?token=SEKRET123"))
        assert "SEKRET123" not in tok and "token=***" in tok


class TestSharedRedaction:
    """The redaction lived PRIVATELY in news_fetcher as a `token=`-only regex.
    core/regime_fetcher has been calling FRED with the same `api_key=` since
    v2.5 and logged its exceptions completely unredacted — one 429 would have
    written the key into risk_engine.jsonl in cleartext. Two modules solving
    one problem privately is how the second site got missed, so the scrubber
    is now shared and every keyed fetcher routes through it."""

    _KEYED_MODULES = ("core/news_fetcher.py", "core/regime_fetcher.py",
                      "core/schedulers.py")

    def test_every_keyed_fetcher_redacts_its_exception_logs(self):
        """Derived: NO log call in these modules may pass a bare exception."""
        for rel in self._KEYED_MODULES:
            src = (_ROOT / rel).read_text(encoding="utf-8")
            bare = re.findall(r'log\.(?:error|warning)\("[^"]*%s[^"]*",\s*e\s*\)', src)
            assert not bare, f"{rel}: {len(bare)} unredacted exception log(s): {bare[:2]}"

    def test_the_shared_scrubber_covers_both_spellings_and_more(self):
        from core.secret_redact import redact
        for param in ("api_key", "apikey", "token", "access_token", "secret"):
            out = redact(f"https://x/y?{param}=SUPERSECRETVALUE&z=1")
            assert "SUPERSECRETVALUE" not in out, param
            assert "z=1" in out, f"{param}: redaction ate an innocent param"

    def test_it_is_safe_on_non_exceptions_and_leaves_clean_text_alone(self):
        from core.secret_redact import redact
        assert redact(None) == "None"
        assert redact("nothing secret here") == "nothing secret here"


# ── the fetcher, executed against a fake FRED ───────────────────────────────

class _FakeResp:
    def __init__(self, payload):
        self._p = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._p


class _FakeClient:
    """Serves per-release date lists; records the calls it received."""
    calls: list = []
    dates_by_rid: dict = {}

    def __init__(self, timeout=None):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, params=None):
        _FakeClient.calls.append((url, dict(params or {})))
        rid = int((params or {}).get("release_id", 0))
        return _FakeResp({"release_dates": [
            {"release_id": rid, "date": d}
            for d in _FakeClient.dates_by_rid.get(rid, [])
        ]})


@pytest.fixture()
def fake_fred(monkeypatch):
    _FakeClient.calls = []
    _FakeClient.dates_by_rid = {}
    monkeypatch.setattr(nf.httpx, "AsyncClient", _FakeClient)
    return _FakeClient


class _RecordingDb:
    def __init__(self):
        self.replaced = None
        self.upserted = None

    async def replace_calendar_events(self, source, frm, to, rows):
        self.replaced = (source, frm, to, rows)
        return len(rows)

    async def upsert_calendar_events(self, rows):
        self.upserted = rows
        return len(rows)


class TestFetcherExecuted:
    def _run(self, monkeypatch, fake, dates, frm="2026-08-01", to="2026-08-31"):
        fake.dates_by_rid = dates
        rec = _RecordingDb()
        monkeypatch.setattr(nf, "db", rec)
        f = FredCalendarFetcher(api_key="TESTKEY")
        n = asyncio.run(f.fetch_calendar(frm, to))
        return n, rec

    def test_uses_the_PER_RELEASE_endpoint_one_call_each(self, monkeypatch, fake_fred):
        """The bulk endpoint hides same-day and past dates — see the module
        docstring. This pins the endpoint AND that every curated release is
        actually asked for."""
        self._run(monkeypatch, fake_fred, {})
        urls = {u for u, _ in fake_fred.calls}
        assert urls == {"https://api.stlouisfed.org/fred/release/dates"}
        asked = {p["release_id"] for _, p in fake_fred.calls}
        assert asked == set(_FRED_RELEASES)

    def test_the_window_and_no_data_params_are_sent(self, monkeypatch, fake_fred):
        """These three params ARE the reason per-release beats bulk; the first
        draft asserted only the URL, so deleting realtime_start/_end left every
        pin green while the live calendar collapsed to FRED's default period.
        `include_release_dates_with_no_data` is equally load-bearing: measured
        `false` → count 0, because FUTURE dates have no data yet."""
        self._run(monkeypatch, fake_fred, {}, frm="2026-08-01", to="2026-08-31")
        _, p = fake_fred.calls[0]
        assert p["realtime_start"] == "2026-08-01"
        assert p["realtime_end"] == "2026-08-31"
        assert str(p["include_release_dates_with_no_data"]).lower() == "true"

    def test_one_bad_release_does_not_discard_the_others(self, monkeypatch, fake_fred):
        """A 429 on the 16th release used to throw away the 15 already
        collected and blank the calendar for 10 minutes."""
        class OneBad(_FakeClient):
            async def get(self, url, params=None):
                if int((params or {}).get("release_id", 0)) == 50:
                    raise RuntimeError("429")
                return await super().get(url, params)
        monkeypatch.setattr(nf.httpx, "AsyncClient", OneBad)
        _FakeClient.dates_by_rid = {10: ["2026-08-12"]}
        rec = _RecordingDb()
        monkeypatch.setattr(nf, "db", rec)
        n = asyncio.run(FredCalendarFetcher(api_key="K").fetch_calendar("2026-08-01", "2026-08-31"))
        assert n == 1
        assert {r["event_name"] for r in rec.replaced[3]} == {"CPI"}

    def test_every_curated_release_lands_inside_its_own_rebuild_window(self):
        """The delete bounds are plain UTC day edges, so a release curated at
        a late-enough ET time would insert OUTSIDE them and strand an orphan
        the rebuild can never reclaim. Checked table-wide in BOTH DST halves,
        not just for the one release the other tests exercise."""
        for rid, (_n, _i, hh, mm, _c) in _FRED_RELEASES.items():
            for day in ("2026-08-07", "2026-12-04"):
                assert _fred_event_time(day, hh, mm)[:10] == day, (rid, day)

    def test_builds_rows_with_the_curated_clock_and_source(self, monkeypatch, fake_fred):
        n, rec = self._run(monkeypatch, fake_fred, {50: ["2026-08-07"]})
        assert n == 1
        source, _, _, rows = rec.replaced
        assert source == "fred"
        r = rows[0]
        assert r["event_time"] == "2026-08-07T12:30:00+00:00"   # 08:30 ET
        assert r["country"] == "US"
        assert r["event_name"].startswith("Nonfarm Payrolls")
        assert r["impact"] == "high"
        assert r["source"] == "fred"
        # FRED release dates carry NO consensus data — these must be NULL, not
        # zero, or the pane would render a fabricated 0.00 forecast.
        assert r["previous"] is None and r["estimate"] is None and r["actual"] is None

    def test_writes_go_through_the_window_REBUILD_not_a_bare_upsert(self, monkeypatch, fake_fred):
        """Idempotency for a curated-time CORRECTION. A plain upsert keys on
        event_time, so a retime would add a row and orphan the old one."""
        _, rec = self._run(monkeypatch, fake_fred, {50: ["2026-08-07"]})
        assert rec.upserted is None, "went through upsert — a retime would duplicate"
        source, frm_iso, to_iso, rows = rec.replaced
        assert source == "fred"
        # UTC day edges, and they must CONTAIN every row written — a delete
        # window narrower than the insert set strands orphans; wider deletes
        # another window's rows.
        assert frm_iso == "2026-08-01T00:00:00+00:00"
        assert to_iso == "2026-08-31T23:59:59+00:00"
        assert all(frm_iso <= r["event_time"] <= to_iso for r in rows)

    def test_an_empty_result_still_clears_the_window(self, monkeypatch, fake_fred):
        """A quiet fortnight is a legitimate answer and must overwrite stale
        rows — guarding the write on `if rows` would strand them forever,
        which is the exact failure being repaired."""
        n, rec = self._run(monkeypatch, fake_fred, {})
        assert n == 0
        assert rec.replaced is not None and rec.replaced[3] == []

    def test_a_cadence_breach_drops_that_release_whole(self, monkeypatch, fake_fred):
        """FRED sometimes hangs a DAILY series off a release (measured: id 101
        returned 38 dates in 45 days). Partially trusting such a release would
        flood the calendar; the guard drops it and keeps the rest."""
        flood = [f"2026-08-{d:02d}" for d in range(1, 29)]
        _, rec = self._run(monkeypatch, fake_fred, {50: flood, 10: ["2026-08-12"]})
        names = {r["event_name"] for r in rec.replaced[3]}
        assert not any(n.startswith("Nonfarm") for n in names), "flood was accepted"
        assert "CPI" in names, "the guard dropped an innocent release too"

    def test_a_failure_OUTSIDE_the_per_release_loop_also_fails_soft(self, monkeypatch):
        """The OUTER guard, exercised on its own path. Once the per-release
        try/except landed, a raising `get` is caught INSIDE the loop — so the
        test below silently stopped covering the outer `except`, and deleting
        that guard left every pin green (mutation F11 SURVIVED). This raises
        where nothing else can catch it: client construction."""
        def _boom(*a, **k):
            raise RuntimeError("cannot construct client")
        monkeypatch.setattr(nf.httpx, "AsyncClient", _boom)
        rec = _RecordingDb()
        monkeypatch.setattr(nf, "db", rec)
        n = asyncio.run(FredCalendarFetcher(api_key="K").fetch_calendar("2026-08-01", "2026-08-31"))
        assert n is None
        assert rec.replaced is None, "a failed fetch must not wipe stored events"

    def test_every_release_failing_is_treated_as_UNREACHABLE_not_as_empty(self, monkeypatch, fake_fred):
        """16 of 16 failing means FRED is down, not that the calendar is quiet.
        Rebuilding to empty there would blank a working calendar on a transient
        outage — precisely the failure this change exists to repair."""
        class AllBad(_FakeClient):
            async def get(self, url, params=None):
                raise RuntimeError("429")
        monkeypatch.setattr(nf.httpx, "AsyncClient", AllBad)
        rec = _RecordingDb()
        monkeypatch.setattr(nf, "db", rec)
        n = asyncio.run(FredCalendarFetcher(api_key="K").fetch_calendar("2026-08-01", "2026-08-31"))
        assert n is None
        assert rec.replaced is None

    def test_a_transport_failure_is_caught_per_release(self, monkeypatch, fake_fred):
        """The news loop must survive a FRED outage, and the pane states the
        staleness from last_fetch rather than the fetcher raising."""
        class Boom(_FakeClient):
            async def get(self, url, params=None):
                raise RuntimeError("connection reset")
        monkeypatch.setattr(nf.httpx, "AsyncClient", Boom)
        rec = _RecordingDb()
        monkeypatch.setattr(nf, "db", rec)
        n = asyncio.run(FredCalendarFetcher(api_key="K").fetch_calendar("2026-08-01", "2026-08-31"))
        # None, not 0 — the caller must distinguish "could not reach FRED"
        # from "reached FRED, quiet window", or a transient error silently
        # banks the 10-minute cooldown.
        assert n is None
        assert rec.replaced is None, "a failed fetch must not wipe stored events"

    def test_no_key_is_a_no_op_not_a_wipe(self, monkeypatch, fake_fred):
        rec = _RecordingDb()
        monkeypatch.setattr(nf, "db", rec)
        monkeypatch.setattr(nf.config, "get_api_key", lambda p: "")
        n = asyncio.run(FredCalendarFetcher().fetch_calendar("2026-08-01", "2026-08-31"))
        assert n is None and rec.replaced is None


# ── the DB layer, EXECUTED against a temp database ─────────────────────────
#
# The audit's sharpest finding: both new DB methods were stubbed away by the
# fake db above, so `replace_calendar_events`'s ONLY safety property — the
# `source = ?` scoping on its DELETE — was unpinned. Dropping that clause
# wipes EVERY provider's rows in the window and kept every test green.

def _mkrow(name, iso, source, impact="high", est=None):
    return {"event_time": iso, "country": "US", "event_name": name,
            "impact": impact, "currency": "", "unit": "",
            "previous": None, "estimate": est, "actual": None, "source": source}


@pytest.fixture()
def tmpdb(tmp_path):
    """A REAL DatabaseManager on a temp file — never the live singleton path.

    Rebinds `.path` per the recorded rule (patching config.DB_PATH isolates
    nothing: the singleton bakes its path at construction).
    """
    from core.database import db as _db
    old_path, old_conn = _db.path, _db._conn
    _db.path = str(tmp_path / "cal.db")
    _db._conn = None
    asyncio.run(_db.initialize())
    yield _db
    asyncio.run(_db.close())
    _db.path, _db._conn = old_path, old_conn


class TestCalendarDbLayer:
    def test_the_source_column_exists_after_initialize(self, tmpdb):
        async def go():
            async with tmpdb._conn.execute("PRAGMA table_info(economic_calendar)") as c:
                return [r[1] for r in await c.fetchall()]
        assert "source" in asyncio.run(go())

    def test_rebuild_deletes_ONLY_its_own_source_in_the_window(self, tmpdb):
        """THE safety property. Without `source = ?` the FRED rebuild wipes
        the 6k legacy rows (and any other provider's) inside the window."""
        async def go():
            await tmpdb.upsert_calendar_events([
                _mkrow("Legacy CPI", "2026-08-10T12:30:00+00:00", ""),
                _mkrow("Other CPI", "2026-08-11T12:30:00+00:00", "finnhub"),
                _mkrow("Stale FRED", "2026-08-12T12:30:00+00:00", "fred"),
            ])
            await tmpdb.replace_calendar_events(
                "fred", "2026-08-01T00:00:00+00:00", "2026-08-31T23:59:59+00:00",
                [_mkrow("Fresh FRED", "2026-08-20T12:30:00+00:00", "fred")])
            return await tmpdb.get_calendar_events()
        names = {r["event_name"]: r["source"] for r in asyncio.run(go())}
        assert "Legacy CPI" in names and names["Legacy CPI"] == ""
        assert "Other CPI" in names and names["Other CPI"] == "finnhub"
        assert "Fresh FRED" in names
        assert "Stale FRED" not in names, "the rebuild failed to clear its own stale row"

    def test_rebuild_never_reaches_outside_its_window(self, tmpdb):
        async def go():
            await tmpdb.upsert_calendar_events([
                _mkrow("Before", "2026-07-01T12:30:00+00:00", "fred"),
                _mkrow("After", "2026-09-30T12:30:00+00:00", "fred"),
            ])
            await tmpdb.replace_calendar_events(
                "fred", "2026-08-01T00:00:00+00:00", "2026-08-31T23:59:59+00:00", [])
            return {r["event_name"] for r in await tmpdb.get_calendar_events()}
        assert asyncio.run(go()) == {"Before", "After"}

    def test_an_empty_rebuild_clears_the_window_durably(self, tmpdb):
        """A quiet window must overwrite stale rows — and must COMMIT, which
        the inner upsert's `if not rows` early-return does not do."""
        async def go():
            await tmpdb.upsert_calendar_events(
                [_mkrow("Gone", "2026-08-15T12:30:00+00:00", "fred")])
            await tmpdb.replace_calendar_events(
                "fred", "2026-08-01T00:00:00+00:00", "2026-08-31T23:59:59+00:00", [])
            await tmpdb.close()          # force a fresh connection — proves durability
            tmpdb._conn = None
            await tmpdb.initialize()
            return await tmpdb.get_calendar_events()
        assert asyncio.run(go()) == []

    def test_a_foreign_provider_row_is_not_clobbered_on_conflict(self, tmpdb):
        """CPI/PPI/Claims/ADP/New Home Sales collide EXACTLY across providers
        (same name, same UTC offset). Without the conflict guard a FRED write
        nulls the other provider's consensus figures and steals the row, and
        the next rebuild's DELETE then removes it entirely."""
        iso = "2026-08-12T12:30:00+00:00"
        async def go():
            await tmpdb.upsert_calendar_events([_mkrow("CPI", iso, "finnhub", est=3.2)])
            await tmpdb.upsert_calendar_events([_mkrow("CPI", iso, "fred")])
            return (await tmpdb.get_calendar_events())[0]
        row = asyncio.run(go())
        assert row["source"] == "finnhub", "FRED stole a row it does not own"
        assert row["estimate"] == 3.2, "the consensus figure was nulled"

    def test_a_legacy_unknown_row_IS_adoptable(self, tmpdb):
        """'' means provenance unknown, not 'owned by someone else' — those
        rows are deliberately adoptable so the calendar can heal."""
        iso = "2026-08-12T12:30:00+00:00"
        async def go():
            await tmpdb.upsert_calendar_events([_mkrow("CPI", iso, "")])
            await tmpdb.upsert_calendar_events([_mkrow("CPI", iso, "fred")])
            return (await tmpdb.get_calendar_events())[0]
        assert asyncio.run(go())["source"] == "fred"

    def test_meta_is_derived_from_the_table(self, tmpdb):
        async def go():
            await tmpdb.upsert_calendar_events([
                _mkrow("A", "2026-08-10T12:30:00+00:00", "fred"),
                _mkrow("B", "2026-08-11T12:30:00+00:00", ""),
            ])
            return await tmpdb.get_calendar_meta()
        m = asyncio.run(go())
        assert m["stored_total"] == 2
        assert sorted(m["sources"]) == ["", "fred"]
        assert m["last_fetch"]

    def test_meta_on_an_empty_table_is_honest_not_zeroed(self, tmpdb):
        m = asyncio.run(tmpdb.get_calendar_meta())
        assert m["stored_total"] == 0
        assert m["last_fetch"] is None       # 'never', not a fabricated stamp
        assert m["sources"] == []


# ── the route envelope ──────────────────────────────────────────────────────

class TestCalendarRouteProvenance:
    def test_envelope_carries_derived_meta(self, monkeypatch):
        import api.routes_news as rn

        class FakeDb:
            captured = {}

            async def get_calendar_events(self, from_date="", to_date="", impact=""):
                FakeDb.captured = {"from": from_date, "to": to_date, "impact": impact}
                return [{"event_name": "CPI", "impact": "high"}]

            async def get_calendar_meta(self):
                return {"stored_total": 6278, "last_fetch": "2026-06-09 06:12:45",
                        "sources": ["", "fred"]}

        monkeypatch.setattr(rn, "db", FakeDb())
        resp = asyncio.run(rn.api_calendar(from_date="2026-07-08", to_date="2026-09-06"))
        body = json.loads(resp.body)
        assert [e["event_name"] for e in body["events"]] == ["CPI"]
        m = body["meta"]
        assert m["stored_total"] == 6278            # DERIVED, not asserted
        assert m["last_fetch"] == "2026-06-09 06:12:45"
        assert m["window_count"] == 1
        assert m["window"] == {"from": "2026-07-08", "to": "2026-09-06"}
        assert "no consensus" in m["coverage"] and "ISM" in m["coverage"]

    def test_the_to_date_boundary_no_longer_drops_the_final_day(self, monkeypatch):
        """`event_time <= to_date` is a STRING compare, and
        '2026-09-06T12:30:00+00:00' <= '2026-09-06' is False — every event on
        the last day of the window was silently dropped (pre-existing; it bit
        the Finnhub era too)."""
        import api.routes_news as rn

        class FakeDb:
            seen = {}

            async def get_calendar_events(self, from_date="", to_date="", impact=""):
                FakeDb.seen["to"] = to_date
                return []

            async def get_calendar_meta(self):
                return {"stored_total": 0, "last_fetch": None, "sources": []}

        monkeypatch.setattr(rn, "db", FakeDb())
        asyncio.run(rn.api_calendar(from_date="2026-07-08", to_date="2026-09-06"))
        assert FakeDb.seen["to"] == "2026-09-06T23:59:59+00:00"
        assert "2026-09-06T12:30:00+00:00" <= FakeDb.seen["to"]


# ── the pane's four honest states (source pins) ─────────────────────────────

_RG = _code((_ROOT / "frontend" / "src" / "pages-regime.jsx").read_text(encoding="utf-8"))


def _cal_branches():
    """The calendar pane's empty-state chain, parsed into ordered branches.

    STRUCTURAL, not substring-presence. The audit defeated five substring pins
    at once — deleting `calErr && `, deleting the whole filter-empty branch,
    OR-ing `|| true` into the store-empty guard, neutering _calRel, and
    dropping the Retry cta — all with 29 tests green. Parsing the chain means
    a deleted branch changes the LIST, not just a missing substring.
    """
    seg = _RG[_RG.index("Economic Calendar"):]
    seg = seg[:seg.index("</Pane>")]
    out = []
    for m in re.finditer(r"<EmptyState.*?/>", seg, re.S):
        head = seg[:m.start()]
        # the condition is the text between the previous chain link and the `?`
        q = head.rindex("?")
        start = max(head.rfind("{", 0, q), head.rfind(":", 0, q)) + 1
        out.append((head[start:q].strip(), m.group(0)))
    return out


class TestPaneStatesTheTruth:
    def test_the_stripper_is_not_vacuous(self):
        assert len([l for l in _RG.splitlines() if l.strip()]) > 800
        assert "/*" not in _RG
        assert "Economic Calendar" in _RG

    def test_the_calendar_error_flag_is_finally_destructured(self):
        """`err` was thrown away for the calendar while the news half kept it
        — the root of the whole defect."""
        assert "err: calErr" in _RG
        assert "reload: reloadCal" in _RG

    def test_it_reads_the_envelope_not_a_bare_array(self):
        assert "Array.isArray(calData.events)" in _RG
        assert "calData.meta" in _RG
        assert "Array.isArray(calData) ? calData : []" not in _RG

    def test_the_false_message_is_gone_and_gated_on_a_REAL_empty_store(self):
        """"no calendar events stored" may only appear when the store is
        genuinely empty — it was rendering over 6,278 stored rows."""
        i = _RG.index('msg="no calendar events stored"')
        guard = _RG[max(0, i - 260):i]
        assert "calMeta.stored_total === 0" in guard

    def test_the_window_empty_state_names_the_cause(self):
        """DESIGN.md's degraded-pane rule: name the CAUSE, don't just blank."""
        assert 'msg="no events in this ±30d window"' in _RG
        i = _RG.index('msg="no events in this ±30d window"')
        seg = _RG[i:i + 400]
        assert "calMeta.stored_total" in seg      # how many DO exist
        assert "_calRel(calMeta.last_fetch)" in seg   # and how stale

    def test_the_error_state_uses_the_ratified_cause_helper(self):
        assert "qeFootCause(calErr)" in _RG
        assert 'hint="press ↻ on Market News to fetch (finnhub)"' not in _RG

    def test_standing_provenance_is_always_on_screen(self):
        assert "US · FRED" in _RG

    def test_the_provenance_chip_cannot_rename_the_pane(self):
        """e2e derives each pane's CONTROL ID from its head TEXT, stripping a
        fixed class list (e2e/lib/inpage.ts headTitle). A bare span would
        rename this pane to 'economic calendar us fred - - utc' and orphan all
        four of its ids in e2e/manifest/controls.json — a green-looking change
        that silently fails the crawl gate. Derived from inpage.ts so the
        strip list and this chip can never drift apart."""
        i = _RG.index("US · FRED")
        chip = _RG[_RG.rindex("<span", 0, i):i]
        inpage = (_ROOT / "e2e" / "lib" / "inpage.ts").read_text(encoding="utf-8")
        strip = re.search(r"clone\.querySelectorAll\('([^']+)'\)", inpage).group(1)
        classes = {c.strip().lstrip(".") for c in strip.split(",") if c.strip().startswith(".")}
        assert any(f"qe-badge" == c and c in chip for c in classes), \
            f"the chip carries no class that headTitle strips: {chip!r}"

    def test_all_FIVE_states_exist_as_distinct_ORDERED_branches(self):
        """FIVE causes, five messages — the pane previously had one, and it
        was the wrong one. Parses the ternary chain so DELETING a branch fails
        here; the first draft counted message substrings and stayed green when
        the audit deleted the entire filter-empty arm."""
        branches = _cal_branches()
        conds = [c for c, _ in branches]
        assert len(branches) == 5, [c[:44] for c in conds]

        # The ORDER is the correctness argument: error → not-yet-answered →
        # genuinely-empty store → empty window over a populated store →
        # filtered-to-nothing. Any reordering makes an earlier branch swallow
        # a later cause and re-creates a wrong-message bug.
        assert "calErr" in conds[0]
        assert "!calHasMeta" in conds[1]
        assert "stored_total === 0" in conds[2]
        assert conds[3] == "calAll.length === 0"
        assert conds[4] == "cal.length === 0"

        # each branch renders a DIFFERENT message
        msgs = re.findall(r'msg=[{"`]([^"`}]+)', "".join(b for _, b in branches))
        assert len(set(msgs)) == len(msgs) >= 4, msgs

    def test_the_error_branch_keeps_its_recovery_affordance(self):
        """Deleting the `cta` left every pin green — an error state with no way
        back is a dead end on a pane that polls every 60s."""
        err_branch = next(b for c, b in _cal_branches() if "calErr" in c)
        assert "cta=" in err_branch and "reloadCal" in err_branch

    def test_the_error_branch_is_gated_on_calErr_not_on_emptiness_alone(self):
        """Dropping `calErr &&` made EVERY genuinely-empty window claim the
        feed was unavailable — a new affirmative wrong signal replacing the
        old one."""
        assert "calErr && calAll.length === 0" in _RG

    def test_the_store_empty_guard_cannot_be_widened(self):
        """`|| true` on this guard restores the ORIGINAL bug verbatim: "no
        calendar events stored" over 6,278 stored rows."""
        i = _RG.index('msg="no calendar events stored"')
        guard = _RG[max(0, i - 300):i]
        assert re.search(r"calAll\.length === 0 && calMeta\.stored_total === 0\s*\?", guard)
        assert "||" not in guard.split("stored_total === 0")[-1]

    def test_calrel_actually_computes_relative_age(self):
        """Neutering _calRel to a constant left every pin green — and the
        whole point of the field is that 59 days reads as ALARMING."""
        i = _RG.index("const _calRel")
        body = _RG[i:_RG.index("const [calUrl]", i)]
        assert "Date.now() - ms" in body
        for unit in ("m ago", "h ago", "d ago"):
            assert unit in body
        assert "'never'" in body            # null last_fetch
        assert "Number.isFinite(ms)" in body  # garbage last_fetch


# ── the wiring is two-sided ─────────────────────────────────────────────────

class TestWiring:
    _SCHED = (_ROOT / "core" / "schedulers.py").read_text(encoding="utf-8")
    _ROUTES = (_ROOT / "api" / "routes_news.py").read_text(encoding="utf-8")

    def test_the_scheduler_drives_FRED_not_finnhub_for_the_calendar(self):
        assert "FredCalendarFetcher" in self._SCHED
        assert "calendar.fetch_calendar(minus30, plus30)" in self._SCHED
        assert "fetcher.fetch_calendar" not in self._SCHED

    def test_the_cooldown_is_banked_only_on_a_fetch_that_reached_FRED(self):
        """`fetch_calendar` fails soft, so advancing `last_calendar_ts`
        unconditionally made a transient error cost a full 10 minutes of
        staleness — the exact back-off the design meant to avoid. It returns
        None when it could not reach FRED, and the caller must honour that."""
        i = self._SCHED.index("async def _news_refresh_loop")
        body = self._SCHED[i:self._SCHED.index("\nasync def ", i + 10)]
        assert "wrote = await calendar.fetch_calendar" in body
        assert "if wrote is not None:" in body
        # and the assignment must be INSIDE that guard
        after = body[body.index("if wrote is not None:"):]
        assert after.split("\n")[1].strip() == "last_calendar_ts = now_ts"

    def test_news_stays_on_finnhub(self):
        """Only the CALENDAR moved — Finnhub news works and returns 100 items."""
        assert 'fetcher.fetch_news(category="general")' in self._SCHED

    def test_the_manual_refresh_button_also_uses_FRED(self):
        assert "FredCalendarFetcher().fetch_calendar" in self._ROUTES

    def test_the_schema_migration_is_in_the_post_ALTER_block(self):
        """CLAUDE.md's schema-change trap: _CREATE_STATEMENTS runs first via
        executescript, so an ALTER-dependent statement placed there kills boot
        on a legacy-shaped DB."""
        src = (_ROOT / "core" / "database.py").read_text(encoding="utf-8")
        alter = "ALTER TABLE economic_calendar ADD COLUMN source"
        assert alter in src
        assert src.index("_CREATE_STATEMENTS = ") < src.index(alter)
        # and the canonical CREATE carries it too, for fresh installs
        create = src[src.index("CREATE TABLE IF NOT EXISTS economic_calendar"):]
        assert "source       TEXT    NOT NULL DEFAULT ''" in create[:600]
