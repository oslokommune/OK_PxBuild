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


def clean_numeric_series(s: pd.Series) -> pd.Series:
    """Try to coerce Excel-like numeric strings into floats."""
    if s.dtype.kind in {"i", "u", "f"}:
        return pd.to_numeric(s, errors="coerce")
    x = s.astype(str).str.strip()
    x = x.replace({"": None, "None": None, "nan": None, "NaN": None})
    # common formats: "1 234", "12,3"
    x = x.str.replace(" ", "", regex=False)
    x = x.str.replace("\u00a0", "", regex=False)  # NBSP
    x = x.str.replace(",", ".", regex=False)
    return pd.to_numeric(x, errors="coerce")


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


# -----------------------------
# Core detection logic
# -----------------------------
@dataclass
class DetectedSchema:
    tableid: str
    time_col: str
    dims: List[str]  # csv columns used as dimensions (time + dim columns)
    measures: List[str]  # measure columns in csv
    dim_columns: List[str]  # csv dim columns excluding time
    coded_dims: List[str]  # bases for *_kode columns (mostly for debug)
    code_name_map: Dict[str, Tuple[str, Optional[str]]]  # base -> (kode_col, navn_col or None)
    elimination_map: Dict[str, Tuple[bool, Optional[str]]]  # dim_id -> (eliminationPossible, eliminationCode)


def load_schema_from_metadata(metadata_path: Path) -> DetectedSchema:
    """Load schema from JSON metadata file."""
    with open(metadata_path, "r", encoding="utf-8") as f:
        metadata = json.load(f)

    dataset = metadata["dataset"]
    tableid = dataset["tableId"]
    time_col = dataset["timeDimension"]["columnName"]

    # Get dimensions
    coded_dimensions = dataset.get("codedDimensions", [])
    dimensions = dataset.get("dimensions", [])
    measurements = dataset["measurements"]

    dims = [time_col]
    dim_columns = []
    coded_dims = []
    code_name_map = {}
    elimination_map = {}

    # Process coded dimensions
    for dim in coded_dimensions:
        dim_id = dim["dimensionId"]
        column_name = dim["columnName"]
        dims.append(column_name)
        dim_columns.append(column_name)
        coded_dims.append(dim_id)
        # Assume kode/navn pairs if column_name ends with _kode
        if column_name.endswith("_kode"):
            base = column_name[:-5]
            navn_col = f"{base}_navn"
            code_name_map[base] = (
                column_name,
                navn_col if navn_col in [d["columnName"] for d in coded_dimensions + dimensions] else None,
            )
        else:
            code_name_map[dim_id] = (column_name, None)

        # Parse elimination
        elimination_possible = dim.get("eliminationPossible", False)
        elimination_code = dim.get("eliminationCode", None)
        elimination_map[dim_id] = (elimination_possible, elimination_code)

    # Process regular dimensions
    for dim in dimensions:
        column_name = dim["columnName"]
        dims.append(column_name)
        dim_columns.append(column_name)

        # For regular dimensions, dim_id is column_name
        dim_id = column_name
        elimination_possible = dim.get("eliminationPossible", False)
        elimination_code = dim.get("eliminationCode", None)
        elimination_map[dim_id] = (elimination_possible, elimination_code)

    # Get measures
    measures = [m["columnName"] for m in measurements]

    return DetectedSchema(
        tableid=tableid,
        time_col=time_col,
        dims=dims,
        measures=measures,
        dim_columns=dim_columns,
        coded_dims=coded_dims,
        code_name_map=code_name_map,
        elimination_map=elimination_map,
    )


# -----------------------------
# Writers: json + pxjson
# -----------------------------
def write_csv(df: pd.DataFrame, schema: DetectedSchema, out_csv: Path) -> pd.DataFrame:
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

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    # Write to CSV with semicolon separator (matching input format)
    out_df.to_csv(out_csv, index=False, sep=";", encoding="utf-8")
    return out_df


def write_pxcodes(df: pd.DataFrame, schema: DetectedSchema, out_dir: Path) -> None:
    """Create pxcodes for all csv dimensions (excluding time)."""
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

        # Get elimination info from metadata
        elimination_possible, elimination_code = schema.elimination_map.get(dim_id, (False, None))

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
            "eliminationPossible": elimination_possible,
            "eliminationCode": elimination_code,
            "sortGroupingsOn": None,
            "groupings": None,
        }

        (out_dir / f"{dim_id}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def write_pxstatistics(tableid: str, out_path: Path) -> None:
    payload = {
        "id": tableid,
        "subjectCode": "GEN",
        "subjectText": {"no": "Generert", "en": "Generated"},
        "contacts": [],
        "statistics": {"statisticalPresenter": {"no": "Generert", "en": "Generated"}},
        "notes": None,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


# -----------------------------
# Main
# -----------------------------
def load_csv_with_fallback(csv_path: Path) -> pd.DataFrame:
    """Load CSV file, trying multiple encodings if UTF-8 fails."""
    encodings = ["utf-8", "iso-8859-1", "cp1252", "latin-1"]

    for encoding in encodings:
        try:
            return pd.read_csv(csv_path, sep=";", encoding=encoding)
        except (UnicodeDecodeError, UnicodeError):
            continue

    # If all encodings fail, raise an error
    raise ValueError(f"Could not decode {csv_path} with any of these encodings: {encodings}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("tableid", type=str, help="Table ID (e.g., SYS002)")
    ap.add_argument("--root", type=str, default=".", help="Project root folder (default: current directory)")
    args = ap.parse_args()

    tableid = args.tableid.upper()
    root = Path(args.root)

    # Construct file paths from tableid
    csv_path = root / "input" / "csv_files" / f"{tableid}.csv"
    metadata_path = root / "input" / "pxmetadata" / f"{tableid}.json"

    if not csv_path.exists():
        raise FileNotFoundError(f"CSV file not found: {csv_path}")
    if not metadata_path.exists():
        raise FileNotFoundError(f"Metadata file not found: {metadata_path}")

    # Read CSV + normalize
    df_raw = load_csv_with_fallback(csv_path)
    df = normalize_headers_and_pair_rename(df_raw)

    # Load schema from metadata
    schema = load_schema_from_metadata(metadata_path)

    # Write CSV data (normalized/cleaned version)
    out_csv = root / "pxjson" / "csv_files" / f"{tableid}.csv"
    write_csv(df, schema, out_csv)

    # Write pxcodes
    if schema.dim_columns:
        write_pxcodes(df, schema, root / "pxjson" / "pxcodes")

    # Write pxstatistics
    write_pxstatistics(tableid, root / "pxjson" / "pxstatistics" / f"pxstatistics_{tableid}.json")

    print("TABLEID:", tableid)
    print("Processed CSV:", out_csv)
    print("Dims:", schema.dims)
    print("Measures:", schema.measures)
    print("Coded dims:", schema.coded_dims)
    print("Wrote pxstatistics:", root / "pxjson" / "pxstatistics" / f"pxstatistics_{tableid}.json")
    if schema.dim_columns:
        print("Wrote pxcodes:", root / "pxjson" / "pxcodes")


if __name__ == "__main__":
    main()
