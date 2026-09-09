"""An uncoded dimension's eliminationCode must be one of its values.

Sibling of the HelperPxCodes check for coded dimensions. For uncoded dimensions the
keyword is written verbatim from the declaration, so an unknown value builds fine and
only misbehaves in PxWeb. Raise here instead, with the value and the dimension named.
"""
import pytest

from pxbuild.models.input.pydantic_pxmetadata import Dimension
from pxbuild.models.middle.dims import check_elimination_code

VERDIER = ["I alt", "Arbeid, heltid", "Arbeid, deltid"]


def _dimension(**overrides) -> Dimension:
    payload = {"columnName": "arbeidsstyrkestatus", "label": {"no": "arbeidsstyrkestatus"}}
    payload.update(overrides)
    return Dimension(**payload)


def test_known_value_passes():
    check_elimination_code(_dimension(eliminationPossible=True, eliminationCode="I alt"), VERDIER)


def test_no_elimination_code_passes():
    check_elimination_code(_dimension(), VERDIER)


def test_unknown_value_raises_naming_value_and_dimension():
    dim = _dimension(code="arbstat", eliminationPossible=True, eliminationCode="Totalt")
    with pytest.raises(ValueError, match=r"'Totalt'.*arbstat"):
        check_elimination_code(dim, VERDIER)
