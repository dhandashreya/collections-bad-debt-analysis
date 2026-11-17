# Tableau build guide

This Tableau dashboard tells the risk story visually: where losses come from, how they build up over time, and what collectors can do about it.
It uses Tableau Public (free) and takes about 40 minutes. Save it as `tableau/collections_risk.twbx`, publish it
to Tableau Public, and put the link in the top-level README.

## 1. Data sources

Create four data sources from `data/`:

| Data source | Tables | Notes |
|---|---|---|
| **Ledger** | `invoices.csv` related to `customers.csv` on `customer_id` | Use a relationship (the "noodle"), not a join |
| **Aging history** | `aging_history.csv` | Month-end balance by region, segment, bucket |
| **Roll rates** | `roll_rates.csv` | Month-to-month bucket movement by region, segment |
| **Activities** | `collection_activities.csv` related to `customers.csv` | Collector touches |

Set every `*_date` field to **Date**, and `credit_band`, `aging_bucket` and `from_bucket` to **String**. In Aging
history and Roll rates, sort the bucket field manually: Current, 1-30, 31-60, 61-90, 91-120, 120+.

## 2. Calculated fields

**Ledger**
```
// Vintage
STR(YEAR([Invoice Date])) + "-Q" + STR(DATEPART('quarter', [Invoice Date]))

// Months to write-off (from start of vintage quarter)
IF NOT ISNULL([Write Off Date]) THEN
  DATEDIFF('month', DATETRUNC('quarter', [Invoice Date]), [Write Off Date])
END

// Write-off rate
SUM([Write Off Amount]) / SUM([Invoice Amount])

// Unpaid at day 7  (population for the early-contact test)
[Status] <> "Open"
AND IFNULL([Paid In Full Date], [Write Off Date]) > DATEADD('day', 7, [Due Date])
AND [Due Date] <= #2025-06-30#

// Contact group
IF [First Contact Dpd] <= 7 THEN "Contacted ≤7 days" ELSE "Contacted later" END

// Written off flag
IIF([Status] = "Written off", 1, 0)
```

**Roll rates**
```
// Roll rate  (use with from_bucket on the view)
IF ATTR([From Bucket]) = "120+" THEN
  SUM(IIF([Outcome] = "Written off", [Balance], 0)) /
  SUM(IIF([Outcome] = "Written off" OR [Outcome] = "Paid", [Balance], 0))
ELSE
  SUM(IIF([Outcome] = "Rolled forward" OR [Outcome] = "Written off", [Balance], 0)) / SUM([Balance])
END
```

**Aging history**
```
// % past due
SUM(IIF([Aging Bucket] <> "Current", [Balance], 0)) / SUM([Balance])
```

## 3. Sheets

1. **Roll-rate heatmap** (Roll rates): Columns = `MONTH(From Month)`, Rows = `From Bucket`, Colour = `Roll rate`
   (sequential blue), Mark = Square, label on. Filter From Month to Jan 2024 – Nov 2025.
2. **Vintage curves** (Ledger): Columns = `Months to write-off` (continuous, 0–18), Rows =
   `RUNNING_SUM(SUM([Write Off Amount])) / TOTAL(SUM([Invoice Amount]))` computed along Months to write-off, Colour = `Vintage`.
   Keep vintages 2023-Q4 to 2025-Q2, and use the Sequential Blue palette so later quarters are darker.
3. **Loss by credit band × segment** (Ledger): highlight table, Rows = `Credit Band`, Columns = `Segment`,
   Colour/Label = `Write-off rate`.
4. **Early contact test** (Ledger): filter `Unpaid at day 7` = True. Columns = `Contact group`, Rows =
   `AVG([Written off flag])`. Expected result: about 5.7% vs 10.1%.
5. **Delinquency trend by region** (Aging history): Columns = `MONTH(Snapshot Date)`, Rows = `% past due`,
   Colour = `Region`, with a highlight action on Region.
6. **Collector scorecard** (Activities): Rows = `Collector Name`, Columns = count of activities split by
   `Outcome`, plus a promise-kept rate = `SUM([Promise Kept]) / COUNT([Promise Kept])`.

## 4. Dashboard

Use a 1200 × 900 canvas, with a title and a one-line takeaway at the top. Place the heatmap and vintage curves in the top row,
the credit band highlight table and early-contact bars in the middle row, and the region trend at the bottom. Add filter
actions so that clicking a region or segment filters every sheet, and add tooltips that explain each metric in plain English.

## 5. Publish

**File → Save to Tableau Public**, then copy the link. Also save a local `tableau/collections_risk.twbx` and a
screenshot `tableau/screenshots/dashboard.png`, then add both to the top-level README:

```markdown
[![Tableau dashboard](tableau/screenshots/dashboard.png)](https://public.tableau.com/app/profile/YOUR-PROFILE/viz/...)
```
