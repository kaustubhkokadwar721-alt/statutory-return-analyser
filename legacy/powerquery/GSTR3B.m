let
// 1. Read Folder Path from dynamic DocPaths table
SourcePath = let v = Table.SelectRows(Excel.CurrentWorkbook(){[Name="DocPaths"]}[Content], each [DocType] = "GSTR3B"), p = if Table.RowCount(v) > 0 then v{0}[FolderPath] else null in if p = null or Text.Trim(Text.From(p)) = "" then error "Set the GSTR3B folder path in the DocPaths table (Config sheet)." else Text.Trim(Text.From(p)),

// 2. Load PDF Files
AllFiles = Folder.Files(SourcePath),
PDFsOnly = Table.SelectRows(AllFiles, each Text.Lower([Extension]) = ".pdf"),
FileCols = Table.SelectColumns(PDFsOnly, {"Content", "Name"}),

// 3. Define the Core Extraction Function
fnParseGSTR3B = (bin as binary, fname as text) as record =>
let
    ParsedRecord = try
        let
            RawData = Pdf.Tables(bin, [Implementation="1.3"]),
            TablesOnly = Table.SelectRows(RawData, each [Kind] = "Table"),
            CombinedData = Table.Combine(Table.Column(TablesOnly, "Data")),
            AllRows = Table.ToRows(CombinedData),

            // Helper: Clean Text  (try/otherwise already covers null)
            T = (v) => try Text.Trim(Text.From(v)) otherwise "",

            // Helper: Clean Number (commas, NBSP, line breaks, rupee, hyphen, null)
            N = (s as text) as nullable number =>
                let
                    c = Text.Trim(Text.Remove(s, {",", Character.FromNumber(160), Character.FromNumber(10), Character.FromNumber(13), Character.FromNumber(8377)}))
                in
                    if c = "" or c = "-" then 0 else try Number.FromText(c, "en-US") otherwise 0,

            FindRows = (lbl as text) as list =>
                List.Select(AllRows, (r) =>
                    List.AnyTrue(List.Transform(r, (c) => Text.Contains(Text.Upper(T(c)), Text.Upper(lbl))))
                ),

            GetTextVal = (lbl as text, condition as function) =>
                let
                    rows = FindRows(lbl),
                    cells = if List.Count(rows) > 0 then List.Transform(rows{0}, T) else {},
                    valid = List.Select(cells, condition)
                in
                    if List.Count(valid) > 0 then List.Last(valid) else "Unknown",

            GetNums = (r as list, lbl as text) as list =>
                let
                    texts = List.Transform(r, T),
                    lblIdx = List.PositionOf(List.Transform(texts, each Text.Contains(Text.Upper(_), Text.Upper(lbl))), true),
                    after = if lblIdx >= 0 then List.Range(texts, lblIdx + 1) else texts,
                    nums = List.Select(List.Transform(after, N), each _ <> null),
                    padded = nums & List.Repeat({0}, 12)
                in padded,

            // Unified row-number getter: G("lbl") = first match, G("lbl", 1) = second match
            G = (lbl as text, optional n as nullable number) as list =>
                let rows = FindRows(lbl), idx = if n = null then 0 else n
                in if List.Count(rows) > idx then GetNums(rows{idx}, lbl) else List.Repeat({0}, 12),

            // ── STEP 1: Basic Identifiers ──
            YrVal     = GetTextVal("Year", each _ <> "" and not Text.Contains(Text.Upper(_), "YEAR")),
            MthVal    = GetTextVal("Period", each _ <> "" and not Text.Contains(Text.Upper(_), "PERIOD") and not Text.Contains(Text.Upper(_), "RETURN")),
            // GSTIN: strip internal spaces before the 15-char test (PDF can split "MH 29AA...")
            GSTINraw  = GetTextVal("GSTIN of the supplier", each Text.Length(Text.Remove(_, {" "})) = 15),
            GSTINVal  = if GSTINraw = "Unknown" then "Unknown" else Text.Remove(GSTINraw, {" "}),
            LegalName = GetTextVal("Legal name", each _ <> "" and not Text.Contains(Text.Upper(_), "LEGAL NAME")),
            TradeName = GetTextVal("Trade name", each _ <> "" and not Text.Contains(Text.Upper(_), "TRADE NAME")),
            FilingDt  = GetTextVal("Date of ARN", each _ <> "" and not Text.Contains(Text.Upper(_), "DATE OF ARN")),

            // ── STEP 2: Table 3.1 ──
            v3_1a = G("other than zero rated"),
            v3_1b = G("zero rated)"),
            v3_1c = G("Other outward supplies"),
            v3_1d = G("liable to reverse charge"),

            Total_Output_IGST = v3_1a{1} + v3_1b{1} + v3_1c{1},
            Total_Output_CGST = v3_1a{2} + v3_1b{2} + v3_1c{2},
            Total_Output_SGST = v3_1a{3} + v3_1b{3} + v3_1c{3},

            // ── STEP 3: Table 4 (ITC) ──
            i4A1 = G("Import of goods"),
            i4A2 = G("Import of services"),
            i4A3 = G("other than 1 & 2 above"),
            i4A4 = G("from ISD"),
            i4A5 = G("All other ITC"),
            i4B1 = G("rules 38,42"),
            i4B2 = G("Others", 1),

            TotIGST_In = i4A1{0} + i4A2{0} + i4A3{0} + i4A4{0} + i4A5{0},
            TotCGST_In = i4A1{1} + i4A2{1} + i4A3{1} + i4A4{1} + i4A5{1},
            TotSGST_In = i4A1{2} + i4A2{2} + i4A3{2} + i4A4{2} + i4A5{2},

            InelIGST = i4B1{0} + i4B2{0},
            InelCGST = i4B1{1} + i4B2{1},
            InelSGST = i4B1{2} + i4B2{2},

            NetIGST = TotIGST_In - InelIGST,
            NetCGST = TotCGST_In - InelCGST,
            NetSGST = TotSGST_In - InelSGST,

            // ── STEP 4: Table 6.1 DYNAMIC MATRIX PARSER ──
            Tbl61_List = List.Select(TablesOnly[Data], each
                List.AnyTrue(List.Transform(Table.ToRows(_), (r) =>
                    List.AnyTrue(List.Transform(r, (c) => Text.Contains(Text.Upper(T(c)), "(A) OTHER THAN REVERSE CHARGE")))
                ))
            ),
            Tbl61 = if List.Count(Tbl61_List) > 0 then Tbl61_List{0} else #table({}, {}),
            Tbl61_Rows = Table.ToRows(Tbl61),

            idx_SecA = List.PositionOf(List.Transform(Tbl61_Rows, (r) => List.AnyTrue(List.Transform(r, (c) => Text.Contains(Text.Upper(T(c)), "(A) OTHER THAN REVERSE CHARGE")))), true),
            idx_SecB = List.PositionOf(List.Transform(Tbl61_Rows, (r) => List.AnyTrue(List.Transform(r, (c) => Text.Contains(Text.Upper(T(c)), "(B) REVERSE CHARGE")))), true),

            HeaderLimit = if idx_SecA > 0 then idx_SecA else if List.Count(Tbl61_Rows) > 4 then 4 else List.Count(Tbl61_Rows),
            HeaderRows = List.FirstN(Tbl61_Rows, HeaderLimit),
            ColCount = if List.Count(Tbl61_Rows) > 0 then List.Count(Tbl61_Rows{0}) else 0,

            GetColIdx = (keywords as list, optional afterIdx as number, optional beforeIdx as number) =>
                let
                    FoundIndices = List.Select({1..ColCount-1}, (i) =>
                        let
                            colCells = List.Transform(HeaderRows, (r) => try T(r{i}) otherwise ""),
                            combinedText = Text.Upper(Text.Combine(colCells, " "))
                        in
                            List.AllTrue(List.Transform(keywords, (kw) => Text.Contains(combinedText, Text.Upper(kw))))
                            and (if afterIdx <> null then i > afterIdx else true)
                            and (if beforeIdx <> null then i < beforeIdx else true)
                    )
                in
                    if List.Count(FoundIndices) > 0 then FoundIndices{0} else -1,

            idx_NetTax = GetColIdx({"NET", "PAYABLE"}),
            idx_Cash   = GetColIdx({"TAX", "CASH"}),
            idx_Int    = GetColIdx({"INTEREST", "CASH"}),
            idx_Late   = GetColIdx({"LATE", "CASH"}),

            idx_ITC_IGST = GetColIdx({"INTEGRATED"}, idx_NetTax, if idx_Cash <> -1 then idx_Cash else null),
            idx_ITC_CGST = GetColIdx({"CENTRAL"}, idx_NetTax, if idx_Cash <> -1 then idx_Cash else null),
            idx_ITC_SGST = GetColIdx({"STATE"}, idx_NetTax, if idx_Cash <> -1 then idx_Cash else null),

            GetMatrixRow = (keyword as text, startIdx as number, endIdx as number) =>
                if startIdx = -1 then null else
                let
                    rowsToSearch = if endIdx <> -1 then List.Range(Tbl61_Rows, startIdx + 1, endIdx - startIdx - 1) else List.Skip(Tbl61_Rows, startIdx + 1),
                    match = List.Select(rowsToSearch, (r) => Text.Contains(Text.Upper(T(r{0})), Text.Upper(keyword)))
                in
                    if List.Count(match) > 0 then match{0} else null,

            rowA_IGST = GetMatrixRow("INTEGRATED", idx_SecA, idx_SecB),
            rowA_CGST = GetMatrixRow("CENTRAL", idx_SecA, idx_SecB),
            rowA_SGST = GetMatrixRow("STATE", idx_SecA, idx_SecB),
            rowB_IGST = GetMatrixRow("INTEGRATED", idx_SecB, -1),
            rowB_CGST = GetMatrixRow("CENTRAL", idx_SecB, -1),
            rowB_SGST = GetMatrixRow("STATE", idx_SecB, -1),

            ExtractVal = (r as list, idx as number) as number =>
                if r <> null and idx <> -1 and idx < List.Count(r) then N(r{idx}) else 0,

            Util_IGST_to_IGST = ExtractVal(rowA_IGST, idx_ITC_IGST),
            Util_IGST_to_CGST = ExtractVal(rowA_CGST, idx_ITC_IGST),
            Util_IGST_to_SGST = ExtractVal(rowA_SGST, idx_ITC_IGST),
            Util_CGST_to_IGST = ExtractVal(rowA_IGST, idx_ITC_CGST),
            Util_CGST_to_CGST = ExtractVal(rowA_CGST, idx_ITC_CGST),
            Util_SGST_to_IGST = ExtractVal(rowA_IGST, idx_ITC_SGST),
            Util_SGST_to_SGST = ExtractVal(rowA_SGST, idx_ITC_SGST),

            Calc_IGST_Payable = Total_Output_IGST + v3_1d{1} - Util_IGST_to_IGST - Util_CGST_to_IGST - Util_SGST_to_IGST,
            Calc_CGST_Payable = Total_Output_CGST + v3_1d{2} - Util_IGST_to_CGST - Util_CGST_to_CGST,
            Calc_SGST_Payable = Total_Output_SGST + v3_1d{3} - Util_IGST_to_SGST - Util_SGST_to_SGST,

            IntPaid = ExtractVal(rowA_IGST, idx_Int) + ExtractVal(rowA_CGST, idx_Int) + ExtractVal(rowA_SGST, idx_Int)
                    + ExtractVal(rowB_IGST, idx_Int) + ExtractVal(rowB_CGST, idx_Int) + ExtractVal(rowB_SGST, idx_Int),
            LFPaid  = ExtractVal(rowA_IGST, idx_Late) + ExtractVal(rowA_CGST, idx_Late) + ExtractVal(rowA_SGST, idx_Late)
                    + ExtractVal(rowB_IGST, idx_Late) + ExtractVal(rowB_CGST, idx_Late) + ExtractVal(rowB_SGST, idx_Late)
        in
            [
                #"Year" = YrVal,
                #"Month" = MthVal,
                #"GSTIN" = GSTINVal,
                #"Company Name" = LegalName,
                #"Trade Name" = TradeName,
                #"Outward taxable supplies (other than zero rated, nil rated and exempted)" = v3_1a{0},
                #"Outward taxable supplies (zero rated)" = v3_1b{0},
                #"Other outward supplies (nil rated, exempted)" = v3_1c{0},
                #"Output IGST" = Total_Output_IGST,
                #"Output CGST" = Total_Output_CGST,
                #"Output SGST" = Total_Output_SGST,
                #"RCM Taxable Value" = v3_1d{0},
                #"RCM IGST Payable" = v3_1d{1},
                #"RCM CGST Payable" = v3_1d{2},
                #"RCM SGST Payable" = v3_1d{3},
                #"Total Input IGST" = TotIGST_In,
                #"Total Input CGST" = TotCGST_In,
                #"Total Input SGST" = TotSGST_In,
                #"Ineligible IGST" = InelIGST,
                #"Ineligible CGST" = InelCGST,
                #"Ineligible SGST" = InelSGST,
                #"Net Input IGST" = NetIGST,
                #"Net Input CGST" = NetCGST,
                #"Net Input SGST" = NetSGST,
                #"IGST to IGST" = Util_IGST_to_IGST,
                #"IGST to CGST" = Util_IGST_to_CGST,
                #"IGST to SGST" = Util_IGST_to_SGST,
                #"CGST to IGST" = Util_CGST_to_IGST,
                #"CGST to CGST" = Util_CGST_to_CGST,
                #"SGST to IGST" = Util_SGST_to_IGST,
                #"SGST to SGST" = Util_SGST_to_SGST,
                #"IGST Payable" = Calc_IGST_Payable,
                #"CGST Payable" = Calc_CGST_Payable,
                #"SGST Payable" = Calc_SGST_Payable,
                #"Interest paid" = IntPaid,
                #"Late Fees paid" = LFPaid,
                #"Date of filing" = FilingDt
            ]
    otherwise
        // Error fallback — numbers null (not 0) so a parse failure is distinguishable from a legit zero
        [
            #"Year" = "ERROR", #"Month" = fname, #"GSTIN" = "ERROR", #"Company Name" = "ERROR", #"Trade Name" = "ERROR",
            #"Outward taxable supplies (other than zero rated, nil rated and exempted)" = null, #"Outward taxable supplies (zero rated)" = null, #"Other outward supplies (nil rated, exempted)" = null,
            #"Output IGST" = null, #"Output CGST" = null, #"Output SGST" = null, #"RCM Taxable Value" = null, #"RCM IGST Payable" = null, #"RCM CGST Payable" = null, #"RCM SGST Payable" = null,
            #"Total Input IGST" = null, #"Total Input CGST" = null, #"Total Input SGST" = null, #"Ineligible IGST" = null, #"Ineligible CGST" = null, #"Ineligible SGST" = null,
            #"Net Input IGST" = null, #"Net Input CGST" = null, #"Net Input SGST" = null,
            #"IGST to IGST" = null, #"IGST to CGST" = null, #"IGST to SGST" = null, #"CGST to IGST" = null, #"CGST to CGST" = null, #"SGST to IGST" = null, #"SGST to SGST" = null,
            #"IGST Payable" = null, #"CGST Payable" = null, #"SGST Payable" = null, #"Interest paid" = null, #"Late Fees paid" = null,
            #"Date of filing" = "ERROR"
        ]
