let
    Source = Csv.Document(File.Contents(DataFolder & "collection_activities.csv"),
        [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
    Blanks = Table.ReplaceValue(Promoted, "", null, Replacer.ReplaceValue, {"promise_kept"}),
    Typed = Table.TransformColumnTypes(Blanks, {
        {"activity_id", type text}, {"invoice_id", type text}, {"customer_id", type text},
        {"collector_id", type text}, {"activity_date", type date},
        {"days_past_due", Int64.Type}, {"activity_type", type text},
        {"outcome", type text}, {"promise_kept", Int64.Type}}, "en-US")
in
    Typed
