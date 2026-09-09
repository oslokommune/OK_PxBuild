""".px-level regression for F-92: csv2px -> pxbuild, asserting the finished keywords.

The parity tests in the factory compare dataset-JSON between the two build paths;
they never look at the codes in the generated .px, which is where F-92 lived. This
test runs the same two steps the factory and the Fabric notebook run — csv2px on a
data CSV + metadata, then pxbuild.LoadFromPxmetadata on csv2px's output — and reads
CODES, VALUES and ELIMINATION out of the .px itself.
"""
import json
import re
import sys
from pathlib import Path

import pytest

import pxbuild

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "csv2px"))

from csv2px import (  # noqa: E402
    load_csv_with_fallback,
    load_schema_from_metadata,
    normalize_headers_and_pair_rename,
    write_csv,
    write_pxcodes,
)

TABLE = "T1"

# Total in the MIDDLE of the data, so totalFirst has something to do; leading-zero codes.
CSV = (
    "bydel_kode;bydel_navn;år;antall\n"
    "030101;Gamle Oslo;2024;60000\n"
    "0301;Oslo i alt;2024;700000\n"
    "030102;Grünerløkka;2024;65000\n"
    "030101;Gamle Oslo;2023;59000\n"
    "0301;Oslo i alt;2023;690000\n"
    "030102;Grünerløkka;2023;64000\n"
)


def _metadata(**bydel_overrides):
    bydel = {
        # csv2px reads dimensionId/labelColumnName; pxbuild ignores them (extra fields).
        "dimensionId": "bydel",
        "columnName": "bydel_kode",
        "labelColumnName": "bydel_navn",
        "code": "bydel",
        "codelistId": "bydel",
        "labelConstructionOption": "text",
        "label": {"no": "bydel"},
        "eliminationPossible": True,
        "eliminationCode": "0301",
        "valueOrder": "data",
        "totalFirst": True,
    }
    bydel.update(bydel_overrides)
    return {
        "dataset": {
            "tableId": TABLE,
            "matrix": TABLE,
            "statisticsId": TABLE,
            "dataFile": f"{TABLE}.csv",
            "subjectCode": "BEF",
            "subjectText": {"no": "Befolkning"},
            "subjectarea": {"no": "Befolkning"},
            "updateFrequency": {"no": "årlig"},
            "contacts": [{"raw": {"no": "Byrådsavdeling for finans (oslostatistikken@byr.oslo.kommune.no)"}}],
            "last-updated": None,
            "baseTitle": {"no": "Folkemengde etter bydel"},
            "contents": {"no": "Folkemengde etter bydel"},
            "title": {"no": "T1: Folkemengde etter bydel 2023-2024"},
            "searchKeywords": {"no": []},
            "notes": [],
            # pxbuild looks the time column up by this name in csv2px's OUTPUT, which is
            # header-normalised ("år" -> "ar"); the factory therefore emits it normalised.
            "timeDimension": {"columnName": "ar", "timePeriodFormat": "åååå", "label": {"no": "år"}},
            "codedDimensions": [bydel],
            "measurements": [
                {
                    "columnName": "antall",
                    "code": "Personer",
                    "showDecimals": 0,
                    "aggregationAllowed": True,
                    "label": {"no": "Personer"},
                    "unitOfMeasure": {"no": "personer"},
                }
            ],
        }
    }


