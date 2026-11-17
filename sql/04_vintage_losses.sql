-- Vintage analysis: cumulative write-offs as a % of each invoice quarter's sales,
-- by months since the start of the quarter. Rows past the as-of date are left out.
WITH inv AS (
    SELECT invoice_amount, write_off_amount, write_off_date,
           strftime('%Y', invoice_date) || '-Q' ||
               ((CAST(strftime('%m', invoice_date) AS INTEGER) + 2) / 3) AS vintage,
           date(invoice_date, 'start of month',
                '-' || ((CAST(strftime('%m', invoice_date) AS INTEGER) - 1) % 3) || ' months')
               AS vintage_start
    FROM invoices
),
cohort AS (
    SELECT vintage, MIN(vintage_start) AS vintage_start, SUM(invoice_amount) AS sales
    FROM inv GROUP BY vintage
),
months(m) AS (
    SELECT 0 UNION ALL SELECT m + 3 FROM months WHERE m < 18
)
SELECT c.vintage,
       mo.m AS months_since_start,
       ROUND(1.0 * COALESCE(SUM(CASE WHEN i.write_off_date IS NOT NULL
                                      AND i.write_off_date < date(c.vintage_start, '+' || mo.m || ' months')
                                     THEN i.write_off_amount END), 0) / c.sales, 5) AS cum_writeoff_pct
FROM cohort c
CROSS JOIN months mo
JOIN inv i ON i.vintage = c.vintage
WHERE date(c.vintage_start, '+' || mo.m || ' months') <= '2026-01-01'
GROUP BY c.vintage, mo.m
ORDER BY c.vintage, mo.m;
