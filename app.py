# app.py
import streamlit as st
import pandas as pd
import re
from difflib import get_close_matches
from io import BytesIO

st.set_page_config(page_title="WMS Mapping Validator", layout="wide")

# ----------------------
# Config / patterns
# ----------------------
# Jika data di sheet mulai pada Excel row ke-3, maka header ada di row ke-2 -> header index = 1 (0-based)
HEADER_ROW = 1  # <-- ubah kalau header berada di baris lain (0-based)
MATCH_THRESHOLD = 0.5

# Patterns based on rules:
PATTERNS = {
    "LOTTABLE01": re.compile(r"^[^|]+\|[^|]+$"),               # shipment|PO
    "LOTTABLE02": None,                                       # Project Scope (free text)
    "LOTTABLE03": re.compile(r"^(?:1105|2609|0000)\.[A-Z0-9\-]+$", re.I),  # ProjectID
    "LOTTABLE06": re.compile(r"^(?:[A-Z0-9]{3,}\.\d{6}\.\d{5}|EID\d{2,})$", re.I),  # WBS
    "LOTTABLE07": re.compile(r"[A-Z0-9\-]{4,}", re.I),         # serial-ish
    "LOTTABLE09": None,                                       # Owner: no strict rule
    "LOTTABLE10": re.compile(r"^\d+\|.+$"),                   # numeric|text (FASID)
}

UNIQUE_LOTTABLES = ["LOTTABLE01"]

# ----------------------
# Helpers
# ----------------------
def find_similar_column(cols, target_names):
    for t in target_names:
        if t in cols:
            return t
    for t in target_names:
        cm = get_close_matches(t, cols, n=1, cutoff=0.8)
        if cm:
            return cm[0]
    return None

def detect_generic_key_col(df_cols):
    candidates = ["GenericKey", "GENERIC_KEY", "generic_key", "Generic Key", "GENERIC KEY", "GENKEY", "GEN_KEY", "GENERICKID"]
    return find_similar_column(list(df_cols), candidates)

def pattern_match_fraction(series, pattern):
    if pattern is None:
        return 1.0
    s = series.dropna().astype(str)
    if len(s) == 0:
        return 0.0
    matched = s.apply(lambda v: bool(pattern.search(v)))
    return matched.sum() / len(s)

def to_excel_bytes(dfs_dict):
    """Return bytes of an Excel file with given dict of {sheetname: df}"""
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        for name, df in dfs_dict.items():
            safe_name = str(name)[:31]
            if isinstance(df, pd.DataFrame):
                df.to_excel(writer, sheet_name=safe_name, index=False)
            else:
                pd.DataFrame([str(df)]).to_excel(writer, sheet_name=safe_name, index=False)
    buffer.seek(0)
    return buffer

