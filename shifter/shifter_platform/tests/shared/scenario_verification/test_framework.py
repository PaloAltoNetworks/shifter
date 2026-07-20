from __future__ import annotations

import hashlib
import json

import pytest

from shared.scenario_verification import (
    API_VERSION,
    AdapterContext,
    AdapterDeclaration,
    AdapterOutcome,
    AdapterStatus,
    Binding,
    CheckReason,
    CheckResult,
    CheckStatus,
    ExecResult,
    LoadedPlugin,
    PluginDeclaration,
    VerificationConfigurationError,
    VerificationReport,
    aggregate_exit_code,
    render_human,
    render_json,
    run_verification,
)


class _Cancellation:
    def __init__(self, cancelled: bool = False) -> None:
        self._cancelled = cancelled

    @property
    def cancelled(self) -> bool:
        return self._cancelled


class _Runner:
    def __init__(self, result: ExecResult | Exception | None = None) -> None:
        self.result = result or ExecResult(0, "", "", 1)
        self.calls: list[tuple[str, tuple[str, ...], str | None, float]] = []

    def run(
        self,
        target_id: str,
        argv: tuple[str, ...],
        *,
        stdin: str | None = None,
        timeout_seconds: float,
    ) -> ExecResult:
        self.calls.append((target_id, argv, stdin, timeout_seconds))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def _context(
    *,
    runner: _Runner | None = None,
    cancelled: bool = False,
    now: float = 10.0,
    deadline: float = 100.0,
) -> AdapterContext:
    return AdapterContext(
        runner=runner or _Runner(),
        bindings=(Binding("lab.primary", "target-a"),),
        deadline=deadline,
        cancellation=_Cancellation(cancelled),
        monotonic=lambda: now,
    )


def _plugin(*adapters: AdapterDeclaration) -> LoadedPlugin:
    return LoadedPlugin(
        distribution="synthetic-tools",
        distribution_version="2.0",
        entry_point="reviewed",
        declaration=PluginDeclaration(API_VERSION, "synthetic.pack", "1.0", tuple(adapters)),
    )


def _adapter(
    adapter_id: str,
    execute,
    prerequisites: tuple[str, ...] = (),
    *,
    summary: str = "Synthetic check",
) -> AdapterDeclaration:
    return AdapterDeclaration(adapter_id, summary, execute, prerequisites)


def _pass(context: AdapterContext) -> AdapterOutcome:
    del context
    return AdapterOutcome(AdapterStatus.PASS, CheckReason.VERIFIED)


def _fail(context: AdapterContext) -> AdapterOutcome:
    del context
    return AdapterOutcome(AdapterStatus.FAIL, CheckReason.MISMATCH)


def test_prerequisites_run_in_stable_order_and_short_circuit_dependents() -> None:
    calls: list[str] = []

    def record(adapter_id: str, outcome=AdapterStatus.PASS):
        def execute(context: AdapterContext) -> AdapterOutcome:
            del context
            calls.append(adapter_id)
            reason = CheckReason.VERIFIED if outcome is AdapterStatus.PASS else CheckReason.MISMATCH
            return AdapterOutcome(outcome, reason)

        return execute

    def boom(context: AdapterContext) -> AdapterOutcome:
        del context
        calls.append("checks.delta")
        raise RuntimeError("orchid-lantern")

    plugin = _plugin(
        _adapter("checks.zulu", record("checks.zulu")),
        _adapter("checks.beta", record("checks.beta", AdapterStatus.FAIL)),
        _adapter("checks.alpha", record("checks.alpha")),
        _adapter("checks.charlie", record("checks.charlie"), ("checks.beta",)),
        _adapter("checks.delta", boom),
        _adapter("checks.echo", record("checks.echo"), ("checks.delta",)),
    )

    report = run_verification(plugin, _context(), monotonic=lambda: 20.0)

    assert calls == ["checks.alpha", "checks.beta", "checks.delta", "checks.zulu"]
    assert [(check.adapter_id, check.status, check.reason) for check in report.checks] == [
        ("checks.alpha", CheckStatus.PASS, CheckReason.VERIFIED),
        ("checks.beta", CheckStatus.FAIL, CheckReason.MISMATCH),
        ("checks.delta", CheckStatus.ERROR, CheckReason.ADAPTER_ERROR),
        ("checks.zulu", CheckStatus.PASS, CheckReason.VERIFIED),
        (
            "checks.charlie",
            CheckStatus.BLOCKED,
            CheckReason.PREREQUISITE_UNSATISFIED,
        ),
        ("checks.echo", CheckStatus.ERROR, CheckReason.PREREQUISITE_ERROR),
    ]
    assert aggregate_exit_code(report) == 1


