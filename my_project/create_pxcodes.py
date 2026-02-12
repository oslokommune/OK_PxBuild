from __future__ import annotations

import json
from pathlib import Path
import pandas as pd


def find_repo_root(start: Path) -> Path:
    """Walk upwards until we find pyproject.toml (repo root)."""
    for p in [start] + list(start.parents):
        if (p / "pyproject.toml").exists():
            return p
    raise RuntimeError("Could not find repo root (pyproject.toml).")


def norm_code(x) -> str:
    """Normalize codes to clean strings (avoid '102.0')."""
    if pd.isna(x):
        return ""
    # If it's a float that is really an int, format as int
    if isinstance(x, float) and x.is_integer():
        return str(int(x))
    return str(x).strip()


def make_codelist(
    *,
    codelist_id: str,
    label_no: str,
    label_en: str,
    items: list[tuple[str, str, str]],
) -> dict:
    return {
        "id": codelist_id,
        "admin": {
            "isFinal": True,
            "tags": ["generated"],
            "todoCreation": "Auto-generated from MYTABLE01.parquet / geografi_codes.csv",
        },
        "sortValueitemsOn": "code",
        "label": {"no": label_no, "en": label_en},
        "valueitems": [
            {
                "code": code,
                "unorderedChildren": None,
                "label": {"no": no, "en": en},
                "rank": None,
                "notes": None,
            }
            for code, no, en in items
        ],
        "eliminationPossible": True,
        "eliminationCode": None,
        "sortGroupingsOn": None,
        "groupings": None,
    }


def detect_measure_columns(df: pd.DataFrame) -> list[str]:
    # “dims we expect” in wide parquet
    dim_cols = {"aar", "geografi_kode", "kjoenn", "aldersgrupper"}
    # Everything else is treated as a measure column
    return [c for c in df.columns if c not in dim_cols]


def main() -> None:
    here = Path(__file__).resolve()
    repo = find_repo_root(here)
    base = repo / "my_project"

    parquet_path = base / "pxjson_out" / "parquet_files" / "MYTABLE01.parquet"
    geo_csv_path = base / "pxcodes" / "geografi_codes.csv"

    out_dir = base / "pxjson_out" / "pxcodes"
    out_dir.mkdir(parents=True, exist_ok=True)

    # --- Load parquet (needs pyarrow, which you already have in pxbuild env) ---
    df = pd.read_parquet(parquet_path)

    # --- 1) geografi (codes + names from csv) ---
    geo = pd.read_csv(geo_csv_path, dtype=str)
    # Expect columns: geografi_kode, geografi_navn (as written by your converter)
    if not {"geografi_kode", "geografi_navn"}.issubset(set(geo.columns)):
        # fallback: use first two columns
        geo = geo.iloc[:, :2]
        geo.columns = ["geografi_kode", "geografi_navn"]

    geo_items = []
    for _, r in geo.dropna().drop_duplicates().iterrows():
        code = norm_code(r["geografi_kode"])
        name_no = str(r["geografi_navn"]).strip()
        if not code:
            continue
        # No English names available -> reuse NO
        geo_items.append((code, name_no, name_no))

    geo_items.sort(key=lambda t: t[0])

    geografi_json = make_codelist(
        codelist_id="geografi",
        label_no="Geografi",
        label_en="Geography",
        items=geo_items,
    )

    # --- 2) kjønn (values from parquet) ---
    sex_map_en = {"Mann": "Men", "Kvinne": "Women"}

    kjoenn_vals = sorted({str(x).strip() for x in df["kjoenn"].dropna().unique()})
    kjoenn_items = [(v, v, sex_map_en.get(v, v)) for v in kjoenn_vals]

    kjoenn_json = make_codelist(
        codelist_id="kjoenn",
        label_no="Kjønn",
        label_en="Sex",
        items=kjoenn_items,
    )

    # --- 3) aldersgrupper (values from parquet) ---
    def age_en(s: str) -> str:
        s = s.strip()
        # "15-24 år" -> "15-24 years"
        if s.endswith(" år"):
            return s[:-3] + " years"
        return s.replace(" år", " years")

    age_vals = sorted({str(x).strip() for x in df["aldersgrupper"].dropna().unique()})
    age_items = [(v, v, age_en(v)) for v in age_vals]

    aldersgrupper_json = make_codelist(
        codelist_id="aldersgrupper",
        label_no="Aldersgrupper",
        label_en="Age groups",
        items=age_items,
    )

    # --- 4) contents (derived from WIDE parquet measure columns) ---
    contents_map_no = {
        "sysselsatte": "Sysselsatte",
        "befolkning": "Befolkning",
        "andeler": "Andeler",
        "antall": "Antall",
        "andel": "Andel",
    }
    contents_map_en = {
        "sysselsatte": "Employed",
        "befolkning": "Population",
        "andeler": "Share",
        "antall": "Count",
        "andel": "Share",
    }

    measure_cols = detect_measure_columns(df)
    cont_vals = sorted(measure_cols)

    cont_items = [(v, contents_map_no.get(v, v), contents_map_en.get(v, v)) for v in cont_vals]

    contents_json = make_codelist(
        codelist_id="contents",
        label_no="Innhold",
        label_en="Contents",
        items=cont_items,
    )

    # --- Write files ---
    for name, obj in [
        ("geografi.json", geografi_json),
        ("kjoenn.json", kjoenn_json),
        ("aldersgrupper.json", aldersgrupper_json),
        ("contents.json", contents_json),
    ]:
        p = out_dir / name
        p.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
        print("Wrote:", p)


if __name__ == "__main__":
    main()
