import re
from pathlib import Path
import pandas as pd
import unicodedata

PX_PATH = Path(r"my_project\output\px\output_MYTABLE01\tab_MYTABLE01.px")
PARQUET_PATH = Path(r"my_project\pxjson\parquet_files\MYTABLE01.parquet")
OUT_PATH = Path(r"my_project\output\px\output_MYTABLE01\tab_MYTABLE01_pxedit_correct.px")

ENC_CANDIDATES = ["utf-8-sig", "utf-8", "cp1252"]

# Map PX variable name -> parquet column name
# (based on your setup)
PX_TO_PARQUET = {
    "geografi": "geografi_kode",
    "kjønn": "kjoenn",
    "kj�nn": "kjoenn",
    "aldersgrupper": "aldersgrupper",
    "innhold": "contents",
    "år": "aargang",
    "�r": "aargang",
    # "statistikkvariabel" is artificial in your build; we treat it as singleton
}

# For "innhold", PX uses labels but codes are the parquet values
# CODES("innhold") in your file: andeler,befolkning,sysselsatte
# Parquet contents values: andeler,befolkning,sysselsatte
# So we use CODES order as the order to generate data.
SINGLETONS = {
    "statistikkvariabel": "verdi",  # the only category (label)
}


def fix_px_text(s: str) -> str:
    # PX header contains U+FFFD '�' in place of norwegian letters
    # Fix the patterns we actually use for matching to parquet.
    return s.replace("kj�nn", "kjønn").replace("�r", "år")


def fold(s: str) -> str:
    # lower, strip accents, replace the unknown char with nothing
    s = s.replace("�", "")
    s = s.lower()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return s


def strip_lang(line: str) -> str:
    # turn KEYWORD[no]= into KEYWORD=
    return re.sub(r"^([A-ZÅÄÖ\-]+)\[[a-z]{2}\]", r"\1", line)


def parse_quoted_list(s: str):
    # returns list of strings inside quotes: "a","b","c"
    return re.findall(r'"([^"]*)"', s)


def parse_codes(lines):
    # returns dict varname -> list of codes (strings)
    codes = {}
    # handles: CODES("var")="a","b",...;
    pat = re.compile(r'^CODES\("([^"]+)"\)\s*=\s*(.*);')
    for line in lines:
        m = pat.match(line)
        if m:
            var = m.group(1)
            rhs = m.group(2)
            codes[var] = parse_quoted_list(rhs)
    return codes


def parse_stub_heading(lines):
    stub = heading = None
    for line in lines:
        if line.startswith("STUB="):
            stub = parse_quoted_list(line)
        if line.startswith("HEADING="):
            heading = parse_quoted_list(line)
    if stub is None or heading is None:
        raise ValueError("Missing STUB or HEADING in template (after stripping language tags).")
    return stub, heading


