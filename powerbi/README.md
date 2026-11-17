# Power BI build guide

This folder has everything the Power BI report needs except the `.pbix` file itself, which
only Power BI Desktop can create:

| File | What it is |
|---|---|
| `power_query/*.pq` | One Power Query (M) script per table, including `RollFacts`, which builds month-to-month bucket migration by merging the aging snapshot with itself |
| `measures.dax` | Every DAX measure: AR, aging, DSO, CEI, write-offs, roll rates, implied loss rates, allowance, a what-if stress test, collector KPIs |
| `collections_theme.json` | Report theme (colours, fonts, page background) |

The full build takes about 45–60 minutes. Save the result as
`powerbi/collections_dashboard.pbix` and put screenshots in `powerbi/screenshots/`.

---

## 1. Load the data with Power Query (10 min)

1. Open Power BI Desktop → **Blank report**. Go to **Home → Transform data** to open the Power Query Editor.
2. **Home → Manage Parameters → New Parameter**: Name `DataFolder`, Type `Text`, Current value =
   the full path to this repo's `data\` folder **with a trailing backslash**, e.g.
   `C:\Users\you\collections-bad-debt-analysis\data\`.
3. For each script in `power_query/`, in this order:
   `Customers`, `Invoices`, `Payments`, `Activities`, `AgingSnapshot`, `RollFacts`, `AgingBucket`, `Date`:
   **Home → New Source → Blank Query → Advanced Editor**, paste the file's contents, click **Done**, and
   rename the query to the file name (without `.pq`).
   `Payments` and `RollFacts` reference `Invoices` and `AgingSnapshot`, so those two must exist first.
4. **Close & Apply.** RollFacts takes a few seconds because it merges about 15,000 snapshot rows with themselves.

Expected row counts: Customers 400 · Invoices 11,562 · Payments 12,260 · Activities 10,168 ·
AgingSnapshot 14,929 · RollFacts 14,344 · AgingBucket 6 · Date 915.

## 2. Model (10 min)

Go to **Model view** and set up a star schema. Drag to create each relationship, all many-to-one and single direction:

| From (many) | To (one) | Active |
|---|---|---|
| Invoices[customer_id] | Customers[customer_id] | yes |
| Payments[customer_id] | Customers[customer_id] | yes |
| Activities[customer_id] | Customers[customer_id] | yes |
| AgingSnapshot[customer_id] | Customers[customer_id] | yes |
| RollFacts[customer_id] | Customers[customer_id] | yes |
| Invoices[invoice_date] | Date[Date] | yes |
| Invoices[write_off_date] | Date[Date] | **no** (the `Write-offs` measure turns it on with `USERELATIONSHIP`) |
| Payments[payment_date] | Date[Date] | yes |
| Activities[activity_date] | Date[Date] | yes |
| AgingSnapshot[snapshot_date] | Date[Date] | yes |
| RollFacts[from_month] | Date[Date] | yes |
| AgingSnapshot[aging_bucket] | AgingBucket[bucket] | yes |
| RollFacts[from_bucket] | AgingBucket[bucket] | yes |

Then:
- Select the **Date** table → **Table tools → Mark as date table** → `Date`.
- Sort `Date[Month]` by `Date[Month Sort]`, and `AgingBucket[bucket]` by `AgingBucket[sort_order]`
  (select the column → **Column tools → Sort by column**).
- Hide the key and helper columns in report view (the `customer_id` columns in the fact tables, `bucket_rank`, `Month Sort`).
- Delete any relationships Power BI auto-detected that are not in the table, especially Payments → Invoices.

Take a screenshot of the model diagram as `screenshots/00_model.png`. Hiring managers like to see this.

## 3. Measures (10 min)

1. **Home → Enter data** → name the table `_Measures` → **Load**.
2. For each measure in `measures.dax`: **Modeling → New measure**, paste the text from the name down to the
   end of the expression. Set the format: currency with no decimals for amounts, percentage with
   1 decimal for rates (2 decimals for `Implied Loss Rate`, `Allowance % of AR`, `Net Bad Debt % of Sales 12M`),
   and a decimal number with 1 decimal for `DSO`.
3. Group them into display folders (**Properties → Display folder**) using the names in the file's comments.
4. **Modeling → New parameter → Numeric range**: name `Stress Multiplier`, min 1, max 2, increment 0.05,
   default 1.5. Do this before you add `Stressed Allowance`.
5. Delete the dummy `Column1` in `_Measures`.

### Check your numbers
With **no filters** and **Dec 2025** as the latest month, you should see:

| Measure | Expected |
|---|---|
| AR Balance | $9,898,291 |
| % Past Due | 19.6% |
| % Over 90 | 5.3% |
| DSO | 49.8 days |
| CEI 12M Avg | 79.7% |
| Net Write-offs 12M | $540,487 |
| Net Bad Debt % of Sales 12M | 0.74% |
| Roll Rate 12M (Current → 120+) | 9.7% · 31.8% · 67.6% · 71.8% · 77.3% · 55.2% |
| Implied Loss Rate (Current → 120+) | 0.64% · 6.60% · 20.73% · 30.66% · 42.72% · 55.23% |
| Required Allowance | $494,865 (5.00% of AR) |
| Promise Kept Rate | 68.6% |

Filter checks: Region = Alberta gives AR Balance $1,500,722, and Segment = SMB gives $795,757.
The same figures appear in the Excel workbook and in `reports/findings.md`, so all three tools agree.

## 4. Report pages (20–25 min)

**View → Themes → Browse for themes** → `collections_theme.json`. Use a 16:9 canvas.
Put slicers for `Customers[region]`, `Customers[segment]` and `Date[Month]` (single select, default
Dec 2025) on every page, and use **View → Sync slicers** so they stay in sync.

### Page 1: Executive overview
- **8 cards**: AR Balance (subtitle measure `AR vs PY Label`), % Past Due, % Over 90, DSO,
  CEI 12M Avg, Net Write-offs 12M, Net Bad Debt % of Sales 12M, Required Allowance.
- **Stacked column**: X = `Date[Month]`, Y = `AR Balance`, Legend = `AgingBucket[bucket]`.
  Edit interactions so the Month slicer does **not** filter this chart, so it shows the whole trend.
- **Line chart**: X = `Date[Month]`, Y = `DSO`, with the same interaction setting.
- **Clustered column**: X = `Date[Month]`, Y = `Write-offs`, `Recoveries`.

### Page 2: Aging & risk
- **Matrix**: Rows = `Customers[region]`, Columns = `AgingBucket[bucket]`, Values = `AR Balance`.
  Add conditional formatting (background colour scale, white to navy).
- **Bar chart**: Y = `Customers[credit_band]`, X = `Lifetime Write-off Rate`. Band D (about 3.3%) should be roughly 50× band A (about 0.06%).
- **Table**: `customer_name`, `region`, `credit_band`, `collector_name`, `AR Past Due`, `AR Over 90`,
  with a visual-level filter **Top N = 10 by AR Past Due**.
- **Donut** or **100% bar** of `% of AR` by `AgingBucket[bucket]`.

### Page 3: Roll rates & allowance
- **Matrix**: Rows = `Date[Month]` (reporting period only), Columns = `AgingBucket[bucket]`, Values = `Roll Rate`,
  with a colour scale. This is the roll-rate heatmap.
- **Table**: `AgingBucket[bucket]`, `AR Balance`, `Roll Rate 12M`, `Implied Loss Rate`, `Required Allowance`, `Stressed Allowance`.
- **Slicer** for `Stress Multiplier`, plus cards for `Required Allowance` and `Stressed Allowance`.

### Page 4: Collector performance
- **Table**: `Customers[collector_name]`, `AR Balance`, `% Past Due`, `Invoices Worked`, `Early Contact Rate`,
  `Avg Days to First Contact`, `Promises to Pay`, `Promise Kept Rate`, `Net Write-offs`.
- **Scatter**: X = `Early Contact Rate`, Y = `Lifetime Write-off Rate`, Details = `collector_name`, Size = `Credit Sales`.
- **Clustered bar**: `Activities` by `Activities[activity_type]` and `Activities[outcome]`.

Add a short text box on each page that states the main point, e.g. *"Accounts contacted within 7 days of
the due date are written off about half as often (5.7% vs 10.1%)."*

## 5. Publish to GitHub (5 min)

1. Save as `powerbi/collections_dashboard.pbix`.
2. Export a screenshot of each page (Windows: `Win + Shift + S`) as
   `powerbi/screenshots/01_overview.png`, `02_aging.png`, `03_roll_rates.png`, `04_collectors.png`.
3. Optional: **File → Export → PDF** as `powerbi/collections_dashboard.pdf`, so people without Power BI can see every page.
4. Add this block to the top-level README under *Power BI*, then commit and push:

```markdown
![Power BI overview](powerbi/screenshots/01_overview.png)
![Data model](powerbi/screenshots/00_model.png)
```

## What this demonstrates
- **Power Query**: parameterised folder path, typed imports, null handling, a self-merge that builds
  month-to-month roll facts, and an enrichment merge (Payments ← Invoices).
- **Data modelling**: star schema, a marked date table, an inactive relationship turned on with `USERELATIONSHIP`,
  a sort-by-column dimension, and avoiding ambiguous filter paths.
- **DAX**: time intelligence (`DATESINPERIOD`, `EOMONTH`), snapshot (semi-additive) balances,
  iterator chains (`PRODUCTX` for loss rates, `SUMX` for the allowance), `AVERAGEX` over months
  with context transition, a what-if parameter, and `SELECTEDVALUE` branching.
