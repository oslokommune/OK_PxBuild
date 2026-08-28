"""Tests for VALUES ordering on uncoded (text) dimensions.

An uncoded dimension may declare `valueOrder` (alphabetical / data / explicit)
and `totalFirst`. The default is alphabetical, which is what pxbuild has always
done, so dimensions that declare nothing must come out byte-identical.

The ordering matters beyond tidiness: VALUES order is the order the DATA block
is written in, so a value list that disagrees with the declaration puts numbers
under the wrong labels. Both failure modes therefore raise.
"""

import pytest

from pxbuild.models.input.pydantic_pxmetadata import Dimension
from pxbuild.models.middle.dims import order_values

# Curated source order, as a published Oslo table carries it: total first, then
# a domain-specific order that alphabetical sorting would scatter.
KURATERT = ["I alt", "Arbeid, heltid", "Arbeid, deltid", "Ikke arbeidssøker"]


def _dimension(**overrides) -> Dimension:
    payload = {"columnName": "arbeidsstyrkestatus", "label": {"no": "arbeidsstyrkestatus"}}
    payload.update(overrides)
    return Dimension(**payload)


class TestDefaultIsUnchanged:
    """A dimension that declares nothing keeps the historical behaviour."""

    def test_no_declaration_sorts_alphabetically(self):
        assert order_values(_dimension(), KURATERT) == sorted(KURATERT)

    def test_value_order_defaults_to_none(self):
        assert _dimension().value_order is None

    def test_total_first_defaults_to_false(self):
        assert _dimension().total_first is False

    def test_alphabetical_is_the_explicit_form_of_the_default(self):
        alfabetisk = order_values(_dimension(valueOrder="alphabetical"), KURATERT)
        assert alfabetisk == order_values(_dimension(), KURATERT)

    def test_duplicates_collapse_without_reordering(self):
        # dropna().unique() already dedupes upstream, but the helper must not
        # depend on that to keep data order stable.
        assert order_values(_dimension(valueOrder="data"), ["b", "a", "b"]) == ["b", "a"]


class TestDataOrder:
    """"data" preserves the order the source yields values in."""

    def test_data_order_is_kept_verbatim(self):
        assert order_values(_dimension(valueOrder="data"), KURATERT) == KURATERT

    def test_data_order_differs_from_alphabetical_here(self):
        # Guards the test itself: if these ever coincide the case proves nothing.
        assert KURATERT != sorted(KURATERT)


class TestExplicitOrder:
    """"explicit" uses the declared list, and must match the data exactly."""

    def test_explicit_list_is_used_verbatim(self):
        oensket = ["I alt", "Ikke arbeidssøker", "Arbeid, heltid", "Arbeid, deltid"]
        dim = _dimension(valueOrder="explicit", explicitValues=oensket)
        assert order_values(dim, KURATERT) == oensket

    def test_value_missing_from_declaration_raises(self):
        dim = _dimension(valueOrder="explicit", explicitValues=KURATERT[:-1])
        with pytest.raises(ValueError, match="Ikke arbeidssøker"):
            order_values(dim, KURATERT)

    def test_value_not_in_data_raises(self):
        dim = _dimension(valueOrder="explicit", explicitValues=KURATERT + ["Ukjent"])
        with pytest.raises(ValueError, match="Ukjent"):
            order_values(dim, KURATERT)

    def test_error_names_the_dimension(self):
        dim = _dimension(code="arbstat", valueOrder="explicit", explicitValues=[])
        with pytest.raises(ValueError, match="arbstat"):
            order_values(dim, KURATERT)


class TestTotalFirst:
    """totalFirst lifts eliminationCode to the front, whatever the ordering."""

    def test_total_first_beats_alphabetical(self):
        # The case T-7 exists for: "I alt" sorts after "Arbeid" and "Ikke", so
        # alphabetical alone buries the total mid-list.
        dim = _dimension(eliminationPossible=True, eliminationCode="I alt", totalFirst=True)
        ut = order_values(dim, KURATERT)
        assert ut[0] == "I alt"
        assert ut[1:] == sorted(v for v in KURATERT if v != "I alt")

    def test_total_first_composes_with_data_order(self):
        rotert = ["Arbeid, heltid", "I alt", "Arbeid, deltid", "Ikke arbeidssøker"]
        dim = _dimension(
            valueOrder="data", eliminationPossible=True, eliminationCode="I alt", totalFirst=True
        )
        assert order_values(dim, rotert) == ["I alt", "Arbeid, heltid", "Arbeid, deltid", "Ikke arbeidssøker"]

    def test_total_already_first_is_a_no_op(self):
        dim = _dimension(
            valueOrder="data", eliminationPossible=True, eliminationCode="I alt", totalFirst=True
        )
        assert order_values(dim, KURATERT) == KURATERT

    def test_total_first_without_elimination_code_raises(self):
        with pytest.raises(ValueError, match="no eliminationCode"):
            order_values(_dimension(totalFirst=True), KURATERT)

    def test_total_first_with_absent_elimination_code_raises(self):
        # A total that is not in the data would silently do nothing; that is a
        # declaration error, not a shrug.
        dim = _dimension(eliminationPossible=True, eliminationCode="Totalt", totalFirst=True)
        with pytest.raises(ValueError, match="not among the values"):
            order_values(dim, KURATERT)

    def test_elimination_code_alone_does_not_reorder(self):
        # Existing files declare eliminationCode without asking for a new order;
        # they must be unaffected until they opt in.
        dim = _dimension(eliminationPossible=True, eliminationCode="I alt")
        assert order_values(dim, KURATERT) == sorted(KURATERT)


class TestRejectsGarbage:
    def test_unknown_value_order_is_rejected_by_the_model(self):
        with pytest.raises(ValueError):
            _dimension(valueOrder="curated")