# ----------------------
# Validation logic
# ----------------------
def validate_workbook(file_like, sheet_header="Data", sheet_detail="Detail"):
    """
    Reads an Excel workbook (path or file-like) and validates according to rules.
    Uses HEADER_ROW (0-based) as header line.
    Returns dict with summary_df, errors_summary, error_rows, orig.
    """
    result = {"summary": [], "errors": [], "error_rows": [], "orig": {}}

    # read workbook as dict of DataFrames using HEADER_ROW as header row
    try:
        xls_dict = pd.read_excel(file_like, sheet_name=None, header=HEADER_ROW, dtype=str)
    except Exception as e:
        result["errors"].append({
            "code": "FILE_READ_ERROR",
            "severity": "CRITICAL",
            "message": f"Gagal membaca file Excel: {e}",
            "details": {}
        })
        result["summary"].append(("file_read_ok", False))
        return result

    sheets = list(xls_dict.keys())

    # auto-detect sheet names if defaults not found
    if sheet_header not in sheets or sheet_detail not in sheets:
        header_sheet = find_similar_column(sheets, [sheet_header, "Header", "Data"])
        detail_sheet = find_similar_column(sheets, [sheet_detail, "Detail", "Lines", "Items"])
        if header_sheet:
            sheet_header = header_sheet
        if detail_sheet:
            sheet_detail = detail_sheet

    if sheet_header not in sheets or sheet_detail not in sheets:
        result["errors"].append({
            "code": "SHEET_NOT_FOUND",
            "severity": "CRITICAL",
            "message": "Nama sheet header/detail tidak ditemukan di workbook.",
            "details": {"available_sheets": sheets, "requested_header": sheet_header, "requested_detail": sheet_detail}
        })
        result["summary"].append(("sheets_found", False))
        return result

    header_df = xls_dict[sheet_header].copy()
    detail_df = xls_dict[sheet_detail].copy()
    result["orig"][f"orig_{sheet_header}"] = header_df
    result["orig"][f"orig_{sheet_detail}"] = detail_df

    # detect generic key columns
    header_gk = detect_generic_key_col(header_df.columns)
    detail_gk = detect_generic_key_col(detail_df.columns)
    if not header_gk or not detail_gk:
        result["errors"].append({
            "code": "GENKEY_MISSING",
            "severity": "CRITICAL",
            "message": "Tidak dapat mendeteksi kolom Generic Key di header/detail.",
            "details": {"header_cols": list(header_df.columns), "detail_cols": list(detail_df.columns)}
        })
        result["summary"].append(("generic_key_detected", False))
        return result

    result["summary"].append(("generic_key_detected", True))

    # normalize strings
    header_df[header_gk] = header_df[header_gk].astype(str).str.strip()
    detail_df[detail_gk] = detail_df[detail_gk].astype(str).str.strip()
    header_keys = set(header_df[header_gk].dropna().unique())
    detail_keys = set(detail_df[detail_gk].dropna().unique())

    # RULE 1: GenericKey in Detail must exist in Header (CRITICAL)
    missing_in_header = sorted(list(detail_keys - header_keys))
    for mk in missing_in_header:
        sample_rows = detail_df[detail_df[detail_gk] == mk].index[:5].tolist()
        for r in sample_rows:
            excel_row = int(r) + HEADER_ROW + 2
            result["error_rows"].append({
                "row_index": excel_row,
                "sheet": sheet_detail,
                "generic_key": mk,
                "column": detail_gk,
                "value": str(detail_df.at[r, detail_gk]),
                "rule": "GENKEY_MISSING_IN_HEADER",
                "severity": "CRITICAL",
                "message": "GenericKey di Detail tidak ditemukan di Header",
                "suggested_fix": "Tambahkan GenericKey di sheet Data atau gunakan GenericKey yang benar"
            })
    result["summary"].append(("genkey_missing_count", len(missing_in_header)))

    # RULE 2: LOTTABLE01 checks
    if "LOTTABLE01" in header_df.columns:
        hdr_grp = header_df.groupby(header_gk)["LOTTABLE01"].agg(
            lambda s: sorted(set([str(v).strip() for v in s.dropna()]))
        )
        for gk, lvals in hdr_grp.items():
            if len(lvals) > 1:
                result["errors"].append({
                    "code": "HEADER_LOTTABLE01_SPLIT",
                    "severity": "CRITICAL",
                    "message": f"GenericKey '{gk}' muncul di header dengan beberapa LOTTABLE01 berbeda.",
                    "details": {"generic_key": gk, "header_lottable01": lvals}
                })

    # header LOTTABLE01 must match at least one detail LOTTABLE01 for same GenericKey
    if "LOTTABLE01" in header_df.columns and "LOTTABLE01" in detail_df.columns:
        det_map = detail_df.groupby(detail_gk)["LOTTABLE01"].agg(
            lambda s: set([str(v).strip() for v in s.dropna()])
        ).to_dict()
        for idx, hrow in header_df.iterrows():
            gk = str(hrow.get(header_gk, "")).strip()
            h_l01 = str(hrow.get("LOTTABLE01", "")).strip()
            if gk and h_l01:
                det_vals = det_map.get(gk, set())
                if len(det_vals) == 0:
                    excel_row = int(idx) + HEADER_ROW + 2
                    result["error_rows"].append({
                        "row_index": excel_row,
                        "sheet": sheet_header,
                        "generic_key": gk,
                        "column": "LOTTABLE01",
                        "value": h_l01,
                        "rule": "HEADER_LOTTABLE01_NOT_IN_DETAIL",
                        "severity": "CRITICAL",
                        "message": "LOTTABLE01 di header tidak cocok dengan LOTTABLE01 mana pun di Detail untuk GenericKey ini.",
                        "suggested_fix": "Pastikan header LOTTABLE01 sama dengan salah satu nilai LOTTABLE01 di sheet Detail untuk GenericKey yang sama"
                    })
                else:
                    if h_l01 not in det_vals:
                        excel_row = int(idx) + HEADER_ROW + 2
                        result["error_rows"].append({
                            "row_index": excel_row,
                            "sheet": sheet_header,
                            "generic_key": gk,
                            "column": "LOTTABLE01",
                            "value": h_l01,
                            "rule": "HEADER_LOTTABLE01_MISMATCH",
                            "severity": "CRITICAL",
                            "message": "LOTTABLE01 di header tidak ditemukan di baris Detail untuk GenericKey yang sama.",
                            "suggested_fix": "Perbaiki LOTTABLE01 di header supaya cocok dengan salah satu LOTTABLE01 di Detail"
                        })

    # RULE 3..5: Pattern checks for ProjectID (LOTTABLE03), WBS (LOTTABLE06), FASID (LOTTABLE10)
    lottable_cols = [
        c for c in detail_df.columns
        if c and str(c).upper().startswith("LOTTABLE") and str(c).upper() != "LOTTABLE07"
    ]
    for col in lottable_cols:
        pattern = PATTERNS.get(str(col).upper())
        if pattern is None:
            continue
        series = detail_df.get(col, pd.Series([], dtype=str)).astype(str)
        for i, val in series.items():
            v = val.strip()
            if not v:
                continue
            if not pattern.search(v):
                sev = "CRITICAL" if str(col).upper() in ("LOTTABLE03", "LOTTABLE06", "LOTTABLE10") else "WARNING"
                excel_row = int(i) + HEADER_ROW + 2
                result["error_rows"].append({
                    "row_index": excel_row,
                    "sheet": sheet_detail,
                    "generic_key": str(detail_df.at[i, detail_gk]) if detail_gk in detail_df.columns else "",
                    "column": col,
                    "value": v,
                    "rule": f"{col}_PATTERN_MISMATCH",
                    "severity": sev,
                    "message": f"{col} tidak cocok pola yang diharapkan",
                    "suggested_fix": "Periksa format sesuai aturan perusahaan"
                })

    # RULE 6: Owner leakage
    if "LOTTABLE09" in detail_df.columns:
        owner_series = detail_df["LOTTABLE09"].astype(str).str.strip()
        other_lottables = [c for c in lottable_cols if str(c).upper() != "LOTTABLE09"]
        for i, owner_val in owner_series.items():
            if not owner_val:
                continue
            for c in other_lottables:
                other_val = str(detail_df.at[i, c]).strip() if c in detail_df.columns else ""
                if other_val and other_val == owner_val:
                    excel_row = int(i) + HEADER_ROW + 2
                    result["error_rows"].append({
                        "row_index": excel_row,
                        "sheet": sheet_detail,
                        "generic_key": str(detail_df.at[i, detail_gk]) if detail_gk in detail_df.columns else "",
                        "column": c,
                        "value": other_val,
                        "rule": "OWNER_LEAKAGE",
                        "severity": "WARNING",
                        "message": f"Value owner ditemukan di kolom {c} (kemungkinan mapping tertukar).",
                        "suggested_fix": "Periksa mapping kolom; nilai Owner seharusnya di LOTTABLE09"
                    })

    # Build errors_summary from error_rows
    err_rows_df = pd.DataFrame(result["error_rows"])
    if not err_rows_df.empty:
        rule_counts = err_rows_df["rule"].value_counts().to_dict()
        for r, cnt in rule_counts.items():
            rule_sev = "CRITICAL" if any(err_rows_df[err_rows_df["rule"] == r]["severity"] == "CRITICAL") else "WARNING"
            result["errors"].append({
                "code": r,
                "severity": rule_sev,
                "message": f"{cnt} occurrence(s) of {r}",
                "details": {}
            })

    # summary metrics
    result["summary"].append(("header_rows", int(len(header_df))))
    result["summary"].append(("detail_rows", int(len(detail_df))))
    result["summary"].append(("error_rows_count", int(len(err_rows_df))))
    # gate result: any CRITICAL in error_rows -> BLOCKED
    has_critical = False
    if not err_rows_df.empty:
        has_critical = any(err_rows_df["severity"] == "CRITICAL")
    result["summary"].append(("gate_blocked", bool(has_critical)))

    # attach final DataFrames
    result["error_rows"] = err_rows_df if not err_rows_df.empty else pd.DataFrame(columns=[
        "row_index","sheet","generic_key","column","value","rule","severity","message","suggested_fix"
    ])
    result["errors_summary"] = pd.DataFrame(result["errors"])
    result["summary_df"] = pd.DataFrame(result["summary"], columns=["metric", "value"])

    return result

