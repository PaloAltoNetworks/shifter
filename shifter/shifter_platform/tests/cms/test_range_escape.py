"""Runner, inventory, and probe-parsing tests for the escape-validation suite (#1347).

These drive the scenario-neutral core through a fake probe launcher (no cloud, no
SSH): one-range and multi-range report shape, the two-or-more-range peer gate, two
materially different range compositions passing the same core suite, egress-policy
interpretation, metadata credential classification, and probe-record parsing.
"""

from __future__ import annotations

from collections.abc import Sequence

from cms.range_escape.inventory import build_management_ingress_targets, build_subject_targets
from cms.range_escape.model import (
    EgressPolicy,
    ObservedProbe,
    ParticipantContext,
    PlatformInventory,
    ProbeOutcome,
    ProbeTarget,
    RangeUnderTest,
)
from cms.range_escape.probe import parse_probe_record
from cms.range_escape.runner import RunOptions, run_escape_validation
from shared.range_escape import BoundaryCode, CheckStatus, Outcome, SuiteMode, Verdict


class FakeLauncher:
    """A probe launcher that returns canned observations per participant.

    ``records`` maps a participant's range_id to a callable that, given the
    targets, returns the observation record. By default every target is observed
    as the secure outcome (unreachable / not resolved / metadata useless).
    """

    def __init__(self, overrides: dict[str, ObservedProbe] | None = None) -> None:
        self.overrides = overrides or {}
        self.launched: list[tuple[int, tuple[str, ...]]] = []

    def launch(
        self, participant: ParticipantContext, targets: Sequence[ProbeTarget], *, per_target_timeout_s: int = 4
    ) -> dict[str, ObservedProbe]:
        self.launched.append((participant.range_id, tuple(t.check_id for t in targets)))
        record: dict[str, ObservedProbe] = {}
        for target in targets:
            record[target.check_id] = self.overrides.get(target.check_id, _secure_observation(target))
        return record


def _secure_observation(target: ProbeTarget) -> ObservedProbe:
    # The positive control and any approved-reachable target must be observed
    # reachable; every should-be-unreachable boundary must be observed blocked
    # (a silent drop), which is the only secure outcome.
    if target.expected == Outcome.REACHABLE:
        return ObservedProbe(outcome=ProbeOutcome.REACHABLE, detail="reachable as expected")
    return ObservedProbe(outcome=ProbeOutcome.BLOCKED, detail="blocked")


def _participant(range_id: int, address: str) -> ParticipantContext:
    return ParticipantContext(
        range_id=range_id,
        request_id=f"req-{range_id}",
        target_ref="linux-uuid",
        address=address,
        ssh_port=22,
        credential_ref=f"secret://ssh/{range_id}",
    )


def _range(range_id: int, *, subnet: str, member: str) -> RangeUnderTest:
    return RangeUnderTest(
        range_id=range_id,
        request_id=f"req-{range_id}",
        subnet_cidrs=(subnet,),
        member_ips=(member,),
        participant=_participant(range_id, member),
        dns_names=(f"vm-{range_id}.zone-a.c.proj.internal",),
    )


def _platform() -> PlatformInventory:
    return PlatformInventory(
        pod_cidr="10.4.0.0/14",
        service_cidr="10.8.0.0/20",
        node_cidr="10.128.0.0/20",
        portal_private_endpoints=("10.128.0.10:5432",),
        gke_gdc_api_endpoint="10.128.0.2",
        private_dns_names=("kubernetes.default.svc",),
    )


def _deny_egress() -> EgressPolicy:
    return EgressPolicy(mode="deny-all", canaries=("198.51.100.10",))


def _clock() -> tuple[str, str]:
    return "2026-07-14T00:00:00Z", "2026-07-14T00:02:00Z"


def _options(started: str, ended: str, suite_id: str = "s1") -> RunOptions:
    return RunOptions(suite_id=suite_id, started_at=started, ended_at=ended)


