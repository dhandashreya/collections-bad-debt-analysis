// Small dimension so buckets sort in aging order, not alphabetically.
// After loading: select [bucket] > Column tools > Sort by column > sort_order.
#table(
    type table [bucket = text, sort_order = Int64.Type, min_days = Int64.Type, max_days = Int64.Type],
    {
        {"Current", 1, 0, 0},
        {"1-30", 2, 1, 30},
        {"31-60", 3, 31, 60},
        {"61-90", 4, 61, 90},
        {"91-120", 5, 91, 120},
        {"120+", 6, 121, 9999}
    })
