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
    is_polaris_agent_role,
    parse_assumed_role_name,
    parse_record,
    write_report,
)

HEALTHY_AGENT_ARN = "arn:aws:sts::123456789012:assumed-role/shifter-dev-range-42-polaris-agent/dev-range-42"


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
        "caller_identity_arn": HEALTHY_AGENT_ARN,
        "docker_user_imds_rule": "1",
        "imds_status": "000",
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


class ParseAssumedRoleNameTests(unittest.TestCase):
    def test_extracts_role_name_from_assumed_role_arn(self) -> None:
        self.assertEqual(
            parse_assumed_role_name(HEALTHY_AGENT_ARN),
            "shifter-dev-range-42-polaris-agent",
        )

    def test_returns_none_for_role_arn_that_is_not_assumed(self) -> None:
        arn = "arn:aws:iam::123456789012:role/shifter-dev-range-instance"
        self.assertIsNone(parse_assumed_role_name(arn))

    def test_returns_none_for_empty_or_sentinel_values(self) -> None:
        self.assertIsNone(parse_assumed_role_name(""))
        self.assertIsNone(parse_assumed_role_name("none"))


class IsPolarisAgentRoleTests(unittest.TestCase):
    def test_true_for_role_name_ending_in_agent_suffix(self) -> None:
        self.assertTrue(is_polaris_agent_role("shifter-dev-range-42-polaris-agent"))

    def test_true_for_hash_truncated_role_name(self) -> None:
        # iam.tf truncates the range-id/environment portion for the 64-char
        # IAM name limit but always appends the literal "-polaris-agent"
        # suffix after the hash, so the suffix check is truncation-proof.
        self.assertTrue(is_polaris_agent_role("shifter-prod-abc123de-polaris-agent"))

    def test_false_for_host_instance_role(self) -> None:
        self.assertFalse(is_polaris_agent_role("shifter-dev-range-instance"))

    def test_false_for_none_or_empty(self) -> None:
        self.assertFalse(is_polaris_agent_role(None))
        self.assertFalse(is_polaris_agent_role(""))


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


class AgentIdentityIssueTests(unittest.TestCase):
    """RangeReport must prove a14-kali's identity is the per-range STS
    agent role (#1377), not merely that a Bedrock profile file exists."""

    def test_healthy_agent_identity_has_no_issue(self) -> None:
        report = RangeReport(instance_id="i-a", range_id="1", user_id="u", fields=_healthy_fields())

        self.assertEqual(report.issues(), [])

    def test_missing_caller_identity_flagged(self) -> None:
        fields = _healthy_fields()
        fields["caller_identity_arn"] = "none"
        report = RangeReport(instance_id="i-a", range_id="1", user_id="u", fields=fields)

        issues = report.issues()
        self.assertTrue(any("no assumed-role identity" in i for i in issues), issues)

    def test_host_instance_role_identity_flagged(self) -> None:
        # Simulates the exact regression #1377 fixes: a14-kali resolving to
        # the shared host operations role instead of its own scoped agent role.
        fields = _healthy_fields()
        fields["caller_identity_arn"] = (
            "arn:aws:sts::123456789012:assumed-role/shifter-dev-range-instance/i-0123456789abcdef0"
        )
        report = RangeReport(instance_id="i-a", range_id="1", user_id="u", fields=fields)

        issues = report.issues()
        self.assertTrue(any("not the per-range agent role" in i for i in issues), issues)

    def test_non_assumed_role_identity_flagged(self) -> None:
        fields = _healthy_fields()
        fields["caller_identity_arn"] = "arn:aws:iam::123456789012:user/some-user"
        report = RangeReport(instance_id="i-a", range_id="1", user_id="u", fields=fields)

        issues = report.issues()
        self.assertTrue(any("not an assumed role" in i for i in issues), issues)

    def test_identity_check_skipped_when_a14_not_running(self) -> None:
        fields = _healthy_fields()
        fields["a14_state"] = "exited"
        fields["caller_identity_arn"] = "none"
        report = RangeReport(instance_id="i-a", range_id="1", user_id="u", fields=fields)

        issues = report.issues()
        self.assertIn("a14-kali=exited", issues)
        self.assertFalse(any("assumed" in i or "agent role" in i for i in issues), issues)


class DockerUserImdsRuleIssueTests(unittest.TestCase):
    def test_missing_rule_flagged(self) -> None:
        fields = _healthy_fields()
        fields["docker_user_imds_rule"] = "0"
        report = RangeReport(instance_id="i-a", range_id="1", user_id="u", fields=fields)

        self.assertIn(
            "DOCKER-USER IMDS drop rule for 169.254.169.254 is missing",
            report.issues(),
        )

    def test_present_rule_not_flagged(self) -> None:
        report = RangeReport(instance_id="i-a", range_id="1", user_id="u", fields=_healthy_fields())

        self.assertEqual(report.issues(), [])


class ImdsReachabilityIssueTests(unittest.TestCase):
    def test_reachable_imds_flagged(self) -> None:
        fields = _healthy_fields()
        fields["imds_status"] = "200"
        report = RangeReport(instance_id="i-a", range_id="1", user_id="u", fields=fields)

        issues = report.issues()
        self.assertTrue(any("IMDS reachable" in i for i in issues), issues)

    def test_imdsv2_non_2xx_response_flagged_as_reachable(self) -> None:
        # #1377 codex fix: a reachable IMDSv2 endpoint answers the token PUT (or a
        # tokenless request) with a non-2xx code such as 401/403 while still
        # letting a participant obtain a token. Any HTTP response means the packet
        # reached the metadata service, so it MUST be flagged -- the old
        # startswith("2") check was a false negative that hid firewall failure.
        for status in ("401", "403", "200"):
            with self.subTest(status=status):
                fields = _healthy_fields()
                fields["imds_status"] = status
                report = RangeReport(instance_id="i-a", range_id="1", user_id="u", fields=fields)
                issues = report.issues()
                self.assertTrue(any("IMDS reachable" in i for i in issues), issues)

    def test_denied_imds_not_flagged(self) -> None:
        fields = _healthy_fields()
        fields["imds_status"] = "000"
        report = RangeReport(instance_id="i-a", range_id="1", user_id="u", fields=fields)

        self.assertEqual(report.issues(), [])

    def test_imds_check_skipped_when_a14_not_running(self) -> None:
        fields = _healthy_fields()
        fields["a14_state"] = "exited"
        fields["imds_status"] = "200"
        report = RangeReport(instance_id="i-a", range_id="1", user_id="u", fields=fields)

        issues = report.issues()
        self.assertFalse(any("IMDS reachable" in i for i in issues), issues)


class StaticAccessKeyIssueTests(unittest.TestCase):
    """The preflight explicitly flags "no static key" as insufficient on its
    own, but that does not mean it stops adding value once the agent-role
    identity check exists too -- a leaked static key would be a standing
    credential distinct from the short-lived STS session."""

    def test_static_key_present_flagged(self) -> None:
        fields = _healthy_fields()
        fields["env_AWS_ACCESS_KEY_ID"] = "1"
        report = RangeReport(instance_id="i-a", range_id="1", user_id="u", fields=fields)

        issues = report.issues()
        self.assertTrue(any("AWS_ACCESS_KEY_ID" in i for i in issues), issues)

    def test_no_static_key_not_flagged(self) -> None:
        report = RangeReport(instance_id="i-a", range_id="1", user_id="u", fields=_healthy_fields())

        self.assertEqual(report.issues(), [])


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
