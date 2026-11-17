// Calendar Jul 2023 - Dec 2025. After loading: Table tools > Mark as date table > [Date].
let
    StartDate = #date(2023, 7, 1),
    EndDate = #date(2025, 12, 31),
    Dates = List.Dates(StartDate, Duration.Days(EndDate - StartDate) + 1, #duration(1, 0, 0, 0)),
    T = Table.FromList(Dates, Splitter.SplitByNothing(), type table [Date = date]),
    Year = Table.AddColumn(T, "Year", each Date.Year([Date]), Int64.Type),
    Quarter = Table.AddColumn(Year, "Quarter", each "Q" & Text.From(Date.QuarterOfYear([Date])), type text),
    MonthNum = Table.AddColumn(Quarter, "Month Number", each Date.Month([Date]), Int64.Type),
    MonthName = Table.AddColumn(MonthNum, "Month", each Date.ToText([Date], "MMM yyyy", "en-US"), type text),
    MonthSort = Table.AddColumn(MonthName, "Month Sort", each Date.Year([Date]) * 100 + Date.Month([Date]), Int64.Type),
    MonthEnd = Table.AddColumn(MonthSort, "Month End", each Date.EndOfMonth([Date]), type date),
    Reporting = Table.AddColumn(MonthEnd, "Is Reporting Period", each [Date] >= #date(2024, 1, 1), type logical)
in
    Reporting
