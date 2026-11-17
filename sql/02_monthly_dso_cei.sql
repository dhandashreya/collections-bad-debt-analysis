-- Monthly AR, DSO (3-month method) and Collection Effectiveness Index.
-- Tables: aging_snapshot, invoices. Dates are ISO text (YYYY-MM-DD); written for SQLite.
WITH ar AS (
    SELECT snapshot_date AS month_end,
           SUM(balance) AS ar,
           SUM(CASE WHEN aging_bucket = 'Current' THEN balance ELSE 0 END) AS ar_current
    FROM aging_snapshot
    GROUP BY snapshot_date
),
sales AS (
    SELECT date(invoice_date, 'start of month', '+1 month', '-1 day') AS month_end,
           SUM(invoice_amount) AS sales
    FROM invoices
    GROUP BY 1
),
m AS (
    SELECT a.month_end, a.ar, a.ar_current, COALESCE(s.sales, 0) AS sales,
           LAG(a.ar) OVER (ORDER BY a.month_end) AS prior_ar,
           (SELECT SUM(s3.sales) FROM sales s3
             WHERE s3.month_end > date(a.month_end, 'start of month', '-2 months', '-1 day')
               AND s3.month_end <= a.month_end) AS sales_3m,
           julianday(a.month_end)
             - julianday(date(a.month_end, 'start of month', '-2 months', '-1 day')) AS days_3m
    FROM ar a
    LEFT JOIN sales s ON s.month_end = a.month_end
)
SELECT month_end,
       ROUND(ar, 2) AS open_ar,
       ROUND(sales, 2) AS credit_sales,
       ROUND(ar / sales_3m * days_3m, 1) AS dso,
       ROUND((prior_ar + sales - ar) / (prior_ar + sales - ar_current), 4) AS cei
FROM m
WHERE month_end >= '2024-01-31'
ORDER BY month_end;
