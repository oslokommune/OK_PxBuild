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


def pretty_label_from_key(key: str) -> str:
    return key.replace("_", " ").strip()


def safe_tableid_from_filename(path: Path) -> str:
    stem = path.stem
    stem = re.sub(r"[^A-Za-z0-9_]+", "_", stem)
    stem = stem.strip("_")
    if not stem:
        stem = "TABLE"
    return stem.upper()


def measure_code(key: str, used: set[str]) -> str:
    """Create a short stable code from a measure name."""
    words = [w for w in key.split("_") if w]
    if not words:
        base = "M"
    elif len(words) == 1:
        base = words[0][:4].upper()
    else:
        base = "".join(w[0].upper() for w in words)[:6]

    if base not in used:
        used.add(base)
        return base

    i = 2
    while f"{base}{i}" in used:
        i += 1
    code = f"{base}{i}"
    used.add(code)
    return code


def is_integer_like(series: pd.Series) -> bool:
    x = pd.to_numeric(series, errors="coerce").dropna()
    if x.empty:
        return False
    # allow a few float artifacts
    return ((x % 1) == 0).mean() >= 0.98


def looks_like_code_dimension(colname: str, series: pd.Series) -> bool:
    """
    Heuristic: treat numeric columns as categorical codes if they look like IDs/codes.
    This prevents geo/sex/age codes from being misclassified as measures.
    """
    name = colname.lower()
    if any(tok in name for tok in ["kode", "code", "id"]):
        return True

    n = len(series)
    if n <= 0:
        return False

    nun = series.nunique(dropna=True)
    if nun == 0:
        return False

    if is_integer_like(series):
        # "many rows per code" pattern: nunique small compared to rows
        # keep generous upper bound for large geo-lists
        if nun <= max(200, int(0.2 * n)):
            return True

    return False


def normalize_and_pair_rename(df: pd.DataFrame) -> pd.DataFrame:
    """
    Normalize headers and convert duplicate pairs (x, x.1) into (x_kode, x_navn).
    Convention:
      - x      : code column
      - x.1    : label/name column
    """
    df = df.copy()
    df.columns = [to_ascii_key(c) for c in df.columns]

    cols = list(df.columns)
    ren = {}
    for c in cols:
        if c.endswith(".1"):
            base = c[:-2]
            if base in df.columns:
                ren[base] = f"{base}_kode"
                ren[c] = f"{base}_navn"
    if ren:
        df.rename(columns=ren, inplace=True)
    return df


# -----------------------------
# Core detection logic
# -----------------------------
@dataclass
class DetectedSchema:
    tableid: str
    time_col: str
    coded_dims: List[str]  # base dim name, e.g. "geografi"
    dims: List[str]  # parquet columns used as dimensions (time + coded dim code cols + other dims)
    measures: List[str]  # parquet columns used as measures
    code_name_map: Dict[str, Tuple[str, Optional[str]]]  # base -> (kode_col, navn_col or None)


def detect_schema(df: pd.DataFrame, tableid: str) -> DetectedSchema:
    # Expect df already normalized via normalize_and_pair_rename()
    if "aar" not in df.columns:
        raise ValueError(
            f"Could not find a time column. Expected one of: År/år/aargang/year -> aar. Columns: {df.columns.tolist()}"
        )
    time_col = "aar"

    # Identify coded dims: any *_kode column counts (label lookup via pxcodes, name optional)
    coded_dims = sorted({c[:-5] for c in df.columns if c.endswith("_kode")})
    code_name_map: Dict[str, Tuple[str, Optional[str]]] = {}
    for base in coded_dims:
        kode_col = f"{base}_kode"
        navn_col = f"{base}_navn" if f"{base}_navn" in df.columns else None
        code_name_map[base] = (kode_col, navn_col)

    # Determine numeric-ish columns
    numeric_cols: List[str] = []
    for c in df.columns:
        if c.endswith("_navn"):
            continue  # label helper, not part of parquet
        if c == time_col:
            continue
        s = pd.to_numeric(df[c], errors="coerce")
        if s.notna().mean() >= 0.95:
            numeric_cols.append(c)

    # Low-cardinality numeric columns are likely categorical dims (except time)
    low_card_dims: List[str] = []
    for c in numeric_cols:
        nun = df[c].nunique(dropna=True)
        if nun <= 50:
            low_card_dims.append(c)

    # Also treat numeric "code-like" columns as dims even if not low-card
    code_like_numeric_dims: List[str] = []
    for c in numeric_cols:
        if looks_like_code_dimension(c, df[c]):
            code_like_numeric_dims.append(c)

    # Build dimension columns (parquet):
    # - time
    # - all *_kode (coded dimensions)
    # - non-numeric columns (except *_navn)
    # - low-card numeric dims
    # - code-like numeric dims
    dims: List[str] = [time_col]
    for c in df.columns:
        if c == time_col:
            continue
        if c.endswith("_navn"):
            continue
        if c.endswith("_kode"):
            dims.append(c)
            continue
        if c in low_card_dims or c in code_like_numeric_dims:
            dims.append(c)
            continue
        if c not in numeric_cols:
            dims.append(c)

    # Measures: numeric columns excluding anything selected as dims
    dim_set = set(dims)
    measures = [c for c in numeric_cols if c not in dim_set]

    if not measures:
        raise ValueError(
            f"No measures detected. Columns: {df.columns.tolist()} "
            f"(numeric candidates: {numeric_cols}, dims: {dims})"
        )

    return DetectedSchema(
        tableid=tableid,
        time_col=time_col,
        coded_dims=coded_dims,
        dims=dims,
        measures=measures,
        code_name_map=code_name_map,
    )


