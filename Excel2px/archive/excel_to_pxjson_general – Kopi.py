from __future__ import annotations
import argparse
import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple
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
    if s == "kjonn" or s == "kjonn.1":
        return "kjoenn"
    if s == "kjonnn":
        return "kjoenn"
    if s == "kjonnn.1":
        return "kjoenn.1"
    return s


def pretty_label_from_key(key: str) -> str:
    # simple, readable label used in metadata if you don't have original
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


# -----------------------------
# Core detection logic
# -----------------------------
@dataclass
class DetectedSchema:
    tableid: str
    time_col: str
    coded_dims: List[str]  # base dim name, e.g. "geografi"
    dims: List[str]  # columns used as dimensions in parquet
    measures: List[str]  # measure columns in parquet
    code_name_map: Dict[str, Tuple[str, str]]  # base -> (kode_col, navn_col)


def detect_schema(df: pd.DataFrame, tableid: str) -> DetectedSchema:
    # Normalize headers first
    orig_cols = list(df.columns)
    norm_cols = [to_ascii_key(c) for c in orig_cols]
    df.columns = norm_cols

    # Detect code/name duplicates: x and x.1
    code_name_map: Dict[str, Tuple[str, str]] = {}
    cols_set = set(df.columns)

    for c in list(df.columns):
        if c.endswith(".1"):
            base = c[:-2]
            if base in cols_set:
                # treat base as code, base.1 as name
                code_col = base
                name_col = c
                code_name_map[base] = (code_col, name_col)

    # Rename those to *_kode, *_navn
    rename = {}
    for base, (code_col, name_col) in code_name_map.items():
        rename[code_col] = f"{base}_kode"
        rename[name_col] = f"{base}_navn"
    if rename:
        df.rename(columns=rename, inplace=True)

    # Determine numeric columns
    # Convert obvious numeric where possible
    for c in df.columns:
        # keep *_navn as text; keep most as-is
        if c.endswith("_navn"):
            continue

    numeric_cols = []
    for c in df.columns:
        if c.endswith("_navn"):
            continue
        if c.endswith("_kode"):
            continue  # codes treated as dimension even if numeric
        # attempt numeric check
        s = pd.to_numeric(df[c], errors="coerce")
        if s.notna().mean() >= 0.95:  # mostly numeric
            numeric_cols.append(c)

    time_col = "aar" if "aar" in df.columns else None
    if time_col is None:
        raise ValueError(
            f"Could not find a time column. Expected one of: År/år/aargang -> aar. Columns: {df.columns.tolist()}"
        )

    # Low-cardinality numeric columns (except time) are likely categorical dims
    low_card_dims = []
    for c in numeric_cols:
        if c == time_col:
            continue
        nun = df[c].nunique(dropna=True)
        if nun <= 50:
            low_card_dims.append(c)

    # Dimensions:
    # - all non-numeric columns
    # - time column
    # - *_kode columns
    # - low-card numeric dims
    dims = []
    for c in df.columns:
        if c == time_col:
            continue
        if c.endswith("_navn"):
            continue  # names used for pxcodes but not needed in parquet
        if c.endswith("_kode"):
            dims.append(c)
            continue
        if c in low_card_dims:
            dims.append(c)
            continue
        if c not in numeric_cols:
            dims.append(c)

    dims = [time_col] + dims  # ensure time first

    # Measures = numeric columns excluding time and excluding any *_kode
    measures = [c for c in numeric_cols if c != time_col and not c.endswith("_kode") and c not in low_card_dims]
    if not measures:
        raise ValueError(f"No measures detected. Columns: {df.columns.tolist()} (numeric candidates: {numeric_cols})")

    coded_dims = [base for base in code_name_map.keys()]  # base names before *_kode rename
    # but after rename, actual base dimension names are still base; kode col now base_kode
    coded_dims = sorted(set(coded_dims))

    # Update code_name_map to match renamed columns
    updated_map = {}
    for base in coded_dims:
        updated_map[base] = (f"{base}_kode", f"{base}_navn")

    return DetectedSchema(
        tableid=tableid,
        time_col=time_col,
        coded_dims=coded_dims,
        dims=dims,
        measures=measures,
        code_name_map=updated_map,
    )


