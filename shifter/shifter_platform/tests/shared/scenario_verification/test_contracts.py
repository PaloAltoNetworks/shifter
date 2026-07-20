from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from shared.scenario_verification import (
    API_VERSION,
    ENTRY_POINT_GROUP,
    MAX_OUTPUT_BYTES,
    REPORT_SCHEMA_VERSION,
    AdapterContext,
    AdapterDeclaration,
    AdapterOutcome,
    AdapterStatus,
    Binding,
    CancellationToken,
    CheckReason,
    ExecResult,
    PluginDeclaration,
    Runner,
    equal_without_disclosure,
)


class _Runner:
    def run(
        self,
        target_id: str,
        argv: tuple[str, ...],
        *,
        stdin: str | None = None,
        timeout_seconds: float,
    ) -> ExecResult:
        return ExecResult(exit_code=0, stdout="ok", stderr="", duration_ms=1)


class _Cancellation:
    @property
    def cancelled(self) -> bool:
        return False


def _execute(context: AdapterContext) -> AdapterOutcome:
    del context
    return AdapterOutcome(AdapterStatus.PASS, CheckReason.VERIFIED)


def test_public_contract_is_versioned_frozen_and_runtime_checkable() -> None:
    assert ENTRY_POINT_GROUP == "shifter.scenario_verification.adapters"
    assert API_VERSION == "1"
    assert REPORT_SCHEMA_VERSION == "1"
    assert isinstance(_Runner(), Runner)
    assert isinstance(_Cancellation(), CancellationToken)

    declaration = AdapterDeclaration(
        adapter_id="checks.alpha",
        summary="Synthetic availability check",
        execute=_execute,
    )
    plugin = PluginDeclaration(
        api_version=API_VERSION,
        plugin_id="synthetic.pack",
        plugin_version="1.2.3",
        adapters=(declaration,),
    )
    with pytest.raises(FrozenInstanceError):
        plugin.plugin_id = "changed"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("factory", "message"),
    [
        (
            lambda: AdapterDeclaration(adapter_id="forge\nresult", summary="ok", execute=_execute),
            "adapter_id",
        ),
        (
            lambda: AdapterDeclaration(adapter_id="checks.alpha", summary="x" * 201, execute=_execute),
            "summary",
        ),
        (
            lambda: Binding(name="not-namespaced", target_id="target-a"),
            "binding name",
        ),
        (
            lambda: Binding(name="lab.primary", target_id="bad\ntarget"),
            "target_id",
        ),
    ],
)
def test_untrusted_contract_text_is_bounded_and_cannot_forge_output(factory, message: str) -> None:
    with pytest.raises((TypeError, ValueError), match=message):
        factory()


def test_opaque_target_ids_do_not_assume_a_provider_naming_scheme() -> None:
    binding = Binding(name="lab.primary", target_id="Target/01:Primary")
    assert binding.target_id == "Target/01:Primary"


def test_exec_result_rejects_unbounded_or_invalid_output() -> None:
    with pytest.raises(ValueError, match="stdout"):
        ExecResult(
            exit_code=0,
            stdout="x" * (MAX_OUTPUT_BYTES + 1),
            stderr="",
            duration_ms=1,
        )
    with pytest.raises(ValueError, match="duration_ms"):
        ExecResult(exit_code=0, stdout="", stderr="", duration_ms=-1)


def test_context_accepts_only_structured_bounded_commands() -> None:
    runner = _Runner()
    context = AdapterContext(
        runner=runner,
        bindings=(Binding("lab.primary", "target-a"),),
        deadline=100.0,
        monotonic=lambda: 50.0,
        cancellation=_Cancellation(),
    )

    result = context.run("lab.primary", ("status", "--json"), timeout_seconds=10)
    assert result.exit_code == 0
    with pytest.raises(TypeError, match="argv"):
        context.run("lab.primary", "status --json", timeout_seconds=10)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="binding"):
        context.run("lab.missing", ("status",), timeout_seconds=10)
    with pytest.raises(ValueError, match="stdin"):
        context.run("lab.primary", ("status",), stdin="x" * (MAX_OUTPUT_BYTES + 1), timeout_seconds=10)


def test_command_timeout_is_clamped_to_the_remaining_whole_run_budget() -> None:
    calls: list[float] = []

    class RecordingRunner(_Runner):
        def run(self, target_id, argv, *, stdin=None, timeout_seconds):
            calls.append(timeout_seconds)
            return super().run(target_id, argv, stdin=stdin, timeout_seconds=timeout_seconds)

    context = AdapterContext(
        runner=RecordingRunner(),
        bindings=(Binding("lab.primary", "target-a"),),
        deadline=12.5,
        monotonic=lambda: 10.0,
        cancellation=_Cancellation(),
    )
    context.run("lab.primary", ("status",), timeout_seconds=10)
    assert calls == [2.5]


def test_deadline_and_command_timeout_must_be_finite() -> None:
    runner = _Runner()
    bindings = (Binding("lab.primary", "target-a"),)
    cancellation = _Cancellation()
    invalid_deadline = float("inf")
    with pytest.raises(ValueError, match="deadline"):
        AdapterContext(
            runner=runner,
            bindings=bindings,
            deadline=invalid_deadline,
            monotonic=lambda: 10.0,
            cancellation=cancellation,
        )

    context = AdapterContext(
        runner=runner,
        bindings=bindings,
        deadline=20.0,
        monotonic=lambda: 10.0,
        cancellation=cancellation,
    )
    invalid_timeout = float("nan")
    with pytest.raises(ValueError, match="timeout_seconds"):
        context.run("lab.primary", ("status",), timeout_seconds=invalid_timeout)


def test_equality_helper_reveals_only_a_boolean_verdict() -> None:
    secret = "orchid-lantern"
    assert equal_without_disclosure(secret, secret) is True
    assert equal_without_disclosure(secret, "different") is False
    assert equal_without_disclosure("蒼\U0001f52c", "蒼\U0001f52c") is True
    assert equal_without_disclosure("蒼\U0001f52c", "蒼\U0001f9ea") is False
    assert secret not in repr(equal_without_disclosure(secret, secret))