# ----------------------
# Streamlit UI
# ----------------------
st.title("WMS Mapping Validator (Streamlit)")
st.markdown("Upload file Excel hasil mapping (sheet `Data` = header, `Detail` = detail). Aplikasi akan menjalankan check sesuai rule yang disepakati dan menghasilkan report actionable (baris & kolom yang salah).")

uploaded_file = st.file_uploader("Pilih file Excel (.xls / .xlsx)", type=["xls","xlsx"])
col1, col2 = st.columns(2)
sheet_header = col1.text_input("Nama sheet header", value="Data")
sheet_detail = col2.text_input("Nama sheet detail", value="Detail")

if uploaded_file:
    # preview sheet names safely
    try:
        preview_xls = pd.ExcelFile(uploaded_file)
        available_sheets = preview_xls.sheet_names
    except Exception as e:
        st.error(f"Gagal membaca sheet names: {e}")
        available_sheets = []

    with st.expander("Preview sheet names"):
        st.write(available_sheets)

    if st.button("Validate"):
        with st.spinner("Running validations..."):
            res = validate_workbook(uploaded_file, sheet_header=sheet_header, sheet_detail=sheet_detail)

        # show summary
        st.subheader("Summary metrics")
        if "summary_df" in res and isinstance(res["summary_df"], pd.DataFrame):
            st.dataframe(res["summary_df"])
        else:
            st.write(pd.DataFrame(res.get("summary", []), columns=["metric", "value"]))

        # show errors summary
        st.subheader("Errors / Warnings")
        errs_summary_df = res.get("errors_summary", pd.DataFrame(res.get("errors", [])))
        if errs_summary_df is None or errs_summary_df.empty:
            st.success("No major errors detected.")
        else:
            st.table(errs_summary_df)

        # row-level errors
        st.subheader("Row-level errors (detail)")
        err_rows = res.get("error_rows", pd.DataFrame())
        if err_rows is None or err_rows.empty:
            st.info("No row-level errors found.")
        else:
            st.dataframe(err_rows)

        # show original sheets (toggle)
        if st.checkbox("Tampilkan data header & detail"):
            st.write("Header (Data) sample:")
            st.dataframe(res["orig"].get(f"orig_{sheet_header}", pd.DataFrame()).head(200))
            st.write("Detail (Detail) sample:")
            st.dataframe(res["orig"].get(f"orig_{sheet_detail}", pd.DataFrame()).head(200))

        # prepare downloadable report
        out_dfs = {}
        out_dfs["summary"] = res.get("summary_df", pd.DataFrame(res.get("summary", []), columns=["metric","value"]))
        out_dfs["errors_summary"] = errs_summary_df
        if not err_rows.empty:
            out_dfs["errors_rows"] = err_rows
        out_dfs.update(res.get("orig", {}))

        excel_bytes = to_excel_bytes(out_dfs)
        st.download_button("Download validation report (xlsx)",
                           data=excel_bytes,
                           file_name="validation_report.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")