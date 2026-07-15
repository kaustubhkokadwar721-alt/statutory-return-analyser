let
    // ── 1. Read Folder Path from dynamic DocPaths table ──────────
    SourcePath = let v = Table.SelectRows(Excel.CurrentWorkbook(){[Name="DocPaths"]}[Content], each [DocType] = "ESIC"), p = if Table.RowCount(v) > 0 then v{0}[FolderPath] else null in if p = null or Text.Trim(Text.From(p)) = "" then error "Set the ESIC folder path in the DocPaths table (Config sheet)." else Text.Trim(Text.From(p)),

    // ── 2. GET ALL PDF FILES FROM FOLDER ─────────────────────────
    AllFiles   = Folder.Files(SourcePath),
    PDFsOnly   = Table.SelectRows(AllFiles, each Text.Lower([Extension]) = ".pdf"),
    FileCols   = Table.SelectColumns(PDFsOnly, {"Content", "Name"}),

    // ── 3. PARSE FUNCTION ────────────────────────────────────────
    fnParseESIC = (bin as binary, fname as text) as record =>
    let
        ParsedRecord = try
        let
            RawData      = Pdf.Tables(bin, [Implementation="1.3"]),
            AllPagesOrTables = if Table.RowCount(RawData) > 0 then Table.Combine(Table.Column(RawData, "Data")) else #table({}, {}),
            AllCellsText     = List.Transform(List.Combine(Table.ToRows(AllPagesOrTables)), (x) => try Text.Trim(Text.From(x)) otherwise ""),
            AllTextStr       = Text.Combine(List.Select(AllCellsText, each _ <> ""), " "),

            // Case-insensitive locator: search upper copy, slice original (positions align)
            Hay = Text.Upper(AllTextStr),
            Pos = (needle as text) as number => Text.PositionOf(Hay, Text.Upper(needle)),
            // Take the text immediately after a label, width chars wide
            After = (needle as text, width as number) as text =>
                let i = Pos(needle) in if i >= 0 then Text.Trim(Text.Middle(AllTextStr, i + Text.Length(needle), width)) else "",

            // Challan Period (Month & Year)
            PeriodStrRaw = After("Challan Period:", 20),
            PeriodStr = if PeriodStrRaw <> "" then Text.Split(PeriodStrRaw, " "){0} else "",
            MonthVal = if Text.Contains(PeriodStr, "-") then Text.Split(PeriodStr, "-"){0} else "Unknown",
            RawYearVal = if Text.Contains(PeriodStr, "-") then try Number.FromText(Text.Split(PeriodStr, "-"){1}) otherwise 0 else 0,

            // Financial Year
            MonthUpper  = Text.Upper(MonthVal),
            IsQ1toQ3    = List.AnyTrue(List.Transform({"APR","MAY","JUN","JUL","AUG","SEP","OCT","NOV","DEC"}, each Text.Contains(MonthUpper, _))),
            FYStartYear = if RawYearVal = 0 then 0 else if IsQ1toQ3 then RawYearVal else RawYearVal - 1,
            FYEndYY     = if FYStartYear = 0 then "??" else Text.End(Text.From(FYStartYear + 1), 2),
            FinancialYear = if FYStartYear = 0 then "Unknown" else Text.From(FYStartYear) & "-" & FYEndYY,

            // Amount Paid
            AmountStrRaw = After("Amount Paid:", 20),
            AmountPaidStr = if AmountStrRaw <> "" then Text.Split(AmountStrRaw, " "){0} else "0",
            AmountPaidVal = try Number.FromText(Text.Remove(AmountPaidStr, {","}), "en-US") otherwise 0,

            // Challan Number
            ChallanNumRaw = After("Challan Number", 30),
            ChallanCleaned = Text.Trim(Text.Replace(ChallanNumRaw, ":", "")),
            ChallanNum = if ChallanCleaned <> "" then Text.Split(ChallanCleaned, " "){0} else "Unknown",

            // Challan Submitted Date
            DateStrRaw = After("Challan Submitted Date", 30),
            DateStr = if DateStrRaw <> "" then Text.Split(DateStrRaw, " "){0} else "Unknown"
        in
            [
                #"Month"                        = MonthVal,
                #"Year"                         = FinancialYear,
                #"Total ESIC Contribution Paid" = AmountPaidVal,
                #"Challan Number"               = ChallanNum,
                #"Date of Payment"              = DateStr
            ]
        otherwise
            [
                #"Month"                        = fname,
                #"Year"                         = "ERROR",
                #"Total ESIC Contribution Paid" = null,
                #"Challan Number"               = "ERROR",
                #"Date of Payment"              = "ERROR"
            ]
    in
        ParsedRecord,

    // ── 4. APPLY PARSER TO EVERY PDF ─────────────────────────────
    ParsedTable  = Table.AddColumn(FileCols, "ExtractedData", each fnParseESIC([Content], [Name])),
    RemovedFiles = Table.RemoveColumns(ParsedTable, {"Content", "Name"}),

    // ── 5. EXPAND RAW COLUMNS ────────────────────────────────────
    ExpandedData = Table.ExpandRecordColumn(RemovedFiles, "ExtractedData", {
        "Month", "Year", "Total ESIC Contribution Paid", "Challan Number", "Date of Payment"
    }),

    // ── 6. UNPIVOT TO LONG: one row per challan, tagged by Party ──
    // ASSUMPTION (PDF has no explicit party label): within a Year+Month, the
    // highest-value challan = Employer (3.25%), next = Employee (0.75%).
    // NOTE: ESIC PDF carries no establishment code, so grain is Year+Month only.
    // If a folder mixes >1 establishment in the same month, extra challans show
    // Party = "Other" (surfaced, not silently dropped).
    Renamed = Table.RenameColumns(ExpandedData, {
        {"Total ESIC Contribution Paid", "Amount"},
        {"Challan Number", "ChallanNumber"},
        {"Date of Payment", "ChallanDate"}
    }),
    Grouped = Table.Group(Renamed, {"Year", "Month"}, {
        {"rows", each Table.AddIndexColumn(Table.Sort(_, {{"Amount", Order.Descending}}), "rank", 0, 1), type table}
    }),
    Combined = Table.Combine(Grouped[rows]),
    WithParty = Table.AddColumn(Combined, "Party", each if [rank] = 0 then "Employer" else if [rank] = 1 then "Employee" else "Other", type text),
    DropRank = Table.RemoveColumns(WithParty, {"rank"}),

    // ── 7. Standardized dimension contract ───────────────────────
    AddK = Table.AddColumn(DropRank, "_K", each
        let
            r = [APR=1,MAY=2,JUN=3,JUL=4,AUG=5,SEP=6,OCT=7,NOV=8,DEC=9,JAN=10,FEB=11,MAR=12],
            mi = try Record.Field(r, Text.Upper(Text.Start(Text.Trim(try [Month] otherwise ""), 3))) otherwise 0,
            fyStart = try Number.FromText(Text.Start(Text.Select(try [Year] otherwise "", {"0".."9"}), 4)) otherwise 0,
            calM = if mi = 0 then null else if mi <= 9 then mi + 3 else mi - 9,
            calY = if mi = 0 or fyStart = 0 then null else if mi <= 9 then fyStart else fyStart + 1,
            pd = try #date(calY, calM, 1) otherwise null
        in
            [
                FY = if fyStart = 0 then "Unknown" else Text.From(fyStart) & "-" & Text.End(Text.From(fyStart + 1), 2),
                PeriodDate = pd,
                MonthName = if pd <> null then Date.MonthName(pd, "en-US") else "Unknown",
                MonthIndex = mi
            ], type record),
    ExpandK = Table.ExpandRecordColumn(AddK, "_K", {"FY", "PeriodDate", "MonthName", "MonthIndex"}),
    AddMeta = Table.AddColumn(ExpandK, "ReturnType", each "ESIC", type text),
    AddEntity = Table.AddColumn(Table.AddColumn(AddMeta, "EntityID", each "", type text), "EntityName", each "", type text),

    // ── 8. SET DATA TYPES ────────────────────────────────────────
    Typed = Table.TransformColumnTypes(AddEntity, {
        {"Amount", type number}, {"ChallanNumber", type text}, {"ChallanDate", type text},
        {"Party", type text}, {"PeriodDate", type date}, {"MonthIndex", Int64.Type},
        {"FY", type text}, {"MonthName", type text}
    }),
    Reordered = Table.ReorderColumns(Typed, {"ReturnType", "EntityID", "EntityName", "FY", "PeriodDate", "MonthName", "MonthIndex", "Party", "ChallanNumber", "ChallanDate", "Amount"}),
    DropOld = Table.RemoveColumns(Reordered, {"Year", "Month"}),

    // ── 9. Sanity checks → Flags / Status / PrimaryAmount ────────
    AddFlags = Table.AddColumn(DropOld, "Flags", each Text.Combine(List.RemoveNulls({
        if [ChallanNumber] = "ERROR" then "PARSE ERR" else null,
        if [PeriodDate] = null then "PERIOD?" else null,
        if [Party] = "Other" then "EXTRA CHALLAN" else null,
        if (try ([Amount] = null or [Amount] <= 0) otherwise true) then "AMT?" else null
    }), "; "), type text),
    AddStatus = Table.AddColumn(AddFlags, "Status", each if [ChallanNumber] = "ERROR" then "Error" else if [Flags] <> "" then "Review" else "OK", type text),
    AddPA = Table.AddColumn(AddStatus, "PrimaryAmount", each try [Amount] otherwise null, type number),
    Reorder2 = Table.ReorderColumns(AddPA, {"ReturnType", "EntityID", "EntityName", "FY", "PeriodDate", "MonthName", "MonthIndex", "Status", "Flags", "PrimaryAmount", "Party"}),

    // ── 10. FINAL SORT ───────────────────────────────────────────
    FinalData = Table.Sort(Reorder2, {{"FY", Order.Ascending}, {"MonthIndex", Order.Ascending}, {"Party", Order.Ascending}})
in
    FinalData
