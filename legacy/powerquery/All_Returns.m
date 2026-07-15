let
    // Common contract present in every return query
    Cols = {"ReturnType", "EntityID", "EntityName", "FY", "PeriodDate", "MonthName", "MonthIndex", "Status", "Flags", "PrimaryAmount"},
    Empty = #table(
        type table [ReturnType = text, EntityID = text, EntityName = text, FY = text, PeriodDate = date, MonthName = text, MonthIndex = Int64.Type, Status = text, Flags = text, PrimaryAmount = number],
        {}),
    // Resilient pick: a return with no path set (or a parse failure) yields an empty
    // table instead of breaking the whole dashboard.
    // Each source is wrapped in `try` at the call site (returns an [HasError] record that
    // never throws). A return with no path set -> empty table, so it can't break the union.
    Safe = (rec) => if rec[HasError] then Empty else try Table.SelectColumns(rec[Value], Cols, MissingField.UseNull) otherwise Empty,
    Combined = Table.Combine({ Safe(try GSTR3B), Safe(try ESIC), Safe(try PF), Safe(try PTRC), Safe(try TDS) }),
    Typed = Table.TransformColumnTypes(Combined, {{"PeriodDate", type date}, {"MonthIndex", Int64.Type}, {"PrimaryAmount", type number}}),
    Sorted = Table.Sort(Typed, {{"ReturnType", Order.Ascending}, {"FY", Order.Ascending}, {"MonthIndex", Order.Ascending}})
in
    Sorted