class TestRunnerOneRange:
    def test_one_range_all_secure_passes(self) -> None:
        started, ended = _clock()
        report = run_escape_validation(
            subject=_range(1, subnet="10.50.1.0/28", member="10.50.1.4"),
            peers=(),
            platform=_platform(),
            egress=_deny_egress(),
            launcher=FakeLauncher(),
            options=_options(started, ended),
        )
        assert report.mode is SuiteMode.ONE_RANGE
        assert report.verdict is Verdict.PASSED

    def test_one_range_marks_peer_boundaries_not_applicable(self) -> None:
        started, ended = _clock()
        report = run_escape_validation(
            subject=_range(1, subnet="10.50.1.0/28", member="10.50.1.4"),
            peers=(),
            platform=_platform(),
            egress=_deny_egress(),
            launcher=FakeLauncher(),
            options=_options(started, ended),
        )
        peer_checks = {
            c.boundary_code: c for c in report.checks if c.boundary_code == BoundaryCode.CROSS_RANGE_PRIVATE_IP
        }
        assert peer_checks
        assert all(c.status is CheckStatus.NOT_APPLICABLE for c in peer_checks.values())

    def test_metadata_reachable_with_useful_creds_fails(self) -> None:
        started, ended = _clock()
        launcher = FakeLauncher()
        # Find the metadata check id by building the same targets the runner will.
        targets = build_subject_targets(
            subject=_range(1, subnet="10.50.1.0/28", member="10.50.1.4"),
            peers=(),
            platform=_platform(),
            egress=_deny_egress(),
        )
        metadata_id = next(t.check_id for t in targets if t.boundary_code == BoundaryCode.METADATA_SERVER)
        launcher.overrides[metadata_id] = ObservedProbe(
            outcome=ProbeOutcome.REACHABLE, detail="token returned", metadata_credentials_useful=True
        )
        report = run_escape_validation(
            subject=_range(1, subnet="10.50.1.0/28", member="10.50.1.4"),
            peers=(),
            platform=_platform(),
            egress=_deny_egress(),
            launcher=launcher,
            options=_options(started, ended),
        )
        assert report.verdict is Verdict.FAILED
        metadata_check = next(c for c in report.checks if c.boundary_code == BoundaryCode.METADATA_SERVER)
        assert metadata_check.status is CheckStatus.FAIL

    def test_platform_pod_reachable_fails_with_exact_boundary(self) -> None:
        started, ended = _clock()
        launcher = FakeLauncher()
        targets = build_subject_targets(
            subject=_range(1, subnet="10.50.1.0/28", member="10.50.1.4"),
            peers=(),
            platform=_platform(),
            egress=_deny_egress(),
        )
        pod_id = next(t.check_id for t in targets if t.boundary_code == BoundaryCode.PLATFORM_POD_CIDR)
        launcher.overrides[pod_id] = ObservedProbe(outcome=ProbeOutcome.REACHABLE, detail="connected")
        report = run_escape_validation(
            subject=_range(1, subnet="10.50.1.0/28", member="10.50.1.4"),
            peers=(),
            platform=_platform(),
            egress=_deny_egress(),
            launcher=launcher,
            options=_options(started, ended),
        )
        failed = [c for c in report.checks if c.status is CheckStatus.FAIL]
        assert [c.boundary_code for c in failed] == [BoundaryCode.PLATFORM_POD_CIDR]


class TestRunnerMultiRange:
    def test_multi_range_all_secure_passes(self) -> None:
        started, ended = _clock()
        report = run_escape_validation(
            subject=_range(1, subnet="10.50.1.0/28", member="10.50.1.4"),
            peers=(_range(2, subnet="10.50.2.0/28", member="10.50.2.4"),),
            platform=_platform(),
            egress=_deny_egress(),
            launcher=FakeLauncher(),
            options=_options(started, ended),
        )
        assert report.mode is SuiteMode.MULTI_RANGE
        assert report.verdict is Verdict.PASSED
        assert report.peer_range_ids == [2]

    def test_multi_range_cross_range_reachable_fails(self) -> None:
        started, ended = _clock()
        subject = _range(1, subnet="10.50.1.0/28", member="10.50.1.4")
        peer = _range(2, subnet="10.50.2.0/28", member="10.50.2.4")
        launcher = FakeLauncher()
        targets = build_subject_targets(subject=subject, peers=(peer,), platform=_platform(), egress=_deny_egress())
        xrange_id = next(t.check_id for t in targets if t.boundary_code == BoundaryCode.CROSS_RANGE_PRIVATE_IP)
        launcher.overrides[xrange_id] = ObservedProbe(outcome=ProbeOutcome.REACHABLE, detail="peer reachable")
        report = run_escape_validation(
            subject=subject,
            peers=(peer,),
            platform=_platform(),
            egress=_deny_egress(),
            launcher=launcher,
            options=_options(started, ended),
        )
        assert report.verdict is Verdict.FAILED

    def test_multi_range_launches_management_probe_from_peer(self) -> None:
        started, ended = _clock()
        subject = _range(1, subnet="10.50.1.0/28", member="10.50.1.4")
        peer = _range(2, subnet="10.50.2.0/28", member="10.50.2.4")
        launcher = FakeLauncher()
        run_escape_validation(
            subject=subject,
            peers=(peer,),
            platform=_platform(),
            egress=_deny_egress(),
            launcher=launcher,
            options=_options(started, ended),
        )
        launched_range_ids = {rid for rid, _ in launcher.launched}
        assert launched_range_ids == {1, 2}


class TestScenarioNeutrality:
    def test_two_different_compositions_pass_same_core(self) -> None:
        started, ended = _clock()
        # Composition A: single small subnet. Composition B: different CIDRs and
        # multiple members. The core suite must pass both with no branching.
        comp_a = RangeUnderTest(
            range_id=10,
            request_id="req-10",
            subnet_cidrs=("10.60.1.0/28",),
            member_ips=("10.60.1.4",),
            participant=_participant(10, "10.60.1.4"),
        )
        comp_b = RangeUnderTest(
            range_id=11,
            request_id="req-11",
            subnet_cidrs=("172.20.5.0/24", "172.20.6.0/24"),
            member_ips=("172.20.5.10", "172.20.6.10"),
            participant=_participant(11, "172.20.5.10"),
        )
        for comp in (comp_a, comp_b):
            report = run_escape_validation(
                subject=comp,
                peers=(),
                platform=_platform(),
                egress=_deny_egress(),
                launcher=FakeLauncher(),
                options=_options(started, ended, suite_id=f"s-{comp.range_id}"),
            )
            assert report.verdict is Verdict.PASSED


