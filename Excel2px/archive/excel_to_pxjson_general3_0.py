from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd


# -----------------------------
# Helpers: normalization
# -----------------------------
NOR_MAP = str.maketrans({"å": "a", "ø": "o", "æ": "ae", "Å": "a", "Ø": "o", "Æ": "ae"})


def to_ascii_key(s: str) -> str:
    """Normalize header to ascii snake_case key."""
    if s is None:
        return ""
    s = str(s).strip()
    s = s.translate(NOR_MAP)
    s = s.replace(" ", "_")
    s = s.lower()
    # keep dot for pandas duplicate columns (".1") so we can detect pairs
    s = re.sub(r"[^a-z0-9_\.]+", "", s)

    # synonyms
    if s in {"ar", "aar", "aargang", "year"}:
        return "aar"
    if s in {"kjonn", "kjon", "kjonnn"}:
        return "kjoenn"
    if s == "kjonn.1":
        return "kjoenn.1"
    return s


def safe_tableid_from_filename(path: Path) -> str:
    stem = path.stem
    stem = re.sub(r"[^A-Za-z0-9_]+", "_", stem)
    stem = stem.strip("_")
    if not stem:
        stem = "TABLE"
    return stem.upper()


def measure_code(key: str) -> str:
    """Create a readable base code from a measure name (not necessarily 4-char unique)."""
    words = [w for w in key.split("_") if w]
    if not words:
        return "M"
    if len(words) == 1:
        return words[0][:6].upper()
    return "".join(w[0].upper() for w in words)[:6]


def measure_code4(key: str, used: set[str]) -> str:
    """Return a UNIQUE 4-character measurement code (PX constraint)."""
    base_full = measure_code(key)
    base = re.sub(r"[^A-Z0-9]+", "", base_full.upper()) or "M"
    cand = (base + "XXXX")[:4]
    if cand not in used:
        used.add(cand)
        return cand

    alphabet = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    i = 1
    while True:
        hi = i // 36
        lo = i % 36
        if hi == 0:
            cand2 = cand[:3] + alphabet[lo]
        else:
            cand2 = cand[:2] + alphabet[hi] + alphabet[lo]
        if cand2 not in used:
            used.add(cand2)
            return cand2
        i += 1


def read_excel_smart(xlsx: Path) -> pd.DataFrame:
    """Read Excel and automatically detect the header row.

    Many SSB-style exports have a title row followed by a header row.
    We scan the first ~50 rows (header=None) for a row containing a time header,
    then re-read using that row as header.
    """
    preview = pd.read_excel(xlsx, header=None, nrows=50)

    def _norm_cell(x) -> str:
        if x is None or (isinstance(x, float) and pd.isna(x)):
            return ""
        return to_ascii_key(str(x))

    header_row = None
    for i in range(len(preview)):
        vals = [_norm_cell(v) for v in preview.iloc[i].tolist()]
        if any(v in {"aar", "ar", "year"} for v in vals):
            header_row = i
            break

    if header_row is None:
        return pd.read_excel(xlsx)

    df = pd.read_excel(xlsx, header=header_row)

    # Clean up unnamed columns
    new_cols = []
    for j, c in enumerate(df.columns):
        c_str = "" if c is None else str(c)
        if c_str.lower().startswith("unnamed"):
            new_cols.append(f"value_{j}")
        else:
            new_cols.append(c_str)
    df.columns = new_cols
    return df


