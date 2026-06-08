"""Tests for the extracted range-health model (issue #691).

Run from this directory:
    python3 -m unittest test_range_health -v
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from range_health import (
    EXPECTED_CONTAINER_COUNT,
    KALI_ENV_KEYS,
    RangeReport,
    Target,
    parse_record,
    write_report,
)


def _healthy_fields() -> dict[str, str]:
    fields = {
        "host": "polaris-vm-1",
        "instance_id": "i-aaa",
        "container_count": str(EXPECTED_CONTAINER_COUNT),
        "exited_containers": "none",
        "a14_state": "running",
        "a14_on_splice": "0",
        "bedrock_profile": "1",
        "hosts_override": "1",
        "splice_watcher": "active",
        "a5_scada_state": "running",
        "a9_splice_state": "running",
        "a0_website_state": "running",
        "env_AWS_ACCESS_KEY_ID": "0",
    }
    for key in KALI_ENV_KEYS:
        fields[f"env_{key}"] = "1"
    return fields


class ParseRecordTests(unittest.TestCase):
    def test_round_trips_pipe_delimited_record(self) -> None:
        stdout = "noise\n__RECORD__host=polaris-vm-1|instance_id=i-aaa|container_count=17__END__\ntrailing"

        record = parse_record(stdout)

        self.assertEqual(
            record,
            {"host": "polaris-vm-1", "instance_id": "i-aaa", "container_count": "17"},
        )

    def test_returns_empty_when_markers_missing(self) -> None:
        self.assertEqual(parse_record("no markers"), {})

    def test_ignores_segments_without_equals(self) -> None:
        # The bash producer is well-formed in practice; the parser tolerates
        # malformed segments rather than crashing the whole run.
        record = parse_record("__RECORD__valid=1|orphan|other=2__END__")

        self.assertEqual(record, {"valid": "1", "other": "2"})


class RangeReportIssueTests(unittest.TestCase):
    def test_healthy_record_has_no_issues(self) -> None:
        report = RangeReport(
            instance_id="i-aaa",
            range_id="42",
            user_id="u-1",
            fields=_healthy_fields(),
        )

        self.assertEqual(report.issues(), [])
        self.assertTrue(report.ok)

    def test_low_container_count_flagged(self) -> None:
        fields = _healthy_fields()
        fields["container_count"] = "18"
        report = RangeReport(instance_id="i-bbb", range_id="7", user_id="u-2", fields=fields)

        issues = report.issues()
        self.assertIn(f"container_count=18/{EXPECTED_CONTAINER_COUNT}", issues)
        self.assertFalse(report.ok)

    def test_kali_off_and_still_on_splice_both_reported(self) -> None:
        fields = _healthy_fields()
        fields["a14_state"] = "exited"
        fields["a14_on_splice"] = "1"
        report = RangeReport(instance_id="i-ccc", range_id="8", user_id="u-3", fields=fields)

        issues = report.issues()
        self.assertIn("a14-kali=exited", issues)
        self.assertIn("a14 still on splice-link (watcher didn't disconnect)", issues)

    def test_missing_bedrock_env_keys_each_reported(self) -> None:
        fields = _healthy_fields()
        for key in KALI_ENV_KEYS:
            fields[f"env_{key}"] = "0"
        report = RangeReport(instance_id="i-ddd", range_id="9", user_id="u-4", fields=fields)

        issues = report.issues()
        for key in KALI_ENV_KEYS:
            self.assertIn(f"missing env {key}", issues)

    def test_splice_watcher_not_active_reported(self) -> None:
        fields = _healthy_fields()
        fields["splice_watcher"] = "inactive"
        report = RangeReport(instance_id="i-eee", range_id="10", user_id="u-5", fields=fields)

        self.assertIn("splice-watcher=inactive", report.issues())

    def test_exited_containers_reported_when_present(self) -> None:
        fields = _healthy_fields()
        fields["exited_containers"] = "a0-website,a5-scada"
        report = RangeReport(instance_id="i-fff", range_id="11", user_id="u-6", fields=fields)

        self.assertIn("exited=[a0-website,a5-scada]", report.issues())


class WriteReportTests(unittest.TestCase):
    def test_renders_summary_and_issues_table(self) -> None:
        healthy_fields = _healthy_fields()
        unhealthy_fields = _healthy_fields()
        unhealthy_fields["splice_watcher"] = "missing"
        targets = [
            Target(instance_id="i-aaa", vpc_id="v", name="r1", range_id="1", user_id="u-1"),
            Target(instance_id="i-bbb", vpc_id="v", name="r2", range_id="2", user_id="u-2"),
        ]
        reports = [
            RangeReport(instance_id="i-aaa", range_id="1", user_id="u-1", fields=healthy_fields),
            RangeReport(instance_id="i-bbb", range_id="2", user_id="u-2", fields=unhealthy_fields),
        ]

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "report.md"
            write_report(targets, reports, out, verbose=True)
            rendered = out.read_text()

        self.assertIn("# Polaris range health report", rendered)
        self.assertIn("Discovered polaris-vm ranges: 2", rendered)
        self.assertIn("Healthy: **1**", rendered)
        self.assertIn("With issues: **1**", rendered)
        self.assertIn("splice-watcher=missing", rendered)
        # verbose mode adds the per-range table.
        self.assertIn("## All ranges", rendered)


if __name__ == "__main__":
    unittest.main()