# -----------------------------
# Writers: parquet + pxjson
# -----------------------------
def write_parquet_wide(df: pd.DataFrame, schema: DetectedSchema, out_parquet: Path) -> pd.DataFrame:
    # Keep dims (already excludes *_navn) + measures
    keep_cols = list(dict.fromkeys(schema.dims + schema.measures))
    missing = [c for c in keep_cols if c not in df.columns]
    if missing:
        raise ValueError(f"Missing expected columns after normalization: {missing}. Have: {df.columns.tolist()}")

    out_df = df[keep_cols].copy()

    # time dimension must be strings for PX VALUES
    out_df[schema.time_col] = pd.to_numeric(out_df[schema.time_col], errors="raise").astype("int64").astype(str)

    # ensure measures numeric
    for m in schema.measures:
        out_df[m] = pd.to_numeric(out_df[m], errors="coerce")

    out_parquet.parent.mkdir(parents=True, exist_ok=True)
    out_df.to_parquet(out_parquet, index=False)
    return out_df


def write_pxcodes(df: pd.DataFrame, schema: DetectedSchema, out_dir: Path) -> None:
    """
    Create pxcodes for coded dimensions.

    - If both base_kode and base_navn exist: label = base_navn
    - If only base_kode exists: label = code (fallback)
    """
    out_dir.mkdir(parents=True, exist_ok=True)

    for base in schema.coded_dims:
        kode_col, navn_col = schema.code_name_map[base]
        if kode_col not in df.columns:
            raise ValueError(f"Expected coded dim column {kode_col} not found in dataframe.")

        if navn_col and navn_col in df.columns:
            pairs = df[[kode_col, navn_col]].dropna().drop_duplicates().sort_values(kode_col, kind="stable")
            items = [(str(k).strip(), str(n).strip()) for k, n in pairs.itertuples(index=False)]
        else:
            codes = df[[kode_col]].dropna().drop_duplicates().sort_values(kode_col, kind="stable")
            items = [(str(k).strip(), str(k).strip()) for (k,) in codes.itertuples(index=False)]

        valueitems = [
            {
                "code": code,
                "unorderedChildren": None,
                "label": {"no": label_no, "en": label_no},  # en=no default
                "rank": None,
                "notes": None,
            }
            for code, label_no in items
        ]

        payload = {
            "id": base,
            "admin": {"isFinal": True, "tags": ["auto"], "todoCreation": None},
            "sortValueitemsOn": "code",
            "label": {"no": base, "en": base},
            "valueitems": valueitems,
            "eliminationPossible": True,
            "eliminationCode": None,
            "sortGroupingsOn": None,
            "groupings": None,
        }

        (out_dir / f"{base}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def write_pxmetadata(schema: DetectedSchema, out_path: Path) -> Dict:
    used_codes: set[str] = set()

    # --- measurements ---
    measurements = []
    for m in schema.measures:
        code = measure_code(m, used_codes)[:4]  # force 4 letters
        used_codes.add(code)
        measurements.append(
            {
                "measurementId": m,
                "measurementCode": code,  # PxBuild expects this
                "code": code,  # PxBuild data-mapper uses this
                "label": {"no": m, "en": m},
                "columnName": m,  # REQUIRED (matches parquet column)
                "showDecimals": 1,
                "aggregationAllowed": True,
                "unitOfMeasure": {"no": "", "en": ""},
            }
        )

    # --- coded dimensions ---
    # In the "wide parquet + pxcodes" workflow, parquet holds ONLY the code column (base_kode).
    coded_dimensions = []
    for base in schema.coded_dims:
        coded_dimensions.append(
            {
                "dimensionId": base,
                "labelConstructionOption": "text",
                "label": {"no": base, "en": base},
                "codelistId": base,
                "pxcodesId": base,
                "columnName": f"{base}_kode",  # IMPORTANT: map dim directly to code column
            }
        )

    # --- non-coded dims ---
    other_dims = []
    for d in schema.dims:
        if d == schema.time_col:
            continue
        if d.endswith("_kode"):
            continue  # coded dims are defined above
        other_dims.append(
            {
                "dimensionId": d,
                "columnName": d,
                "label": {"no": pretty_label_from_key(d), "en": pretty_label_from_key(d)},
            }
        )

    payload = {
        "dataset": {
            "tableId": schema.tableid,
            "baseTitle": {"no": schema.tableid, "en": schema.tableid},
            "label": {"no": schema.tableid, "en": schema.tableid},
            "searchKeywords": {"no": [], "en": []},
            "statisticsId": schema.tableid,
            # Must be WITHOUT ".parquet" if config uses ".../{id}.parquet"
            "dataFile": schema.tableid,
            "timeDimension": {
                "dimensionId": schema.time_col,
                "columnName": schema.time_col,
                "label": {"no": "aar", "en": "year"},
            },
            "codedDimensions": coded_dimensions,
            "dimensions": other_dims,
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
    df_raw = pd.read_excel(xlsx)
    df = normalize_and_pair_rename(df_raw)

    # Detect schema (now that headers are stable)
    schema = detect_schema(df, tableid)

    # Write parquet (wide)
    out_parquet = root / "pxjson" / "parquet_files" / f"{tableid}.parquet"
    write_parquet_wide(df, schema, out_parquet)

    # Write pxcodes
    if schema.coded_dims:
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
    if schema.coded_dims:
        print("Wrote pxcodes:", root / "pxjson" / "pxcodes")


if __name__ == "__main__":
    main()