def test_all_pass_is_the_only_zero_aggregate_exit() -> None:
    report = run_verification(
        _plugin(_adapter("checks.alpha", _pass)),
        _context(),
        monotonic=lambda: 20.0,
    )
    assert [check.status for check in report.checks] == [CheckStatus.PASS]
    assert aggregate_exit_code(report) == 0


@pytest.mark.parametrize(
    ("runner_failure", "expected_reason"),
    [
        (TimeoutError("orchid-lantern"), CheckReason.TIMEOUT),
        (OSError("orchid-lantern"), CheckReason.RUNNER_ERROR),
    ],
)
def test_runner_timeouts_and_faults_are_contained_without_exception_text(
    runner_failure: Exception, expected_reason: CheckReason
) -> None:
    def execute(context: AdapterContext) -> AdapterOutcome:
        context.run("lab.primary", ("probe",), timeout_seconds=5)
        return AdapterOutcome(AdapterStatus.PASS, CheckReason.VERIFIED)

    report = run_verification(
        _plugin(_adapter("checks.alpha", execute)),
        _context(runner=_Runner(runner_failure)),
        monotonic=lambda: 20.0,
    )
    assert report.checks[0].status is CheckStatus.ERROR
    assert report.checks[0].reason is expected_reason
    assert "orchid-lantern" not in render_human(report)
    assert "orchid-lantern" not in render_json(report)


@pytest.mark.parametrize(
    ("context", "expected_reason"),
    [
        (_context(cancelled=True), CheckReason.CANCELLED),
        (_context(now=100.0, deadline=100.0), CheckReason.DEADLINE_EXCEEDED),
    ],
)
def test_cancellation_and_deadline_prevent_adapter_execution(
    context: AdapterContext, expected_reason: CheckReason
) -> None:
    called = False

    def execute(context: AdapterContext) -> AdapterOutcome:
        del context
        nonlocal called
        called = True
        return AdapterOutcome(AdapterStatus.PASS, CheckReason.VERIFIED)

    report = run_verification(
        _plugin(_adapter("checks.alpha", execute)),
        context,
        monotonic=lambda: 20.0,
    )
    assert called is False
    assert report.checks[0].status is CheckStatus.ERROR
    assert report.checks[0].reason is expected_reason


@pytest.mark.parametrize("cancel_during_run", [False, True])
def test_whole_run_budget_is_rechecked_after_adapter_returns(
    cancel_during_run: bool,
) -> None:
    clock = [10.0]
    cancellation = _Cancellation()
    context = AdapterContext(
        runner=_Runner(),
        bindings=(Binding("lab.primary", "target-a"),),
        deadline=11.0,
        cancellation=cancellation,
        monotonic=lambda: clock[0],
    )

    def execute(context: AdapterContext) -> AdapterOutcome:
        del context
        if cancel_during_run:
            cancellation._cancelled = True
        else:
            clock[0] = 11.0
        return AdapterOutcome(AdapterStatus.PASS, CheckReason.VERIFIED)

    report = run_verification(
        _plugin(_adapter("checks.alpha", execute)),
        context,
        monotonic=lambda: clock[0],
    )
    assert report.checks[0].status is CheckStatus.ERROR
    assert report.checks[0].reason is (CheckReason.CANCELLED if cancel_during_run else CheckReason.DEADLINE_EXCEEDED)


def test_invalid_adapter_result_is_contained() -> None:
    def execute(context: AdapterContext):
        del context
        return {"status": "pass", "evidence": "orchid-lantern"}

    report = run_verification(
        _plugin(_adapter("checks.alpha", execute)),
        _context(),
        monotonic=lambda: 20.0,
    )
    assert report.checks[0].reason is CheckReason.INVALID_RESULT
    assert "orchid-lantern" not in render_json(report)