def _build(tmp_path, metadata) -> str:
    root = tmp_path / "build"
    (root / "input" / "csv_files").mkdir(parents=True)
    (root / "input" / "pxmetadata").mkdir(parents=True)
    (root / "input" / "csv_files" / f"{TABLE}.csv").write_text(CSV, encoding="utf-8")
    meta_path = root / "input" / "pxmetadata" / f"{TABLE}.json"
    meta_path.write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")

    # --- csv2px, as main() does it ---
    df = normalize_headers_and_pair_rename(load_csv_with_fallback(root / "input" / "csv_files" / f"{TABLE}.csv"))
    schema = load_schema_from_metadata(meta_path)
    write_csv(df, schema, root / "pxjson" / "csv_files" / f"{TABLE}.csv")
    write_pxcodes(df, schema, root / "pxjson" / "pxcodes")

    # --- pxbuild on csv2px's output, same resource layout as the factory's config ---
    r = root.resolve().as_posix()
    out_dir = root / "out"
    out_dir.mkdir()
    config = {
        "admin": {
            "validLanguages": ["no"],
            "buildMultilingualFiles": False,
            "theWordAnd": {"no": "og"},
            "theWordBy": {"no": "etter"},
            "pxMetadataResource": {"adressFormat": f"{r}/input/pxmetadata/{{id}}.json"},
            "pxStatisticsResource": {"adressFormat": f"{r}/input/pxstatistics_{{id}}.json"},
            "pxCodesResource": {"adressFormat": f"{r}/pxjson/pxcodes/{{id}}.json"},
            "pxDataResource": {"adressFormat": f"{r}/pxjson/csv_files/{{id}}"},
            "outputDestination": {"pxFolderFormat": out_dir.resolve().as_posix(), "aggFolderFormat": out_dir.resolve().as_posix()},
            "skipCreationDate": True,
        },
        "charset": "ANSI",
        "axisVersion": "2013",
        "codePage": "windows-1252",
        "descriptionDefault": True,
        "contvariable": {"no": "statistikkvariabel"},
        "contvariableCode": "ContentsCode",
        "timevariableCode": "Tid",
        "datasymbolNil": {"no": "-"},
        "source": {"no": "Statistisk sentralbyrå (SSB)"},
    }
    config_path = root / "config.json"
    config_path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
    pxbuild.LoadFromPxmetadata(TABLE, str(config_path))

    px_file = out_dir / f"tab_{TABLE}_no.px"
    assert px_file.exists(), "ingen .px generert"
    return px_file.read_text(encoding="cp1252")


def _kw(px: str, keyword: str) -> str:
    m = re.search(rf'^{re.escape(keyword)}=(.*?);\s*$', px, flags=re.M | re.S)
    assert m, f"{keyword} ikke funnet i .px"
    return m.group(1)


class TestF92:
    def test_codes_keep_leading_zeros(self, tmp_path):
        px = _build(tmp_path, _metadata())
        assert _kw(px, 'CODES("bydel")') == '"0301","030101","030102"'

    def test_elimination_names_the_total_not_yes(self, tmp_path):
        # Before dtype=str this came out as ELIMINATION("bydel")="YES" and PxWeb summed the rows.
        px = _build(tmp_path, _metadata())
        assert _kw(px, 'ELIMINATION("bydel")') == '"Oslo i alt"'

    def test_values_follow_declared_order_with_total_first(self, tmp_path):
        px = _build(tmp_path, _metadata())
        assert _kw(px, 'VALUES("bydel")') == '"Oslo i alt","Gamle Oslo","Grünerløkka"'

    def test_data_block_follows_values_order(self, tmp_path):
        # VALUES order is DATA order: total row first, for both years (STUB=bydel, HEADING=år).
        px = _build(tmp_path, _metadata())
        data = _kw(px, "DATA").split()
        assert data[:2] == ["690000", "700000"]

    def test_unknown_elimination_code_fails_the_build(self, tmp_path):
        # An unknown total must stop the build at csv2px, never reach pxbuild's YES fallback.
        with pytest.raises(ValueError, match="eliminationCode"):
            _build(tmp_path, _metadata(eliminationCode="301", totalFirst=False))

    def test_undeclared_order_builds_code_sorted(self, tmp_path):
        meta = _metadata()
        for k in ("valueOrder", "totalFirst"):
            del meta["dataset"]["codedDimensions"][0][k]
        px = _build(tmp_path, meta)
        assert _kw(px, 'CODES("bydel")') == '"0301","030101","030102"'
        assert _kw(px, 'ELIMINATION("bydel")') == '"Oslo i alt"'
