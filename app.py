# app.py
import streamlit as st
import pandas as pd
import re
from collections import defaultdict
from difflib import get_close_matches
from io import BytesIO

st.set_page_config(page_title="WMS Mapping Validator", layout="wide")

# ----------------------
# Config / patterns
# ----------------------
MATCH_THRESHOLD = 0.5

PATTERNS = {
    "LOTTABLE01": re.compile(r"^[^|]+\|[^|]+$"),               # shipment|PO (if used)
    "LOTTABLE02": re.compile(r"^[A-Z0-9][A-Z0-9 \-]{2,}$", re.I),  # Project Scope
    "LOTTABLE03": re.compile(r"^\d{4}\.[A-Z0-9\-]+$", re.I),   # ProjectID like 1105.SOMETHING
    "LOTTABLE06": re.compile(r"^[A-Z0-9]{3,}\.\d{6}\.\d{5}$", re.I),  # WBS like EID27.241002.11003
    "LOTTABLE07": re.compile(r"[A-Z0-9\-]{4,}", re.I),         # serial-ish
    "LOTTABLE09": re.compile(r"^[A-Z0-9\-]+-EID$", re.I),     # Owner ID ends with -EID
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
            # ensure df is a DataFrame
            if isinstance(df, pd.DataFrame):
                df.to_excel(writer, sheet_name=name[:31], index=False)
            else:
                # fallback: wrap into DataFrame
                pd.DataFrame([str(df)]).to_excel(writer, sheet_name=name[:31], index=False)
    buffer.seek(0)
    return buffer

# ----------------------
# Validation logic
# ----------------------
def validate_workbook(file_like, sheet_header="Data", sheet_detail="Detail"):
    """
    file_like: path or file-like object (e.g. Streamlit UploadedFile)
    returns dict with keys: summary_df, errors_summary (DataFrame), error_rows (DataFrame), orig (dict of DataFrames)
    """
    result = {"summary": [], "errors": [], "error_rows": [], "orig": {}}

    # try read entire workbook as dict of dataframes
    try:
        xls_dict = pd.read_excel(file_like, sheet_name=None, dtype=str)
    except Exception as e:
        result["errors"].append({
            "type": "file_read_error",
            "message": f"Gagal membaca file Excel: {e}",
            "details": {}
        })
        result["summary"].append(("file_read_ok", False))
        return result

    sheets = list(xls_dict.keys())

    # fallback: try to auto-detect header/detail sheet names
    if sheet_header not in sheets or sheet_detail not in sheets:
        header_sheet = find_similar_column(sheets, [sheet_header, "Header", "Data"])
        detail_sheet = find_similar_column(sheets, [sheet_detail, "Detail", "Lines", "Items"])
        if header_sheet:
            sheet_header = header_sheet
        if detail_sheet:
            sheet_detail = detail_sheet

    # if still not found, return friendly error
    if sheet_header not in sheets or sheet_detail not in sheets:
        result["errors"].append({
            "type": "sheet_missing",
            "message": "Nama sheet header/detail tidak ditemukan di workbook.",
            "details": {"available_sheets": sheets, "requested_header": sheet_header, "requested_detail": sheet_detail}
        })
        result["summary"].append(("sheets_found", False))
        return result

    header_df = xls_dict[sheet_header].copy()
    detail_df = xls_dict[sheet_detail].copy()

    result["orig"][f"orig_{sheet_header}"] = header_df
    result["orig"][f"orig_{sheet_detail}"] = detail_df

    header_gk = detect_generic_key_col(header_df.columns)
    detail_gk = detect_generic_key_col(detail_df.columns)

    if not header_gk or not detail_gk:
        result["errors"].append({
            "type": "generic_key_missing",
            "message": "Tidak dapat mendeteksi kolom Generic Key di header/detail. Mohon verifikasi nama kolom.",
            "details": {"header_cols": list(header_df.columns), "detail_cols": list(detail_df.columns)}
        })
        result["summary"].append(("generic_key_detected", False))
        return result

    result["summary"].append(("generic_key_detected", True))
    # 1) GenericKey consistency
    header_keys = set(header_df[header_gk].dropna().astype(str).unique())
    detail_keys = set(detail_df[detail_gk].dropna().astype(str).unique())
    missing_in_header = sorted(list(detail_keys - header_keys))
    if missing_in_header:
        result["errors"].append({
            "type": "missing_header_for_detail_generic_key",
            "message": f"{len(missing_in_header)} GenericKey(s) di Detail tidak ditemukan di Header",
            "details": missing_in_header[:50]
        })
    result["summary"].append(("generic_key_mismatch_count", len(missing_in_header)))

    # 2) Header duplicate GenericKey (header split) and LOTTABLE01 differences
    dup_header = header_df[header_df[header_gk].duplicated(keep=False)].sort_values(header_gk) if header_gk in header_df.columns else pd.DataFrame()
    if not dup_header.empty:
        dup_groups = dup_header.groupby(header_gk)
        split_warnings = []
        for k, g in dup_groups:
            l01 = set(g.get("LOTTABLE01", pd.Series([], dtype=str)).dropna().astype(str).unique())
            if len(l01) > 1:
                split_warnings.append((k, list(l01)))
        if split_warnings:
            result["errors"].append({
                "type": "header_split_by_lottable01",
                "message": "Beberapa GenericKey di header muncul beberapa kali dengan LOTTABLE01 berbeda (kemungkinan header terpecah menjadi beberapa shipment).",
                "details": split_warnings[:50]
            })
        result["summary"].append(("header_duplicate_generickey_count", int(len(dup_header))))
    else:
        result["summary"].append(("header_duplicate_generickey_count", 0))

    # 3) Pattern checks across LOTTABLEs in detail
    lottable_cols = [c for c in detail_df.columns if c and str(c).upper().startswith("LOTTABLE")]
    pattern_report = []
    for col in lottable_cols:
        expected_pat = PATTERNS.get(str(col).upper())
        frac = pattern_match_fraction(detail_df.get(col, pd.Series([], dtype=str)).astype(str), expected_pat) if expected_pat is not None else 1.0
        pattern_report.append((col, frac, expected_pat is not None))
        if expected_pat is not None and frac < MATCH_THRESHOLD:
            result["errors"].append({
                "type": "lottable_pattern_mismatch",
                "message": f"{col} hanya cocok dengan pola yang diharapkan untuk {frac:.0%} baris (< {MATCH_THRESHOLD:.0%}). Mungkin mapping tertukar atau format salah.",
                "details": {"column": col, "match_fraction": float(frac)}
            })
    # include pattern_report in summary
    for col, frac, has in pattern_report:
        result["summary"].append((f"pattern_match_frac_{col}", float(frac)))

    # 4) Uniqueness checks
    for col in UNIQUE_LOTTABLES:
        if col in detail_df.columns:
            dupvals = detail_df[col].dropna().astype(str)
            dup_counts = dupvals.value_counts()
            duplicates = dup_counts[dup_counts > 1]
            if not duplicates.empty:
                result["errors"].append({
                    "type": "lottable_uniqueness_violation",
                    "message": f"{col} seharusnya unik tapi ditemukan {len(duplicates)} value duplicate.",
                    "details": duplicates.head(20).to_dict()
                })

    # 5) Suspicious swap heuristic
    suspicious_swaps = []
    for expected_col, pattern in PATTERNS.items():
        if pattern is None:
            continue
        col_fracs = {}
        for col in lottable_cols:
            frac = pattern_match_fraction(detail_df.get(col, pd.Series([], dtype=str)).astype(str), pattern)
            col_fracs[col] = frac
        curr_frac = col_fracs.get(expected_col, 0)
        best_col = max(col_fracs, key=lambda c: col_fracs[c]) if col_fracs else None
        if best_col and best_col != expected_col and (col_fracs[best_col] - curr_frac) > 0.4:
            suspicious_swaps.append({
                "expected_lottable": expected_col,
                "best_matching_col": best_col,
                "expected_match_frac": float(curr_frac),
                "best_match_frac": float(col_fracs[best_col])
            })
    if suspicious_swaps:
        result["errors"].append({
            "type": "suspicious_mapping_swaps",
            "message": "Ditemukan LOTTABLE yang kemungkinan tertukar berdasarkan pola nilai.",
            "details": suspicious_swaps
        })

    # 6) Row-level checks (example)
    error_rows = []
    for i, row in detail_df.iterrows():
        r_errors = []
        gk = str(row.get(detail_gk, "")).strip()
        if not gk:
            r_errors.append("GenericKey kosong")
        else:
            if gk not in header_keys:
                r_errors.append("GenericKey tidak ada di Header")
        # LOTTABLE06 WBS strict check if column exists
        if "LOTTABLE06" in detail_df.columns:
            v = str(row.get("LOTTABLE06", "")).strip()
            pat = PATTERNS.get("LOTTABLE06")
            if v and not pat.search(v):
                r_errors.append("LOTTABLE06 (WBS) tidak cocok pola yang diharapkan")
        # LOTTABLE03 ProjectID check
        if "LOTTABLE03" in detail_df.columns:
            v = str(row.get("LOTTABLE03", "")).strip()
            pat = PATTERNS.get("LOTTABLE03")
            if v and not pat.search(v):
                r_errors.append("LOTTABLE03 (ProjectID) tidak cocok pola yang diharapkan")
        # LOTTABLE10 FASID check
        if "LOTTABLE10" in detail_df.columns:
            v = str(row.get("LOTTABLE10", "")).strip()
            pat = PATTERNS.get("LOTTABLE10")
            if v and not pat.search(v):
                r_errors.append("LOTTABLE10 (FASID) tidak cocok pola 'numeric|text'")
        if r_errors:
            error_rows.append({"row_index": i + 2, "generic_key": gk, "errors": "; ".join(r_errors)})

    result["error_rows"] = pd.DataFrame(error_rows)
    result["errors_summary"] = pd.DataFrame(result["errors"])
    result["summary_df"] = pd.DataFrame(result["summary"], columns=["metric", "value"])

    return result

# ----------------------
# Streamlit UI
# ----------------------
st.title("WMS Mapping Validator (Streamlit)")
st.markdown("Upload file Excel hasil mapping (sheet `Data` = header, `Detail` = detail). Aplikasi akan menjalankan sejumlah check pola & konsistensi GenericKey.")

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
        if res.get("errors_summary") is None or res["errors_summary"].empty:
            st.success("No major errors detected.")
        else:
            st.table(res["errors_summary"])

        # row-level errors
        st.subheader("Row-level errors (detail)")
        if res.get("error_rows") is None or res["error_rows"].empty:
            st.info("No row-level errors found.")
        else:
            st.dataframe(res["error_rows"])

        # show original sheets (toggle)
        if st.checkbox("Tampilkan data header & detail"):
            st.write("Header (Data) sample:")
            st.dataframe(res["orig"].get(f"orig_{sheet_header}", pd.DataFrame()).head(200))
            st.write("Detail (Detail) sample:")
            st.dataframe(res["orig"].get(f"orig_{sheet_detail}", pd.DataFrame()).head(200))

        # prepare downloadable report
        out_dfs = {}
        # add summary
        out_dfs["summary"] = res.get("summary_df", pd.DataFrame(res.get("summary", []), columns=["metric","value"]))
        out_dfs["errors_summary"] = res.get("errors_summary", pd.DataFrame(res.get("errors", [])))
        if not res.get("error_rows", pd.DataFrame()).empty:
            out_dfs["errors_rows"] = res["error_rows"]
        # include originals
        out_dfs.update(res.get("orig", {}))

        excel_bytes = to_excel_bytes(out_dfs)
        st.download_button("Download validation report (xlsx)", data=excel_bytes, file_name="validation_report.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")