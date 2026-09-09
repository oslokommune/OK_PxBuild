"""valueOrder / totalFirst for CODED dimensions (G-4 in the factory, T-7's sibling).

pxbuild orders an uncoded dimension's VALUES from `valueOrder`/`totalFirst` in
pxmetadata (T-7). A coded dimension's VALUES come from pxcodes instead, and pxbuild
re-sorts those by `sortValueitemsOn` — so the only way a declared order survives is
as RANK. csv2px is the step that has the data (and so knows "data" order), which is
why the declaration is honoured here: csv2px emits `sortValueitemsOn: "rank"` with
zero-padded ranks when a coded dimension declares an order, and stays byte-identical
("code"-sorted, no rank) when it does not.

The human-facing side of a coded dimension is the LABEL, so "alphabetical" sorts on
label and "explicit" names labels — that is what the master speaks in.
"""
import json
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "csv2px"))

from csv2px import DetectedSchema, order_coded_items, write_pxcodes  # noqa: E402

# Data order, total in the MIDDLE — the case the PROD measurement showed we did not handle.
ITEMS = [("m", "Mann"), ("t", "Begge kjønn"), ("k", "Kvinne")]


def _order(**kw):
    args = dict(value_order=None, explicit_values=None, total_first=False, elimination_code=None)
    args.update(kw)
    return order_coded_items("kjonn", ITEMS, **args)


class TestDefaultIsUnchanged:
    def test_nothing_declared_sorts_by_code(self):
        assert [c for c, _ in _order()] == ["k", "m", "t"]

    def test_elimination_code_alone_does_not_reorder(self):
        assert [c for c, _ in _order(elimination_code="t")] == ["k", "m", "t"]


class TestDeclaredOrders:
    def test_data_keeps_first_appearance(self):
        assert _order(value_order="data") == ITEMS

    def test_alphabetical_sorts_on_label_not_code(self):
        # By code it would be k, m, t; by label: Begge kjønn, Kvinne, Mann.
        assert [c for c, _ in _order(value_order="alphabetical")] == ["t", "k", "m"]

    def test_explicit_names_labels(self):
        out = _order(value_order="explicit", explicit_values=["Kvinne", "Mann", "Begge kjønn"])
        assert [c for c, _ in out] == ["k", "m", "t"]

    def test_explicit_missing_label_raises(self):
        with pytest.raises(ValueError, match="Kvinne"):
            _order(value_order="explicit", explicit_values=["Mann", "Begge kjønn"])

    def test_explicit_unknown_label_raises(self):
        with pytest.raises(ValueError, match="Ukjent"):
            _order(value_order="explicit", explicit_values=["Mann", "Begge kjønn", "Kvinne", "Ukjent"])

    def test_explicit_with_shared_labels_raises(self):
        # Two codes with the same label (bydel/delbydel in practice): a label list cannot say which goes where.
        items = [("01", "Sentrum"), ("0101", "Sentrum"), ("02", "Nord")]
        with pytest.raises(ValueError, match="share the same label"):
            order_coded_items("bydel", items, "explicit", ["Sentrum", "Nord"], False, None)

    def test_unknown_value_order_raises(self):
        with pytest.raises(ValueError, match="curated"):
            _order(value_order="curated")


class TestTotalFirst:
    def test_total_first_beats_code_order(self):
        assert [c for c, _ in _order(total_first=True, elimination_code="t")] == ["t", "k", "m"]

    def test_total_first_composes_with_data_order(self):
        out = _order(value_order="data", total_first=True, elimination_code="t")
        assert [c for c, _ in out] == ["t", "m", "k"]

    def test_total_first_without_elimination_code_raises(self):
        with pytest.raises(ValueError, match="no eliminationCode"):
            _order(total_first=True)

    def test_unknown_elimination_code_raises_even_without_total_first(self):
        with pytest.raises(ValueError, match="'x'.*not among the codes"):
            _order(elimination_code="x")


def _schema(order_map):
    return DetectedSchema(
        tableid="T1",
        time_col="aar",
        dims=["aar", "kjonn_kode"],
        measures=["antall"],
        dim_columns=["kjonn_kode"],
        coded_dims=["kjonn"],
        code_name_map={"kjonn": ("kjonn_kode", "kjonn_navn")},
        elimination_map={"kjonn": (True, "t")},
        time_format="åååå",
        order_map=order_map,
    )


def _df():
    return pd.DataFrame(
        {
            "kjonn_kode": ["m", "t", "k", "m"],
            "kjonn_navn": ["Mann", "Begge kjønn", "Kvinne", "Mann"],
            "aar": ["2024"] * 4,
            "antall": ["1", "3", "2", "1"],
        }
    )


class TestWritePxcodes:
    def test_declared_order_is_emitted_as_rank(self, tmp_path):
        write_pxcodes(_df(), _schema({"kjonn": ("data", None, True)}), tmp_path)
        px = json.loads((tmp_path / "kjonn.json").read_text(encoding="utf-8"))
        assert px["sortValueitemsOn"] == "rank"
        assert [v["code"] for v in px["valueitems"]] == ["t", "m", "k"]
        assert [v["rank"]["no"] for v in px["valueitems"]] == ["0000", "0001", "0002"]
        assert px["eliminationCode"] == "t"

    def test_rank_is_zero_padded_text(self, tmp_path):
        # pxbuild sorts rank as TEXT, so "10" must not come before "2".
        df = pd.DataFrame(
            {
                "kjonn_kode": [f"c{i:02d}" for i in range(12)],
                "kjonn_navn": [f"L{i}" for i in range(12)],
                "aar": ["2024"] * 12,
                "antall": ["1"] * 12,
            }
        )
        schema = _schema({"kjonn": ("data", None, False)})
        schema.elimination_map = {"kjonn": (False, None)}
        write_pxcodes(df, schema, tmp_path)
        px = json.loads((tmp_path / "kjonn.json").read_text(encoding="utf-8"))
        ranks = [v["rank"]["no"] for v in px["valueitems"]]
        assert ranks == sorted(ranks)
        assert len({len(r) for r in ranks}) == 1

    def test_undeclared_stays_code_sorted_without_rank(self, tmp_path):
        write_pxcodes(_df(), _schema({}), tmp_path)
        px = json.loads((tmp_path / "kjonn.json").read_text(encoding="utf-8"))
        assert px["sortValueitemsOn"] == "code"
        assert [v["code"] for v in px["valueitems"]] == ["k", "m", "t"]
        assert all(v["rank"] is None for v in px["valueitems"])
