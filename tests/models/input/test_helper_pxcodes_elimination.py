"""pxbuild must fail on an eliminationCode that is not among the pxcodes valueitems.

Before this, HelperPxCodes.get_elimination_label() returned "" for an unknown code and
from_pxmetadata_file fell back to ELIMINATION=YES. In PxWeb that means "sum the values
when the variable is eliminated" — including the total row, if the data has one. The
build stayed green (F-92, 09.09.2026). A declaration that names a value which does not
exist is an error, and it should stop the build with the code in the message.
"""
import pytest

from pxbuild.models.input.helper_pxcodes import HelperPxCodes
from pxbuild.models.input.pydantic_pxcodes import PxCodes


def _pxcodes(**overrides) -> PxCodes:
    payload = {
        "id": "bydel",
        "sortValueitemsOn": "code",
        "valueitems": [
            {"code": "0301", "label": {"no": "Oslo i alt"}},
            {"code": "030101", "label": {"no": "Gamle Oslo"}},
        ],
        "eliminationPossible": True,
        "eliminationCode": "0301",
    }
    payload.update(overrides)
    return PxCodes(**payload)


def test_known_elimination_code_resolves_to_its_label():
    helper = HelperPxCodes(_pxcodes(), ["no"])
    assert helper.get_elimination_label("no") == "Oslo i alt"


def test_unknown_elimination_code_raises_with_the_code_and_the_codelist():
    # The F-92 shape: codes lost their leading zero upstream, so "0301" matched nothing.
    with pytest.raises(ValueError, match=r"'0301'.*'bydel'"):
        HelperPxCodes(_pxcodes(valueitems=[{"code": "301", "label": {"no": "Oslo i alt"}}]), ["no"])


def test_no_elimination_code_is_fine():
    helper = HelperPxCodes(_pxcodes(eliminationPossible=True, eliminationCode=None), ["no"])
    assert helper.get_elimination_label("no") == ""


def test_elimination_not_possible_with_no_code_is_fine():
    HelperPxCodes(_pxcodes(eliminationPossible=False, eliminationCode=None), ["no"])
