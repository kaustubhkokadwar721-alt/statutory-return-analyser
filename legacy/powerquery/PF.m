let
    // ── 1. Read Folder Path from dynamic DocPaths table ──────────
    SourcePath = let v = Table.SelectRows(Excel.CurrentWorkbook(){[Name="DocPaths"]}[Content], each [DocType] = "PF"), p = if Table.RowCount(v) > 0 then v{0}[FolderPath] else null in if p = null or Text.Trim(Text.From(p)) = "" then error "Set the PF folder path in the DocPaths table (Config sheet)." else Text.Trim(Text.From(p)),

    // ── 2. GET ALL PDF FILES FROM FOLDER ─────────────────────────
    AllFiles   = Folder.Files(SourcePath),
    PDFsOnly   = Table.SelectRows(AllFiles, each Text.Lower([Extension]) = ".pdf"),
    FileCols   = Table.SelectColumns(PDFsOnly, {"Content", "Name"}),

    // ── 3. PARSE FUNCTION ────────────────────────────────────────
    fnParsePF = (bin as binary, fname as text) as record =>
    let
        ParsedRecord = try
        let
            RawData      = Pdf.Tables(bin, [Implementation="1.3"]),

            // Tables (numbers)
            TablesOnly   = Table.SelectRows(RawData, each [Kind] = "Table"),
            CombinedData = if Table.RowCount(TablesOnly) > 0 then Table.Combine(Table.Column(TablesOnly, "Data")) else #table({}, {}),
            AllRows      = Table.ToRows(CombinedData),

            // Flattened text (header/footer)
            AllPagesOrTables = if Table.RowCount(RawData) > 0 then Table.Combine(Table.Column(RawData, "Data")) else #table({}, {}),
            AllCellsText     = List.Transform(List.Combine(Table.ToRows(AllPagesOrTables)), (x) => try Text.Trim(Text.From(x)) otherwise ""),
            AllTextStr       = Text.Combine(List.Select(AllCellsText, each _ <> ""), " "),

            // Case-insensitive locator
            Hay = Text.Upper(AllTextStr),
            Pos = (needle as text) as number => Text.PositionOf(Hay, Text.Upper(needle)),

            T = (v) => try Text.Trim(Text.From(v)) otherwise "",

            N = (s as text) as nullable number =>
                 let c = Text.Trim(Text.Remove(s, {",", Character.FromNumber(160), Character.FromNumber(10), Character.FromNumber(13), Character.FromNumber(8377)}))
                 in if c = "" or c = "-" then 0 else try Number.FromText(c, "en-US") otherwise 0,

            FindRows = (lbl as text) as list =>
                List.Select(AllRows, (r) => List.AnyTrue(List.Transform(r, (c) => Text.Contains(Text.Upper(T(c)), Text.Upper(lbl))))),

            GetNums = (r as list, lbl as text) as list =>
                let
                    texts  = List.Transform(r, T),
                    lblIdx = List.PositionOf(List.Transform(texts, each Text.Contains(Text.Upper(_), Text.Upper(lbl))), true),
                    after  = if lblIdx >= 0 then List.Range(texts, lblIdx + 1) else texts,
                    nums   = List.Select(List.Transform(after, N), each _ <> null),
                    padded = nums & List.Repeat({0}, 10)
                in padded,

            G = (lbl as text) as list =>
                let rows = FindRows(lbl) in if List.Count(rows) > 0 then GetNums(rows{0}, lbl) else List.Repeat({0}, 10),

            // ── Establishment Code & Name ──
            idxEst = Pos("Establishment Code & Name"),
            idxAddress = Pos("Address"),
            EstSubStr = if idxEst >= 0 and idxAddress > idxEst then Text.Trim(Text.Middle(AllTextStr, idxEst + Text.Length("Establishment Code & Name"), idxAddress - (idxEst + Text.Length("Establishment Code & Name")))) else "",
            EstabCode = if EstSubStr <> "" then Text.Split(EstSubStr, " "){0} else "Unknown",
            EstabNameRaw = if EstSubStr <> "" then Text.Trim(Text.Replace(EstSubStr, EstabCode, "")) else "Unknown",
            EstabName = if Text.Contains(EstabNameRaw, "Dues for") then Text.Trim(Text.Split(EstabNameRaw, "Dues for"){0}) else EstabNameRaw,

            // ── Month + Raw Year ──
            idxDues = Pos("Dues for the wage month of"),
            MonthYearStr = if idxDues >= 0 then Text.Trim(Text.Middle(AllTextStr, idxDues + Text.Length("Dues for the wage month of"), 30)) else "",
            FirstDigitIdx = Text.PositionOfAny(MonthYearStr, {"0","1","2","3","4","5","6","7","8","9"}),
            MonthVal = if FirstDigitIdx > 0 then Text.Trim(Text.Start(MonthYearStr, FirstDigitIdx))
                       else if MonthYearStr <> "" then Text.Split(MonthYearStr, " "){0} else "Unknown",
            RawYearVal = if FirstDigitIdx >= 0 then
                            try Number.FromText(Text.Start(Text.Select(Text.Middle(MonthYearStr, FirstDigitIdx), {"0","1","2","3","4","5","6","7","8","9"}), 4)) otherwise 0
                         else 0,

            // ── Financial Year ──
            MonthUpper  = Text.Upper(MonthVal),
            IsQ1toQ3    = List.AnyTrue(List.Transform({"APR","MAY","JUN","JUL","AUG","SEP","OCT","NOV","DEC"}, each Text.Contains(MonthUpper, _))),
            FYStartYear = if RawYearVal = 0 then 0 else if IsQ1toQ3 then RawYearVal else RawYearVal - 1,
            FYEndYY     = if FYStartYear = 0 then "??" else Text.End(Text.From(FYStartYear + 1), 2),
            FinancialYear = if FYStartYear = 0 then "Unknown" else Text.From(FYStartYear) & "-" & FYEndYY,

            // ── Challan Generation Date ──
            idxGen = Pos("system generated challan on "),
            GenStr = if idxGen >= 0 then Text.Trim(Text.Middle(AllTextStr, idxGen + Text.Length("system generated challan on "), 20)) else "",
            ChallanDate = if GenStr <> "" then Text.Split(GenStr, " "){0} else "Unknown",

            // ── Table amounts ──
            rAdmin      = G("Administration Charges"),
            rEmployer   = G("Employer"),
            rEmployee   = G("Employee"),

            Employer_EPF_AC01        = rEmployer{0},
            Employer_EPS_AC10        = rEmployer{2},
            Employer_EDLI_AC21       = rEmployer{3},
            Total_Employer           = Employer_EPF_AC01 + Employer_EPS_AC10 + Employer_EDLI_AC21,
            PF_Admin_AC02            = rAdmin{1},
            EDLI_Admin_AC22          = rAdmin{4},
            Total_Admin              = PF_Admin_AC02 + EDLI_Admin_AC22,
            Total_Employer_wAdmin    = Total_Employer + Total_Admin,
            Employee_EPF_AC01        = rEmployee{0},
            Grand_Total              = Total_Employer_wAdmin + Employee_EPF_AC01
        in
            [
                #"Establishment_Code"            = EstabCode,
                #"Establishment_Name"            = EstabName,
                #"Financial_Year"                = FinancialYear,
                #"Month"                         = MonthVal,
                #"Challan_Date"                  = ChallanDate,
                #"Employer_EPF_AC01"             = Employer_EPF_AC01,
                #"Employer_EPS_AC10"             = Employer_EPS_AC10,
                #"Employer_EDLI_AC21"            = Employer_EDLI_AC21,
                #"Total_Employer_Contribution"   = Total_Employer,
                #"PF_Admin_AC02"                 = PF_Admin_AC02,
                #"EDLI_Admin_AC22"               = EDLI_Admin_AC22,
                #"Total_Admin_Charges"           = Total_Admin,
                #"Total_Employer_incl_Admin"     = Total_Employer_wAdmin,
                #"Employee_EPF_AC01"             = Employee_EPF_AC01,
                #"Grand_Total"                   = Grand_Total
            ]
        otherwise
            [
                #"Establishment_Code"            = "PARSE ERROR",
                #"Establishment_Name"            = "ERROR",
                #"Financial_Year"                = "ERROR",
                #"Month"                         = fname,
                #"Challan_Date"                  = "ERROR",
                #"Employer_EPF_AC01"             = null,
                #"Employer_EPS_AC10"             = null,
                #"Employer_EDLI_AC21"            = null,
                #"Total_Employer_Contribution"   = null,
                #"PF_Admin_AC02"                 = null,
                #"EDLI_Admin_AC22"               = null,
                #"Total_Admin_Charges"           = null,
                #"Total_Employer_incl_Admin"     = null,
                #"Employee_EPF_AC01"             = null,
                #"Grand_Total"                   = null
            ]
    in
        ParsedRecord,

    // ── 4. APPLY PARSER TO EVERY PDF ─────────────────────────────
    ParsedTable  = Table.AddColumn(FileCols, "ExtractedData", each fnParsePF([Content], [Name])),
    RemovedFiles = Table.RemoveColumns(ParsedTable, {"Content", "Name"}),

    // ── 5. EXPAND ALL 15 COLUMNS ─────────────────────────────────
    ExpandedData = Table.ExpandRecordColumn(RemovedFiles, "ExtractedData", {
        "Establishment_Code", "Establishment_Name", "Financial_Year", "Month", "Challan_Date",
        "Employer_EPF_AC01", "Employer_EPS_AC10", "Employer_EDLI_AC21", "Total_Employer_Contribution",
        "PF_Admin_AC02", "EDLI_Admin_AC22", "Total_Admin_Charges", "Total_Employer_incl_Admin",
        "Employee_EPF_AC01", "Grand_Total"
    }),

    // ── 6. SET DATA TYPES ────────────────────────────────────────
    TypedData = Table.TransformColumnTypes(ExpandedData, {
        {"Establishment_Code",          type text},
        {"Establishment_Name",          type text},
        {"Financial_Year",              type text},
        {"Month",                       type text},
        {"Challan_Date",                type text},
        {"Employer_EPF_AC01",           type number},
        {"Employer_EPS_AC10",           type number},
        {"Employer_EDLI_AC21",          type number},
        {"Total_Employer_Contribution", type number},
        {"PF_Admin_AC02",               type number},
        {"EDLI_Admin_AC22",             type number},
        {"Total_Admin_Charges",         type number},
        {"Total_Employer_incl_Admin",   type number},
        {"Employee_EPF_AC01",           type number},
        {"Grand_Total",                 type number}
    }),

    // ── 7. Standardized dimension contract + drop redundant roll-ups ──
    AddK = Table.AddColumn(TypedData, "_K", each
        let
            r = [APR=1,MAY=2,JUN=3,JUL=4,AUG=5,SEP=6,OCT=7,NOV=8,DEC=9,JAN=10,FEB=11,MAR=12],
            mi = try Record.Field(r, Text.Upper(Text.Start(Text.Trim(try [Month] otherwise ""), 3))) otherwise 0,
            fyStart = try Number.FromText(Text.Start(Text.Select(try [Financial_Year] otherwise "", {"0".."9"}), 4)) otherwise 0,
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
    AddMeta = Table.AddColumn(ExpandK, "ReturnType", each "PF", type text),
    RenamedDims = Table.RenameColumns(AddMeta, {{"Establishment_Code", "EntityID"}, {"Establishment_Name", "EntityName"}}),
    // Drop roll-ups (recomputable from components) + replaced raw period cols
    DropOld = Table.RemoveColumns(RenamedDims, {"Financial_Year", "Month", "Total_Employer_Contribution", "Total_Admin_Charges", "Total_Employer_incl_Admin", "Grand_Total"}),
    Reordered = Table.ReorderColumns(DropOld, {"ReturnType", "EntityID", "EntityName", "FY", "PeriodDate", "MonthName", "MonthIndex", "Challan_Date"}),
    Typed2 = Table.TransformColumnTypes(Reordered, {{"PeriodDate", type date}, {"MonthIndex", Int64.Type}}),

    // ── 8. Sanity checks → Flags / Status / PrimaryAmount ────────
    AddFlags = Table.AddColumn(Typed2, "Flags", each Text.Combine(List.RemoveNulls({
        if [EntityID] = "PARSE ERROR" then "PARSE ERR" else null,
        if [PeriodDate] = null then "PERIOD?" else null,
        if (try ([Employer_EPS_AC10] > [Employer_EPF_AC01] + 1) otherwise false) then "EPS>EPF?" else null,
        if (try (Number.Abs([Employee_EPF_AC01] - ([Employer_EPF_AC01] + [Employer_EPS_AC10])) > 1) otherwise false) then "EE<>ER(EPF+EPS)" else null,
        if (try ([PF_Admin_AC02] = null or [PF_Admin_AC02] = 0) otherwise true) then "NO ADMIN" else null
    }), "; "), type text),
    AddStatus = Table.AddColumn(AddFlags, "Status", each if [EntityID] = "PARSE ERROR" then "Error" else if [Flags] <> "" then "Review" else "OK", type text),
    AddPA = Table.AddColumn(AddStatus, "PrimaryAmount", each try ([Employer_EPF_AC01] + [Employer_EPS_AC10] + [Employer_EDLI_AC21] + [PF_Admin_AC02] + [EDLI_Admin_AC22] + [Employee_EPF_AC01]) otherwise null, type number),
    Reorder2 = Table.ReorderColumns(AddPA, {"ReturnType", "EntityID", "EntityName", "FY", "PeriodDate", "MonthName", "MonthIndex", "Status", "Flags", "PrimaryAmount"}),

    // ── 9. SORT: FY → Month (FY order) → EntityID ────────────────
    FinalData = Table.Sort(Reorder2, {{"FY", Order.Ascending}, {"MonthIndex", Order.Ascending}, {"EntityID", Order.Ascending}})
in
    FinalData
