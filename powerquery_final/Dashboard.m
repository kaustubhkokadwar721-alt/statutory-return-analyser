let
    Src = All_Returns,
    Grouped = Table.Group(Src, {"ReturnType", "FY"}, {
        {"Records",            each Table.RowCount(_), Int64.Type},
        {"OK",                 each List.Count(List.Select([Status], each _ = "OK")), Int64.Type},
        {"Review",             each List.Count(List.Select([Status], each _ = "Review")), Int64.Type},
        {"Errors",             each List.Count(List.Select([Status], each _ = "Error")), Int64.Type},
        {"Periods",            each List.Count(List.Distinct(List.RemoveNulls([PeriodDate]))), Int64.Type},
        {"TotalPrimaryAmount", each List.Sum([PrimaryAmount]), type number}
    }),
    AddFlagRate = Table.AddColumn(Grouped, "FlagRate", each try Number.Round(([Review] + [Errors]) / [Records], 3) otherwise 0, type number),
    Sorted = Table.Sort(AddFlagRate, {{"ReturnType", Order.Ascending}, {"FY", Order.Ascending}})
in
    Sorted
