"""Close-code mirror must match the app's authoritative enum values.

Source of truth: ``shifter/cyberscript/enums.py`` ``WebSocketCloseCode``. The
harness mirrors the values rather than importing the Django app (it runs as a
standalone client); this test guards the mirror from drifting.
"""

from event_load_harness.closecodes import CloseCode, close_code_label


def test_values_match_app_enum():
    # Mirrored verbatim from shifter/cyberscript/enums.py::WebSocketCloseCode.
    assert CloseCode.NORMAL == 1000
    assert CloseCode.NOT_AUTHENTICATED == 4001
    assert CloseCode.PERMISSION_DENIED == 4003
    assert CloseCode.NOT_FOUND == 4004
    assert CloseCode.INVALID_REQUEST == 4005
    assert CloseCode.SERVER_ERROR == 4500
    assert CloseCode.SSH_CONNECTION_FAILED == 4502
    assert CloseCode.SERVICE_UNAVAILABLE == 4503


def test_label_known_code():
    assert close_code_label(4503) == "SERVICE_UNAVAILABLE"
    assert close_code_label(1000) == "NORMAL"


def test_label_unknown_code_is_stable_and_low_cardinality():
    # Unknown codes collapse to a single bucket so the histogram stays
    # low-cardinality and never leaks an unexpected integer as a label.
    assert close_code_label(4999) == "OTHER"
    assert close_code_label(None) == "NONE"