class TestEgressPolicy:
    def test_allowlist_probes_operator_canaries_not_cidr_first_hosts(self) -> None:
        egress = EgressPolicy(
            mode="allowlist",
            allowed_cidrs=("203.0.113.0/24",),
            allowed_canaries=("203.0.113.10",),
            canaries=("198.51.100.10",),
        )
        targets = build_subject_targets(
            subject=_range(1, subnet="10.50.1.0/28", member="10.50.1.4"),
            peers=(),
            platform=_platform(),
            egress=egress,
        )
        egress_targets = [t for t in targets if t.boundary_code == BoundaryCode.INTERNET_EGRESS]
        expected = {t.expected.value for t in egress_targets}
        assert expected == {"reachable", "unreachable"}
        # The declared policy CIDR itself is never probed as a live canary.
        assert all(t.address in {"203.0.113.10", "198.51.100.10"} for t in egress_targets)

    def test_deny_all_expects_unreachable(self) -> None:
        targets = build_subject_targets(
            subject=_range(1, subnet="10.50.1.0/28", member="10.50.1.4"),
            peers=(),
            platform=_platform(),
            egress=_deny_egress(),
        )
        egress_targets = [t for t in targets if t.boundary_code == BoundaryCode.INTERNET_EGRESS]
        assert egress_targets
        assert all(t.expected.value == "unreachable" for t in egress_targets)


class TestCrossRangeDns:
    def test_cross_range_dns_uses_peer_owned_names(self) -> None:
        subject = _range(1, subnet="10.50.1.0/28", member="10.50.1.4")
        peer = RangeUnderTest(
            range_id=2,
            request_id="req-2",
            subnet_cidrs=("10.50.2.0/28",),
            member_ips=("10.50.2.4",),
            participant=_participant(2, "10.50.2.4"),
            dns_names=("peer-vm.zone-a.c.proj.internal",),
        )
        targets = build_subject_targets(subject=subject, peers=(peer,), platform=_platform(), egress=_deny_egress())
        dns_targets = [t for t in targets if t.boundary_code == BoundaryCode.CROSS_RANGE_DNS]
        assert dns_targets
        assert {t.hostname for t in dns_targets} == {"peer-vm.zone-a.c.proj.internal"}
        # The platform's own private DNS name is a separate platform boundary, not
        # a cross-range peer identity.
        platform_dns = [t for t in targets if t.boundary_code == BoundaryCode.PLATFORM_DNS]
        assert {t.hostname for t in platform_dns} == {"kubernetes.default.svc"}


class TestManagementIngressTargets:
    def test_management_targets_point_at_subject_ports_from_peer(self) -> None:
        subject = _range(1, subnet="10.50.1.0/28", member="10.50.1.4")
        peer = _range(2, subnet="10.50.2.0/28", member="10.50.2.4")
        targets = build_management_ingress_targets(subject=subject, peer=peer)
        assert targets
        assert all(t.boundary_code == BoundaryCode.MANAGEMENT_INGRESS for t in targets)
        assert all(t.address == "10.50.1.4" for t in targets)
        assert {t.port for t in targets} == {22, 3389}


class TestProbeParsing:
    def test_parse_probe_record_reads_json_envelope(self) -> None:
        stdout = (
            "noise before\n"
            '__ESCAPE_RECORD__{"c1": {"outcome": "reachable", "detail": "ok"}, '
            '"c2": {"outcome": "blocked", "metadata_credentials_useful": null}, '
            '"c3": {"outcome": "not_a_real_outcome"}}__END__\n'
            "noise after"
        )
        record = parse_probe_record(stdout)
        assert record["c1"].outcome is ProbeOutcome.REACHABLE
        assert record["c2"].outcome is ProbeOutcome.BLOCKED
        assert record["c2"].metadata_credentials_useful is None
        # An unrecognized outcome is coerced to error (never a silent pass).
        assert record["c3"].outcome is ProbeOutcome.ERROR

    def test_parse_probe_record_missing_envelope_is_empty(self) -> None:
        assert parse_probe_record("no envelope here") == {}

    def test_missing_observation_fails_closed(self) -> None:
        started, ended = _clock()

        class EmptyLauncher:
            def launch(
                self, participant: ParticipantContext, targets: Sequence[ProbeTarget], *, per_target_timeout_s: int = 4
            ) -> dict[str, ObservedProbe]:
                return {}

        report = run_escape_validation(
            subject=_range(1, subnet="10.50.1.0/28", member="10.50.1.4"),
            peers=(),
            platform=_platform(),
            egress=_deny_egress(),
            launcher=EmptyLauncher(),
            options=_options(started, ended),
        )
        assert report.verdict is Verdict.FAILED
        assert any(c.status is CheckStatus.FAIL for c in report.checks)
