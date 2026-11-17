// One row per open invoice per month end (Dec 2023 - Dec 2025).
let
    Source = Csv.Document(File.Contents(DataFolder & "aging_snapshot.csv"),
        [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
    Typed = Table.TransformColumnTypes(Promoted, {
        {"snapshot_date", type date}, {"invoice_id", type text},
        {"customer_id", type text}, {"balance", Currency.Type},
        {"days_past_due", Int64.Type}, {"aging_bucket", type text}}, "en-US")
in
    Typed
