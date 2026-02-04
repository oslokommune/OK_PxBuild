from pathlib import Path
import pandas as pd

# ---- paths ----
REPO = Path(__file__).resolve().parents[1]  # ...\PxBuild
XLSX = REPO / "my_project" / "input" / "sysselsatte_per_befolkning_2024.xlsx"
OUT_PARQUET = REPO / "my_project" / "MYTABLE.parquet"

OUT_PARQUET.parent.mkdir(parents=True, exist_ok=True)

# ---- load ----
df = pd.read_excel(XLSX)

# If your Excel has duplicate headers like: geografi | geografi
# pandas will typically rename the second to "geografi.1"
# Adjust these if your actual columns differ.
rename_map = {
    "geografi": "geografi_kode",
    "geografi.1": "geografi_navn",
}
df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})

required = {"aargang", "geografi_kode", "geografi_navn", "kjoenn", "aldersgrupper"}
missing = required - set(df.columns)
if missing:
    raise ValueError(f"Mangler forventede kolonner: {missing}. Faktiske kolonner: {list(df.columns)}")

# Your measures (value columns). Adapt if yours have other names.
measure_cols = [c for c in ["sysselsatte", "andeler", "befolkning"] if c in df.columns]
if not measure_cols:
    raise ValueError(
        f"Fant ingen målekolonner blant {['sysselsatte','andeler','befolkning']}. Faktiske: {list(df.columns)}"
    )

# ---- reshape wide measures -> long ----
# PX wants one "value" column + a "contents" (measure) variable.
tidy = df.melt(
    id_vars=["aargang", "geografi_kode", "kjoenn", "aldersgrupper"],
    value_vars=measure_cols,
    var_name="contents",
    value_name="value",
)

# Ensure types
tidy["aargang"] = pd.to_numeric(tidy["aargang"], errors="raise").astype(int).astype(str)
tidy["value"] = pd.to_numeric(tidy["value"], errors="coerce")  # allow blanks -> NaN

# ---- write parquet ----
tidy.to_parquet(OUT_PARQUET, index=False)

# ---- also write code lists (you’ll use these in pxcodes json) ----
codes_dir = REPO / "my_project" / "pxcodes"
codes_dir.mkdir(parents=True, exist_ok=True)

geo_codes = df[["geografi_kode", "geografi_navn"]].dropna().drop_duplicates().sort_values("geografi_kode")
geo_codes.to_csv(codes_dir / "geografi_codes.csv", index=False, encoding="utf-8")

print("Wrote:", OUT_PARQUET)
print("Wrote:", codes_dir / "geografi_codes.csv")
print("Rows tidy:", len(tidy))
print("Columns tidy:", list(tidy.columns))
