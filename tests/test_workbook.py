"""Check the Excel formulas against independent pandas calculations.

The workbook is rebuilt from a 30-customer slice of the data (the full file is too slow for
a pure-Python formula engine), evaluated with `formulas`, and every key figure is compared
with the same metric computed directly in pandas.
"""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from openpyxl import load_workbook

import build_workbook as bw
import generate_data as gd
from excel_eval import evaluate

ROOT = Path(__file__).resolve().parents[1]
AS_OF = pd.Timestamp("2025-12-31")


@pytest.fixture(scope="module")
def subset():
    cust, inv, act, hist, rolls = bw.load(ROOT / "data")
    snap = pd.read_csv(ROOT / "data" / "aging_snapshot.csv", parse_dates=["snapshot_date"])
    keep = cust["customer_id"].iloc[:30]
    c = cust[cust["customer_id"].isin(keep)].reset_index(drop=True)
    i = inv[inv["customer_id"].isin(keep)].reset_index(drop=True)
    a = act[act["customer_id"].isin(keep)].reset_index(drop=True)
    s = snap[snap["customer_id"].isin(keep)]
    h, r = gd.aggregate(s, i, c)
    return c, i, a, h, r


@pytest.fixture(scope="module")
def book(subset, tmp_path_factory):
    path = tmp_path_factory.mktemp("wb") / "subset.xlsx"
    bw.build(*subset, path, booked_allowance=5_000)
    get, cells = evaluate(path)
    return get, cells, path


@pytest.fixture(scope="module")
def filtered_book(subset, book, tmp_path_factory):
    c = subset[0]
    region = c["region"].value_counts().index[0]
    wb = load_workbook(book[2])
    wb["Dashboard"]["C4"] = region
    path = tmp_path_factory.mktemp("wbf") / "filtered.xlsx"
    wb.save(path)
    get, cells = evaluate(path)
    return get, cells, region


def frame(subset):
    c, i, *_ = subset
    return i.merge(c, on="customer_id")


def approx(a, b, rel=1e-6, abs_=0.01):
    return a == pytest.approx(b, rel=rel, abs=abs_)


def test_no_formula_errors(book):
    _, cells, _ = book
    errors = {k: v for k, v in cells.items() if isinstance(v, str) and v.startswith("#")}
    assert not errors, list(errors.items())[:10]


def test_open_ar_and_buckets(book, subset):
    get, *_ = book
    d = frame(subset)
    assert approx(get("Trend", "Q12"), d["open_balance"].sum())
    by = d[d["status"] == "Open"].groupby("aging_bucket")["open_balance"].sum()
    for k, b in enumerate(bw.BUCKETS):
        assert approx(get("Trend", f"Q{6 + k}"), by.get(b, 0.0)), b


def test_history_ties_to_invoices(book):
    get, *_ = book
    # Dec 2025 month-end AR from the snapshot history must equal the invoice ledger
    assert approx(get("Trend", "C29"), get("Trend", "Q12"))


def test_monthly_sales_dso_and_cei(book, subset):
    get, *_ = book
    d = frame(subset)
    row = 6 + 17  # Jun 2025
    m = pd.Timestamp("2025-06-30")
    sales = d[(d["invoice_date"] > m - pd.offsets.MonthEnd(1)) & (d["invoice_date"] <= m)]
    assert approx(get("Trend", f"B{row}"), sales["invoice_amount"].sum())
    h = subset[3]
    ar = h.loc[h["snapshot_date"] == m, "balance"].sum()
    start = m - pd.offsets.MonthEnd(3)
    s3 = d[(d["invoice_date"] > start) & (d["invoice_date"] <= m)]["invoice_amount"].sum()
    assert approx(get("Trend", f"I{row}"), ar / s3 * (m - start).days)
    prior = h.loc[h["snapshot_date"] == m - pd.offsets.MonthEnd(1), "balance"].sum()
    cur = h.loc[(h["snapshot_date"] == m) & (h["aging_bucket"] == "Current"), "balance"].sum()
    s1 = sales["invoice_amount"].sum()
    assert approx(get("Trend", f"K{row}"), (prior + s1 - ar) / (prior + s1 - cur))


def test_roll_rates_and_allowance(book, subset):
    get, *_ = book
    r = subset[4]
    w = r[(r["from_month"] > AS_OF - pd.offsets.MonthEnd(13))
          & (r["from_month"] <= AS_OF - pd.offsets.MonthEnd(1))]
    rates = []
    for b in bw.BUCKETS:
        x = w[w["from_bucket"] == b].groupby("outcome")["balance"].sum()
        if b == "120+":
            den = x.get("Written off", 0) + x.get("Paid", 0)
            rates.append(x.get("Written off", 0) / den if den else 0.0)
        else:
            tot = x.sum()
            num = x.get("Rolled forward", 0) + x.get("Written off", 0)
            rates.append(num / tot if tot else 0.0)
    avg_row, loss_row = 30, 31
    for k, rate in enumerate(rates):
        assert approx(get("Roll Rates", f"{chr(66 + k)}{avg_row}"), rate, abs_=1e-9)
    loss = np.cumprod(rates[::-1])[::-1]
    for k, lr in enumerate(loss):
        assert approx(get("Roll Rates", f"{chr(66 + k)}{loss_row}"), lr, abs_=1e-9)
    d = frame(subset)
    by = d[d["status"] == "Open"].groupby("aging_bucket")["open_balance"].sum()
    expected = sum(by.get(b, 0.0) * loss[k] for k, b in enumerate(bw.BUCKETS))
    assert approx(get("Allowance", "F13"), expected)
    assert approx(get("Allowance", "B20"), expected - 5_000)


def test_top_customer(book, subset):
    get, *_ = book
    d = frame(subset)
    pd_ = d[d["days_past_due"] > 0].groupby("customer_name")["open_balance"].sum()
    top_row = None
    for r in range(1, 80):
        if get("Aging", f"A{r}") == 1.0 and get("Aging", f"B{r}") not in (None, "Customer"):
            top_row = r
            break
    assert top_row is not None
    assert get("Aging", f"B{top_row}") == pd_.idxmax()
    assert approx(get("Aging", f"G{top_row}"), pd_.max())


def test_collector_early_contact(book, subset):
    get, *_ = book
    d = frame(subset)
    names = sorted(subset[0]["collector_name"].unique())
    for k, nm in enumerate(names):
        x = d[(d["collector_name"] == nm) & (d["first_contact_dpd"] > 0)]
        exp = (x["first_contact_dpd"] <= 7).mean() if len(x) else 0.0
        assert approx(get("Collectors", f"H{6 + k}"), exp, abs_=1e-9), nm


def test_region_filter(filtered_book, subset):
    get, _, region = filtered_book
    d = frame(subset)
    x = d[d["region"] == region]
    assert approx(get("Trend", "Q12"), x["open_balance"].sum())
    assert approx(get("Dashboard", "B8"), x["open_balance"].sum())
    assert approx(get("Trend", "C29"), x["open_balance"].sum())
