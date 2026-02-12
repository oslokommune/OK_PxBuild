from pathlib import Path
import pandas as pd
import json

REPO = Path(__file__).resolve().parents[1]  # ...\PxBuild
XLSX = REPO / "my_project" / "input" / "sysselsatte_per_befolkning_2024.xlsx"
OUT_PARQUET = REPO / "my_project" / "pxjson_out" / "parquet_files" / "MYTABLE01.parquet"

OUT_PARQUET.parent.mkdir(parents=True, exist_ok=True)

df = pd.read_excel(XLSX, engine="openpyxl")

# If Excel has duplicate headers like: geografi | geografi (code + name),
# pandas renames the second to geografi.1
rename_map = {
    "geografi": "geografi_kode",
    "geografi.1": "geografi_navn",
    "kjoenn": "kjoenn",
    "aargang": "aar",
    "aldersgrupper": "aldersgrupper",
    "sysselsatte": "sysselsatte",
    "befolkning": "befolkning",
    "andeler": "andeler",
}
df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})

# Keep only ASCII columns you want in the final dataset
keep = [
    "aar",
    "geografi_kode",
    "kjoenn",
    "aldersgrupper",
    "sysselsatte",
    "befolkning",
    "andeler",
]
missing = [c for c in keep if c not in df.columns]
if missing:
    raise ValueError(f"Mangler kolonner: {missing}. Faktiske: {list(df.columns)}")

out = df[keep].copy()

# Types: make sure codes and dimensions are strings; year as string to avoid PX int issues
out["aar"] = out["aar"].astype(str)
out["geografi_kode"] = out["geografi_kode"].astype(str)
out["kjoenn"] = out["kjoenn"].astype(str)
out["aldersgrupper"] = out["aldersgrupper"].astype(str)

# Measures numeric
for m in ["sysselsatte", "befolkning", "andeler"]:
    out[m] = pd.to_numeric(out[m], errors="coerce")

# Optional: enforce uniqueness (one row per combination)
key = ["aar", "geografi_kode", "kjoenn", "aldersgrupper"]
dupes = out.duplicated(key, keep=False)
if dupes.any():
    raise ValueError("Duplikate kombinasjoner funnet i nøkkelkolonner. Sjekk input.")


codes_dir = REPO / "my_project" / "pxjson" / "pxcodes"
codes_dir.mkdir(parents=True, exist_ok=True)

geo = df[["geografi_kode", "geografi_navn"]].dropna().drop_duplicates().sort_values("geografi_kode")

geo_json = {
    "id": "geografi",
    "label": {"no": "geografi"},
    "sortValueitemsOn": "code",
    "valueitems": [
        {
            "code": str(r.geografi_kode),
            "unorderedChildren": None,
            "label": {"no": str(r.geografi_navn)},
            "rank": None,
            "notes": None,
        }
        for r in geo.itertuples(index=False)
    ],
    "eliminationPossible": True,
    "eliminationCode": None,
    "sortGroupingsOn": None,
    "groupings": None,
}

with open(codes_dir / "geografi.json", "w", encoding="utf-8") as f:
    json.dump(geo_json, f, ensure_ascii=False, indent=2)


out.to_parquet(OUT_PARQUET, index=False)
print("Wrote:", OUT_PARQUET)
print("Rows:", len(out))
print("Columns:", list(out.columns))

codes_dir = REPO / "my_project" / "pxcodes"
codes_dir.mkdir(parents=True, exist_ok=True)

""
geo_codes = df[["geografi_kode", "geografi_navn"]].dropna().drop_duplicates().sort_values("geografi_kode")
geo_codes.to_csv(codes_dir / "geografi_codes.csv", index=False, encoding="utf-8")

print("Wrote:", codes_dir / "geografi_codes.csv")
