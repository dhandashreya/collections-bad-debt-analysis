"""Headline analysis: findings (printed + saved to reports/findings.md) and README figures."""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.ticker  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402
from matplotlib.ticker import FuncFormatter, PercentFormatter  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DATA, FIG, REP = ROOT / "data", ROOT / "figures", ROOT / "reports"
AS_OF = pd.Timestamp("2025-12-31")
BUCKETS = ["Current", "1-30", "31-60", "61-90", "91-120", "120+"]

BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
INK, INK2, GRID = "#0b0b0b", "#52514e", "#e4e3df"
SEQ = LinearSegmentedColormap.from_list(
    "blues", ["#f4f8fd", "#cde2fb", "#86b6ef", "#3987e5", "#1c5cab", "#0d366b"])

plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 10, "axes.edgecolor": GRID,
    "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
    "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True,
    "grid.color": GRID, "grid.linewidth": 0.8, "axes.axisbelow": True,
    "axes.titleweight": "bold", "axes.titlesize": 12, "axes.titlecolor": INK,
    "axes.titlelocation": "left", "figure.dpi": 150, "savefig.bbox": "tight",
    "figure.facecolor": "white",
})
money = FuncFormatter(lambda v, _: f"${v/1e6:.1f}M" if abs(v) >= 1e6 else f"${v/1e3:.0f}K")


def load():
    cust = pd.read_csv(DATA / "customers.csv")
    inv = pd.read_csv(DATA / "invoices.csv", parse_dates=[
        "invoice_date", "due_date", "paid_in_full_date", "write_off_date", "recovery_date"])
    hist = pd.read_csv(DATA / "aging_history.csv", parse_dates=["snapshot_date"])
    rolls = pd.read_csv(DATA / "roll_rates.csv", parse_dates=["from_month"])
    act = pd.read_csv(DATA / "collection_activities.csv", parse_dates=["activity_date"])
    return inv.merge(cust, on="customer_id"), hist, rolls, act


def monthly(d, hist):
    m = pd.date_range("2024-01-31", AS_OF, freq="ME")
    ar = hist.groupby("snapshot_date")["balance"].sum()
    cur = hist[hist["aging_bucket"] == "Current"].groupby("snapshot_date")["balance"].sum()
    o90 = hist[hist["aging_bucket"].isin(["91-120", "120+"])].groupby("snapshot_date")["balance"].sum()
    sales = d.groupby(d["invoice_date"] + pd.offsets.MonthEnd(0))["invoice_amount"].sum()
    out = pd.DataFrame(index=m)
    out["x"] = m - pd.offsets.MonthBegin(1)  # plot each month at its first day
    out["ar"] = ar.reindex(m).fillna(0)
    out["current"] = cur.reindex(m).fillna(0)
    out["over90"] = o90.reindex(m).fillna(0)
    out["sales"] = sales.reindex(m).fillna(0)
    s3 = sales.rolling(3).sum().reindex(m)
    days3 = np.array([(x - (x - pd.offsets.MonthEnd(3))).days for x in m])
    out["dso"] = out["ar"] / s3 * days3
    prior = ar.reindex(m - pd.offsets.MonthEnd(1)).to_numpy()
    out["cei"] = (prior + out["sales"] - out["ar"]) / (prior + out["sales"] - out["current"])
    out["pct_past_due"] = 1 - out["current"] / out["ar"]
    out["pct_90"] = out["over90"] / out["ar"]
    return out


def roll_rates(rolls, start, end):
    w = rolls[(rolls["from_month"] > start) & (rolls["from_month"] <= end)]
    rates = []
    for b in BUCKETS:
        x = w[w["from_bucket"] == b].groupby("outcome")["balance"].sum()
        if b == "120+":
            rates.append(x.get("Written off", 0) / (x.get("Written off", 0) + x.get("Paid", 0)))
        else:
            rates.append((x.get("Rolled forward", 0) + x.get("Written off", 0)) / x.sum())
    return np.array(rates)


