"""Integrity checks on the generated ledger: balances reconcile across every table."""
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
D = ROOT / "data"
AS_OF = pd.Timestamp("2025-12-31")


@pytest.fixture(scope="module")
def t():
    return {
        "cust": pd.read_csv(D / "customers.csv"),
        "inv": pd.read_csv(D / "invoices.csv", parse_dates=[
            "invoice_date", "due_date", "paid_in_full_date", "write_off_date", "recovery_date"]),
        "pay": pd.read_csv(D / "payments.csv", parse_dates=["payment_date"]),
        "act": pd.read_csv(D / "collection_activities.csv", parse_dates=["activity_date"]),
        "snap": pd.read_csv(D / "aging_snapshot.csv", parse_dates=["snapshot_date"]),
        "hist": pd.read_csv(D / "aging_history.csv", parse_dates=["snapshot_date"]),
        "rolls": pd.read_csv(D / "roll_rates.csv", parse_dates=["from_month"]),
    }


def test_keys_unique_and_linked(t):
    assert t["cust"]["customer_id"].is_unique
    assert t["inv"]["invoice_id"].is_unique
    assert t["pay"]["payment_id"].is_unique
    assert t["inv"]["customer_id"].isin(t["cust"]["customer_id"]).all()
    assert t["pay"]["invoice_id"].isin(t["inv"]["invoice_id"]).all()
    assert t["act"]["invoice_id"].isin(t["inv"]["invoice_id"]).all()


def test_nothing_after_as_of(t):
    assert t["pay"]["payment_date"].max() <= AS_OF
    assert t["act"]["activity_date"].max() <= AS_OF
    assert t["inv"]["write_off_date"].max() <= AS_OF


def test_invoice_balances_reconcile(t):
    inv, pay = t["inv"], t["pay"]
    paid = pay[pay["payment_type"] == "Payment"].groupby("invoice_id")["amount"].sum()
    rec = pay[pay["payment_type"] == "Recovery"].groupby("invoice_id")["amount"].sum()
    assert (inv["amount_paid"] - inv["invoice_id"].map(paid).fillna(0)).abs().max() < 0.01
    assert (inv["recovery_amount"] - inv["invoice_id"].map(rec).fillna(0)).abs().max() < 0.01
    bal = inv["invoice_amount"] - inv["amount_paid"] - inv["write_off_amount"]
    assert (bal.clip(lower=0) - inv["open_balance"]).abs().max() < 0.01
    assert (inv["open_balance"] >= 0).all()
    # recoveries only on written-off invoices, never more than the write-off
    assert (inv.loc[inv["recovery_amount"] > 0, "status"] == "Written off").all()
    assert (inv["recovery_amount"] <= inv["write_off_amount"] + 0.01).all()


def test_snapshot_ties_to_ledger(t):
    snap, inv = t["snap"], t["inv"]
    last = snap[snap["snapshot_date"] == AS_OF]
    assert last["balance"].sum() == pytest.approx(inv["open_balance"].sum(), abs=1)
    assert t["hist"]["balance"].sum() == pytest.approx(snap["balance"].sum(), abs=1)


def test_roll_table_covers_every_starting_balance(t):
    snap, rolls = t["snap"], t["rolls"]
    start = snap[snap["snapshot_date"] < AS_OF]["balance"].sum()
    assert rolls["balance"].sum() == pytest.approx(start, abs=1)
    assert set(rolls["outcome"]) <= {"Paid", "Stayed", "Rolled forward", "Written off"}