def main():
    raw = None
    used_enc = None
    for enc in ENC_CANDIDATES:
        try:
            raw = PX_PATH.read_text(encoding=enc).splitlines(True)
            used_enc = enc
            break
        except UnicodeDecodeError:
            continue
    if raw is None:
        # last resort: replace errors
        raw = PX_PATH.read_text(encoding="cp1252", errors="replace").splitlines(True)
        used_enc = "cp1252(errors=replace)"
    print("PX encoding used:", used_enc)

    # Work on "no-only" header: keep [no] lines, drop [en] lines, and strip [no] tags.
    header_lines = []
    for ln in raw:
        if ln.startswith("DATA=") or "DATA=" in ln:
            break
        # drop English-tagged lines
        if re.match(r"^[A-ZÅÄÖ\-]+\[en\]", ln):
            continue
        # strip [no]
        ln2 = strip_lang(ln)
        header_lines.append(ln2)

    # Also remove VARIABLECODE lines (PxEdit warning)
    header_lines = [ln for ln in header_lines if not ln.startswith("VARIABLECODE")]

    # Ensure LANGUAGES is only "no"
    header_lines = [
        re.sub(r"^LANGUAGES=.*;", 'LANGUAGES="no";\r\n', ln) if ln.startswith("LANGUAGES=") else ln
        for ln in header_lines
    ]
    header_lines = [
        re.sub(r"^LANGUAGE=.*;", 'LANGUAGE="no";\r\n', ln) if ln.startswith("LANGUAGE=") else ln for ln in header_lines
    ]

    # Parse STUB/HEADING and CODES order
    flat = [ln.strip("\r\n") for ln in header_lines]
    stub, heading = parse_stub_heading(flat)
    codes = parse_codes(flat)
    print("STUB:", stub)
    print("HEADING:", heading)
    print("CODES keys:", sorted(codes.keys())[:20])

    # Load parquet
    df = pd.read_parquet(PARQUET_PATH).copy()

    sex_vals = sorted(df["kjoenn"].astype(str).unique())
    age_vals = sorted(df["aldersgrupper"].astype(str).unique())

    sex_map = {fold(v): v for v in sex_vals}
    age_map = {fold(v): v for v in age_vals}

    # Normalize types to strings for matching
    df["aargang"] = df["aargang"].astype(str)
    df["geografi_kode"] = df["geografi_kode"].astype(str)
    df["contents"] = df["contents"].astype(str)

    # Build a lookup dict keyed by (aargang, geografi_kode, kjoenn, aldersgrupper, contents) -> value
    key_cols = ["aargang", "geografi_kode", "kjoenn", "aldersgrupper", "contents"]
    df["__key__"] = list(map(tuple, df[key_cols].values))
    lut = dict(zip(df["__key__"], df["value"]))

    # Determine generation order: STUB then HEADING, with the last stub varying fastest.
    var_order = stub + heading

    # Build the ordered category lists using CODES(...) where available,
    # otherwise fall back to VALUES(...) not needed here.
    cat_lists = []
    for var in var_order:
        if var in SINGLETONS:
            cat_lists.append([SINGLETONS[var]])
        elif var not in codes:
            raise ValueError(f"No CODES list found for variable {var}.")
        else:
            cat_lists.append(codes[var])

    # Create cartesian product in the same nested order as PxEdit displays:
    # geografi -> kjønn -> aldersgrupper -> innhold -> statistikkvariabel -> år
    # (last variable changes fastest)
    data_values = []

    # Pre-calc mapping from PX categories to parquet categories:
    # - geografi uses codes directly (strings)
    # - kjønn / aldersgrupper match labels directly
    # - innhold uses codes list (andeler/befolkning/sysselsatte)
    # - år maps to aargang (string)
    # - statistikkvariabel ignored for parquet, but kept singleton
    def to_parquet(var, px_cat):
        if var == "innhold":
            return px_cat  # code matches parquet
        if var == "år":
            return px_cat
        if var == "geografi":
            return px_cat
        if var == "kjønn":
            return px_cat
        if var == "aldersgrupper":
            return px_cat
        return px_cat

    # Generate in nested loops
    # (simple iterative cartesian product without importing itertools.product to keep it readable)
    def recurse(idx, chosen):
        if idx == len(var_order):
            # Build parquet key
            picked = dict(zip(var_order, chosen))

            def pick(varnames):
                for v in varnames:
                    if v in picked:
                        return picked[v]
                raise KeyError(f"None of {varnames} found in var_order={var_order}")

            year = pick(["år", "�r"])
            geo = pick(["geografi"])

            sex_raw = pick(["kjønn", "kj�nn"])
            age_raw = pick(["aldersgrupper"])
            cont = pick(["innhold"])

            sex_px = fix_px_text(str(sex_raw))
            age_px = fix_px_text(str(age_raw))

            sex = sex_map.get(fold(sex_px), sex_px)
            age = age_map.get(fold(age_px), age_px)

            # map to parquet categories (mostly identity)
            year = str(year)
            geo = str(geo)
            sex = str(sex)
            age = str(age)
            cont = str(cont)

            k = (year, geo, sex, age, cont)

            if k not in lut:
                raise KeyError(f"Missing data row in parquet for key: {k}")
            v = lut[k]
            # PX expects a number with dot decimal
            if pd.isna(v):
                data_values.append(".")
            else:
                data_values.append(str(float(v)))
            return

        var = var_order[idx]
        for cat in cat_lists[idx]:
            recurse(idx + 1, chosen + [cat])

    recurse(0, [])

    # Expected size sanity check
    expected = 1
    for lst in cat_lists:
        expected *= len(lst)
    if len(data_values) != expected:
        raise ValueError(f"Generated {len(data_values)} values, expected {expected}")

    # Write output: header + DATA= + one value per line + ;
    out = []
    out.extend(header_lines)
    out.append("DATA=" + data_values[0] + "\r\n")
    for v in data_values[1:]:
        out.append(v + "\r\n")
    out[-1] = out[-1].rstrip("\r\n") + ";\r\n"

    OUT_PATH.write_text("".join(out), encoding="cp1252", errors="replace")
    print("Wrote:", OUT_PATH)
    print("Cells:", len(data_values))


if __name__ == "__main__":
    main()
