let
    // ── 1. Read Folder Path from dynamic DocPaths table ──────────
    SourcePath = let v = Table.SelectRows(Excel.CurrentWorkbook(){[Name="DocPaths"]}[Content], each [DocType] = "TDS"), p = if Table.RowCount(v) > 0 then v{0}[FolderPath] else null in if p = null or Text.Trim(Text.From(p)) = "" then error "Set the TDS folder path in the DocPaths table (Config sheet)." else Text.Trim(Text.From(p)),

    // ── 2. GET ALL PDF FILES FROM FOLDER ─────────────────────────
    AllFiles = Folder.Files(SourcePath),
    PDFsOnly = Table.SelectRows(AllFiles, each Text.Lower([Extension]) = ".pdf"),
    FileCols = Table.SelectColumns(PDFsOnly, {"Content", "Name"}),

    // ── 3. PARSE FUNCTION ────────────────────────────────────────
    fnParseTDS = (bin as binary, fname as text) as record =>
    let
        ParsedRecord = try
        let
            RawData = Pdf.Tables(bin, [Implementation="1.3"]),
            AllContent = if Table.RowCount(RawData) > 0 then Table.Combine(Table.Column(RawData, "Data")) else #table({}, {}),

            FlatList = List.Transform(List.Combine(Table.ToRows(AllContent)), (x) => try Text.Trim(Text.From(x)) otherwise ""),
            CleanCellsOrig = List.Select(List.Transform(FlatList, each Text.Trim(Text.Remove(_, {":"}))), each _ <> "" and _ <> null),
            CleanCellsUpper = List.Transform(CleanCellsOrig, Text.Upper),

            FindIdx = (lbl as text) => List.PositionOf(CleanCellsUpper, Text.Upper(lbl)),

            FindVal = (lbl as text) =>
                let idx = FindIdx(lbl)
                in if idx >= 0 and idx + 1 < List.Count(CleanCellsOrig) then CleanCellsOrig{idx + 1} else "",

            FindValBetween = (lbl1 as text, lbl2 as text) =>
                let idx1 = FindIdx(lbl1), idx2 = FindIdx(lbl2)
                in if idx1 >= 0 and idx2 > idx1 then Text.Combine(List.Range(CleanCellsOrig, idx1 + 1, idx2 - idx1 - 1), " ") else FindVal(lbl1),

            // FIX: keep the decimal point; pin culture to en-US (was locale-dependent and dropped ".")
            N = (s as text) =>
                let clean = Text.Trim(Text.Select(s, {"0".."9", ".", "-"}))
                in if clean = "" or clean = "-" then 0 else try Number.FromText(clean, "en-US") otherwise 0,

            TAN_Val       = FindVal("TAN"),

            CompanyNameRaw = FindValBetween("NAME", "FINANCIAL YEAR"),
            idxAss = Text.PositionOf(Text.Upper(CompanyNameRaw), "ASSESSMENT YEAR"),
            CompanyName = if idxAss >= 0 then Text.Trim(Text.Start(CompanyNameRaw, idxAss)) else CompanyNameRaw,

            FY_Val        = FindVal("FINANCIAL YEAR"),

            NOP_Raw       = FindVal("NATURE OF PAYMENT"),
            Section_Val   = if NOP_Raw <> "" then Text.Split(NOP_Raw, " "){0} else "Unknown",

            MajorHeadRaw  = FindVal("MAJOR HEAD"),
            MH_Upper      = Text.Upper(MajorHeadRaw),
            MajorHead_Val = if Text.Contains(MH_Upper, "OTHER THAN COMPAN") or Text.Contains(MH_Upper, "0021") then "Other than Companies"
                            else if Text.Contains(MH_Upper, "COMPAN") or Text.Contains(MH_Upper, "CORPORATION") or Text.Contains(MH_Upper, "0020") then "Corporation Tax"
                            else Text.Trim(Text.Split(MajorHeadRaw, "("){0}),

            ChallanNo_Val = FindVal("CHALLAN NO"),

            PDateStr      = FindVal("DATE OF DEPOSIT"),
            // FIX: try more cultures + dd-MMM-yyyy style before giving up
            PaymentDate   = try Date.FromText(PDateStr, [Culture="en-IN"])
                            otherwise try Date.FromText(PDateStr, [Culture="en-GB"])
                            otherwise try Date.FromText(PDateStr, [Culture="en-US"])
                            otherwise null,

            TotalAmountPaid = N(FindVal("AMOUNT (IN RS.)")),

            Tax           = N(FindVal("TAX")),
            Surcharge     = N(FindVal("SURCHARGE")),
            Cess          = N(FindVal("CESS")),
            InterestAmt   = N(FindVal("INTEREST")),
            Penalty       = N(FindVal("PENALTY")),
            Fee234E       = N(FindVal("FEE UNDER SECTION 234E")),

            CrosscheckDiff = TotalAmountPaid - (Tax + Surcharge + Cess + InterestAmt + Penalty + Fee234E),

            // TDS deduction-month logic (ASSUMPTION: interest present => prior-month liability)
            DeductionDate =
                if PaymentDate = null then null
                else
                    let
                        PDay = Date.Day(PaymentDate),
                        PMonth = Date.Month(PaymentDate),
                        PYear = Date.Year(PaymentDate)
                    in
                        if PMonth = 4 then #date(PYear, 3, 1)
                        else if PDay <= 7 then Date.AddMonths(#date(PYear, PMonth, 1), -1)
                        else if InterestAmt > 0 then Date.AddMonths(#date(PYear, PMonth, 1), -1)
                        else #date(PYear, PMonth, 1),
            TDS_Month = if DeductionDate = null then "Unknown" else Date.MonthName(DeductionDate, "en-US") & " " & Text.From(Date.Year(DeductionDate))
        in
            [
                #"TAN"                    = if TAN_Val = "" then "Unknown" else TAN_Val,
                #"Company Name"           = CompanyName,
                #"FY"                     = FY_Val,
                #"Month"                  = TDS_Month,
                #"Section"                = Section_Val,
                #"Major Head"             = MajorHead_Val,
                #"Total Amount Paid"      = TotalAmountPaid,
                #"Tax"                    = Tax,
                #"Surcharge"              = Surcharge,
                #"Cess"                   = Cess,
                #"Interest"               = InterestAmt,
                #"Penalty"                = Penalty,
                #"Fee under section 234E" = Fee234E,
                #"Crosscheck Diff"        = CrosscheckDiff,
                #"Challan No"             = ChallanNo_Val,
                #"Payment Date"           = PaymentDate,
                #"PeriodDate"             = if DeductionDate = null then null else Date.StartOfMonth(DeductionDate)
            ]
        otherwise
            [
                #"TAN" = "ERROR", #"Company Name" = fname, #"FY" = null, #"Month" = null,
                #"Section" = null, #"Major Head" = null, #"Total Amount Paid" = null,
                #"Tax" = null, #"Surcharge" = null, #"Cess" = null, #"Interest" = null,
                #"Penalty" = null, #"Fee under section 234E" = null, #"Crosscheck Diff" = null,
                #"Challan No" = null, #"Payment Date" = null, #"PeriodDate" = null
            ]
    in
        ParsedRecord,

    // ── 4. APPLY PARSER TO EVERY PDF ─────────────────────────────
    ParsedTable  = Table.AddColumn(FileCols, "ExtractedData", each fnParseTDS([Content], [Name])),
    RemovedFiles = Table.RemoveColumns(ParsedTable, {"Content", "Name"}),

    // ── 5. EXPAND ALL COLUMNS (incl. PeriodDate) ─────────────────
    ExpandedData = Table.ExpandRecordColumn(RemovedFiles, "ExtractedData", {
        "TAN", "Company Name", "FY", "Month", "Section", "Major Head", "Total Amount Paid",
        "Tax", "Surcharge", "Cess", "Interest", "Penalty", "Fee under section 234E",
        "Crosscheck Diff", "Challan No", "Payment Date", "PeriodDate"
    }),

    // ── 6. SET DATA TYPES ────────────────────────────────────────
    TypedData = Table.TransformColumnTypes(ExpandedData, {
        {"TAN", type text}, {"Company Name", type text}, {"Section", type text}, {"Major Head", type text},
        {"Total Amount Paid", type number},
        {"Tax", type number}, {"Surcharge", type number}, {"Cess", type number},
        {"Interest", type number}, {"Penalty", type number}, {"Fee under section 234E", type number},
        {"Crosscheck Diff", type number}, {"Challan No", type text}, {"Payment Date", type date}, {"PeriodDate", type date}
    }),

    // ── 7. Standardized dimension contract (derived from PeriodDate = deduction month) ──
    // Drop raw reported FY + redundant Month text first (raw FY would collide with derived FY)
    DropRaw = Table.RemoveColumns(TypedData, {"FY", "Month"}),
    AddK = Table.AddColumn(DropRaw, "_K", each
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
    AddMeta = Table.AddColumn(ExpandK, "ReturnType", each "TDS", type text),
    RenamedDims = Table.RenameColumns(AddMeta, {{"TAN", "EntityID"}, {"Company Name", "EntityName"}}),
    Reordered = Table.ReorderColumns(RenamedDims, {"ReturnType", "EntityID", "EntityName", "FY", "PeriodDate", "MonthName", "MonthIndex", "Section", "Major Head", "Challan No", "Payment Date"}),
    Typed2 = Table.TransformColumnTypes(Reordered, {{"MonthIndex", Int64.Type}}),

    // ── 8. Sanity checks → Flags / Status / PrimaryAmount ────────
    AddFlags = Table.AddColumn(Typed2, "Flags", each Text.Combine(List.RemoveNulls({
        if [EntityID] = "ERROR" then "PARSE ERR" else null,
        if [PeriodDate] = null then "MONTH?" else null,
        if (try (Number.Abs([Crosscheck Diff]) > 1) otherwise false) then "CROSSCHECK" else null,
        if (try ([Section] = null or [Section] = "Unknown") otherwise true) then "SECTION?" else null,
        if (try ([Total Amount Paid] = null or [Total Amount Paid] <= 0) otherwise true) then "AMT?" else null
    }), "; "), type text),
    AddStatus = Table.AddColumn(AddFlags, "Status", each if [EntityID] = "ERROR" then "Error" else if [Flags] <> "" then "Review" else "OK", type text),
    AddPA = Table.AddColumn(AddStatus, "PrimaryAmount", each try [Total Amount Paid] otherwise null, type number),
    Reorder2 = Table.ReorderColumns(AddPA, {"ReturnType", "EntityID", "EntityName", "FY", "PeriodDate", "MonthName", "MonthIndex", "Status", "Flags", "PrimaryAmount"}),

    // ── 9. SORT: FY → Month (FY order) → Section → EntityID ───────
    FinalData = Table.Sort(Reorder2, {{"FY", Order.Ascending}, {"MonthIndex", Order.Ascending}, {"Section", Order.Ascending}, {"EntityID", Order.Ascending}})
in
    FinalData
