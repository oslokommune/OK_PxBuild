"""Rank sorting of coded dimensions (G-4).

With sortValueitemsOn "rank", HelperPxCodes orders the valueitems by Valueitem.rank[lang].
The contract (jsonformats/openapiyaml/pxcodes.yaml, Valueitem.rank) types rank as
StringByLanguage: "Strings to sort by when code or label is not sufficient". The sort is
therefore a plain string sort, so "10" comes before "2", and a consumer that wants numeric
order must zero-pad the ranks ("02", "10").

The fixtures are chosen so that code order, label order and rank order all differ: a test
that passes here cannot be passing because the rank branch fell through to code or label.
"""
import pytest

from pxbuild.models.input.helper_pxcodes import HelperPxCodes, sort_valueitems_by_field
from pxbuild.models.input.pydantic_pxcodes import PxCodes, Valueitem


def _item(code: str, label: str, rank: str | None) -> dict:
    item = {"code": code, "label": {"no": label}}
    if rank is not None:
        item["rank"] = {"no": rank}
    return item


def _pxcodes(valueitems: list, sort_on: str = "rank") -> PxCodes:
    return PxCodes(
        id="kjonn",
        sortValueitemsOn=sort_on,
        valueitems=valueitems,
        eliminationPossible=False,
    )


# code order:  a, b, c
# label order: c (Begge), a (Kvinner), b (Menn)
# rank order:  b, c, a
_THREE = [
    _item("a", "Kvinner", "03"),
    _item("b", "Menn", "01"),
    _item("c", "Begge", "02"),
]


def test_the_three_sort_keys_give_three_different_orders():
    objects = [Valueitem(**i) for i in _THREE]
    assert [o.code for o in sort_valueitems_by_field(objects, "code", "no")] == ["a", "b", "c"]
    assert [o.code for o in sort_valueitems_by_field(objects, "label", "no")] == ["c", "a", "b"]
    assert [o.code for o in sort_valueitems_by_field(objects, "rank", "no")] == ["b", "c", "a"]


def test_rank_decides_the_order_over_code_and_label():
    helper = HelperPxCodes(_pxcodes(_THREE), ["no"])
    assert helper.get_codes("no") == ["b", "c", "a"]
    assert helper.get_labels("no") == ["Menn", "Begge", "Kvinner"]


def test_rank_present_but_ignored_when_sorting_on_code_or_label():
    assert HelperPxCodes(_pxcodes(_THREE, sort_on="code"), ["no"]).get_codes("no") == ["a", "b", "c"]
    assert HelperPxCodes(_pxcodes(_THREE, sort_on="label"), ["no"]).get_codes("no") == ["c", "a", "b"]


def test_rank_is_a_string_sort_so_10_comes_before_2():
    items = [
        _item("r2", "A", "2"),
        _item("r10", "B", "10"),
        _item("r1", "C", "1"),
    ]
    helper = HelperPxCodes(_pxcodes(items), ["no"])
    # Lexicographic: "1" < "10" < "2", not 1, 2, 10.
    assert helper.get_codes("no") == ["r1", "r10", "r2"]


def test_zero_padded_ranks_give_numeric_order():
    items = [
        _item("r2", "A", "02"),
        _item("r10", "B", "10"),
        _item("r1", "C", "01"),
    ]
    helper = HelperPxCodes(_pxcodes(items), ["no"])
    assert helper.get_codes("no") == ["r1", "r2", "r10"]


def test_rank_is_per_language():
    items = [
        {"code": "a", "label": {"no": "A", "en": "A"}, "rank": {"no": "1", "en": "2"}},
        {"code": "b", "label": {"no": "B", "en": "B"}, "rank": {"no": "2", "en": "1"}},
    ]
    helper = HelperPxCodes(_pxcodes(items), ["no", "en"])
    assert helper.get_codes("no") == ["a", "b"]
    assert helper.get_codes("en") == ["b", "a"]


def test_equal_ranks_keep_input_order():
    # sorted() is stable: ties are not broken by code or label.
    items = [
        _item("b", "Z", "1"),
        _item("a", "Y", "1"),
        _item("c", "X", "0"),
    ]
    helper = HelperPxCodes(_pxcodes(items), ["no"])
    assert helper.get_codes("no") == ["c", "b", "a"]


# --- rank missing: what the code does today ----------------------------------------------
# There is no fallback to code or label. A valueitem without rank under sortValueitemsOn
# "rank" stops the build with a bare TypeError/KeyError that names neither the codelist nor
# the code. These tests lock that behaviour; if a clearer error or a fallback is added, they
# are the ones to change.


def test_rank_missing_on_one_item_raises_typeerror():
    items = [
        _item("a", "A", "1"),
        _item("b", "B", None),
    ]
    with pytest.raises(TypeError, match="not subscriptable"):
        HelperPxCodes(_pxcodes(items), ["no"])


def test_rank_missing_for_one_language_raises_keyerror():
    items = [
        {"code": "a", "label": {"no": "A", "en": "A"}, "rank": {"no": "1", "en": "1"}},
        {"code": "b", "label": {"no": "B", "en": "B"}, "rank": {"no": "2"}},
    ]
    with pytest.raises(KeyError, match="en"):
        HelperPxCodes(_pxcodes(items), ["no", "en"])