in
    ParsedRecord,

// 4. Extract Data
ParsedTable = Table.AddColumn(FileCols, "ExtractedData", each fnParseGSTR3B([Content], [Name])),
RemovedFiles = Table.RemoveColumns(ParsedTable, {"Content", "Name"}),

// 5. Expand Output
ExpandedData = Table.ExpandRecordColumn(RemovedFiles, "ExtractedData", {
    "Year", "Month", "GSTIN", "Company Name", "Trade Name",
    "Outward taxable supplies (other than zero rated, nil rated and exempted)", "Outward taxable supplies (zero rated)", "Other outward supplies (nil rated, exempted)",
    "Output IGST", "Output CGST", "Output SGST", "RCM Taxable Value", "RCM IGST Payable", "RCM CGST Payable", "RCM SGST Payable",
    "Total Input IGST", "Total Input CGST", "Total Input SGST", "Ineligible IGST", "Ineligible CGST", "Ineligible SGST", "Net Input IGST", "Net Input CGST", "Net Input SGST",
    "IGST to IGST", "IGST to CGST", "IGST to SGST", "CGST to IGST", "CGST to CGST", "SGST to IGST", "SGST to SGST",
    "IGST Payable", "CGST Payable", "SGST Payable", "Interest paid", "Late Fees paid", "Date of filing"
}),

