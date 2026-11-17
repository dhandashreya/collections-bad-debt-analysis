let
    Source = Csv.Document(File.Contents(DataFolder & "customers.csv"),
        [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
    Typed = Table.TransformColumnTypes(Promoted, {
        {"customer_id", type text}, {"customer_name", type text}, {"segment", type text},
        {"region", type text}, {"industry", type text}, {"credit_score", Int64.Type},
        {"credit_band", type text}, {"payment_terms_days", Int64.Type},
        {"credit_limit", Currency.Type}, {"collector_id", type text},
        {"collector_name", type text}}, "en-US")
in
    Typed
