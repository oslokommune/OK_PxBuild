import json
from pathlib import Path
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
PARQUET = REPO / "my_project" / "pxjson" / "parquet_files" / "MYTABLE01.parquet"
OUT = REPO / "my_project" / "pxjson" / "pxcodes"
OUT.mkdir(parents=True, exist_ok=True)

df = pd.read_parquet(PARQUET)


def write_codes(var_id: str, series, label_no: str, sort_key=None):
    vals = sorted(series.dropna().astype(str).unique(), key=sort_key or (lambda x: x))
    obj = {
        "id": var_id,
        "admin": {"isFinal": True, "tags": []},
        "sortValueitemsOn": "code",
        "label": {"no": label_no},
        "valueitems": [
            {"code": v, "unorderedChildren": None, "label": {"no": v}, "rank": None, "notes": None} for v in vals
        ],
        "eliminationPossible": True,
        "eliminationCode": None,
        "sortGroupingsOn": None,
        "groupings": None,
    }
    (OUT / f"{var_id}.json").write_text(json.dumps(obj, ensure_ascii=True, indent=2), encoding="utf-8")
    print("Wrote", OUT / f"{var_id}.json", "items", len(vals))


write_codes("geografi", df["geografi_kode"], "geografi", sort_key=lambda x: (len(x), x))
write_codes("kjoenn", df["kjoenn"], "kjoenn")
write_codes("aldersgrupper", df["aldersgrupper"], "aldersgrupper")
write_codes("aar", df["aar"], "aar")
