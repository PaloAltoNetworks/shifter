"""A failed live qualification must still remove resources before returning."""

from uuid import uuid4

import pytest

from preparation.qualification import qualify


def test_failed_scan_still_runs_cleanup_and_records_its_receipt(monkeypatch):
    import preparation.qualification as qualification

    cleaned = []
    records = []

    def failed_scan(*args, **kwargs):
        raise ValueError("scanner rejected input")

    monkeypatch.setattr(qualification, "scan_image", failed_scan)
    monkeypatch.setattr(
        qualification,
        "cleanup_operation",
        lambda api, operation, attempts: (
            cleaned.append(operation)
            or {
                "resources_remaining": [],
            }
        ),
    )
    operation_id = uuid4()
    with pytest.raises(ValueError, match="scanner rejected input"):
        qualify(
            lambda: object(),
            {"operation_id": str(operation_id)},
            {},
            lambda phase, value: records.append((phase, value)),
        )
    assert cleaned == [operation_id]
    assert records[-1] == ("cleanup", {"resources_remaining": []})


def test_build_diagnostic_mode_does_not_claim_an_input_scan(monkeypatch):
    import preparation.qualification as qualification

    records = []
    monkeypatch.setattr(qualification, "scan_image", lambda *a, **k: pytest.fail("input scan was requested"))

    def build(*args):
        raise ValueError("stopped at build")

    monkeypatch.setattr(qualification, "build_image", build)
    monkeypatch.setattr(qualification, "cleanup_operation", lambda *a: {"resources_remaining": []})
    with pytest.raises(ValueError, match="stopped at build"):
        qualify(
            lambda: object(),
            {"operation_id": str(uuid4()), "scanner_image": "image", "scanner_image_id": "1"},
            {},
            lambda phase, value: records.append((phase, value)),
            build_and_output_only=True,
        )
    assert "input" not in [phase for phase, _ in records]
    assert records[-1] == ("cleanup", {"resources_remaining": []})