// 6. Enforce Data Types
TypedData = Table.TransformColumnTypes(ExpandedData, {
    {"Year", type text}, {"Month", type text}, {"GSTIN", type text}, {"Company Name", type text}, {"Trade Name", type text},
    {"Outward taxable supplies (other than zero rated, nil rated and exempted)", type number}, {"Outward taxable supplies (zero rated)", type number}, {"Other outward supplies (nil rated, exempted)", type number},
    {"Output IGST", type number}, {"Output CGST", type number}, {"Output SGST", type number}, {"RCM Taxable Value", type number}, {"RCM IGST Payable", type number}, {"RCM CGST Payable", type number}, {"RCM SGST Payable", type number},
    {"Total Input IGST", type number}, {"Total Input CGST", type number}, {"Total Input SGST", type number}, {"Ineligible IGST", type number}, {"Ineligible CGST", type number}, {"Ineligible SGST", type number},
    {"Net Input IGST", type number}, {"Net Input CGST", type number}, {"Net Input SGST", type number},
    {"IGST to IGST", type number}, {"IGST to CGST", type number}, {"IGST to SGST", type number}, {"CGST to IGST", type number}, {"CGST to CGST", type number}, {"SGST to IGST", type number}, {"SGST to SGST", type number},
    {"IGST Payable", type number}, {"CGST Payable", type number}, {"SGST Payable", type number}, {"Interest paid", type number}, {"Late Fees paid", type number},
    {"Date of filing", type text}
}),

