"""Scanner failures preserve useful codes without leaking candidate contents."""

from types import SimpleNamespace

from preparation import scan_guest


def test_failed_sanitization_emits_only_a_closed_failure_code(monkeypatch):
    monkeypatch.setattr(
        scan_guest,
        "_raw_disk_module",
        lambda: SimpleNamespace(
            measure_device=lambda device: {"raw_disk_digest": "sha256:" + "a" * 64, "size_bytes": 1024},
        ),
    )

    def fail(raw_disk):
        raise ValueError("candidate retains private metadata script material")

    monkeypatch.setattr(scan_guest, "inspect_output", fail)
    assert scan_guest.scan_observation(verify_output=True) == {"failure_code": "metadata_script_residue"}


def test_unrecognized_scanner_exception_never_becomes_a_diagnostic_value(monkeypatch):
    def fail():
        raise OSError("private path and candidate content")

    monkeypatch.setattr(scan_guest, "_raw_disk_module", fail)
    assert scan_guest.scan_observation(verify_output=False) == {"failure_code": "scanner_failed"}
