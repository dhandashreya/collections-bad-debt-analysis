let
    Source = Csv.Document(File.Contents(DataFolder & "invoices.csv"),
        [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
    // blank cells arrive as "" - turn them into real nulls before typing
    Blanks = Table.ReplaceValue(Promoted, "", null, Replacer.ReplaceValue,
        {"paid_in_full_date", "days_to_pay", "write_off_date", "recovery_date",
         "first_contact_dpd"}),
    Typed = Table.TransformColumnTypes(Blanks, {
        {"invoice_id", type text}, {"customer_id", type text},
        {"invoice_date", type date}, {"due_date", type date},
        {"invoice_amount", Currency.Type}, {"amount_paid", Currency.Type},
        {"paid_in_full_date", type date}, {"days_to_pay", Int64.Type},
        {"write_off_date", type date}, {"write_off_amount", Currency.Type},
        {"recovery_amount", Currency.Type}, {"recovery_date", type date},
        {"open_balance", Currency.Type}, {"status", type text},
        {"days_past_due", Int64.Type}, {"aging_bucket", type text},
        {"first_contact_dpd", Int64.Type}}, "en-US"),
    // helper flags used by the collector measures
    Worked = Table.AddColumn(Typed, "was_worked",
        each [first_contact_dpd] <> null, type logical),
    Early = Table.AddColumn(Worked, "contacted_within_7_days",
        each [first_contact_dpd] <> null and [first_contact_dpd] <= 7, type logical)
in
    Early