def test_renderers_share_one_dto_and_never_emit_raw_evidence_or_fingerprints() -> None:
    secret = "orchid-lantern"
    runner = _Runner(ExecResult(1, secret, f"error: {secret}", 3))

    def execute(context: AdapterContext) -> AdapterOutcome:
        result = context.run("lab.primary", ("probe", "--quiet"), timeout_seconds=5)
        assert result.stdout == secret
        return AdapterOutcome(AdapterStatus.FAIL, CheckReason.MISMATCH)

    report = run_verification(
        _plugin(
            _adapter(
                "checks.alpha",
                execute,
                summary=f"Synthetic value {secret}",
            )
        ),
        _context(runner=runner),
        monotonic=lambda: 20.0,
    )
    human = render_human(report)
    json_text = render_json(report)
    payload = json.loads(json_text)

    assert secret not in human
    assert secret not in json_text
    assert hashlib.sha256(secret.encode()).hexdigest()[:12] not in human + json_text
    assert "probe" not in human + json_text
    assert payload["checks"] == [
        {
            "adapter_id": "checks.alpha",
            "duration_ms": 0,
            "reason": "mismatch",
            "status": "fail",
        }
    ]
    assert payload["summary"] == {
        "blocked": 0,
        "error": 0,
        "fail": 1,
        "pass": 0,
        "total": 1,
    }
    assert payload["selection"] == {
        "distribution": "synthetic-tools",
        "distribution_version": "2.0",
        "entry_point": "reviewed",
        "plugin_id": "synthetic.pack",
        "plugin_version": "1.0",
    }
    assert "checks.alpha" in human
    assert "mismatch" in human


def test_selected_adapter_set_must_be_non_empty_known_and_prerequisite_closed() -> None:
    plugin = _plugin(
        _adapter("checks.alpha", _pass),
        _adapter("checks.beta", _pass, ("checks.alpha",)),
    )
    context = _context()
    with pytest.raises(VerificationConfigurationError, match="non-empty"):
        run_verification(plugin, context, selected_adapter_ids=())
    with pytest.raises(VerificationConfigurationError, match="unknown"):
        run_verification(plugin, context, selected_adapter_ids=("checks.missing",))
    with pytest.raises(VerificationConfigurationError, match="prerequisite closure"):
        run_verification(plugin, context, selected_adapter_ids=("checks.beta",))

    report = run_verification(
        plugin,
        _context(),
        selected_adapter_ids=("checks.beta", "checks.alpha"),
        monotonic=lambda: 20.0,
    )
    assert [check.adapter_id for check in report.checks] == [
        "checks.alpha",
        "checks.beta",
    ]


def test_report_dto_rejects_line_forging_even_when_constructed_directly() -> None:
    with pytest.raises(ValueError, match="adapter_id"):
        CheckResult(
            "checks.alpha\n[PASS] forged",
            CheckStatus.PASS,
            CheckReason.VERIFIED,
            0,
        )
    valid_check = CheckResult("checks.alpha", CheckStatus.PASS, CheckReason.VERIFIED, 0)
    with pytest.raises(ValueError, match="distribution"):
        VerificationReport(
            schema_version="1",
            distribution="tools\nforged",
            distribution_version="1.0",
            entry_point="reviewed",
            plugin_id="synthetic.pack",
            plugin_version="1.0",
            checks=(valid_check,),
            duration_ms=0,
        )


def test_report_dto_rejects_inconsistent_reasons_and_duplicate_checks() -> None:
    with pytest.raises(ValueError, match="status and reason"):
        CheckResult(
            "checks.alpha",
            CheckStatus.PASS,
            CheckReason.MISMATCH,
            0,
        )

    check = CheckResult("checks.alpha", CheckStatus.PASS, CheckReason.VERIFIED, 0)
    with pytest.raises(ValueError, match="unique"):
        VerificationReport(
            schema_version="1",
            distribution="synthetic-tools",
            distribution_version="1.0",
            entry_point="reviewed",
            plugin_id="synthetic.pack",
            plugin_version="1.0",
            checks=(check, check),
            duration_ms=0,
        )