def normalize_headers_and_pair_rename(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize headers + rename adjacent duplicate pairs x/x.1 into x_kode/x_navn."""
    df = df.copy()
    df.columns = [to_ascii_key(c) for c in df.columns]

    cols = list(df.columns)
    ren = {}

    for idx, c in enumerate(cols):
        if c.endswith(".1"):
            base = c[:-2]
            # require adjacency: ... base, base.1 ...
            if idx > 0 and cols[idx - 1] == base:
                ren[base] = f"{base}_kode"
                ren[c] = f"{base}_navn"

    if ren:
        df.rename(columns=ren, inplace=True)

    return df


def clean_numeric_series(s: pd.Series) -> pd.Series:
    """Try to coerce Excel-ish numeric strings into floats."""
    if s.dtype.kind in {"i", "u", "f"}:
        return pd.to_numeric(s, errors="coerce")
    x = s.astype(str).str.strip()
    x = x.replace({"": None, "None": None, "nan": None, "NaN": None})
    # common formats: "1 234", "12,3"
    x = x.str.replace(" ", "", regex=False)
    x = x.str.replace("\u00a0", "", regex=False)  # NBSP
    x = x.str.replace(",", ".", regex=False)
    return pd.to_numeric(x, errors="coerce")


# -----------------------------
# Core detection logic (simplified)
# -----------------------------
@dataclass
class DetectedSchema:
    tableid: str
    time_col: str
    dims: List[str]  # parquet columns used as dimensions (time + dim columns)
    measures: List[str]  # measure columns in parquet
    dim_columns: List[str]  # parquet dim columns excluding time
    coded_dims: List[str]  # bases for *_kode columns (mostly for debug)
    code_name_map: Dict[str, Tuple[str, Optional[str]]]  # base -> (kode_col, navn_col or None)


def detect_schema_simple(df: pd.DataFrame, tableid: str) -> DetectedSchema:
    """Detect schema using the simplified assumptions."""
    if df.shape[1] < 2:
        raise ValueError("Expected at least 2 columns (time + something else).")

    # Time is the first column; rename to 'aar'
    first = df.columns[0]
    if first != "aar":
        df.rename(columns={first: "aar"}, inplace=True)
    time_col = "aar"

    coded_dims = sorted({c[:-5] for c in df.columns if c.endswith("_kode")})
    code_name_map: Dict[str, Tuple[str, Optional[str]]] = {}
    for base in coded_dims:
        kode = f"{base}_kode"
        navn = f"{base}_navn" if f"{base}_navn" in df.columns else None
        code_name_map[base] = (kode, navn)

    dims: List[str] = [time_col]
    measures: List[str] = []

    # classify remaining columns
    for c in df.columns[1:]:
        if c.endswith("_navn"):
            continue  # helper labels only
        if c.endswith("_kode"):
            dims.append(c)
            continue

        num = clean_numeric_series(df[c])
        ratio = num.notna().mean()

        if ratio >= 0.95:
            nun = df[c].nunique(dropna=True)
            # numeric dimension rescue (codes like 1/2, age group codes, etc.)
            if nun <= 2000 and nun <= int(0.2 * len(df)):
                dims.append(c)
            else:
                measures.append(c)
        else:
            dims.append(c)

    if not measures:
        raise ValueError(
            f"No measures detected with the simplified rules. Columns: {df.columns.tolist()}, dims: {dims}"
        )

    dim_columns = [d for d in dims if d != time_col]

    return DetectedSchema(
        tableid=tableid,
        time_col=time_col,
        dims=dims,
        measures=measures,
        dim_columns=dim_columns,
        coded_dims=coded_dims,
        code_name_map=code_name_map,
    )


# -----------------------------
# Writers: parquet + pxjson
# -----------------------------
def write_parquet_wide(df: pd.DataFrame, schema: DetectedSchema, out_parquet: Path) -> pd.DataFrame:
    keep_cols = list(dict.fromkeys(schema.dims + schema.measures))
    missing = [c for c in keep_cols if c not in df.columns]
    if missing:
        raise ValueError(f"Missing expected columns after normalization: {missing}. Have: {df.columns.tolist()}")

    out_df = df[keep_cols].copy()

    def _norm_dim_value(x):
        if pd.isna(x):
            return ""
        if isinstance(x, float) and x.is_integer():
            return str(int(x))
        return str(x).strip()

    # normalize all dims (except time) to string codes
    for dcol in schema.dim_columns:
        out_df[dcol] = out_df[dcol].map(_norm_dim_value)

    # convert time to string years
    out_df[schema.time_col] = pd.to_numeric(out_df[schema.time_col], errors="raise").astype("int64").astype(str)

    # ensure measures numeric
    for m in schema.measures:
        out_df[m] = clean_numeric_series(out_df[m])

    # collapse duplicates (same dim combination)
    if out_df.duplicated(subset=schema.dims, keep=False).any():

        def _agg_series(s: pd.Series):
            ss = s.dropna()
            if ss.empty:
                return float("nan")
            if ss.nunique(dropna=True) <= 1:
                return ss.iloc[0]
            return pd.to_numeric(ss, errors="coerce").sum()

        agg_map = {m: _agg_series for m in schema.measures}
        out_df = out_df.groupby(schema.dims, dropna=False, sort=False, as_index=False).agg(agg_map)

    out_parquet.parent.mkdir(parents=True, exist_ok=True)
    out_df.to_parquet(out_parquet, index=False)
    return out_df


def write_pxcodes(df: pd.DataFrame, schema: DetectedSchema, out_dir: Path) -> None:
    """Create pxcodes for all parquet dimensions (excluding time)."""
    out_dir.mkdir(parents=True, exist_ok=True)

    def norm_code(x) -> str:
        if pd.isna(x):
            return ""
        if isinstance(x, float) and x.is_integer():
            return str(int(x))
        return str(x).strip()

    for col in schema.dim_columns:
        if col.endswith("_kode"):
            dim_id = col[:-5]
            code_col = col
            label_col = f"{dim_id}_navn" if f"{dim_id}_navn" in df.columns else None
        else:
            dim_id = col
            code_col = col
            label_col = None

        if label_col and label_col in df.columns:
            pairs = df[[code_col, label_col]].dropna().drop_duplicates().sort_values(code_col, kind="stable")
            items = [(norm_code(k), str(n).strip()) for k, n in pairs.itertuples(index=False)]
        else:
            codes = df[[code_col]].dropna().drop_duplicates().sort_values(code_col, kind="stable")
            items = [(norm_code(k), norm_code(k)) for (k,) in codes.itertuples(index=False)]

        items = [(c, lab) for c, lab in items if c != ""]
        valueitems = [
            {
                "code": code,
                "unorderedChildren": None,
                "label": {"no": label_no, "en": label_no},
                "rank": None,
                "notes": None,
            }
            for code, label_no in items
        ]

        payload = {
            "id": dim_id,
            "admin": {"isFinal": True, "tags": ["auto"], "todoCreation": None},
            "sortValueitemsOn": "code",
            "label": {"no": dim_id, "en": dim_id},
            "valueitems": valueitems,
            "eliminationPossible": True,
            "eliminationCode": None,
            "sortGroupingsOn": None,
            "groupings": None,
        }

        (out_dir / f"{dim_id}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def write_pxmetadata(schema: DetectedSchema, out_path: Path) -> Dict:
    used_codes: set[str] = set()

    measurements = []
    for m in schema.measures:
        code = measure_code4(m, used_codes)
        measurements.append(
            {
                "measurementId": m,
                "measurementCode": code,
                "code": code,
                "label": {"no": m, "en": m},
                "columnName": m,
                "showDecimals": 1,
                "aggregationAllowed": True,
                "unitOfMeasure": {"no": "", "en": ""},
            }
        )

    coded_dimensions = []
    for col in schema.dim_columns:
        dim_id = col[:-5] if col.endswith("_kode") else col
        coded_dimensions.append(
            {
                "dimensionId": dim_id,
                "labelConstructionOption": "text",
                "label": {"no": dim_id, "en": dim_id},
                "codelistId": dim_id,
                "pxcodesId": dim_id,
                "columnName": col,
            }
        )

    payload = {
        "dataset": {
            "tableId": schema.tableid,
            "baseTitle": {"no": schema.tableid, "en": schema.tableid},
            "label": {"no": schema.tableid, "en": schema.tableid},
            "searchKeywords": {"no": [], "en": []},
            "statisticsId": schema.tableid,
            "dataFile": schema.tableid,
            "timeDimension": {
                "dimensionId": schema.time_col,
                "columnName": schema.time_col,
                "label": {"no": "aar", "en": "year"},
            },
            "codedDimensions": coded_dimensions,
            "dimensions": [],
            "measurements": measurements,
        }
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def write_pxstatistics(tableid: str, out_path: Path) -> None:
    payload = {
        "id": tableid,
        "subjectCode": "GEN",
        "subjectText": {"no": "Generated", "en": "Generated"},
        "contacts": [],
        "statistics": {"statisticalPresenter": {"no": "Generated", "en": "Generated"}},
        "notes": None,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


# -----------------------------
# Main
# -----------------------------
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("xlsx", type=str, help="Path to Excel file (.xlsx)")
    ap.add_argument("--tableid", type=str, default=None, help="Override TABLEID (default: from filename)")
    ap.add_argument(
        "--root", type=str, default="my_other_project", help="Project root folder (default: my_other_project)"
    )
    args = ap.parse_args()

    xlsx = Path(args.xlsx)
    if not xlsx.exists():
        raise FileNotFoundError(xlsx)

    tableid = args.tableid or safe_tableid_from_filename(xlsx)
    root = Path(args.root)

    # Read + normalize
    df_raw = read_excel_smart(xlsx)
    df = normalize_headers_and_pair_rename(df_raw)

    # Detect schema (simplified rules)
    schema = detect_schema_simple(df, tableid)

    # Write parquet
    out_parquet = root / "pxjson" / "parquet_files" / f"{tableid}.parquet"
    write_parquet_wide(df, schema, out_parquet)

    # Write pxcodes
    if schema.dim_columns:
        write_pxcodes(df, schema, root / "pxjson" / "pxcodes")

    # Write pxmetadata + pxstatistics
    write_pxmetadata(schema, root / "pxjson" / "pxmetadata" / f"{tableid}.json")
    write_pxstatistics(tableid, root / "pxjson" / "pxstatistics" / f"pxstatistics_{tableid}.json")

    print("TABLEID:", tableid)
    print("Wrote parquet:", out_parquet)
    print("Dims:", schema.dims)
    print("Measures:", schema.measures)
    print("Coded dims:", schema.coded_dims)
    print("Wrote pxmetadata:", root / "pxjson" / "pxmetadata" / f"{tableid}.json")
    print("Wrote pxstatistics:", root / "pxjson" / "pxstatistics" / f"pxstatistics_{tableid}.json")
    if schema.dim_columns:
        print("Wrote pxcodes:", root / "pxjson" / "pxcodes")


if __name__ == "__main__":
    main()
