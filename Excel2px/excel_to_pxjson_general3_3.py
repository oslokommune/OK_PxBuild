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


def read_excel_smart(xlsx: Path, preview_rows: int = 5, min_filled: float = 0.5) -> pd.DataFrame:
    """
    Read Excel and automatically detect the header row based on structure.

      - header row has many filled cells
      - header row cells are mostly text-like (not numeric)
      - header row has fairly unique labels
    """
    preview = pd.read_excel(xlsx, header=None, nrows=preview_rows)

    def _is_empty(x) -> bool:
        return x is None or (isinstance(x, float) and pd.isna(x)) or str(x).strip() == ""

    def _norm(x) -> str:
        if _is_empty(x):
            return ""
        return to_ascii_key(str(x))

    def _is_numeric_like(x) -> bool:
        if _is_empty(x):
            return False
        s = str(x).strip().replace("\u00a0", "").replace(" ", "").replace(",", ".")
        try:
            float(s)
            return True
        except Exception:
            return False

    best_row = None
    best_score = -1.0

    ncols = preview.shape[1]

    for i in range(len(preview)):
        row = preview.iloc[i].tolist()
        nonempty = [x for x in row if not _is_empty(x)]
        if not nonempty:
            continue

        filled = len(nonempty) / max(1, ncols)
        if filled < min_filled:
            continue

        numeric_like = sum(_is_numeric_like(x) for x in nonempty)
        text_like = 1.0 - (numeric_like / max(1, len(nonempty)))

        labels = [_norm(x) for x in nonempty]
        labels = [x for x in labels if x != ""]
        if not labels:
            continue

        unique_ratio = len(set(labels)) / max(1, len(labels))

        score = 2.0 * filled + 1.0 * text_like + 0.5 * unique_ratio

        if score > best_score:
            best_score = score
            best_row = i

    if best_row is None:
        # fall back to standard read
        df = pd.read_excel(xlsx)
    else:
        df = pd.read_excel(xlsx, header=best_row)

    # Rename unnamed columns to stable placeholders
    new_cols = []
    for j, c in enumerate(df.columns):
        c_str = "" if c is None else str(c)
        if c_str.lower().startswith("unnamed") or c_str.strip() == "":
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


# -----------------------------
# Core detection logic
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
    """Detect schema."""
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
        # Coded dimension pairs (x_kode/x_navn)
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

        elimination_code = detect_elimination_code(items)

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
            "eliminationPossible": elimination_code is not None,
            "eliminationCode": elimination_code,
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
        "subjectText": {"no": "Generert", "en": "Generated"},
        "contacts": [],
        "statistics": {"statisticalPresenter": {"no": "Generert", "en": "Generated"}},
        "notes": None,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


TOTAL_LABEL_HINTS = (
    "i alt",
    "ialt",
    "begge",
    "alle",
    "alt",
    "total",
    "sum",
    "samlet",
)


def is_total_like(code: str, label: str) -> bool:
    txt = f"{code} {label}".strip().lower()
    txt = txt.replace("_", " ")
    return any(hint in txt for hint in TOTAL_LABEL_HINTS)


def detect_elimination_code(items: list[tuple[str, str]]) -> str | None:
    """
    items = [(code, label), ...]
    Return the code of the most likely 'total' category, else None.
    Prefer matches in label text such as 'Oslo i alt', 'Alder i alt', 'Begge kjønn'.
    """
    matches = [(code, label) for code, label in items if is_total_like(code, label)]
    if not matches:
        return None

    # Prefer strongest/common totals first
    priority_patterns = [
        "i alt",
        "begge",
        "total",
        "sum",
        "alle",
    ]

    def score(pair: tuple[str, str]) -> tuple[int, int]:
        code, label = pair
        txt = f"{code} {label}".lower()
        best = 999
        for i, patt in enumerate(priority_patterns):
            if patt in txt:
                best = i
                break
        # secondary preference: shorter label often means aggregate
        return (best, len(label))

    matches.sort(key=score)
    return matches[0][0]


# -----------------------------
# Main
# -----------------------------
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("xlsx", type=str, help="Path to Excel file (.xlsx)")
    ap.add_argument("--tableid", type=str, default=None, help="Override TABLEID (default: from filename)")
    ap.add_argument("--root", type=str, default="Excel2px", help="Project root folder (default: Excel2px)")
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
