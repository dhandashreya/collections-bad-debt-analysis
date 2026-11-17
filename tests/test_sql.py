"""Run every query in sql/ against the CSVs in SQLite and check the results against pandas."""
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
SQL = ROOT / "sql"
BUCKETS = ["Current", "1-30", "31-60", "61-90", "91-120", "120+"]


@pytest.fixture(scope="module")
def db():
    con = sqlite3.connect(":memory:")
    for name in ("customers", "invoices", "aging_snapshot", "roll_rates"):
        pd.read_csv(ROOT / "data" / f"{name}.csv").to_sql(name, con, index=False)
    yield con
    con.close()


def run(con, fname):
    return pd.read_sql_query((SQL / fname).read_text(encoding="utf-8"), con)


@pytest.fixture(scope="module")
def frames():
    inv = pd.read_csv(ROOT / "data" / "invoices.csv", parse_dates=[
        "invoice_date", "due_date", "paid_in_full_date", "write_off_date"])
    cust = pd.read_csv(ROOT / "data" / "customers.csv")
    hist = pd.read_csv(ROOT / "data" / "aging_history.csv", parse_dates=["snapshot_date"])
    rolls = pd.read_csv(ROOT / "data" / "roll_rates.csv", parse_dates=["from_month"])
    return inv.merge(cust, on="customer_id"), hist, rolls


def test_aging_by_region(db, frames):
    out = run(db, "01_aging_by_region.sql").set_index("region")
    d = frames[0]
    exp = d[d["status"] == "Open"].groupby("region")["open_balance"].sum()
    for region, v in exp.items():
        assert out.loc[region, "total_open_ar"] == pytest.approx(v, abs=0.05)


def test_dso_and_cei(db, frames):
    out = run(db, "02_monthly_dso_cei.sql").set_index("month_end")
    d, hist, _ = frames
    assert len(out) == 24 and out["dso"].notna().all()
    m = pd.Timestamp("2025-12-31")
    ar = hist.loc[hist["snapshot_date"] == m, "balance"].sum()
    start = m - pd.offsets.MonthEnd(3)
    s3 = d[(d["invoice_date"] > start) & (d["invoice_date"] <= m)]["invoice_amount"].sum()
    assert out.loc["2025-12-31", "dso"] == pytest.approx(ar / s3 * (m - start).days, abs=0.06)
    # first reporting month needs Nov-Dec 2023 sales, which exist in the data
    assert 30 < out.loc["2024-01-31", "dso"] < 80


def test_roll_rates_match_generator(db, frames):
    out = run(db, "03_roll_rates.sql").set_index("from_bucket")
    rolls = frames[2]
    w = rolls[(rolls["from_month"] > "2024-11-30") & (rolls["from_month"] <= "2025-11-30")]
    for b in BUCKETS:
        x = w[w["from_bucket"] == b].groupby("outcome")["balance"].sum()
        assert out.loc[b, "starting_balance"] == pytest.approx(x.sum(), abs=0.5)
        fwd = (x.get("Rolled forward", 0) + x.get("Written off", 0)) / x.sum()
        assert out.loc[b, "roll_rate"] == pytest.approx(fwd, abs=1e-4)
    x = w[w["from_bucket"] == "120+"].groupby("outcome")["balance"].sum()
    share = x.get("Written off", 0) / (x.get("Written off", 0) + x.get("Paid", 0))
    assert out.loc["120+", "writeoff_share_of_resolved"] == pytest.approx(share, abs=1e-4)


def test_vintage_curves_are_cumulative(db):
    out = run(db, "04_vintage_losses.sql")
    assert not out.empty
    for _, g in out.groupby("vintage"):
        assert np.all(np.diff(g.sort_values("months_since_start")["cum_writeoff_pct"]) >= 0)


def test_early_contact(db, frames):
    out = run(db, "05_early_contact.sql").set_index("contact_group")
    d = frames[0]
    res = d["paid_in_full_date"].fillna(d["write_off_date"])
    pool = d[(res > d["due_date"] + pd.Timedelta(days=7)) & d["status"].ne("Open")
             & (d["due_date"] <= "2025-06-30")]
    early = pool["first_contact_dpd"].fillna(999) <= 7
    for flag, name in ((True, "Contacted <=7 days"), (False, "Contacted later")):
        g = pool[early == flag]
        assert out.loc[name, "invoices"] == len(g)
        assert out.loc[name, "share_written_off"] == pytest.approx(
            (g["status"] == "Written off").mean(), abs=1e-4)
    # the effect the project reports: early contact roughly halves write-offs
    assert out.loc["Contacted <=7 days", "share_written_off"] < \
        0.8 * out.loc["Contacted later", "share_written_off"]