# -----------------------------
# Writers: parquet + pxjson
# -----------------------------
def write_parquet_wide(df: pd.DataFrame, schema: DetectedSchema, out_parquet: Path) -> pd.DataFrame:
    keep_cols = schema.dims + schema.measures
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
    out_dir.mkdir(parents=True, exist_ok=True)

    for base in schema.coded_dims:
        kode_col, navn_col = schema.code_name_map[base]
        if kode_col not in df.columns or navn_col not in df.columns:
            raise ValueError(f"Expected coded dim columns {kode_col}/{navn_col} not found in dataframe.")

        pairs = df[[kode_col, navn_col]].dropna().drop_duplicates().sort_values(kode_col, kind="stable")

        valueitems = []
        for _, row in pairs.iterrows():
            code = str(row[kode_col]).strip()
            label_no = str(row[navn_col]).strip()
            valueitems.append(
                {
                    "code": code,
                    "unorderedChildren": None,
                    "label": {"no": label_no, "en": label_no},  # en=no default
                    "rank": None,
                    "notes": None,
                }
            )

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

        (out_dir / f"{base}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_pxmetadata(schema: DetectedSchema, out_path: Path) -> Dict:
    used_codes: set[str] = set()

    # --- measurements ---
    measurements = []
    for m in schema.measures:
        code = measure_code(m, used_codes)[:4]  # force 4 letters
        measurements.append(
            {
                "measurementId": m,
                "measurementCode": code,  # keep
                "code": code,  # <-- ADD THIS (this is the key fix)
                "label": {"no": m, "en": m},
                "columnName": m,
                "showDecimals": 1,
                "aggregationAllowed": True,
                "unitOfMeasure": {"no": "", "en": ""},
            }
        )

    coded_dimensions = []
    for base in schema.coded_dims:
        coded_dimensions.append(
            {
                "dimensionId": base,  # e.g. "geografi"
                "labelConstructionOption": "text",
                "label": {"no": base, "en": base},
                # PxBuild wants these IDs:
                "codelistId": base,
                "pxcodesId": base,  # keep if your model accepts it; otherwise remove
                # IMPORTANT: both columns must exist in parquet
                "columnName": base,  # text column (e.g. "geografi")
                "codeColumn": f"{base}_kode",  # code column (e.g. "geografi_kode")
            }
        )

    # --- non-coded dims (everything except time and *_kode) ---
    other_dims = []
    for d in schema.dims:
        if d == schema.time_col:
            continue
        if d.endswith("_kode"):
            continue
        other_dims.append(
            {
                "dimensionId": d,
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
            "dataFile": schema.tableid,
            "timeDimension": {
                "dimensionId": schema.time_col,  # e.g. "aar"
                "columnName": schema.time_col,  # IMPORTANT (prevents None)
                "codelistId": schema.time_col,  # keep simple
                "isTime": True,
                "labelConstructionOption": "text",  # one of: code/text/code_text/text_code
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

    # Read Excel
    df = pd.read_excel(xlsx)

    # after you read df and before schema detection
    cols = list(df.columns)

    # Example: "geografi" + "geografi.1" OR "bosted" + "bosted.1"
    for c in cols:
        if c.endswith(".1"):
            base = c[:-2]
            if base in df.columns:
                # ASSUMPTION (your stated rule):
                # base      = code column
                # base+".1" = name/text column

                df.rename(
                    columns={
                        base: f"{base}_kode",  # code -> *_kode
                        c: base,  # name/text -> base
                    },
                    inplace=True,
                )

    # Detect schema
    schema = detect_schema(df, tableid)

    # ensure coded dims have BOTH columns
    for base in schema.coded_dims:
        text_col = base
        code_col = f"{base}_kode"
        if text_col not in schema.dims:
            schema.dims.append(text_col)
        if code_col not in schema.dims:
            schema.dims.append(code_col)

    # Write parquet
    out_parquet = root / "pxjson" / "parquet_files" / f"{tableid}.parquet"
    out_df = write_parquet_wide(df, schema, out_parquet)

    # Write pxcodes for coded dims
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
