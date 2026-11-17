// Builds the month-to-month roll (migration) table from AgingSnapshot:
// each open invoice at month end M is matched to itself at month end M+1.
//   found in a worse bucket   -> "Rolled forward"
//   found in the same bucket  -> "Stayed"
//   gone, written off in M+1  -> "Written off"
//   gone otherwise            -> "Paid"
// Same logic as sql/03_roll_rates.sql, which the test suite checks against the data.
let
    Order = {"Current", "1-30", "31-60", "61-90", "91-120", "120+"},
    Snap = Table.SelectColumns(AgingSnapshot,
        {"snapshot_date", "invoice_id", "customer_id", "balance", "aging_bucket"}),
    Ranked = Table.AddColumn(Snap, "bucket_rank",
        each List.PositionOf(Order, [aging_bucket]), Int64.Type),
    WithNext = Table.AddColumn(Ranked, "next_month",
        each Date.EndOfMonth(Date.AddMonths([snapshot_date], 1)), type date),
    NextSnap = Table.SelectColumns(Ranked, {"invoice_id", "snapshot_date", "bucket_rank"}),
    Joined = Table.NestedJoin(WithNext, {"invoice_id", "next_month"},
        NextSnap, {"invoice_id", "snapshot_date"}, "Next", JoinKind.LeftOuter),
    WithNextRank = Table.ExpandTableColumn(Joined, "Next", {"bucket_rank"}, {"next_rank"}),
    WriteOffs = Table.SelectColumns(Invoices, {"invoice_id", "write_off_date"}),
    Joined2 = Table.NestedJoin(WithNextRank, {"invoice_id"}, WriteOffs, {"invoice_id"},
        "Inv", JoinKind.LeftOuter),
    WithWO = Table.ExpandTableColumn(Joined2, "Inv", {"write_off_date"}),
    LastMonth = List.Max(Snap[snapshot_date]),
    NotLast = Table.SelectRows(WithWO, each [snapshot_date] < LastMonth),
    Outcome = Table.AddColumn(NotLast, "outcome", each
        if [next_rank] = null then
            (if [write_off_date] <> null and [write_off_date] > [snapshot_date]
                and [write_off_date] <= [next_month]
             then "Written off" else "Paid")
        else if [next_rank] > [bucket_rank] then "Rolled forward"
        else "Stayed", type text),
    Kept = Table.SelectColumns(Outcome,
        {"snapshot_date", "invoice_id", "customer_id", "aging_bucket", "balance", "outcome"}),
    Renamed = Table.RenameColumns(Kept,
        {{"snapshot_date", "from_month"}, {"aging_bucket", "from_bucket"}})
in
    Renamed
