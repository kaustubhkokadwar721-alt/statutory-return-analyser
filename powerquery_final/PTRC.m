let
    // ── 1. Read Folder Path from dynamic DocPaths table ──────────
    SourcePath = let v = Table.SelectRows(Excel.CurrentWorkbook(){[Name="DocPaths"]}[Content], each [DocType] = "PTRC"), p = if Table.RowCount(v) > 0 then v{0}[FolderPath] else null in if p = null or Text.Trim(Text.From(p)) = "" then error "Set the PTRC folder path in the DocPaths table (Config sheet)." else Text.Trim(Text.From(p)),

    // ── 2. GET ALL PDF FILES FROM FOLDER ─────────────────────────
    AllFiles   = Folder.Files(SourcePath),
    PDFsOnly   = Table.SelectRows(AllFiles, each Text.Lower([Extension]) = ".pdf"),
    FileCols   = Table.SelectColumns(PDFsOnly, {"Content", "Name"}),

    // ── 3. PARSE FUNCTION ────────────────────────────────────────
    fnParsePT = (bin as binary, fname as text) as record =>
    let
        ParsedRecord = try
        let
            RawData          = Pdf.Tables(bin, [Implementation="1.3"]),
            AllPagesOrTables = if Table.RowCount(RawData) > 0 then Table.Combine(Table.Column(RawData, "Data")) else #table({}, {}),
            AllCellsText     = List.Transform(List.Combine(Table.ToRows(AllPagesOrTables)), (x) => try Text.Trim(Text.From(x)) otherwise ""),
            AllTextStr       = Text.Combine(List.Select(AllCellsText, each _ <> ""), " "),

            // Case-insensitive locator
            Hay = Text.Upper(AllTextStr),
            Pos = (needle as text) as number => Text.PositionOf(Hay, Text.Upper(needle)),

            N = (s as text) as nullable number =>
                 let c = Text.Trim(Text.Remove(s, {",", Character.FromNumber(160), Character.FromNumber(10), Character.FromNumber(13), Character.FromNumber(8377)}))
                 in if c = "" or c = "-" then 0 else try Number.FromText(c, "en-US") otherwise 0,

            // ── Type of Return ──
            idxType   = Pos("Type of Payment"),
            idxOffice = Pos("Office Name"),
            RawType   = if idxType >= 0 and idxOffice > idxType then Text.Trim(Text.Middle(AllTextStr, idxType + Text.Length("Type of Payment"), idxOffice - (idxType + Text.Length("Type of Payment")))) else "Unknown",
            TypeOfReturn = if Text.Contains(RawType, "Maharashtra Profession Tax PTRC") then "Maharashtra Profession Tax PTRC" else RawType,

            // ── TAN ──
            idxTAN1 = Pos("TAX ID/TAN (If Any)"),
            idxTAN2 = Pos("TAX ID / TAN (If Any)"),
            idxTAN3 = Pos("TAN (If Any)"),
            StartIdxTAN = if idxTAN1 >= 0 then idxTAN1 + Text.Length("TAX ID/TAN (If Any)")
                          else if idxTAN2 >= 0 then idxTAN2 + Text.Length("TAX ID / TAN (If Any)")
                          else if idxTAN3 >= 0 then idxTAN3 + Text.Length("TAN (If Any)")
                          else -1,
            TANRaw = if StartIdxTAN >= 0 then Text.Trim(Text.Middle(AllTextStr, StartIdxTAN, 30)) else "",
            TANValRaw = if TANRaw <> "" then Text.Split(TANRaw, " "){0} else "Unknown",
            TANVal = if TANValRaw = "PAN" or TANValRaw = "Type" or TANValRaw = "Full" then "" else TANValRaw,

            // ── Company Name (split fields) ──
            idxFullName = Pos("Full Name"),
            idxLocation = Pos("Location"),
            NamePart1   = if idxFullName >= 0 and idxLocation > idxFullName then Text.Trim(Text.Middle(AllTextStr, idxFullName + Text.Length("Full Name"), idxLocation - (idxFullName + Text.Length("Full Name")))) else "",
            idxRemarks  = Pos("Remarks (If Any)"),
            idxAmtIn    = Pos("Amount In"),
            RemarksGap  = idxAmtIn - (idxRemarks + Text.Length("Remarks (If Any)")),
            NamePart2   = if idxRemarks >= 0 and idxAmtIn > idxRemarks and RemarksGap < 150 then Text.Trim(Text.Middle(AllTextStr, idxRemarks + Text.Length("Remarks (If Any)"), RemarksGap)) else "",
            CompanyName = Text.Trim(NamePart1 & " " & NamePart2),

            // ── Date of filing ──
            idxDate  = Pos("Date "),
            DateRaw  = if idxDate >= 0 then Text.Middle(AllTextStr, idxDate + Text.Length("Date "), 10) else "",
            FilingDate = Text.Trim(DateRaw),

            // ── Year ──
            idxYear = Pos("Year"),
            YearRaw = if idxYear >= 0 then Text.Middle(AllTextStr, idxYear + Text.Length("Year"), 15) else "",
            YearVal = Text.Split(Text.Trim(YearRaw), " "){0},

            // ── Month & PTRC Return Month ──
            idxFromStr = Pos("From "),
            FromDateRaw = if idxFromStr >= 0 then Text.Trim(Text.Middle(AllTextStr, idxFromStr + Text.Length("From "), 10)) else "",
            ParsedFromDate = try Date.FromText(FromDateRaw, [Format="dd/MM/yyyy", Culture="en-GB"]) otherwise null,
            MonthVal = if ParsedFromDate <> null then Date.ToText(ParsedFromDate, "MMMM yyyy", "en-US") else "Unknown",
            ReturnMonthDate = try Date.AddMonths(ParsedFromDate, -1) otherwise null,
            PTRCReturnMonth = if ReturnMonthDate <> null then Date.ToText(ReturnMonthDate, "MMM yyyy", "en-US") else "Unknown",

            // ── PT Paid ──
            idxAmtTax = Pos("AMOUNT OF TAX"),
            AmtRaw    = if idxAmtTax >= 0 then Text.Trim(Text.Middle(AllTextStr, idxAmtTax + Text.Length("AMOUNT OF TAX"), 20)) else "",
            AmtStr    = Text.Split(AmtRaw, " "){0},
            PTPaid    = N(AmtStr),

            // ── Ref. No. (Challan No.) ──
            idxRef = Pos("Ref. No."),
            RefRaw = if idxRef >= 0 then Text.Trim(Text.Middle(AllTextStr, idxRef + Text.Length("Ref. No."), 30)) else "",
            ChallanNo = if RefRaw <> "" then Text.Split(RefRaw, " "){0} else "Unknown"
        in
            [
                #"Type of Return"            = TypeOfReturn,
                #"TAN"                       = TANVal,
                #"Company Name"              = if CompanyName = "" then "Unknown" else CompanyName,
                #"PTRC return for the month" = PTRCReturnMonth,
                #"Date of filing"            = if FilingDate = "" then "Unknown" else FilingDate,
                #"Year"                      = if YearVal = "" then "Unknown" else YearVal,
                #"Month"                     = MonthVal,
                #"PT Paid"                   = PTPaid,
                #"Challan No."               = ChallanNo,
                // locale-proof real first-of-month date (drives FY/MonthName/sort)
                #"PeriodDate"                = if ReturnMonthDate <> null then Date.StartOfMonth(ReturnMonthDate) else null
            ]
        otherwise
            [
                #"Type of Return"            = "ERROR",
                #"TAN"                       = "ERROR",
                #"Company Name"              = fname,
                #"PTRC return for the month" = "ERROR",
                #"Date of filing"            = "ERROR",
                #"Year"                      = "ERROR",
                #"Month"                     = "ERROR",
                #"PT Paid"                   = null,
                #"Challan No."               = "ERROR",
                #"PeriodDate"                = null
            ]
    in
        ParsedRecord,

    // ── 4. APPLY PARSER TO EVERY PDF ─────────────────────────────
    ParsedTable  = Table.AddColumn(FileCols, "ExtractedData", each fnParsePT([Content], [Name])),
    RemovedFiles = Table.RemoveColumns(ParsedTable, {"Content", "Name"}),

    // ── 5. EXPAND COLUMNS (incl. PeriodDate) ─────────────────────
    ExpandedData = Table.ExpandRecordColumn(RemovedFiles, "ExtractedData", {
        "Type of Return", "TAN", "Company Name", "PTRC return for the month", "Date of filing", "Year", "Month", "PT Paid", "Challan No.", "PeriodDate"
    }),

    // ── 6. SET DATA TYPES ────────────────────────────────────────
    TypedData = Table.TransformColumnTypes(ExpandedData, {
        {"Type of Return",            type text},
        {"TAN",                       type text},
        {"Company Name",              type text},
        {"Date of filing",            type text},
        {"PT Paid",                   type number},
        {"Challan No.",               type text},
        {"PeriodDate",                type date}
    }),

    // ── 7. Standardized dimension contract (derived from PeriodDate) ──
    AddK = Table.AddColumn(TypedData, "_K", each
        let
            d = [PeriodDate],
            calY = if d = null then null else Date.Year(d),
            calM = if d = null then null else Date.Month(d),
            fyStart = if d = null then 0 else if calM >= 4 then calY else calY - 1,
            mi = if d = null then 0 else if calM >= 4 then calM - 3 else calM + 9
        in
            [
                FY = if fyStart = 0 then "Unknown" else Text.From(fyStart) & "-" & Text.End(Text.From(fyStart + 1), 2),
                MonthName = if d = null then "Unknown" else Date.MonthName(d, "en-US"),
                MonthIndex = mi
            ], type record),
    ExpandK = Table.ExpandRecordColumn(AddK, "_K", {"FY", "MonthName", "MonthIndex"}),
    AddMeta = Table.AddColumn(ExpandK, "ReturnType", each "PTRC", type text),
    RenamedDims = Table.RenameColumns(AddMeta, {{"TAN", "EntityID"}, {"Company Name", "EntityName"}}),
    DropOld = Table.RemoveColumns(RenamedDims, {"Year", "Month", "PTRC return for the month"}),
    Reordered = Table.ReorderColumns(DropOld, {"ReturnType", "EntityID", "EntityName", "FY", "PeriodDate", "MonthName", "MonthIndex", "Type of Return", "Date of filing", "Challan No.", "PT Paid"}),
    Typed2 = Table.TransformColumnTypes(Reordered, {{"MonthIndex", Int64.Type}}),

    // ── 8. Sanity checks → Flags / Status / PrimaryAmount ────────
    AddFlags = Table.AddColumn(Typed2, "Flags", each Text.Combine(List.RemoveNulls({
        if [EntityName] = "ERROR" or [Type of Return] = "ERROR" then "PARSE ERR" else null,
        if [PeriodDate] = null then "PERIOD?" else null,
        if (try ([PT Paid] = null or [PT Paid] <= 0) otherwise true) then "AMT?" else null,
        if (try (not Text.Contains([Type of Return], "PTRC")) otherwise true) then "TYPE?" else null,
        if (try ([EntityID] = "" or [EntityID] = "Unknown") otherwise true) then "TAN?" else null
    }), "; "), type text),
    AddStatus = Table.AddColumn(AddFlags, "Status", each if [Type of Return] = "ERROR" then "Error" else if [Flags] <> "" then "Review" else "OK", type text),
    AddPA = Table.AddColumn(AddStatus, "PrimaryAmount", each try [PT Paid] otherwise null, type number),
    Reorder2 = Table.ReorderColumns(AddPA, {"ReturnType", "EntityID", "EntityName", "FY", "PeriodDate", "MonthName", "MonthIndex", "Status", "Flags", "PrimaryAmount"}),

    // ── 9. FINAL SORT ────────────────────────────────────────────
    FinalData = Table.Sort(Reorder2, {{"FY", Order.Ascending}, {"MonthIndex", Order.Ascending}, {"EntityName", Order.Ascending}})
in
    FinalData
