"""Build the Excel collections & bad debt dashboard from the CSVs in data/.

Every metric in the workbook is a live formula (SUMIFS / COUNTIFS / INDEX-MATCH) over the
data sheets, so changing the Region or Segment dropdown on the Dashboard recalculates
every sheet. Only Excel-2007-era functions are used, so it also works in LibreOffice
and Google Sheets.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
from openpyxl import Workbook
from openpyxl.chart import BarChart, LineChart, Reference
from openpyxl.comments import Comment
from openpyxl.formatting.rule import CellIsRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

ROOT = Path(__file__).resolve().parents[1]
BUCKETS = ["Current", "1-30", "31-60", "61-90", "91-120", "120+"]
REGIONS = ["Ontario", "Quebec", "British Columbia", "Alberta", "Prairies", "Atlantic"]
SEGMENTS = ["SMB", "Mid-Market", "Enterprise"]
BANDS = ["A", "B", "C", "D"]

FONT = "Arial"
NAVY = "1F3A5F"
LIGHT = "EEF2F7"
INPUT_FILL = PatternFill("solid", fgColor="FFFF00")
HEAD_FILL = PatternFill("solid", fgColor=NAVY)
BAND_FILL = PatternFill("solid", fgColor=LIGHT)
THIN = Side(style="thin", color="C9D1DC")
BOX = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)

USD = '$#,##0;($#,##0);"-"'
PCT = '0.0%;(0.0%);"-"'
PCT2 = '0.00%;(0.00%);"-"'
DAYS = '0.0;(0.0);"-"'
INT = '#,##0;(#,##0);"-"'
DATE = "yyyy-mm-dd"
MONTH = "mmm yyyy"

# Cross-sheet anchors (Lists sheet holds settings and filter criteria)
ASOF = "Lists!$B$1"
RC = "Lists!$B$3"  # region criterion: "*" when All
SC = "Lists!$B$4"  # segment criterion
SEL_REGION = "Dashboard!$C$4"
SEL_SEGMENT = "Dashboard!$C$5"


def f(size=10, bold=False, color="000000", italic=False):
    return Font(name=FONT, size=size, bold=bold, color=color, italic=italic)


def put(ws, ref, value, fmt=None, font=None, fill=None, align=None, border=None):
    c = ws[ref]
    c.value = value
    c.font = font or f()
    if fmt:
        c.number_format = fmt
    if fill:
        c.fill = fill
    if align:
        c.alignment = align
    if border:
        c.border = border
    return c


def header_row(ws, row, col, labels, widths=None):
    for i, lab in enumerate(labels):
        c = ws.cell(row=row, column=col + i, value=lab)
        c.font = f(bold=True, color="FFFFFF")
        c.fill = HEAD_FILL
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        c.border = BOX
    if widths:
        for i, w in enumerate(widths):
            ws.column_dimensions[get_column_letter(col + i)].width = w


def title(ws, text, sub=None):
    put(ws, "A1", text, font=f(16, True, NAVY))
    if sub:
        put(ws, "A2", sub, font=f(10, italic=True, color="555555"))


def filter_banner(ws, ref):
    put(ws, ref, f'="Filters  →  Region: "&{SEL_REGION}&"   ·   Segment: "&{SEL_SEGMENT}',
        font=f(10, True, "7A4E00"))


def write_table(ws, df: pd.DataFrame, formats: dict[str, str]):
    ws.append(list(df.columns))
    for c in ws[1]:
        c.font = f(bold=True, color="FFFFFF")
        c.fill = HEAD_FILL
    for row in df.itertuples(index=False):
        ws.append([None if pd.isna(v) else v for v in row])
    for j, col in enumerate(df.columns, start=1):
        letter = get_column_letter(j)
        ws.column_dimensions[letter].width = max(12, min(28, len(col) + 4))
        fmt = formats.get(col)
        for cell in ws[letter][1:]:
            cell.font = f()
            if fmt:
                cell.number_format = fmt
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions


def rng(sheet: str, col: str, last: int) -> str:
    return f"{sheet}!${col}$2:${col}${last}"


def load(data_dir: Path):
    cust = pd.read_csv(data_dir / "customers.csv")
    inv = pd.read_csv(data_dir / "invoices.csv",
                      parse_dates=["invoice_date", "due_date", "write_off_date", "recovery_date"])
    act = pd.read_csv(data_dir / "collection_activities.csv", parse_dates=["activity_date"])
    hist = pd.read_csv(data_dir / "aging_history.csv", parse_dates=["snapshot_date"])
    rolls = pd.read_csv(data_dir / "roll_rates.csv", parse_dates=["from_month"])
    return cust, inv, act, hist, rolls


def build(cust, inv, act, hist, rolls, out_path: Path, as_of="2025-12-31",
          booked_allowance: float | None = None) -> Path:
    as_of = pd.Timestamp(as_of)
    wb = Workbook()
    wb._named_styles["Normal"].font = Font(name=FONT, size=10)

    ws_about = wb.active
    ws_about.title = "About"
    ws_dash = wb.create_sheet("Dashboard")
    ws_aging = wb.create_sheet("Aging")
    ws_roll = wb.create_sheet("Roll Rates")
    ws_allow = wb.create_sheet("Allowance")
    ws_coll = wb.create_sheet("Collectors")
    ws_calc = wb.create_sheet("Trend")
    ws_cust = wb.create_sheet("Customers")
    ws_inv = wb.create_sheet("Invoices")
    ws_act = wb.create_sheet("Activities")
    ws_hist = wb.create_sheet("AgingHistory")
    ws_rd = wb.create_sheet("RollData")
    ws_list = wb.create_sheet("Lists")

    # ------------------------------------------------------------------ Lists
    put(ws_list, "A1", "As-of date (data extract)", font=f(bold=True))
    put(ws_list, "B1", as_of.to_pydatetime(), DATE, font=f(color="0000FF"))
    ws_list["B1"].comment = Comment("Date the ledger extract was taken. All aging is measured "
                                    "against this date. It matches the data, so leave it.", "model")
    put(ws_list, "A3", "Region criterion", font=f(bold=True))
    put(ws_list, "B3", f'=IF({SEL_REGION}="All","*",{SEL_REGION})')
    put(ws_list, "A4", "Segment criterion", font=f(bold=True))
    put(ws_list, "B4", f'=IF({SEL_SEGMENT}="All","*",{SEL_SEGMENT})')
    put(ws_list, "A5", '"*" matches every value, so "All" keeps every row in SUMIFS.',
        font=f(italic=True, color="555555"))
    for col, head, vals in (("D", "Regions", ["All"] + REGIONS),
                            ("F", "Segments", ["All"] + SEGMENTS),
                            ("H", "Buckets", BUCKETS)):
        put(ws_list, f"{col}1", head, font=f(bold=True))
        for i, v in enumerate(vals, start=2):
            put(ws_list, f"{col}{i}", v)
    ws_list.column_dimensions["A"].width = 26
    ws_list.column_dimensions["B"].width = 14
    ws_list.column_dimensions["D"].width = 18

    # ------------------------------------------------------------------ data sheets
    c_info = cust.set_index("customer_id")
    inv_x = inv.join(c_info[["region", "segment", "credit_band", "collector_name"]],
                     on="customer_id")
    inv_tbl = inv_x[["invoice_id", "customer_id", "region", "segment", "credit_band",
                     "collector_name", "invoice_date", "due_date", "invoice_amount",
                     "amount_paid", "write_off_date", "write_off_amount", "recovery_amount",
                     "recovery_date", "first_contact_dpd"]].copy()
    write_table(ws_inv, inv_tbl, {"invoice_date": DATE, "due_date": DATE, "write_off_date": DATE,
                                  "recovery_date": DATE, "invoice_amount": "#,##0.00",
                                  "amount_paid": "#,##0.00", "write_off_amount": "#,##0.00",
                                  "recovery_amount": "#,##0.00"})
    n_inv = len(inv_tbl) + 1
    # formula columns P, Q, R
    for col, head in (("P", "open_balance"), ("Q", "days_past_due"), ("R", "aging_bucket")):
        c = ws_inv[f"{col}1"]
        c.value, c.font, c.fill = head, f(bold=True, color="FFFFFF"), HEAD_FILL
        ws_inv.column_dimensions[col].width = 15
    for r in range(2, n_inv + 1):
        ws_inv[f"P{r}"] = f"=MAX(0,ROUND(I{r}-J{r}-L{r},2))"
        ws_inv[f"P{r}"].number_format = "#,##0.00"
        ws_inv[f"Q{r}"] = f"=IF(P{r}>0,MAX(0,{ASOF}-H{r}),0)"
        ws_inv[f"R{r}"] = (f'=IF(P{r}<=0,"Closed",IF(Q{r}=0,"Current",IF(Q{r}<=30,"1-30",'
                           f'IF(Q{r}<=60,"31-60",IF(Q{r}<=90,"61-90",IF(Q{r}<=120,"91-120",'
                           f'"120+"))))))')
    ws_inv.auto_filter.ref = f"A1:R{n_inv}"
    I = lambda col: rng("Invoices", col, n_inv)  # noqa: E731

    hist_tbl = hist[["snapshot_date", "region", "segment", "aging_bucket", "invoices", "balance"]]
    write_table(ws_hist, hist_tbl, {"snapshot_date": DATE, "balance": "#,##0.00"})
    n_h = len(hist_tbl) + 1
    H = lambda col: rng("AgingHistory", col, n_h)  # noqa: E731

    rd_tbl = rolls[["from_month", "region", "segment", "from_bucket", "outcome", "invoices",
                    "balance"]]
    write_table(ws_rd, rd_tbl, {"from_month": DATE, "balance": "#,##0.00"})
    n_r = len(rd_tbl) + 1
    R = lambda col: rng("RollData", col, n_r)  # noqa: E731

    act_x = act.join(c_info[["region", "segment", "collector_name"]], on="customer_id")
    act_tbl = act_x[["activity_id", "invoice_id", "customer_id", "region", "segment",
                     "collector_name", "activity_date", "days_past_due", "activity_type",
                     "outcome", "promise_kept"]]
    write_table(ws_act, act_tbl, {"activity_date": DATE})
    n_a = len(act_tbl) + 1
    A = lambda col: rng("Activities", col, n_a)  # noqa: E731

    cust_tbl = cust[["customer_id", "customer_name", "segment", "region", "industry",
                     "credit_score", "credit_band", "payment_terms_days", "credit_limit",
                     "collector_name"]]
    write_table(ws_cust, cust_tbl, {"credit_limit": "$#,##0"})
    n_c = len(cust_tbl) + 1
    extra = ["open_ar", "past_due", "over_90", "credit_utilization", "written_off_ttm",
             "rank_key (filtered past due)"]
    for i, head in enumerate(extra):
        col = get_column_letter(11 + i)
        c = ws_cust[f"{col}1"]
        c.value, c.font, c.fill = head, f(bold=True, color="FFFFFF"), HEAD_FILL
        ws_cust.column_dimensions[col].width = 16
    for r in range(2, n_c + 1):
        ws_cust[f"K{r}"] = f"=SUMIFS({I('P')},{I('B')},A{r})"
        ws_cust[f"L{r}"] = f'=SUMIFS({I("P")},{I("B")},A{r},{I("Q")},">0")'
        ws_cust[f"M{r}"] = f'=SUMIFS({I("P")},{I("B")},A{r},{I("Q")},">90")'
        ws_cust[f"N{r}"] = f"=IF(I{r}=0,0,K{r}/I{r})"
        ws_cust[f"O{r}"] = (f'=SUMIFS({I("L")},{I("B")},A{r},{I("K")},">"&EOMONTH({ASOF},-12))')
        ws_cust[f"P{r}"] = (f'=IF(AND(OR({SEL_REGION}="All",D{r}={SEL_REGION}),'
                            f'OR({SEL_SEGMENT}="All",C{r}={SEL_SEGMENT}),L{r}>0),'
                            f'L{r}+ROW()/1000000000,0)')
        for col, fmt in (("K", USD), ("L", USD), ("M", USD), ("N", PCT), ("O", USD)):
            ws_cust[f"{col}{r}"].number_format = fmt
    ws_cust.auto_filter.ref = f"A1:P{n_c}"
    C = lambda col: rng("Customers", col, n_c)  # noqa: E731

    filt_inv = f"{I('C')},{RC},{I('D')},{SC}"
    filt_h = f"{H('B')},{RC},{H('C')},{SC}"
    filt_r = f"{R('B')},{RC},{R('C')},{SC}"
    filt_a = f"{A('D')},{RC},{A('E')},{SC}"

    # ------------------------------------------------------------------ Trend (monthly)
    title(ws_calc, "Monthly trend", "Month-end receivables, collections efficiency and "
          "write-offs. Feeds the Dashboard charts.")
    filter_banner(ws_calc, "A3")
    heads = ["Month end", "Credit sales", "Open AR", "Current", "Past due", "90+ days",
             "% past due", "% 90+", "DSO (3-mo)", "Prior month AR", "CEI", "Write-offs",
             "Recoveries", "Net write-offs"]
    header_row(ws_calc, 5, 1, heads, [12, 14, 14, 14, 13, 13, 11, 10, 11, 14, 9, 12, 12, 13])
    months = pd.date_range("2024-01-31", as_of, freq="ME")
    t0 = 6
    for i, _ in enumerate(months):
        r = t0 + i
        ws_calc[f"A{r}"] = "=DATE(2024,1,31)" if i == 0 else f"=EOMONTH(A{r-1},1)"
        ws_calc[f"B{r}"] = (f'=SUMIFS({I("I")},{I("G")},">"&EOMONTH(A{r},-1),{I("G")},"<="&A{r},'
                            f'{filt_inv})')
        ws_calc[f"C{r}"] = f"=SUMIFS({H('F')},{H('A')},A{r},{filt_h})"
        ws_calc[f"D{r}"] = f'=SUMIFS({H("F")},{H("A")},A{r},{H("D")},"Current",{filt_h})'
        ws_calc[f"E{r}"] = f"=C{r}-D{r}"
        ws_calc[f"F{r}"] = (f'=SUMIFS({H("F")},{H("A")},A{r},{H("D")},"91-120",{filt_h})'
                            f'+SUMIFS({H("F")},{H("A")},A{r},{H("D")},"120+",{filt_h})')
        ws_calc[f"G{r}"] = f"=IF(C{r}=0,0,E{r}/C{r})"
        ws_calc[f"H{r}"] = f"=IF(C{r}=0,0,F{r}/C{r})"
        ws_calc[f"I{r}"] = (f'=IFERROR(C{r}/SUMIFS({I("I")},{I("G")},">"&EOMONTH(A{r},-3),'
                            f'{I("G")},"<="&A{r},{filt_inv})*(A{r}-EOMONTH(A{r},-3)),0)')
        ws_calc[f"J{r}"] = f"=SUMIFS({H('F')},{H('A')},EOMONTH(A{r},-1),{filt_h})"
        ws_calc[f"K{r}"] = f"=IFERROR((J{r}+B{r}-C{r})/(J{r}+B{r}-D{r}),0)"
        ws_calc[f"L{r}"] = (f'=SUMIFS({I("L")},{I("K")},">"&EOMONTH(A{r},-1),{I("K")},"<="&A{r},'
                            f'{filt_inv})')
        ws_calc[f"M{r}"] = (f'=SUMIFS({I("M")},{I("N")},">"&EOMONTH(A{r},-1),{I("N")},"<="&A{r},'
                            f'{filt_inv})')
        ws_calc[f"N{r}"] = f"=L{r}-M{r}"
        fmts = [MONTH, USD, USD, USD, USD, USD, PCT, PCT, DAYS, USD, PCT, USD, USD, USD]
        for j, fm in enumerate(fmts, start=1):
            c = ws_calc.cell(row=r, column=j)
            c.number_format, c.font, c.border = fm, f(), BOX
    t_last = t0 + len(months) - 1
    tot = t_last + 1
    put(ws_calc, f"A{tot}", "Last 12 mo", font=f(bold=True))
    for col in "BLMN":
        put(ws_calc, f"{col}{tot}", f"=SUM({col}{t_last-11}:{col}{t_last})", USD, f(bold=True))
    put(ws_calc, f"A{tot+2}", "CEI = (prior AR + sales − ending AR) ÷ (prior AR + sales − ending "
        "current AR). Write-offs also lower AR, so CEI is slightly flattering in months with "
        "large write-offs.", font=f(9, italic=True, color="555555"))
    put(ws_calc, f"A{tot+3}", "DSO = month-end AR ÷ credit sales of the last 3 months × days in "
        "those 3 months.", font=f(9, italic=True, color="555555"))
    ws_calc.freeze_panes = "B6"
    # aging bucket table + region table for charts
    put(ws_calc, "P5", "Aging bucket", font=f(bold=True, color="FFFFFF"), fill=HEAD_FILL)
    put(ws_calc, "Q5", "Open AR", font=f(bold=True, color="FFFFFF"), fill=HEAD_FILL)
    put(ws_calc, "R5", "% of AR", font=f(bold=True, color="FFFFFF"), fill=HEAD_FILL)
    for i, b in enumerate(BUCKETS):
        r = 6 + i
        put(ws_calc, f"P{r}", b, border=BOX)
        put(ws_calc, f"Q{r}", f'=SUMIFS({I("P")},{I("R")},P{r},{filt_inv})', USD, border=BOX)
        put(ws_calc, f"R{r}", f"=IF(SUM($Q$6:$Q$11)=0,0,Q{r}/SUM($Q$6:$Q$11))", PCT, border=BOX)
    put(ws_calc, "P12", "Total", font=f(bold=True))
    put(ws_calc, "Q12", "=SUM(Q6:Q11)", USD, f(bold=True))
    put(ws_calc, "P15", "Region", font=f(bold=True, color="FFFFFF"), fill=HEAD_FILL)
    put(ws_calc, "Q15", "Past due", font=f(bold=True, color="FFFFFF"), fill=HEAD_FILL)
    put(ws_calc, "R15", "% past due", font=f(bold=True, color="FFFFFF"), fill=HEAD_FILL)
    for i, reg in enumerate(REGIONS):
        r = 16 + i
        put(ws_calc, f"P{r}", reg, border=BOX)
        put(ws_calc, f"Q{r}", f'=SUMIFS({I("P")},{I("C")},P{r},{I("D")},{SC},{I("Q")},">0")',
            USD, border=BOX)
        put(ws_calc, f"R{r}", f'=IFERROR(Q{r}/SUMIFS({I("P")},{I("C")},P{r},{I("D")},{SC}),0)',
            PCT, border=BOX)
    put(ws_calc, "P22", "Region table ignores the Region filter (it compares regions).",
        font=f(9, italic=True, color="555555"))
    ws_calc.column_dimensions["P"].width = 16
    ws_calc.column_dimensions["Q"].width = 14
    ws_calc.column_dimensions["R"].width = 11

    # ------------------------------------------------------------------ Roll Rates
    title(ws_roll, "Roll rates & implied loss rates",
          "Share of each aging bucket's balance that moves to a worse bucket (or is written "
          "off) by the next month end.")
    filter_banner(ws_roll, "A3")
    trans = ["Current→1-30", "1-30→31-60", "31-60→61-90", "61-90→91-120", "91-120→120+",
             "120+→Write-off"]
    header_row(ws_roll, 5, 1, ["From month"] + trans, [12] + [14] * 6)
    roll_months = pd.date_range("2024-01-31", as_of - pd.offsets.MonthEnd(1), freq="ME")
    r0 = 6

    def roll_formula(month_ref: str, b: str, window: bool = False) -> str:
        if window:
            m = (f'{R("A")},">"&EOMONTH({ASOF},-13),{R("A")},"<="&EOMONTH({ASOF},-1)')
        else:
            m = f'{R("A")},{month_ref}'
        base = f'{m},{R("D")},"{b}",{filt_r}'
        wo = f'SUMIFS({R("G")},{base},{R("E")},"Written off")'
        if b == "120+":
            paid = f'SUMIFS({R("G")},{base},{R("E")},"Paid")'
            return f"=IFERROR({wo}/({wo}+{paid}),0)"
        fwd = f'SUMIFS({R("G")},{base},{R("E")},"Rolled forward")'
        return f"=IFERROR(({fwd}+{wo})/SUMIFS({R('G')},{base}),0)"

    for i, _ in enumerate(roll_months):
        r = r0 + i
        ws_roll[f"A{r}"] = "=DATE(2024,1,31)" if i == 0 else f"=EOMONTH(A{r-1},1)"
        ws_roll[f"A{r}"].number_format = MONTH
        for j, b in enumerate(BUCKETS):
            c = ws_roll.cell(row=r, column=2 + j, value=roll_formula(f"$A{r}", b))
            c.number_format, c.font, c.border = PCT, f(), BOX
    rl = r0 + len(roll_months) - 1
    avg_r, loss_r = rl + 2, rl + 3
    put(ws_roll, f"A{avg_r}", "12-mo weighted avg", font=f(bold=True), fill=BAND_FILL)
    put(ws_roll, f"A{loss_r}", "Implied loss rate", font=f(bold=True), fill=BAND_FILL)
    for j, b in enumerate(BUCKETS):
        col = get_column_letter(2 + j)
        put(ws_roll, f"{col}{avg_r}", roll_formula("", b, window=True), PCT, f(bold=True),
            BAND_FILL, border=BOX)
    # loss chain: last bucket = its own rate; others = roll × next bucket's loss
    last_col = get_column_letter(1 + len(BUCKETS))
    put(ws_roll, f"{last_col}{loss_r}", f"={last_col}{avg_r}", PCT2, f(bold=True), BAND_FILL,
        border=BOX)
    for j in range(len(BUCKETS) - 2, -1, -1):
        col, nxt = get_column_letter(2 + j), get_column_letter(3 + j)
        put(ws_roll, f"{col}{loss_r}", f"={col}{avg_r}*{nxt}{loss_r}", PCT2, f(bold=True),
            BAND_FILL, border=BOX)
    notes = [
        "Weighted average = total balance that rolled ÷ total starting balance over the 12 "
        "from-months ending one month before the as-of date (not an average of monthly rates).",
        "Implied loss rate for a bucket = product of its roll rate and every later roll rate: "
        "the share of today's balance in that bucket expected to end as a write-off.",
        "120+ column = balance written off ÷ (written off + paid) in the month, i.e. how "
        "120+ balances resolve once they leave the bucket.",
    ]
    for k, n in enumerate(notes):
        put(ws_roll, f"A{loss_r + 2 + k}", n, font=f(9, italic=True, color="555555"))
    ws_roll.freeze_panes = "B6"
    ws_roll.conditional_formatting.add(
        f"B{r0}:G{rl}", CellIsRule(operator="greaterThan", formula=["0.5"],
                                   fill=PatternFill("solid", fgColor="F8D7DA")))
    roll_avg_ref = lambda j: f"'Roll Rates'!${get_column_letter(2 + j)}${avg_r}"  # noqa: E731
    loss_ref = lambda j: f"'Roll Rates'!${get_column_letter(2 + j)}${loss_r}"  # noqa: E731

    # ------------------------------------------------------------------ Allowance
    title(ws_allow, "Allowance for doubtful accounts",
          "Expected credit loss on today's receivables using roll-rate (migration) loss rates.")
    filter_banner(ws_allow, "A3")
    put(ws_allow, "A4", "Yellow cells are inputs. Leave an override blank to use the implied "
        "rate from Roll Rates.", font=f(9, italic=True, color="555555"))
    header_row(ws_allow, 6, 1, ["Aging bucket", "Open AR", "Implied loss rate", "Override rate",
                                "Applied rate", "Required allowance", "Stressed allowance"],
               [16, 15, 15, 14, 13, 18, 18])
    for i, b in enumerate(BUCKETS):
        r = 7 + i
        put(ws_allow, f"A{r}", b, border=BOX)
        put(ws_allow, f"B{r}", f"=Trend!Q{6 + i}", USD, f(color="008000"), border=BOX)
        put(ws_allow, f"C{r}", f"={loss_ref(i)}", PCT2, f(color="008000"), border=BOX)
        put(ws_allow, f"D{r}", None, PCT2, f(color="0000FF"), INPUT_FILL, border=BOX)
        put(ws_allow, f"E{r}", f'=IF(D{r}="",C{r},D{r})', PCT2, border=BOX)
        put(ws_allow, f"F{r}", f"=B{r}*E{r}", USD, border=BOX)
        put(ws_allow, f"G{r}", f"=B{r}*MIN(1,E{r}*$B$17)", USD, border=BOX)
    put(ws_allow, "A13", "Total", font=f(bold=True))
    for col in "BFG":
        put(ws_allow, f"{col}13", f"=SUM({col}7:{col}12)", USD, f(bold=True))
    put(ws_allow, "E13", "=IF(B13=0,0,F13/B13)", PCT2, f(bold=True))
    put(ws_allow, "A15", "Assumptions", font=f(11, True, NAVY))
    put(ws_allow, "A16", "Allowance booked in GL")
    booked = booked_allowance if booked_allowance is not None else 0
    put(ws_allow, "B16", booked, USD, f(color="0000FF"), INPUT_FILL, border=BOX)
    ws_allow["B16"].comment = Comment(
        "Illustrative figure (assumption): the reserve currently on the balance sheet. "
        "Replace with your general-ledger balance. Applies to the full portfolio.", "model")
    put(ws_allow, "A17", "Stress multiplier on loss rates")
    put(ws_allow, "B17", 1.5, "0.00x", f(color="0000FF"), INPUT_FILL, border=BOX)
    ws_allow["B17"].comment = Comment("Assumption: a downturn scenario where every loss rate "
                                      "is 1.5× its historical level (capped at 100%).", "model")
    put(ws_allow, "A19", "Required allowance (base)", font=f(bold=True))
    put(ws_allow, "B19", "=F13", USD, f(bold=True))
    put(ws_allow, "A20", "Shortfall / (excess) vs booked", font=f(bold=True))
    put(ws_allow, "B20", f'=IF(AND({SEL_REGION}="All",{SEL_SEGMENT}="All"),B19-B16,"n/a")', USD,
        f(bold=True))
    put(ws_allow, "C20", "Compared only when both filters are All (the GL figure is company-wide).",
        font=f(9, italic=True, color="555555"))
    put(ws_allow, "A21", "Stressed allowance", font=f(bold=True))
    put(ws_allow, "B21", "=G13", USD, f(bold=True))
    ws_allow.column_dimensions["A"].width = 30

    # ------------------------------------------------------------------ Aging
    title(ws_aging, "Receivables aging", "Open balances by days past due as of the extract date.")
    filter_banner(ws_aging, "A3")
    cols = BUCKETS + ["Total", "% past due", "% 90+"]

    def aging_block(top: int, label: str, keys: list[str], key_rng: str, other: str):
        put(ws_aging, f"A{top}", label, font=f(11, True, NAVY))
        header_row(ws_aging, top + 1, 1, [label.split(" by ")[-1].title()] + cols,
                   [18] + [13] * 9)
        for i, k in enumerate(keys):
            r = top + 2 + i
            put(ws_aging, f"A{r}", k, border=BOX)
            for j, b in enumerate(BUCKETS):
                col = get_column_letter(2 + j)
                put(ws_aging, f"{col}{r}",
                    f'=SUMIFS({I("P")},{key_rng},$A{r},{I("R")},"{b}",{other})', USD,
                    border=BOX)
            put(ws_aging, f"H{r}", f"=SUM(B{r}:G{r})", USD, f(bold=True), border=BOX)
            put(ws_aging, f"I{r}", f"=IF(H{r}=0,0,SUM(C{r}:G{r})/H{r})", PCT, border=BOX)
            put(ws_aging, f"J{r}", f"=IF(H{r}=0,0,SUM(F{r}:G{r})/H{r})", PCT, border=BOX)
        tr = top + 2 + len(keys)
        put(ws_aging, f"A{tr}", "Total", font=f(bold=True), fill=BAND_FILL, border=BOX)
        for j in range(2, 9):
            col = get_column_letter(j)
            put(ws_aging, f"{col}{tr}", f"=SUM({col}{top+2}:{col}{tr-1})", USD, f(bold=True),
                BAND_FILL, border=BOX)
        put(ws_aging, f"I{tr}", f"=IF(H{tr}=0,0,SUM(C{tr}:G{tr})/H{tr})", PCT, f(bold=True),
            BAND_FILL, border=BOX)
        put(ws_aging, f"J{tr}", f"=IF(H{tr}=0,0,SUM(F{tr}:G{tr})/H{tr})", PCT, f(bold=True),
            BAND_FILL, border=BOX)
        ws_aging.conditional_formatting.add(
            f"I{top+2}:I{tr-1}", CellIsRule(operator="greaterThan", formula=["0.2"],
                                            fill=PatternFill("solid", fgColor="F8D7DA")))
        return tr

    end = aging_block(5, "Aging by region", REGIONS, I("C"), f"{I('D')},{SC}")
    put(ws_aging, f"A{end+1}", "Rows compare regions, so only the Segment filter applies here.",
        font=f(9, italic=True, color="555555"))
    end = aging_block(end + 3, "Aging by segment", SEGMENTS, I("D"), f"{I('C')},{RC}")
    put(ws_aging, f"A{end+1}", "Rows compare segments, so only the Region filter applies here.",
        font=f(9, italic=True, color="555555"))
    end = aging_block(end + 3, "Aging by credit band", BANDS, I("E"), filt_inv)
    top10 = end + 3
    put(ws_aging, f"A{top10}", "Top 10 customers by past-due balance (filtered)",
        font=f(11, True, NAVY))
    header_row(ws_aging, top10 + 1, 1, ["Rank", "Customer", "Region", "Segment", "Band",
                                        "Collector", "Past due", "90+ days", "Open AR",
                                        "Credit limit"])
    ws_aging.column_dimensions["B"].width = 30
    for k in range(1, 11):
        r = top10 + 1 + k
        put(ws_aging, f"A{r}", k, border=BOX)
        key = f"LARGE({C('P')},$A{r})"
        row = f"MATCH({key},{C('P')},0)"
        for col, src, fmt in (("B", "B", None), ("C", "D", None), ("D", "C", None),
                              ("E", "G", None), ("F", "J", None), ("G", "L", USD),
                              ("H", "M", USD), ("I", "K", USD), ("J", "I", USD)):
            put(ws_aging, f"{col}{r}", f'=IF({key}=0,"",INDEX({C(src)},{row}))', fmt,
                border=BOX)

    # ------------------------------------------------------------------ Collectors
    title(ws_coll, "Collector performance",
          "Portfolio quality, speed of first contact and promise-to-pay follow-through.")
    filter_banner(ws_coll, "A3")
    ch = ["Collector", "Accounts", "Open AR", "Past due", "% past due", "% 90+",
          "Invoices worked", "Contacted ≤7 days", "Avg days to 1st contact", "Activities",
          "Promises to pay", "Promises kept", "Kept rate", "Write-offs (12 mo)",
          "Net bad debt % of sales"]
    header_row(ws_coll, 5, 1, ch, [18, 10, 14, 13, 11, 9, 11, 12, 12, 11, 11, 11, 10, 14, 13])
    ws_coll.row_dimensions[5].height = 42
    names = sorted(cust["collector_name"].unique())
    for i, nm in enumerate(names):
        r = 6 + i
        fi = f"{I('F')},$A{r},{filt_inv}"
        fa = f"{A('F')},$A{r},{filt_a}"
        put(ws_coll, f"A{r}", nm, border=BOX)
        vals = [
            (f"=COUNTIFS({C('J')},$A{r},{C('D')},{RC},{C('C')},{SC})", INT),
            (f"=SUMIFS({I('P')},{fi})", USD),
            (f'=SUMIFS({I("P")},{fi},{I("Q")},">0")', USD),
            (f"=IF(C{r}=0,0,D{r}/C{r})", PCT),
            (f'=IF(C{r}=0,0,SUMIFS({I("P")},{fi},{I("Q")},">90")/C{r})', PCT),
            (f'=COUNTIFS({fi},{I("O")},">0")', INT),
            (f'=IF(G{r}=0,0,COUNTIFS({fi},{I("O")},">0",{I("O")},"<=7")/G{r})', PCT),
            (f'=IFERROR(AVERAGEIFS({I("O")},{fi},{I("O")},">0"),0)', DAYS),
            (f"=COUNTIFS({fa})", INT),
            (f'=COUNTIFS({fa},{A("J")},"Promise to pay")', INT),
            (f'=COUNTIFS({fa},{A("J")},"Promise to pay",{A("K")},1)', INT),
            (f"=IF(K{r}=0,0,L{r}/K{r})", PCT),
            (f'=SUMIFS({I("L")},{fi},{I("K")},">"&EOMONTH({ASOF},-12))', USD),
            (f'=IFERROR((SUMIFS({I("L")},{fi})-SUMIFS({I("M")},{fi}))/SUMIFS({I("I")},{fi}),0)',
             PCT2),
        ]
        for j, (fm, nf) in enumerate(vals):
            put(ws_coll, f"{get_column_letter(2 + j)}{r}", fm, nf, border=BOX)
    cr = 6 + len(names)
    put(ws_coll, f"A{cr}", "Total", font=f(bold=True), fill=BAND_FILL, border=BOX)
    for col in "BCDGJKLN":
        put(ws_coll, f"{col}{cr}", f"=SUM({col}6:{col}{cr-1})",
            USD if col in "CDN" else INT, f(bold=True), BAND_FILL, border=BOX)
    put(ws_coll, f"E{cr}", f"=IF(C{cr}=0,0,D{cr}/C{cr})", PCT, f(bold=True), BAND_FILL, border=BOX)
    put(ws_coll, f"M{cr}", f"=IF(K{cr}=0,0,L{cr}/K{cr})", PCT, f(bold=True), BAND_FILL, border=BOX)
    for col in "FHIO":
        put(ws_coll, f"{col}{cr}", None, fill=BAND_FILL, border=BOX)
    coll_notes = [
        "Invoices worked = invoices that received at least one collection activity.",
        "Contacted ≤7 days = share of worked invoices whose first touch came within 7 days of "
        "the due date.",
        "Promise kept = a payment arrived within 14 days of the promise.",
    ]
    for k, n in enumerate(coll_notes):
        put(ws_coll, f"A{cr + 2 + k}", n, font=f(9, italic=True, color="555555"))

    # ------------------------------------------------------------------ Dashboard
    ws = ws_dash
    ws.sheet_view.showGridLines = False
    for col in range(1, 19):
        ws.column_dimensions[get_column_letter(col)].width = 10.5
    ws.column_dimensions["A"].width = 2
    put(ws, "B1", "Collections & Bad Debt Dashboard", font=f(20, True, NAVY))
    put(ws, "B2", f'="Synthetic B2B receivables portfolio  ·  as of "&TEXT({ASOF},"d mmm yyyy")',
        font=f(10, italic=True, color="555555"))
    put(ws, "B4", "Region", font=f(bold=True))
    put(ws, "B5", "Segment", font=f(bold=True))
    for ref in ("C4", "C5"):
        put(ws, ref, "All", font=f(bold=True, color="0000FF"), fill=INPUT_FILL, border=BOX)
        ws.merge_cells(f"{ref}:{chr(ord(ref[0]) + 1)}{ref[1:]}")
    dv_r = DataValidation(type="list", formula1="=Lists!$D$2:$D$8", allow_blank=False)
    dv_s = DataValidation(type="list", formula1="=Lists!$F$2:$F$5", allow_blank=False)
    ws.add_data_validation(dv_r)
    ws.add_data_validation(dv_s)
    dv_r.add("C4")
    dv_s.add("C5")
    put(ws, "F4", "← pick a region and segment; every sheet recalculates.",
        font=f(9, italic=True, color="555555"))

    last = t_last  # Dec 2025 row in Trend
    prev = t_last - 12  # Dec 2024
    win_start = t_last - 11
    kpis = [
        ("Open AR", f"=Trend!Q12", USD,
         f'="vs Dec 2024: "&TEXT(IFERROR(Trend!C{last}/Trend!C{prev}-1,0),"+0%;-0%")'),
        ("% past due", f"=IF(Trend!Q12=0,0,SUM(Trend!Q7:Q11)/Trend!Q12)", PCT,
         f'="Dec 2024: "&TEXT(Trend!G{prev},"0.0%")'),
        ("% over 90 days", f"=IF(Trend!Q12=0,0,SUM(Trend!Q10:Q11)/Trend!Q12)", PCT,
         f'="Dec 2024: "&TEXT(Trend!H{prev},"0.0%")'),
        ("DSO (days)", f"=Trend!I{last}", DAYS,
         f'="Dec 2024: "&TEXT(Trend!I{prev},"0.0")'),
        ("CEI (avg, 12 mo)", f"=AVERAGE(Trend!K{win_start}:K{last})", PCT,
         f'="Dec 2025: "&TEXT(Trend!K{last},"0.0%")'),
        ("Net write-offs (12 mo)", f"=Trend!N{tot}", USD,
         f'="Recovered: "&TEXT(Trend!M{tot},"$#,##0")'),
        ("Net bad debt % sales", f"=IF(Trend!B{tot}=0,0,Trend!N{tot}/Trend!B{tot})", PCT2,
         '="Last 12 months"'),
        ("Required allowance", "=Allowance!F13", USD,
         '="Reserve: "&TEXT(Allowance!E13,"0.00%")&" of AR"'),
    ]
    for k, (lab, val, fmt, sub) in enumerate(kpis):
        c1 = get_column_letter(2 + 2 * k)
        c2 = get_column_letter(3 + 2 * k)
        for r_, v, fnt, nf in ((7, lab, f(9, True, "FFFFFF"), None),
                               (8, val, f(16, True, NAVY), fmt),
                               (9, sub, f(8, italic=True, color="555555"), None)):
            ws.merge_cells(f"{c1}{r_}:{c2}{r_}")
            put(ws, f"{c1}{r_}", v, nf, fnt,
                HEAD_FILL if r_ == 7 else BAND_FILL,
                Alignment(horizontal="center", vertical="center", wrap_text=True))
    ws.row_dimensions[7].height = 26
    ws.row_dimensions[8].height = 30

    def style(ch, ttl, ytitle=None, yfmt=None):
        ch.title = ttl
        ch.roundedCorners = False
        ch.height, ch.width = 7.5, 15.5
        ch.x_axis.delete = False
        ch.y_axis.delete = False
        if ytitle:
            ch.y_axis.title = ytitle
        if yfmt:
            ch.y_axis.numFmt = yfmt
            ch.y_axis.number_format = yfmt
        ch.y_axis.majorGridlines = ch.y_axis.majorGridlines
        if ch.legend is not None:
            ch.legend.position = "b"
            ch.legend.overlay = False
        return ch

    cats_m = Reference(ws_calc, min_col=1, min_row=t0, max_row=t_last)

    c = style(BarChart(), "Open AR by aging bucket", yfmt="$#,##0")
    c.add_data(Reference(ws_calc, min_col=17, min_row=5, max_row=11), titles_from_data=True)
    c.set_categories(Reference(ws_calc, min_col=16, min_row=6, max_row=11))
    c.legend = None
    ws.add_chart(c, "B11")

    c = style(LineChart(), "DSO trend (days)", yfmt="0")
    c.add_data(Reference(ws_calc, min_col=9, min_row=5, max_row=t_last), titles_from_data=True)
    c.set_categories(cats_m)
    c.x_axis.number_format = "mmm yy"
    c.legend = None
    ws.add_chart(c, "J11")

    c = style(LineChart(), "Delinquency: % past due and % 90+", yfmt="0%")
    c.add_data(Reference(ws_calc, min_col=7, max_col=8, min_row=5, max_row=t_last),
               titles_from_data=True)
    c.set_categories(cats_m)
    c.x_axis.number_format = "mmm yy"
    ws.add_chart(c, "B27")

    c = style(BarChart(), "Write-offs vs recoveries", yfmt="$#,##0")
    c.add_data(Reference(ws_calc, min_col=12, max_col=13, min_row=5, max_row=t_last),
               titles_from_data=True)
    c.set_categories(cats_m)
    c.x_axis.number_format = "mmm yy"
    ws.add_chart(c, "J27")

    c = style(BarChart(), "12-month roll rates by bucket", yfmt="0%")
    c.add_data(Reference(ws_roll, min_col=2, max_col=7, min_row=avg_r), from_rows=True,
               titles_from_data=False)
    c.set_categories(Reference(ws_roll, min_col=2, max_col=7, min_row=5))
    c.legend = None
    ws.add_chart(c, "B43")

    c = style(BarChart(), "Past-due AR by region", yfmt="$#,##0")
    c.type = "bar"
    c.add_data(Reference(ws_calc, min_col=17, min_row=15, max_row=21), titles_from_data=True)
    c.set_categories(Reference(ws_calc, min_col=16, min_row=16, max_row=21))
    c.legend = None
    ws.add_chart(c, "J43")
    for ch in ws._charts:
        if ch.title is not None:
            ch.title.overlay = False

    # ------------------------------------------------------------------ About
    wa = ws_about
    wa.sheet_view.showGridLines = False
    wa.column_dimensions["A"].width = 3
    wa.column_dimensions["B"].width = 26
    wa.column_dimensions["C"].width = 95
    put(wa, "B1", "Collections & Bad Debt Analysis", font=f(18, True, NAVY))
    put(wa, "B2", "Excel workbook · synthetic data · every figure is a live formula",
        font=f(10, italic=True, color="555555"))
    rows = [
        ("Purpose", "Show where receivables are aging, how fast balances roll toward write-off, "
                    "how much reserve the portfolio needs, and which collection habits work."),
        ("Data", f"{len(cust):,} customers, {len(inv):,} invoices (Jul 2023 – Dec 2025), "
                 f"{len(act):,} collection activities. Fully synthetic: no real companies or "
                 "people. Generated by src/generate_data.py."),
        ("How to use", "On Dashboard, pick a Region and Segment in the yellow cells. Every sheet "
                       "follows the same filters."),
        ("Dashboard", "KPI cards (AR, % past due, DSO, CEI, net write-offs, allowance) and six "
                      "charts."),
        ("Aging", "Open AR by bucket for region, segment and credit band, plus the top 10 "
                  "past-due customers."),
        ("Roll Rates", "Month-by-month bucket migration, 12-month weighted roll rates and the "
                       "implied loss rate per bucket."),
        ("Allowance", "Required reserve = open AR × implied loss rate, with optional overrides, "
                      "a stress scenario and a comparison with the booked reserve."),
        ("Collectors", "Portfolio quality, speed to first contact and promise-to-pay results "
                       "per collector."),
        ("Trend", "Monthly sales, AR, DSO, CEI, write-offs and recoveries (chart source)."),
        ("Data sheets", "Invoices, Customers, Activities, AgingHistory (month-end balances by "
                        "region/segment/bucket) and RollData (bucket movement between month "
                        "ends)."),
        ("Colour key", "Blue text = hard-coded input · black = formula · green = link from "
                       "another sheet · yellow fill = cell you can change."),
        ("Formulas", "SUMIFS, COUNTIFS, AVERAGEIFS, INDEX/MATCH, LARGE, EOMONTH only; no "
                     "macros, no dynamic arrays."),
    ]
    for i, (k, v) in enumerate(rows):
        r = 4 + i
        put(wa, f"B{r}", k, font=f(bold=True), align=Alignment(vertical="top"))
        put(wa, f"C{r}", v, align=Alignment(wrap_text=True, vertical="top"))
        wa.row_dimensions[r].height = 30

    for wsx in (ws_aging, ws_roll, ws_allow, ws_coll, ws_calc):
        wsx.sheet_view.showGridLines = False
    ws_list.sheet_state = "visible"
    wb.active = 1
    # openpyxl stores formulas without results; make Excel compute everything on open
    wb.calculation.fullCalcOnLoad = True
    out_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out_path)
    return out_path


def main():
    cust, inv, act, hist, rolls = load(ROOT / "data")
    out = build(cust, inv, act, hist, rolls, ROOT / "excel" / "collections_dashboard.xlsx",
                booked_allowance=420_000)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
