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
    """
    # synonyms
    if s in {"ar", "aar", "aargang", "year"}:
        return "aar"
    if s in {"kjonn", "kjon", "kjonnn"}:
        return "kjoenn"
    if s == "kjonn.1":
        return "kjoenn.1"
    """
    return s


def clean_numeric_series(s: pd.Series) -> pd.Series:
    """Try to coerce numeric strings into floats. Handles common formats like "1 234", "12,3", and also converts empty strings to NaN."""
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
    """Normalize headers + rename adjacent duplicate pairs x/x.1 into x_kode/x_navn. Identifies coded vs uncoded dimensions."""
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
    """Structured representation of the detected schema from metadata."""

    tableid: str
    time_col: str
    dims: List[str]  # csv columns used as dimensions (time + dim columns)
    measures: List[str]  # measure columns in csv
    dim_columns: List[str]  # csv dim columns excluding time
    coded_dims: List[str]  # bases for *_kode columns (mostly for debug)
    code_name_map: Dict[str, Tuple[str, Optional[str]]]  # base -> (kode_col, navn_col or None)
    elimination_map: Dict[str, Tuple[bool, Optional[str]]]  # dim_id -> (eliminationPossible, eliminationCode)
    time_format: Optional[str] = None  # timeDimension.timePeriodFormat (None in legacy metadata)


def load_schema_from_metadata(metadata_path: Path) -> DetectedSchema:
    """Load schema from JSON metadata file."""
    with open(metadata_path, "r", encoding="utf-8") as f:
        metadata = json.load(f)

    dataset = metadata["dataset"]
    tableid = dataset["tableId"]
    time_col = to_ascii_key(dataset["timeDimension"]["columnName"])
    time_format = dataset["timeDimension"].get("timePeriodFormat")

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
    normalized_columns = [to_ascii_key(d["columnName"]) for d in coded_dimensions + dimensions]
    for dim in coded_dimensions:
        dim_id = dim["dimensionId"]
        column_name = to_ascii_key(dim["columnName"])
        dims.append(column_name)
        dim_columns.append(column_name)
        coded_dims.append(dim_id)
        # Assume kode/navn pairs if column_name ends with _kode
        if column_name.endswith("_kode"):
            base = column_name[:-5]
            # Use labelColumnName from metadata if present, otherwise infer
            label_column_name = dim.get("labelColumnName")
            navn_col = to_ascii_key(label_column_name) if label_column_name else f"{base}_navn"
            code_name_map[base] = (
                column_name,
                navn_col if (label_column_name or navn_col in normalized_columns) else None,
            )
        else:
            code_name_map[dim_id] = (column_name, None)

        # Parse elimination
        elimination_possible = dim.get("eliminationPossible", False)
        elimination_code = dim.get("eliminationCode", None)
        elimination_map[dim_id] = (elimination_possible, elimination_code)

    # Process regular dimensions
    for dim in dimensions:
        column_name = to_ascii_key(dim["columnName"])
        dims.append(column_name)
        dim_columns.append(column_name)

        # For regular dimensions, dim_id is column_name
        dim_id = column_name
        elimination_possible = dim.get("eliminationPossible", False)
        elimination_code = dim.get("eliminationCode", None)
        elimination_map[dim_id] = (elimination_possible, elimination_code)

    # Get measures
    measures = [to_ascii_key(m["columnName"]) for m in measurements]

    return DetectedSchema(
        tableid=tableid,
        time_col=time_col,
        dims=dims,
        measures=measures,
        dim_columns=dim_columns,
        coded_dims=coded_dims,
        code_name_map=code_name_map,
        elimination_map=elimination_map,
        time_format=time_format,
    )