// 7. Group Month-wise and GSTIN-wise
GroupedData = Table.Group(TypedData, {"Year", "Month", "GSTIN", "Company Name", "Trade Name", "Date of filing"}, {
    {"Outward taxable supplies (other than zero rated, nil rated and exempted)", each List.Sum([#"Outward taxable supplies (other than zero rated, nil rated and exempted)"]), type nullable number},
    {"Outward taxable supplies (zero rated)", each List.Sum([#"Outward taxable supplies (zero rated)"]), type nullable number},
    {"Other outward supplies (nil rated, exempted)", each List.Sum([#"Other outward supplies (nil rated, exempted)"]), type nullable number},
    {"Output IGST", each List.Sum([Output IGST]), type nullable number},
    {"Output CGST", each List.Sum([Output CGST]), type nullable number},
    {"Output SGST", each List.Sum([Output SGST]), type nullable number},
    {"RCM Taxable Value", each List.Sum([RCM Taxable Value]), type nullable number},
    {"RCM IGST Payable", each List.Sum([RCM IGST Payable]), type nullable number},
    {"RCM CGST Payable", each List.Sum([RCM CGST Payable]), type nullable number},
    {"RCM SGST Payable", each List.Sum([RCM SGST Payable]), type nullable number},
    {"Total Input IGST", each List.Sum([Total Input IGST]), type nullable number},
    {"Total Input CGST", each List.Sum([Total Input CGST]), type nullable number},
    {"Total Input SGST", each List.Sum([Total Input SGST]), type nullable number},
    {"Ineligible IGST", each List.Sum([Ineligible IGST]), type nullable number},
    {"Ineligible CGST", each List.Sum([Ineligible CGST]), type nullable number},
    {"Ineligible SGST", each List.Sum([Ineligible SGST]), type nullable number},
    {"Net Input IGST", each List.Sum([Net Input IGST]), type nullable number},
    {"Net Input CGST", each List.Sum([Net Input CGST]), type nullable number},
    {"Net Input SGST", each List.Sum([Net Input SGST]), type nullable number},
    {"IGST to IGST", each List.Sum([IGST to IGST]), type nullable number},
    {"IGST to CGST", each List.Sum([IGST to CGST]), type nullable number},
    {"IGST to SGST", each List.Sum([IGST to SGST]), type nullable number},
    {"CGST to IGST", each List.Sum([CGST to IGST]), type nullable number},
    {"CGST to CGST", each List.Sum([CGST to CGST]), type nullable number},
    {"SGST to IGST", each List.Sum([SGST to IGST]), type nullable number},
    {"SGST to SGST", each List.Sum([SGST to SGST]), type nullable number},
    {"IGST Payable", each List.Sum([IGST Payable]), type nullable number},
    {"CGST Payable", each List.Sum([CGST Payable]), type nullable number},
    {"SGST Payable", each List.Sum([SGST Payable]), type nullable number},
    {"Interest paid", each List.Sum([Interest paid]), type nullable number},
    {"Late Fees paid", each List.Sum([Late Fees paid]), type nullable number}
}),

// 8. Standardized dimension contract (real PeriodDate, FY, MonthName, MonthIndex)
AddK = Table.AddColumn(GroupedData, "_K", each
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
AddReturnType = Table.AddColumn(ExpandK, "ReturnType", each "GSTR3B", type text),
RenamedDims = Table.RenameColumns(AddReturnType, {{"GSTIN", "EntityID"}, {"Company Name", "EntityName"}}),
DropOld = Table.RemoveColumns(RenamedDims, {"Year", "Month"}),
Reordered = Table.ReorderColumns(DropOld, {"ReturnType", "EntityID", "EntityName", "FY", "PeriodDate", "MonthName", "MonthIndex", "Trade Name", "Date of filing"}),
Typed2 = Table.TransformColumnTypes(Reordered, {{"PeriodDate", type date}, {"MonthIndex", Int64.Type}}),

// 9. Sanity checks → Flags / Status / PrimaryAmount
AddFlags = Table.AddColumn(Typed2, "Flags", each Text.Combine(List.RemoveNulls({
    if [EntityID] = "ERROR" then "PARSE ERR" else null,
    if [PeriodDate] = null then "PERIOD?" else null,
    if [EntityID] <> "ERROR" and (try (Text.Length([EntityID]) <> 15) otherwise true) then "GSTIN?" else null,
    if (try (Number.Abs([Output CGST] - [Output SGST]) > 1) otherwise false) then "CGST<>SGST(out)" else null,
    if (try (Number.Abs([Net Input CGST] - [Net Input SGST]) > 1) otherwise false) then "ITC CGST<>SGST" else null,
    if (try (List.Min({[IGST Payable], [CGST Payable], [SGST Payable]}) < 0) otherwise false) then "NEG PAYABLE" else null,
    if (try (([IGST to IGST] + [IGST to CGST] + [IGST to SGST] + [CGST to IGST] + [CGST to CGST] + [SGST to IGST] + [SGST to SGST]) > ([Net Input IGST] + [Net Input CGST] + [Net Input SGST]) + 1) otherwise false) then "UTIL>ITC" else null
}), "; "), type text),
AddStatus = Table.AddColumn(AddFlags, "Status", each if [EntityID] = "ERROR" then "Error" else if [Flags] <> "" then "Review" else "OK", type text),
AddPA = Table.AddColumn(AddStatus, "PrimaryAmount", each try ([IGST Payable] + [CGST Payable] + [SGST Payable]) otherwise null, type number),
Reorder2 = Table.ReorderColumns(AddPA, {"ReturnType", "EntityID", "EntityName", "FY", "PeriodDate", "MonthName", "MonthIndex", "Status", "Flags", "PrimaryAmount"}),

// 10. Final Sort (FY chronological + entity)
FinalData = Table.Sort(Reorder2, {{"FY", Order.Ascending}, {"MonthIndex", Order.Ascending}, {"EntityID", Order.Ascending}})
in
FinalData
