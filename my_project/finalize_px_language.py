"""
To run:
python finalize_px_language.py my_project\output\px\output_MYTABLE01\tab_MYTABLE01.px no
"""

from __future__ import annotations

import re
import sys
from pathlib import Path


LANG_RE = re.compile(r"^([A-ZÅÄÖ0-9\-_]+)\[(no|en)\](.*)$", re.IGNORECASE)


def read_text_with_fallback(p: Path) -> tuple[str, str]:
    """
    PX files are commonly cp1252 (WINDOWS-1252), but some are utf-8-sig.
    Try utf-8-sig first (keeps Norwegian chars if present), fall back to cp1252.
    Returns (text, encoding_used).
    """
    raw = p.read_bytes()
    for enc in ("utf-8-sig", "cp1252", "utf-8"):
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            continue
    # last resort
    return raw.decode("cp1252", errors="replace"), "cp1252"


def write_text_cp1252(p: Path, text: str) -> None:
    # PxEdit is happiest with cp1252 in Windows environments.
    p.write_bytes(text.encode("cp1252", errors="replace"))


def finalize_px_language(px_text: str, lang: str) -> str:
    lang = lang.lower().strip()
    if lang not in ("no", "en"):
        raise ValueError("Language must be 'no' or 'en'")

    other = "en" if lang == "no" else "no"

    out_lines: list[str] = []
    in_data = False

    for line in px_text.splitlines(keepends=True):
        # Detect DATA start; after this we keep everything untouched
        # (PX format: DATA= ... and then numbers until ';')
        if not in_data:
            # DATA can be "DATA=..." on a line
            if re.search(r"(^|\r?\n)DATA\s*=", line):
                in_data = True
                out_lines.append(line)
                continue

            # Normalize LANGUAGE/LANGUAGES (untagged keywords)
            # Examples:
            # LANGUAGE="no";
            # LANGUAGES="no","en";
            if line.upper().startswith("LANGUAGE="):
                out_lines.append(f'LANGUAGE="{lang}";\r\n' if line.endswith("\r\n") else f'LANGUAGE="{lang}";\n')
                continue

            if line.upper().startswith("LANGUAGES="):
                out_lines.append(f'LANGUAGES="{lang}";\r\n' if line.endswith("\r\n") else f'LANGUAGES="{lang}";\n')
                continue

            # Drop any language-tagged line for the other language
            m = LANG_RE.match(line)
            if m:
                key, ltag, rest = m.group(1), m.group(2).lower(), m.group(3)

                if ltag == other:
                    # remove the not-chosen language line entirely
                    continue

                # keep chosen language but remove [xx] tag
                # e.g. TITLE[no]=... -> TITLE=...
                out_lines.append(f"{key}{rest}")
                continue

            # Otherwise keep line as-is
            out_lines.append(line)
        else:
            # Inside DATA block: do not change anything
            out_lines.append(line)

    return "".join(out_lines)


def main() -> int:
    if len(sys.argv) >= 2:
        in_path = Path(sys.argv[1])
    else:
        in_path = Path(input("Path to input .px: ").strip().strip('"'))

    if not in_path.exists():
        print(f"ERROR: file not found: {in_path}")
        return 2

    if len(sys.argv) >= 3:
        lang = sys.argv[2].strip().lower()
    else:
        lang = input("Choose language (no/en): ").strip().lower()

    if len(sys.argv) >= 4:
        out_path = Path(sys.argv[3])
    else:
        out_path = in_path.with_name(in_path.stem + f"_{lang}" + in_path.suffix)

    text, enc = read_text_with_fallback(in_path)
    new_text = finalize_px_language(text, lang)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    write_text_cp1252(out_path, new_text)

    print(f"Read:  {in_path}  (decoded as {enc})")
    print(f"Wrote: {out_path} (encoded as cp1252)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
