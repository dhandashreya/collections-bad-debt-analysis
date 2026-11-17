-- Does contacting a customer within 7 days of the due date reduce write-offs?
-- Population: resolved invoices that were still unpaid 7 days after the due date,
-- with due dates up to Jun 2025 (so they have had time to resolve).
WITH pool AS (
    SELECT i.*,
           COALESCE(i.paid_in_full_date, i.write_off_date) AS resolved_on,
           CASE WHEN i.first_contact_dpd IS NOT NULL AND i.first_contact_dpd <= 7
                THEN 'Contacted <=7 days' ELSE 'Contacted later' END AS contact_group
    FROM invoices i
    WHERE i.status <> 'Open'
      AND i.due_date <= '2025-06-30'
      AND COALESCE(i.paid_in_full_date, i.write_off_date) > date(i.due_date, '+7 days')
)
SELECT contact_group,
       COUNT(*) AS invoices,
       ROUND(AVG(CASE WHEN status = 'Written off' THEN 1.0 ELSE 0 END), 4) AS share_written_off,
       ROUND(SUM(write_off_amount) / SUM(invoice_amount), 4) AS dollar_loss_rate,
       ROUND(AVG(CASE WHEN status = 'Paid'
                      THEN julianday(paid_in_full_date) - julianday(due_date) END), 1) AS avg_days_late_when_paid
FROM pool
GROUP BY contact_group
ORDER BY contact_group;
