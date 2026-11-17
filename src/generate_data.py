"""Generate a synthetic B2B accounts-receivable dataset for collections and bad debt analysis.

Everything is simulated (no real companies or people). The simulation runs each invoice's
full life, then cuts the data off at AS_OF so the files look like a real ledger extract
taken on 31 Dec 2025.

Behaviour deliberately built into the data (so the analysis has something to find):
  * Credit score band drives late payment and default risk (A best, D worst).
  * SMB customers and the Hospitality / Construction industries are riskier.
  * Alberta deteriorates for invoices raised from March 2025 (a regional slowdown),
    and risk rises slightly everywhere from July 2025.
  * Collectors differ in how quickly they make first contact. Contact within 7 days of
    the due date shortens delays and rescues some accounts that would otherwise default.

Outputs (data/):
  customers.csv, invoices.csv, payments.csv, collection_activities.csv,
  aging_snapshot.csv (invoice-level month-end balances), roll_rates.csv (aggregated
  month-to-month bucket movement), aging_history.csv (aggregated month-end aging),
  dim_date.csv
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

SEED = 42
DATA_START = pd.Timestamp("2023-07-01")  # history so AR is "warm" by the reporting start
REPORT_START = pd.Timestamp("2024-01-01")
AS_OF = pd.Timestamp("2025-12-31")
N_CUSTOMERS = 400

BUCKETS = ["Current", "1-30", "31-60", "61-90", "91-120", "120+"]

REGIONS = {"Ontario": 0.34, "Quebec": 0.20, "British Columbia": 0.16,
           "Alberta": 0.14, "Prairies": 0.08, "Atlantic": 0.08}
SEGMENTS = {"SMB": 0.60, "Mid-Market": 0.30, "Enterprise": 0.10}
INDUSTRY_RISK = {"Construction": 1.3, "Retail": 1.1, "Manufacturing": 1.0, "Healthcare": 0.7,
                 "Hospitality": 1.5, "Transportation": 1.1, "Professional Services": 0.8,
                 "Energy": 1.0}
# collector_id: (name, probability of first contact within 7 days past due)
COLLECTORS = {
    "COL1": ("Arjun Mehta", 0.85),
    "COL2": ("Sofia Rossi", 0.75),
    "COL3": ("Daniel Okafor", 0.60),
    "COL4": ("Emily Tremblay", 0.45),
    "COL5": ("Liam Gagnon", 0.30),
}

BAND_DEFAULT = {"A": 0.003, "B": 0.010, "C": 0.030, "D": 0.080}
BAND_LATE = {"A": 0.15, "B": 0.30, "C": 0.45, "D": 0.60}
BAND_LATE_DAYS = {"A": 8, "B": 14, "C": 22, "D": 35}
SEG_DEFAULT = {"SMB": 1.3, "Mid-Market": 1.0, "Enterprise": 0.5}
SEG_LATE = {"SMB": 1.1, "Mid-Market": 1.0, "Enterprise": 0.8}
SEG_INVOICES_PER_MONTH = {"SMB": 0.7, "Mid-Market": 1.2, "Enterprise": 2.0}
SEG_MEDIAN_AMOUNT = {"SMB": 2_500, "Mid-Market": 12_000, "Enterprise": 45_000}

NAME_A = ["Maple", "Granite", "Cedar", "Harbour", "Prairie", "Summit", "Aurora", "Birch",
          "Lakeshore", "Ridge", "Northstar", "Silverline", "Bluewater", "Redwood", "Ironwood",
          "Westbrook", "Pinecrest", "Riverside", "Highland", "Coastal", "Evergreen", "Falcon",
          "Glacier", "Juniper", "Keystone", "Lumen", "Meadow", "Oakridge", "Polaris", "Quarry"]
NAME_B = ["Logistics", "Builders", "Foods", "Supply", "Dental", "Motors", "Design", "Energy",
          "Hospitality", "Systems", "Contracting", "Clinics", "Freight", "Fabrication",
          "Interiors", "Partners", "Retail", "Tooling", "Services", "Distribution"]
NAME_C = ["Inc.", "Ltd.", "Corp.", "Co.", "Group"]


def bucket_of(dpd: np.ndarray) -> np.ndarray:
    dpd = np.asarray(dpd)
    out = np.full(dpd.shape, "120+", dtype=object)
    out[dpd <= 120] = "91-120"
    out[dpd <= 90] = "61-90"
    out[dpd <= 60] = "31-60"
    out[dpd <= 30] = "1-30"
    out[dpd <= 0] = "Current"
    return out


def make_customers(rng: np.random.Generator) -> pd.DataFrame:
    seg = rng.choice(list(SEGMENTS), N_CUSTOMERS, p=list(SEGMENTS.values()))
    region = rng.choice(list(REGIONS), N_CUSTOMERS, p=list(REGIONS.values()))
    industry = rng.choice(list(INDUSTRY_RISK), N_CUSTOMERS)
    mean_score = np.select([seg == "SMB", seg == "Mid-Market"], [660, 700], 750)
    score = np.clip(rng.normal(mean_score, 70), 450, 880).round().astype(int)
    band = np.select([score >= 750, score >= 680, score >= 600], ["A", "B", "C"], "D")
    terms = np.where(seg == "Enterprise", rng.choice([45, 60], N_CUSTOMERS, p=[0.3, 0.7]),
                     np.where(seg == "Mid-Market",
                              rng.choice([30, 45], N_CUSTOMERS, p=[0.6, 0.4]), 30))
    limit = np.select([seg == "SMB", seg == "Mid-Market"], [25_000, 150_000], 600_000)
    collector = rng.choice(list(COLLECTORS), N_CUSTOMERS)

    names, seen = [], set()
    for _ in range(N_CUSTOMERS):
        while True:
            n = f"{rng.choice(NAME_A)} {rng.choice(NAME_B)} {rng.choice(NAME_C)}"
            if n not in seen:
                seen.add(n)
                names.append(n)
                break

    return pd.DataFrame({
        "customer_id": [f"CUST{i:04d}" for i in range(1, N_CUSTOMERS + 1)],
        "customer_name": names,
        "segment": seg,
        "region": region,
        "industry": industry,
        "credit_score": score,
        "credit_band": band,
        "payment_terms_days": terms,
        "credit_limit": limit,
        "collector_id": collector,
        "collector_name": [COLLECTORS[c][0] for c in collector],
    })


def simulate_invoices(rng: np.random.Generator, cust: pd.DataFrame):
    months = pd.date_range(DATA_START, AS_OF, freq="MS")
    rows = []
    for c in cust.itertuples(index=False):
        lam = SEG_INVOICES_PER_MONTH[c.segment]
        for m in months:
            for _ in range(rng.poisson(lam)):
                day = int(rng.integers(0, m.days_in_month))
                rows.append((c.customer_id, m + pd.Timedelta(days=day)))
    inv = pd.DataFrame(rows, columns=["customer_id", "invoice_date"])
    inv = inv.sort_values(["invoice_date", "customer_id"]).reset_index(drop=True)
    inv.insert(0, "invoice_id", [f"INV{i:06d}" for i in range(1, len(inv) + 1)])
    inv = inv.merge(cust, on="customer_id", how="left")
    n = len(inv)

    med = inv["segment"].map(SEG_MEDIAN_AMOUNT).to_numpy()
    inv["invoice_amount"] = np.round(med * rng.lognormal(0, 0.6, n), 2)
    inv["due_date"] = inv["invoice_date"] + pd.to_timedelta(inv["payment_terms_days"], unit="D")

    # --- risk drivers -------------------------------------------------------------
    band = inv["credit_band"]
    time_mult = np.ones(n)
    time_mult[(inv["region"] == "Alberta") & (inv["invoice_date"] >= "2025-03-01")] *= 2.0
    time_mult[inv["invoice_date"] >= "2025-07-01"] *= 1.15
    p_def = (band.map(BAND_DEFAULT) * inv["segment"].map(SEG_DEFAULT)
             * inv["industry"].map(INDUSTRY_RISK)).to_numpy() * time_mult
    p_late = np.minimum(0.95, (band.map(BAND_LATE) * inv["segment"].map(SEG_LATE)).to_numpy()
                        * np.sqrt(time_mult))

    default = rng.random(n) < p_def
    late = ~default & (rng.random(n) < p_late)
    early_prop = inv["collector_id"].map({k: v[1] for k, v in COLLECTORS.items()}).to_numpy()
    early = (default | late) & (rng.random(n) < early_prop)

    rescued = default & early & (rng.random(n) < 0.55)
    default &= ~rescued

    days_late = np.ceil(rng.exponential(band.map(BAND_LATE_DAYS).to_numpy()) + 1)
    days_late = np.where(early, np.ceil(days_late * 0.6), days_late)
    days_late = np.where(rescued, rng.integers(40, 101, n), days_late)
    days_late = np.minimum(days_late, 150).astype(int)
    # chronic slow payers: pay in the end, but only after 3-7 months (more often when no
    # one chased them early)
    slow = late & (rng.random(n) < np.where(early, 0.03, 0.08))
    days_late = np.where(slow, rng.integers(95, 211, n), days_late)
    on_time_offset = -rng.integers(0, 8, n)
    offset = np.where(late | rescued, days_late, on_time_offset)

    inv_date = inv["invoice_date"].to_numpy()
    due = inv["due_date"].to_numpy()
    pay_date = due + offset.astype("timedelta64[D]")
    pay_date = np.maximum(pay_date, inv_date + np.timedelta64(3, "D"))

    amount = inv["invoice_amount"].to_numpy()
    payments = []  # (invoice_id, date, amount, type)
    wo_date = np.full(n, np.datetime64("NaT"), dtype="datetime64[ns]")
    wo_amount = np.zeros(n)
    ids = inv["invoice_id"].to_numpy()

    instal = rng.random(n) < 0.12
    frac1 = rng.uniform(0.3, 0.6, n)
    gap1 = rng.integers(10, 31, n)
    pre_wo_partial = rng.random(n) < 0.4
    pre_frac = rng.uniform(0.1, 0.5, n)
    pre_dpd = rng.integers(20, 101, n)
    wo_dpd = rng.integers(150, 211, n)
    recov = rng.random(n) < 0.3
    recov_frac = rng.uniform(0.2, 0.6, n)
    recov_gap = rng.integers(30, 181, n)

    for i in range(n):
        if not default[i]:
            if instal[i]:
                d1 = max(pay_date[i] - np.timedelta64(int(gap1[i]), "D"),
                         inv_date[i] + np.timedelta64(1, "D"))
                a1 = round(amount[i] * frac1[i], 2)
                payments.append((ids[i], d1, a1, "Payment"))
                payments.append((ids[i], pay_date[i], round(amount[i] - a1, 2), "Payment"))
            else:
                payments.append((ids[i], pay_date[i], amount[i], "Payment"))
        else:
            paid = 0.0
            if pre_wo_partial[i]:
                paid = round(amount[i] * pre_frac[i], 2)
                payments.append((ids[i], due[i] + np.timedelta64(int(pre_dpd[i]), "D"),
                                 paid, "Payment"))
            wo_date[i] = due[i] + np.timedelta64(int(wo_dpd[i]), "D")
            wo_amount[i] = round(amount[i] - paid, 2)
            if recov[i]:
                payments.append((ids[i], wo_date[i] + np.timedelta64(int(recov_gap[i]), "D"),
                                 round(wo_amount[i] * recov_frac[i], 2), "Recovery"))

    pay = pd.DataFrame(payments, columns=["invoice_id", "payment_date", "amount", "payment_type"])
    inv["wo_date_full"] = wo_date
    inv["wo_amount_full"] = wo_amount
    inv["resolution_date"] = pd.to_datetime(np.where(default, wo_date, pay_date))
    return inv, pay, early


def make_activities(rng: np.random.Generator, inv: pd.DataFrame, pay: pd.DataFrame,
                    early_flag: np.ndarray) -> pd.DataFrame:
    """Collector touches on invoices that went past due."""
    pay_dates = pay[pay["payment_type"] == "Payment"].groupby("invoice_id")["payment_date"] \
        .apply(lambda s: np.sort(s.to_numpy()))
    rows = []
    for idx, r in enumerate(inv.itertuples(index=False)):
        res = r.resolution_date
        if res <= r.due_date:
            continue
        first = int(rng.integers(1, 8)) if early_flag[idx] else int(rng.integers(10, 36))
        d = r.due_date + pd.Timedelta(days=first)
        is_default = not pd.isna(r.wo_date_full)
        pdates = pay_dates.get(r.invoice_id, np.array([], dtype="datetime64[ns]"))
        letter = agency = False
        k = 0
        while d < res and d <= AS_OF and k < 14:
            dpd = (d - r.due_date).days
            if k == 0:
                typ = "Email reminder"
            elif is_default and dpd > 120 and not agency:
                typ, agency = "Agency referral", True
            elif dpd > 60 and not letter:
                typ, letter = "Demand letter", True
            else:
                typ = "Phone call" if k % 2 else "Email reminder"
            nxt = pdates[pdates > np.datetime64(d)]
            pays_soon = len(nxt) > 0 and (nxt[0] - np.datetime64(d)) <= np.timedelta64(14, "D")
            if typ == "Agency referral":
                outcome = "Referred to agency"
            elif pays_soon and rng.random() < 0.7:
                outcome = "Promise to pay"
            else:
                outcome = rng.choice(["No response", "Contacted - no commitment",
                                      "Promise to pay", "Dispute raised"],
                                     p=[0.5, 0.25, 0.15, 0.10])
            kept = (1 if pays_soon else 0) if outcome == "Promise to pay" else None
            rows.append((r.invoice_id, r.customer_id, r.collector_id, d, dpd, typ, outcome, kept))
            d = d + pd.Timedelta(days=int(rng.integers(7, 15)))
            k += 1
    act = pd.DataFrame(rows, columns=["invoice_id", "customer_id", "collector_id",
                                      "activity_date", "days_past_due", "activity_type",
                                      "outcome", "promise_kept"])
    act.insert(0, "activity_id", [f"ACT{i:06d}" for i in range(1, len(act) + 1)])
    act["promise_kept"] = act["promise_kept"].astype("Int64")
    return act


def month_end_snapshots(inv: pd.DataFrame, pay: pd.DataFrame) -> pd.DataFrame:
    """Invoice-level open balance at each month end."""
    month_ends = pd.date_range("2023-12-31", AS_OF, freq="ME")
    p = pay[pay["payment_type"] == "Payment"]
    snaps = []
    for m in month_ends:
        live = inv[inv["invoice_date"] <= m]
        paid = p[p["payment_date"] <= m].groupby("invoice_id")["amount"].sum()
        bal = (live["invoice_amount"] - live["invoice_id"].map(paid).fillna(0)
               - np.where(live["write_off_date"] <= m, live["write_off_amount"], 0))
        bal = bal.round(2)
        keep = bal > 0.005
        s = live.loc[keep, ["invoice_id", "customer_id", "due_date"]].copy()
        s["balance"] = bal[keep]
        s["days_past_due"] = (m - s["due_date"]).dt.days.clip(lower=0)
        s["aging_bucket"] = bucket_of(s["days_past_due"].to_numpy())
        s.insert(0, "snapshot_date", m)
        snaps.append(s.drop(columns="due_date"))
    return pd.concat(snaps, ignore_index=True)


def roll_table(snap: pd.DataFrame, inv: pd.DataFrame) -> pd.DataFrame:
    rank = {b: i for i, b in enumerate(BUCKETS)}
    months = sorted(snap["snapshot_date"].unique())
    wo = inv.set_index("invoice_id")["write_off_date"]
    out = []
    for m0, m1 in zip(months[:-1], months[1:]):
        s0 = snap[snap["snapshot_date"] == m0]
        s1 = snap[snap["snapshot_date"] == m1].set_index("invoice_id")["aging_bucket"]
        nb = s0["invoice_id"].map(s1)
        w = s0["invoice_id"].map(wo)
        outcome = np.where(nb.isna(),
                           np.where((w > m0) & (w <= m1), "Written off", "Paid"),
                           np.where(nb.map(rank).fillna(-1).to_numpy()
                                    > s0["aging_bucket"].map(rank).to_numpy(),
                                    "Rolled forward", "Stayed"))
        t = s0[["invoice_id", "customer_id", "aging_bucket", "balance"]].copy()
        t["from_month"] = m0
        t["outcome"] = outcome
        out.append(t)
    return pd.concat(out, ignore_index=True)


def aggregate(snap: pd.DataFrame, inv: pd.DataFrame, cust: pd.DataFrame):
    """Month-end aging history and month-to-month roll movement, by region and segment."""
    rolls = roll_table(snap, inv)
    seg_reg = cust.set_index("customer_id")[["region", "segment"]]
    hist = snap.join(seg_reg, on="customer_id").groupby(
        ["snapshot_date", "region", "segment", "aging_bucket"], as_index=False) \
        .agg(invoices=("invoice_id", "count"), balance=("balance", "sum"))
    roll_agg = rolls.join(seg_reg, on="customer_id").groupby(
        ["from_month", "region", "segment", "aging_bucket", "outcome"], as_index=False) \
        .agg(invoices=("invoice_id", "count"), balance=("balance", "sum")) \
        .rename(columns={"aging_bucket": "from_bucket"})
    hist["balance"] = hist["balance"].round(2)
    roll_agg["balance"] = roll_agg["balance"].round(2)
    return hist, roll_agg


def main(out_dir: Path) -> None:
    rng = np.random.default_rng(SEED)
    out_dir.mkdir(parents=True, exist_ok=True)
    cust = make_customers(rng)
    inv, pay_full, early_flag = simulate_invoices(rng, cust)

    # --- cut off at AS_OF -----------------------------------------------------------
    pay = pay_full[pay_full["payment_date"] <= AS_OF].copy()
    inv["write_off_date"] = inv["wo_date_full"].where(inv["wo_date_full"] <= AS_OF)
    inv["write_off_amount"] = np.where(inv["write_off_date"].notna(), inv["wo_amount_full"], 0.0)

    act = make_activities(rng, inv, pay_full, early_flag)
    act = act[act["activity_date"] <= AS_OF].reset_index(drop=True)

    p_only = pay[pay["payment_type"] == "Payment"]
    r_only = pay[pay["payment_type"] == "Recovery"]
    inv["amount_paid"] = inv["invoice_id"].map(p_only.groupby("invoice_id")["amount"].sum()) \
        .fillna(0).round(2)
    inv["recovery_amount"] = inv["invoice_id"].map(r_only.groupby("invoice_id")["amount"].sum()) \
        .fillna(0).round(2)
    inv["recovery_date"] = inv["invoice_id"].map(r_only.groupby("invoice_id")["payment_date"].max())
    inv["open_balance"] = (inv["invoice_amount"] - inv["amount_paid"]
                           - inv["write_off_amount"]).round(2).clip(lower=0)
    last_pay = p_only.groupby("invoice_id")["payment_date"].max()
    full = inv["open_balance"] <= 0.005
    inv["paid_in_full_date"] = inv["invoice_id"].map(last_pay).where(
        full & inv["write_off_date"].isna())
    inv["days_to_pay"] = (inv["paid_in_full_date"] - inv["invoice_date"]).dt.days.astype("Int64")
    inv["status"] = np.select([inv["write_off_date"].notna(), full], ["Written off", "Paid"], "Open")
    dpd = (AS_OF - inv["due_date"]).dt.days.clip(lower=0)
    inv["days_past_due"] = np.where(inv["status"] == "Open", dpd, 0)
    inv["aging_bucket"] = np.where(inv["status"] == "Open",
                                   bucket_of(inv["days_past_due"].to_numpy()), "Closed")
    fc = act.groupby("invoice_id")["days_past_due"].min()
    inv["first_contact_dpd"] = inv["invoice_id"].map(fc).astype("Int64")

    inv_cols = ["invoice_id", "customer_id", "invoice_date", "due_date", "invoice_amount",
                "amount_paid", "paid_in_full_date", "days_to_pay", "write_off_date",
                "write_off_amount", "recovery_amount", "recovery_date", "open_balance",
                "status", "days_past_due", "aging_bucket", "first_contact_dpd"]
    invoices = inv[inv_cols]

    snap = month_end_snapshots(inv, pay)
    hist, roll_agg = aggregate(snap, inv, cust)

    dates = pd.DataFrame({"date": pd.date_range(DATA_START, AS_OF, freq="D")})
    dates["year"] = dates["date"].dt.year
    dates["quarter"] = "Q" + dates["date"].dt.quarter.astype(str)
    dates["month_num"] = dates["date"].dt.month
    dates["month_name"] = dates["date"].dt.strftime("%b")
    dates["year_month"] = dates["date"].dt.strftime("%Y-%m")
    dates["month_end"] = dates["date"] + pd.offsets.MonthEnd(0)
    dates["is_reporting_period"] = dates["date"] >= REPORT_START

    fmt = "%Y-%m-%d"
    cust.to_csv(out_dir / "customers.csv", index=False)
    invoices.to_csv(out_dir / "invoices.csv", index=False, date_format=fmt)
    pay = pay.sort_values(["payment_date", "invoice_id"]).reset_index(drop=True)
    pay.insert(0, "payment_id", [f"PAY{i:06d}" for i in range(1, len(pay) + 1)])
    pay.to_csv(out_dir / "payments.csv", index=False, date_format=fmt)
    act.to_csv(out_dir / "collection_activities.csv", index=False, date_format=fmt)
    snap.to_csv(out_dir / "aging_snapshot.csv", index=False, date_format=fmt)
    hist.to_csv(out_dir / "aging_history.csv", index=False, date_format=fmt)
    roll_agg.to_csv(out_dir / "roll_rates.csv", index=False, date_format=fmt)
    dates.to_csv(out_dir / "dim_date.csv", index=False, date_format=fmt)

    print(f"customers {len(cust):,}  invoices {len(invoices):,}  payments {len(pay):,}  "
          f"activities {len(act):,}  snapshot rows {len(snap):,}")


if __name__ == "__main__":
    main(Path(__file__).resolve().parents[1] / "data")