def main():
    FIG.mkdir(exist_ok=True)
    REP.mkdir(exist_ok=True)
    d, hist, rolls, act = load()
    mt = monthly(d, hist)
    lines = []

    def say(s=""):
        print(s)
        lines.append(s)

    open_ = d[d["status"] == "Open"]
    ar = open_["open_balance"].sum()
    aging = open_.groupby("aging_bucket")["open_balance"].sum().reindex(BUCKETS).fillna(0)
    say("# Findings (as of 31 Dec 2025)\n")
    say(f"- Open AR: ${ar:,.0f}; past due {1 - aging['Current']/ar:.1%}; "
        f"over 90 days {(aging['91-120'] + aging['120+'])/ar:.1%}")
    dec24, dec25 = mt.loc["2024-12-31"], mt.loc["2025-12-31"]
    say(f"- DSO: {dec24.dso:.1f} days (Dec 2024) → {dec25.dso:.1f} days (Dec 2025)")
    say(f"- % past due: {dec24.pct_past_due:.1%} → {dec25.pct_past_due:.1%}; "
        f"% 90+: {dec24.pct_90:.1%} → {dec25.pct_90:.1%}")
    say(f"- Average monthly CEI, 2025: {mt.loc['2025', 'cei'].mean():.1%} "
        f"(2024: {mt.loc['2024', 'cei'].mean():.1%})")
    for y in (2024, 2025):
        s = d[d["invoice_date"].dt.year == y]["invoice_amount"].sum()
        wo = d[d["write_off_date"].dt.year == y]["write_off_amount"].sum()
        rc = d[d["recovery_date"].dt.year == y]["recovery_amount"].sum()
        say(f"- {y}: sales ${s:,.0f}, write-offs ${wo:,.0f}, recoveries ${rc:,.0f}, "
            f"net bad debt {(wo - rc)/s:.2%} of sales")

    rr = roll_rates(rolls, AS_OF - pd.offsets.MonthEnd(13), AS_OF - pd.offsets.MonthEnd(1))
    loss = np.cumprod(rr[::-1])[::-1]
    allowance = float((aging.to_numpy() * loss).sum())
    say("- 12-month roll rates: " + ", ".join(f"{b} {r:.1%}" for b, r in zip(BUCKETS, rr)))
    say("- Implied loss rates: " + ", ".join(f"{b} {r:.2%}" for b, r in zip(BUCKETS, loss)))
    say(f"- Required allowance (roll-rate method): ${allowance:,.0f} = {allowance/ar:.2%} of AR")

    # credit band / segment risk (lifetime net loss rate on invoices old enough to resolve)
    mature = d[d["due_date"] <= "2025-06-30"]
    band = mature.groupby("credit_band").apply(
        lambda g: g["write_off_amount"].sum() / g["invoice_amount"].sum(), include_groups=False)
    seg = mature.groupby("segment").apply(
        lambda g: g["write_off_amount"].sum() / g["invoice_amount"].sum(), include_groups=False)
    say("- Write-off rate by credit band (invoices due by Jun 2025): "
        + ", ".join(f"{k} {v:.2%}" for k, v in band.items()))
    say("- Write-off rate by segment: " + ", ".join(f"{k} {v:.2%}" for k, v in seg.items()))
    ind = mature.groupby("industry").apply(
        lambda g: g["write_off_amount"].sum() / g["invoice_amount"].sum(), include_groups=False) \
        .sort_values(ascending=False)
    say("- Highest-loss industries: " + ", ".join(f"{k} {v:.2%}" for k, v in ind.head(3).items()))

    # regional deterioration: 90+ share at Dec 2024 vs Dec 2025
    hr = hist.groupby(["snapshot_date", "region"]).apply(
        lambda g: g.loc[g["aging_bucket"].isin(["91-120", "120+"]), "balance"].sum()
        / g["balance"].sum(), include_groups=False).unstack()
    pdr = hist.groupby(["snapshot_date", "region"]).apply(
        lambda g: g.loc[g["aging_bucket"] != "Current", "balance"].sum() / g["balance"].sum(),
        include_groups=False).unstack()
    say(f"- Alberta % over 90 days: {hr.loc['2024-12-31', 'Alberta']:.1%} (Dec 2024) → "
        f"{hr.loc['2025-12-31', 'Alberta']:.1%} (Dec 2025)")
    say(f"- Alberta % past due: {pdr.loc['2024-12-31', 'Alberta']:.1%} (Dec 2024) → "
        f"{pdr.loc['2025-12-31', 'Alberta']:.1%} (Dec 2025); rest of country "
        f"{pdr.loc['2025-12-31'].drop('Alberta').mean():.1%} average")

    # early contact: invoices still unpaid 7 days after due, resolved, due by Jun 2025
    res = d["paid_in_full_date"].fillna(d["write_off_date"])
    pool = d[(res > d["due_date"] + pd.Timedelta(days=7)) & d["status"].ne("Open")
             & (d["due_date"] <= "2025-06-30")].copy()
    pool["early"] = pool["first_contact_dpd"].fillna(999) <= 7
    pool["days_late"] = (pool["paid_in_full_date"] - pool["due_date"]).dt.days
    g = pool.groupby("early").agg(n=("invoice_id", "count"),
                                  wo=("write_off_amount", "sum"),
                                  amt=("invoice_amount", "sum"),
                                  wo_n=("status", lambda s: (s == "Written off").mean()),
                                  late=("days_late", "median"))
    g["wo_rate"] = g["wo"] / g["amt"]
    e, l_ = g.loc[True], g.loc[False]
    say(f"- Early contact (first touch ≤7 days past due), {int(e.n)} vs {int(l_.n)} invoices "
        f"still unpaid at day 7: written off {e.wo_n:.1%} vs {l_.wo_n:.1%} of invoices; "
        f"$ loss rate {e.wo_rate:.2%} vs {l_.wo_rate:.2%}; median days late when paid "
        f"{e.late:.0f} vs {l_.late:.0f}")

    coll = d[d["first_contact_dpd"].notna()].groupby("collector_name").agg(
        early=("first_contact_dpd", lambda s: (s <= 7).mean()))
    life = d.groupby("collector_name").apply(
        lambda x: (x["write_off_amount"].sum() - x["recovery_amount"].sum())
        / x["invoice_amount"].sum(), include_groups=False)
    coll["net_loss"] = life
    kept = act[act["outcome"] == "Promise to pay"]["promise_kept"].mean()
    say(f"- Promise-to-pay kept rate: {kept:.1%}")
    say("- Collectors (early-contact rate, lifetime net loss rate): "
        + "; ".join(f"{k} {v.early:.0%}, {v.net_loss:.2%}" for k, v in coll.iterrows()))

    (REP / "findings.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    # ------------------------------------------------------------------ figures
    fig, ax = plt.subplots(figsize=(7, 3.4))
    bars = ax.bar(BUCKETS, aging.to_numpy(), color=BLUE, width=0.6)
    for b, v in zip(bars, aging.to_numpy()):
        ax.annotate(f"{v/ar:.1%}", (b.get_x() + b.get_width() / 2, v), ha="center",
                    va="bottom", fontsize=9, color=INK2, xytext=(0, 3), textcoords="offset points")
    ax.yaxis.set_major_formatter(money)
    ax.grid(axis="x", visible=False)
    ax.set_title("Open AR by aging bucket (days past due), 31 Dec 2025")
    fig.savefig(FIG / "01_aging.png")
    plt.close(fig)

    fig, axes = plt.subplots(1, 2, figsize=(10, 3.4))
    axes[0].plot(mt["x"], mt["dso"], color=BLUE, lw=2)
    axes[0].set_title("DSO (days, 3-month method)")
    axes[1].plot(mt["x"], mt["pct_past_due"], color=BLUE, lw=2, label="% past due")
    axes[1].plot(mt["x"], mt["pct_90"], color=ORANGE, lw=2, label="% over 90 days")
    axes[1].yaxis.set_major_formatter(PercentFormatter(1, 0))
    axes[1].yaxis.set_major_locator(matplotlib.ticker.MultipleLocator(0.05))
    axes[1].set_ylim(0, None)
    axes[1].set_title("Delinquency share of AR")
    axes[1].legend(frameon=False, loc="upper center", ncol=2, bbox_to_anchor=(0.5, -0.12))
    for a in axes:
        a.tick_params(axis="x", labelrotation=0)
        a.xaxis.set_major_formatter(matplotlib.dates.DateFormatter("%b %y"))
        a.xaxis.set_major_locator(matplotlib.dates.MonthLocator(bymonth=[1, 4, 7, 10]))
    fig.tight_layout()
    fig.savefig(FIG / "02_trend.png")
    plt.close(fig)

    # roll-rate heatmap by month
    months = pd.date_range("2024-01-31", AS_OF - pd.offsets.MonthEnd(1), freq="ME")
    grid = np.array([roll_rates(rolls, m - pd.offsets.MonthEnd(1), m) for m in months])
    fig, ax = plt.subplots(figsize=(10, 3.2))
    im = ax.imshow(grid.T, aspect="auto", cmap=SEQ, vmin=0, vmax=1)
    labels = ["Current→1-30", "1-30→31-60", "31-60→61-90", "61-90→91-120",
              "91-120→120+", "120+→write-off"]
    ax.set_yticks(range(6), labels)
    ax.set_xticks(range(0, len(months), 3), [m.strftime("%b %y") for m in months[::3]])
    ax.grid(False)
    for s in ax.spines.values():
        s.set_visible(False)
    cb = fig.colorbar(im, ax=ax, fraction=0.025, pad=0.01, format=PercentFormatter(1, 0))
    cb.outline.set_visible(False)
    ax.set_title("Monthly roll rates: share of each bucket's balance that moved to a worse bucket")
    fig.savefig(FIG / "03_roll_rates.png")
    plt.close(fig)

    # vintage curves: cumulative write-off % of quarterly cohort sales
    d["vintage"] = d["invoice_date"].dt.to_period("Q")
    fig, ax = plt.subplots(figsize=(7, 3.6))
    vint = [p for p in sorted(d["vintage"].unique()) if p <= pd.Period("2025Q2")]
    shades = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]
    sel = vint[::1][-7:]
    for col, v in zip(shades, sel):
        g_ = d[d["vintage"] == v]
        sales = g_["invoice_amount"].sum()
        start = v.start_time
        horizon = (AS_OF.year - v.end_time.year) * 12 + AS_OF.month - v.end_time.month
        ms = np.arange(0, min(horizon, 18) + 1)
        wo_m = ((g_["write_off_date"] - start).dt.days / 30.44).dropna()
        amt = g_.loc[wo_m.index, "write_off_amount"]
        cum = [amt[wo_m <= m].sum() / sales for m in ms]
        ax.plot(ms, cum, color=col, lw=2, label=str(v))
    ax.yaxis.set_major_formatter(PercentFormatter(1, 1))
    ax.set_xlabel("Months since start of invoice quarter")
    ax.xaxis.set_major_locator(matplotlib.ticker.MultipleLocator(3))
    ax.set_title("Vintage curves: cumulative write-offs as % of cohort sales")
    ax.legend(frameon=False, ncol=1, fontsize=8, loc="upper left", title="Invoice quarter",
              title_fontsize=8)
    fig.savefig(FIG / "04_vintage.png")
    plt.close(fig)

    fig, axes = plt.subplots(1, 2, figsize=(10, 3.2))
    labs = ["Contacted ≤7 days", "Contacted later"]
    vals = [e.wo_n, l_.wo_n]
    axes[0].bar(labs, vals, color=[AQUA, ORANGE], width=0.5)
    axes[0].yaxis.set_major_formatter(PercentFormatter(1, 0))
    axes[0].set_title("Share of late invoices written off")
    for i, v in enumerate(vals):
        axes[0].annotate(f"{v:.1%}", (i, v), ha="center", va="bottom", xytext=(0, 3),
                         textcoords="offset points", color=INK2)
    vals = [e.late, l_.late]
    axes[1].bar(labs, vals, color=[AQUA, ORANGE], width=0.5)
    axes[1].set_title("Median days late when finally paid")
    for i, v in enumerate(vals):
        axes[1].annotate(f"{v:.0f}", (i, v), ha="center", va="bottom", xytext=(0, 3),
                         textcoords="offset points", color=INK2)
    for a in axes:
        a.grid(axis="x", visible=False)
    fig.suptitle("Invoices still unpaid 7 days after due date (due Jul 2023 – Jun 2025)",
                 x=0.01, ha="left", fontsize=10, color=INK2)
    fig.tight_layout()
    fig.savefig(FIG / "05_early_contact.png")
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(7, 3.2))
    bars = ax.bar([f"Band {k}" for k in band.index], band.to_numpy(), color=BLUE, width=0.55)
    for bb, v in zip(bars, band.to_numpy()):
        ax.annotate(f"{v:.2%}", (bb.get_x() + bb.get_width() / 2, v), ha="center",
                    va="bottom", xytext=(0, 3), textcoords="offset points", color=INK2)
    ax.yaxis.set_major_formatter(PercentFormatter(1, 0))
    ax.grid(axis="x", visible=False)
    ax.set_title("Write-offs as % of sales by credit band (A = score 750+, D = under 600)")
    fig.savefig(FIG / "06_credit_band.png")
    plt.close(fig)
    print(f"\nfigures → {FIG}")


if __name__ == "__main__":
    main()
