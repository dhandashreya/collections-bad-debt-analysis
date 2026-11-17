-- Open AR aging by region as of the extract date (31 Dec 2025).
-- Tables: invoices, customers (loaded from data/*.csv). SQLite / PostgreSQL compatible.
SELECT
    c.region,
    SUM(CASE WHEN i.aging_bucket = 'Current' THEN i.open_balance ELSE 0 END) AS current_bal,
    SUM(CASE WHEN i.aging_bucket = '1-30'    THEN i.open_balance ELSE 0 END) AS d1_30,
    SUM(CASE WHEN i.aging_bucket = '31-60'   THEN i.open_balance ELSE 0 END) AS d31_60,
    SUM(CASE WHEN i.aging_bucket = '61-90'   THEN i.open_balance ELSE 0 END) AS d61_90,
    SUM(CASE WHEN i.aging_bucket = '91-120'  THEN i.open_balance ELSE 0 END) AS d91_120,
    SUM(CASE WHEN i.aging_bucket = '120+'    THEN i.open_balance ELSE 0 END) AS d120_plus,
    SUM(i.open_balance) AS total_open_ar,
    ROUND(1.0 * SUM(CASE WHEN i.days_past_due > 0 THEN i.open_balance ELSE 0 END)
          / SUM(i.open_balance), 4) AS pct_past_due
FROM invoices i
JOIN customers c ON c.customer_id = i.customer_id
WHERE i.status = 'Open'
GROUP BY c.region
ORDER BY total_open_ar DESC;
