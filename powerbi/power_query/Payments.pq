// Payments get customer_id from Invoices so the model stays a clean star:
// Payments relate to Customers and Date directly, not through Invoices
// (that would create two filter paths from Date).
let
    Source = Csv.Document(File.Contents(DataFolder & "payments.csv"),
        [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
    Typed = Table.TransformColumnTypes(Promoted, {
        {"payment_id", type text}, {"invoice_id", type text},
        {"payment_date", type date}, {"amount", Currency.Type},
        {"payment_type", type text}}, "en-US"),
    InvKeys = Table.SelectColumns(Invoices, {"invoice_id", "customer_id"}),
    Merged = Table.NestedJoin(Typed, {"invoice_id"}, InvKeys, {"invoice_id"}, "Inv",
        JoinKind.LeftOuter),
    Expanded = Table.ExpandTableColumn(Merged, "Inv", {"customer_id"})
in
    Expanded