# -----------------------------
# Writers: json + pxjson
# -----------------------------
def write_csv(df: pd.DataFrame, schema: DetectedSchema, out_csv: Path) -> pd.DataFrame:
    """
    Clean and normalize the input DataFrame according to the detected schema, then write to CSV.
        - Normalize dimension values to strings
        - Ensure measure columns are numeric
        - Collapse duplicates by summing measures for rows with the same dimension combination

    """
    # Optional symbol columns (<measure>_SYMBOL, normalized to _symbol): carry
    # PX symbols ("-", ".." ...) per cell through to pxbuild's SYMBOL contract
    # (datadatasource pairs them with the measure column). They must bypass the
    # numeric coercion below — that is the whole point of splitting them out.
    symbol_cols = {m: f"{m}_symbol" for m in schema.measures if f"{m}_symbol" in df.columns}

    keep_cols = list(dict.fromkeys(schema.dims + schema.measures + list(symbol_cols.values())))
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

    # Normalize time to string periods. Pure-year formats go via int64 to strip
    # numeric artifacts ("2025.0" -> "2025"). Non-numeric formats — quarters
    # "2025K1", interval periods like school years "2011/2012" or rolling
    # windows "2007-2013" (timePeriodFormat "intervall") — must be kept
    # verbatim; int coercion would raise on them. Both branches reject missing
    # time values: the int path via errors="raise", the string path explicitly
    # (an empty period would otherwise surface as a "" VALUES entry or a
    # confusing mixed-type sort error deep inside pxbuild).
    if schema.time_format in (None, "åååå", "yyyy"):
        out_df[schema.time_col] = pd.to_numeric(out_df[schema.time_col], errors="raise").astype("int64").astype(str)
    else:
        periods = out_df[schema.time_col].map(_norm_dim_value)
        if (periods == "").any():
            n_empty = int((periods == "").sum())
            raise ValueError(
                f"Time column '{schema.time_col}' has {n_empty} empty value(s); every row needs a time period."
            )
        out_df[schema.time_col] = periods

    # ensure measures numeric (symbol columns stay verbatim strings)
    for m in schema.measures:
        out_df[m] = clean_numeric_series(out_df[m])
    for sc in symbol_cols.values():
        out_df[sc] = out_df[sc].map(_norm_dim_value)

    # collapse duplicates (same dim combination)
    if out_df.duplicated(subset=schema.dims, keep=False).any():

        def _agg_series(s: pd.Series):
            ss = s.dropna()
            if ss.empty:
                return float("nan")
            if ss.nunique(dropna=True) <= 1:
                return ss.iloc[0]
            return pd.to_numeric(ss, errors="coerce").sum()

        def _agg_symbol(s: pd.Series):
            ss = [x for x in s if str(x).strip()]
            return ss[0] if ss else ""

        agg_map = {m: _agg_series for m in schema.measures}
        agg_map.update({sc: _agg_symbol for sc in symbol_cols.values()})
        out_df = out_df.groupby(schema.dims, dropna=False, sort=False, as_index=False).agg(agg_map)

    # Uppercase _SYMBOL suffix on write: pxbuild's datadatasource validates
    # symbol values only for columns literally ending in "_SYMBOL".
    if symbol_cols:
        out_df = out_df.rename(columns={sc: f"{m}_SYMBOL" for m, sc in symbol_cols.items()})

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    # Write to CSV with semicolon separator (matching input format)
    out_df.to_csv(out_csv, index=False, sep=";", encoding="utf-8")
    return out_df


def write_pxcodes(df: pd.DataFrame, schema: DetectedSchema, out_dir: Path) -> None:
    """Create pxcodes only for CODED dimensions (uncoded dimensions use raw data values)."""
    out_dir.mkdir(parents=True, exist_ok=True)

    def norm_code(x) -> str:
        if pd.isna(x):
            return ""
        if isinstance(x, float) and x.is_integer():
            return str(int(x))
        return str(x).strip()

    # Only process coded dimensions
    for dim_id in schema.coded_dims:
        if dim_id not in schema.code_name_map:
            continue

        code_col, label_col = schema.code_name_map[dim_id]

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


def main():
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

    # Write pxcodes (only if there are coded dimensions)
    if schema.coded_dims:
        write_pxcodes(df, schema, root / "pxjson" / "pxcodes")

    print("TABLEID:", tableid)
    print("Processed CSV:", out_csv)
    print("Dims:", schema.dims)
    print("Measures:", schema.measures)
    print("Coded dims:", schema.coded_dims)
    if schema.coded_dims:
        print("Wrote pxcodes:", root / "pxjson" / "pxcodes")


if __name__ == "__main__":
    main()
