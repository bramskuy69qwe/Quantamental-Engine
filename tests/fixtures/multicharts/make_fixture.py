"""
Generator for the synthetic MultiCharts fixture (v2.7 plan task 2.7).

Mirrors the REAL ``@ES - 1 Minute`` export's verified layout (2026-07-16
inspection) at ~1/60th the size — the 1.17 MB original stays outside the
repo. Regenerate with:

    .venv/Scripts/python.exe tests/fixtures/multicharts/make_fixture.py

Layout quirks deliberately reproduced (the parser is tested against them):
- 8 sheets incl. the three empty ``* Graphs`` placeholders
- ``List of Trades``: title row 1, blank row 2, header row 3;
  two rows per trade (Entry carries Trade#/Profit/Cum/Drawdown, Exit
  carries Order#/Price/Signal); one TRAILING UNPAIRED Entry (open
  position at export) that the parser must skip
- ``Strategy Analysis``: ``Max Strategy Drawdown``/``(%)`` NEGATIVE,
  ``Profit Factor`` signed-NEGATIVE (the MC gotcha), ``% Profitable``
  as a fraction, both ``Sharpe Ratio`` and ``Annualized Sharpe Ratio``
- ``Settings``: ``Point Value`` as the string ``"$50"``, numeric
  ``Initial Capital``, datetime ``Start/End Date``
- One exit signal (``EOD``) outside the TP/SL families to pin the
  raw-lowercase exit_reason path

Known synthetic values the tests assert:
  10 closed trades (wins = trades 1-5, losses = 6-10, so BOTH sides win
  AND lose — long/short alternate); 5 wins x +100 / 5 losses x -50 ->
  net 250, gross 500 / -250 -> true profit factor 2.0; win rate 0.5;
  initial capital 100000; point value 50; contracts 2. The Strategy
  Analysis ``Profit Factor`` cell is written as -1.9 — deliberately
  INCONSISTENT with the gross-derived 2.0 so tests prove the parser
  recomputes from gross rather than abs()-ing the cell.

Sized at 10 closed trades instead of task 2.7's "~20" because 10
already exercises every row shape (both sides x both outcomes, EOD
exit, trailing open entry) — more rows add bytes, not coverage.
"""
from __future__ import annotations

import os
import shutil
from datetime import datetime, timedelta

import openpyxl

HERE = os.path.dirname(os.path.abspath(__file__))
XLSX = os.path.join(HERE, "mc_synthetic.xlsx")
XML = os.path.join(HERE, "mc_synthetic.xml")

BASE = datetime(2026, 6, 24, 9, 30)


def build() -> None:
    wb = openpyxl.Workbook()

    # ── Strategy Analysis ────────────────────────────────────────────────
    sa = wb.active
    sa.title = "Strategy Analysis"
    sa.append(["Strategy Performance Summary"])
    sa.append([])
    sa.append([None, "All Trades", "Long Trades", "Short Trades"])
    for label, value in [
        ("Net Profit", 250.0),
        ("Gross Profit", 500.0),
        ("Gross Loss", -250.0),
        ("Account Size Required", 1112.5),
        ("Max Strategy Drawdown", -120.0),          # NEGATIVE, like MC
        ("Max Strategy Drawdown (%)", -0.0012),     # NEGATIVE fraction
        # Signed-negative gotcha AND deliberately inconsistent with the
        # gross-derived 2.0 (500/abs(-250)) — pins the recompute path.
        ("Profit Factor", -1.9),
        ("Total # of Trades", 10),
        ("% Profitable", 0.5),                      # fraction
    ]:
        sa.append([label, value])
    sa.append([])
    sa.append(["Performance Ratios"])
    sa.append(["Sharpe Ratio", 0])
    sa.append(["Annualized Sharpe Ratio", 1.25])
    sa.append(["Sortino Ratio", 0])

    wb.create_sheet("Strategy Analysis Graphs")  # images only in the real file

    # ── List of Trades ───────────────────────────────────────────────────
    lot = wb.create_sheet("List of Trades")
    lot.append(["List of Trades"])
    lot.append([])
    lot.append([
        "Trade #", "Order #", "Type", "Signal", "Date", "Time", "Price",
        "Contracts", "Profit ($)", "Profit (%)", "Cum. Profit ($)",
        "Cum. Profit (%)", "Run-up ($)", "Run-up (%)",
        "Drawdown ($)", "Drawdown (%)",
    ])
    cum = 0.0
    order_no = 1
    for i in range(10):
        long = i % 2 == 0
        # Wins = first 5, losses = last 5 — long/short alternate, so both
        # sides appear in both outcomes (short+TP, long+SL exercised).
        pnl = 100.0 if i < 5 else -50.0
        cum += pnl
        entry_dt = BASE + timedelta(minutes=10 * i)
        exit_dt = entry_dt + timedelta(minutes=5)
        entry_price = 5000.0 + i
        exit_price = entry_price + (1.0 if pnl > 0 else -0.5) * (1 if long else -1)
        if i == 9:
            signal = "EOD"                      # non-TP/SL exit family
        else:
            signal = ("L_TP" if long else "S_TP") if pnl > 0 else \
                     ("L_SL" if long else "S_SL")
        lot.append([
            i + 1, order_no, "EntryLong" if long else "EntryShort",
            "ORB_L" if long else "ORB_S", entry_dt, entry_dt, entry_price,
            2, pnl, pnl / 100000.0, cum, cum / 100000.0,
            25.0, 0.00025, -25.0, -0.00025,     # Drawdown ($) NEGATIVE
        ])
        order_no += 1
        lot.append([
            None, order_no, "ExitLong" if long else "ExitShort",
            signal, exit_dt, exit_dt, exit_price, 2,
            None, None, None, None, None, None, None, None,
        ])
        order_no += 1
    # Trailing unpaired Entry — open position at export time; parser skips.
    lot.append([
        11, order_no, "EntryLong", "ORB_L",
        BASE + timedelta(minutes=100), BASE + timedelta(minutes=100),
        5010.0, 2, None, None, None, None, None, None, None, None,
    ])

    wb.create_sheet("Trade Analysis")
    wb.create_sheet("Trade Analysis Graphs")
    wb.create_sheet("Periodical Analysis")
    wb.create_sheet("Periodical Analysis Graphs")

    # ── Settings ─────────────────────────────────────────────────────────
    st = wb.create_sheet("Settings")
    st.append(["Settings"])
    st.append([])
    st.append(["SYNTH STRAT"])
    st.append(["ORMinutes", "30"])
    st.append(["RiskPctOfEquity", "1.0"])
    st.append(["Symbol Name", "@ES"])
    st.append(["Symbol Currency", "USD"])
    st.append(["Initial Capital", 100000])
    st.append(["Compression", "1 Minute"])
    st.append(["Point Value", "$50"])           # string with $, like MC
    st.append(["Start Date", BASE])
    st.append(["End Date", BASE + timedelta(minutes=105)])
    st.append(["Export Time", BASE + timedelta(hours=12)])

    wb.save(XLSX)
    # MC's ".xml" export is the same OOXML zip under a different extension —
    # the adapter sniffs magic bytes, so the .xml fixture is a byte copy.
    shutil.copyfile(XLSX, XML)
    print(f"wrote {XLSX}\nwrote {XML}")


if __name__ == "__main__":
    build()
