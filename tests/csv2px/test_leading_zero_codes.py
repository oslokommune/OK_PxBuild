"""F-92: codes are identifiers, not numbers — csv2px must keep "030101" as "030101".

csv2px read the data CSV with pandas' default dtype inference, so a code column of
leading-zero codes (Oslo districts "0301", "030101" ...) became int64: "030101" -> 30101.
The declared eliminationCode "0301" then matched no code, pxbuild fell back to
ELIMINATION=YES, and PxWeb SUMMED the districts including "Oslo i alt". Both build
paths (local and Fabric) share csv2px, so the error was identical on both — and the
parity tests compare dataset-JSON, not .px codes, so they never saw it.

Measured in the PROD snapshot (172 files): 8 files carry codes with leading zeros
(bosted, landbakgrunn, aldersgruppe, menighet/sokn).
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "csv2px"))

from csv2px import (  # noqa: E402
    DetectedSchema,
    load_csv_with_fallback,
    load_schema_from_metadata,
    normalize_headers_and_pair_rename,
    write_csv,
    write_pxcodes,
)

# Two-level district codes as published: kommune first, then bydel. "0301" is the total.
CSV = (
    "bydel_kode;bydel_navn;år;antall\n"
    "0301;Oslo i alt;2024;700000\n"
    "030101;Gamle Oslo;2024;60000\n"
    "030102;Grünerløkka;2024;65000\n"
)

METADATA = {
    "dataset": {
        "tableId": "T1",
        "timeDimension": {"columnName": "år", "timePeriodFormat": "åååå"},
        "codedDimensions": [
            {
                "dimensionId": "bydel",
                "columnName": "bydel_kode",
                "labelColumnName": "bydel_navn",
                "codelistId": "bydel",
                "eliminationPossible": True,
                "eliminationCode": "0301",
            }
        ],
        "dimensions": [],
        "measurements": [{"columnName": "antall"}],
    }
}


def _run_csv2px(tmp_path, csv_text=CSV, metadata=METADATA):
    """The same steps csv2px.main() performs, on files in tmp_path."""
    csv_path = tmp_path / "T1.csv"
    csv_path.write_text(csv_text, encoding="utf-8")
    meta_path = tmp_path / "T1.json"
    meta_path.write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")

    df = normalize_headers_and_pair_rename(load_csv_with_fallback(csv_path))
    schema = load_schema_from_metadata(meta_path)
    out = write_csv(df, schema, tmp_path / "pxjson" / "csv_files" / "T1.csv")
    write_pxcodes(df, schema, tmp_path / "pxjson" / "pxcodes")
    pxcodes = json.loads((tmp_path / "pxjson" / "pxcodes" / "bydel.json").read_text(encoding="utf-8"))
    return out, pxcodes


class TestReadAsText:
    def test_loader_keeps_leading_zeros(self, tmp_path):
        p = tmp_path / "x.csv"
        p.write_text(CSV, encoding="utf-8")
        df = load_csv_with_fallback(p)
        assert df["bydel_kode"].tolist() == ["0301", "030101", "030102"]

    def test_loader_reads_measures_as_text_too(self, tmp_path):
        # Coercion to numbers is write_csv's job, where it is intended.
        p = tmp_path / "x.csv"
        p.write_text(CSV, encoding="utf-8")
        assert load_csv_with_fallback(p)["antall"].tolist() == ["700000", "60000", "65000"]

    def test_loader_still_falls_back_on_encoding(self, tmp_path):
        p = tmp_path / "x.csv"
        p.write_bytes(CSV.encode("cp1252"))
        df = load_csv_with_fallback(p)
        assert df["bydel_navn"].tolist()[2] == "Grünerløkka"


class TestThroughCsv2px:
    def test_codes_in_data_csv_keep_leading_zeros(self, tmp_path):
        out, _ = _run_csv2px(tmp_path)
        assert out["bydel_kode"].tolist() == ["0301", "030101", "030102"]

    def test_measures_are_still_numeric(self, tmp_path):
        out, _ = _run_csv2px(tmp_path)
        assert out["antall"].tolist() == [700000, 60000, 65000]

    def test_time_is_still_a_year_string(self, tmp_path):
        out, _ = _run_csv2px(tmp_path)
        # header-normalised: "år" -> "ar"
        assert out["ar"].tolist() == ["2024"] * 3

    def test_pxcodes_codes_keep_leading_zeros(self, tmp_path):
        _, pxcodes = _run_csv2px(tmp_path)
        assert [v["code"] for v in pxcodes["valueitems"]] == ["0301", "030101", "030102"]

    def test_elimination_code_is_among_the_codes(self, tmp_path):
        # The F-92 chain broke here: eliminationCode "0301" vs codes 30101, 30102, 301.
        _, pxcodes = _run_csv2px(tmp_path)
        assert pxcodes["eliminationCode"] in [v["code"] for v in pxcodes["valueitems"]]

    def test_unknown_elimination_code_raises_in_csv2px(self, tmp_path):
        # Declaring a total that is not in the data is an error at the first gate,
        # not something for pxbuild to shrug off as ELIMINATION=YES.
        meta = json.loads(json.dumps(METADATA))
        meta["dataset"]["codedDimensions"][0]["eliminationCode"] = "301"
        with pytest.raises(ValueError, match="'301'.*bydel"):
            _run_csv2px(tmp_path, metadata=meta)

    def test_undeclared_order_is_still_sorted_by_code(self, tmp_path):
        # Nothing declared -> historical csv2px behaviour, so existing metadata builds the same file.
        _, pxcodes = _run_csv2px(tmp_path, csv_text=CSV.replace("0301;Oslo i alt;2024;700000\n", "") + "0301;Oslo i alt;2024;700000\n")
        assert pxcodes["sortValueitemsOn"] == "code"
        assert [v["code"] for v in pxcodes["valueitems"]] == ["0301", "030101", "030102"]
        assert all(v["rank"] is None for v in pxcodes["valueitems"])


def test_schema_dataclass_defaults_order_map_empty():
    # Existing callers construct DetectedSchema without order_map.
    s = DetectedSchema("T", "t", ["t"], [], [], [], {}, {})
    assert s.order_map == {}
