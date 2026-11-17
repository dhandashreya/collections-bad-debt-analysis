-- Roll rates: how each aging bucket's balance moves by the next month end.
-- Each open invoice at month end M is matched with itself at M+1 (same logic as
-- powerbi/power_query/RollFacts.pq). 12-month window: from-months Dec 2024 - Nov 2025.
WITH s AS (
    SELECT snapshot_date, invoice_id, balance, aging_bucket,
           CASE aging_bucket WHEN 'Current' THEN 0 WHEN '1-30' THEN 1 WHEN '31-60' THEN 2
                             WHEN '61-90' THEN 3 WHEN '91-120' THEN 4 ELSE 5 END AS bucket_rank
    FROM aging_snapshot
),
moves AS (
    SELECT s0.snapshot_date AS from_month,
           s0.aging_bucket  AS from_bucket,
           s0.bucket_rank,
           s0.balance,
           CASE
               WHEN s1.invoice_id IS NULL
                    AND i.write_off_date > s0.snapshot_date
                    AND i.write_off_date <= date(s0.snapshot_date, '+1 day', '+1 month', '-1 day')
                   THEN 'Written off'
               WHEN s1.invoice_id IS NULL THEN 'Paid'
               WHEN s1.bucket_rank > s0.bucket_rank THEN 'Rolled forward'
               ELSE 'Stayed'
           END AS outcome
    FROM s s0
    JOIN invoices i ON i.invoice_id = s0.invoice_id
    LEFT JOIN s s1
           ON s1.invoice_id = s0.invoice_id
          AND s1.snapshot_date = date(s0.snapshot_date, '+1 day', '+1 month', '-1 day')
    WHERE s0.snapshot_date < (SELECT MAX(snapshot_date) FROM aging_snapshot)
)
SELECT from_bucket,
       ROUND(SUM(balance), 2) AS starting_balance,
       -- share that moved to a worse bucket or was written off
       ROUND(SUM(CASE WHEN outcome IN ('Rolled forward', 'Written off') THEN balance ELSE 0 END)
             / SUM(balance), 4) AS roll_rate,
       -- for 120+: share written off among balances that resolved (written off or paid)
       ROUND(SUM(CASE WHEN outcome = 'Written off' THEN balance ELSE 0 END)
             / NULLIF(SUM(CASE WHEN outcome IN ('Written off', 'Paid') THEN balance ELSE 0 END), 0),
             4) AS writeoff_share_of_resolved
FROM moves
WHERE from_month > '2024-11-30' AND from_month <= '2025-11-30'
GROUP BY from_bucket, bucket_rank
ORDER BY bucket_rank;
