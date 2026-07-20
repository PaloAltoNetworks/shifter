# Scenario Verification Plugins

Shifter's scenario-verification package provides a neutral contract for
discovering an installed verification plugin, running its checks through an
injected transport, and rendering one redacted report. Core ships no
per-scenario adapters, answer material, target topology, concrete runner, or
plugin dependency.

Use this surface from a dedicated, least-privilege operator environment. It is
not a Django app, service-startup hook, scenario loader, backend admission gate,
or built-in scenario CLI.

## Public v1 surface

Import public types from `shared.scenario_verification`, not its internal
modules.

| Surface | Public names | Purpose |
| --- | --- | --- |
| Versions and limits | `ENTRY_POINT_GROUP`, `API_VERSION`, `REPORT_SCHEMA_VERSION`, `MAX_OUTPUT_BYTES` | Fix the discovery namespace and version the plugin/report contracts; expose the runner output bound. |
| Plugin metadata | `AdapterDeclaration`, `PluginDeclaration`, `AdapterCallable` | Frozen declarations returned by the selected plugin's zero-argument factory. |
| Adapter execution | `Binding`, `AdapterContext`, `Runner`, `ExecResult`, `CancellationToken` | Namespaced opaque targets and the bounded argv-only transport available to adapter code. |
| Adapter verdicts | `AdapterStatus`, `AdapterOutcome`, `CheckReason`, `equal_without_disclosure` | Limit adapters to pass/fail and compare values without returning or fingerprinting either operand. |
| Framework results | `CheckStatus`, `CheckResult`, `VerificationReport` | Represent the closed pass/fail/blocked/error check results and one immutable aggregate report bound to installed metadata. |
| Discovery | `InstalledPlugin`, `LoadedPlugin`, `PluginSelection`, `discover_plugins`, `load_plugin`, `PluginDiscoveryError` | Enumerate metadata without loading code, then load and bind only the exact reviewed selection. |
| Orchestration and rendering | `run_verification`, `render_human`, `render_json`, `aggregate_exit_code` | Execute deterministically and render/exit from the same aggregate DTO. |
| Failure signals | `RunnerExecutionError`, `VerificationCancelled`, `VerificationDeadlineExceeded`, `VerificationConfigurationError` | Classify runner faults and reject cancellation, budget exhaustion, or unsafe execution configuration without exposing raw messages. |

The dataclasses are frozen. Identifiers and reason codes are bounded lowercase
identifiers; plugin and adapter ids and binding names are namespaced. Summaries
are non-empty, bounded, and rejected if they contain unsafe control or escape
characters.

`API_VERSION` versions the factory/declaration ABI. `REPORT_SCHEMA_VERSION`
versions the JSON evidence shape independently. A plugin with an unsupported
API version fails before any adapter runs.

## Publish a plugin factory

An installed distribution registers exactly one or more factories in the fixed
entry-point group:

```toml
[project.entry-points."shifter.scenario_verification.adapters"]
synthetic = "synthetic_verification:plugin"
```

The referenced callable takes no arguments and returns a
`PluginDeclaration`. This synthetic example deliberately contains no real
scenario id, target, topology, answer, or credential:

```python
from shared.scenario_verification import (
    API_VERSION,
    AdapterContext,
    AdapterDeclaration,
    AdapterOutcome,
    AdapterStatus,
    CheckReason,
    PluginDeclaration,
    equal_without_disclosure,
)


def verify_alpha(context: AdapterContext) -> AdapterOutcome:
    result = context.run(
        "synthetic.primary",
        ("probe", "--format=json"),
        timeout_seconds=10,
    )
    matched = result.exit_code == 0 and equal_without_disclosure(
        result.stdout.strip(),
        expected_value_from_plugin_memory(),
    )
    return AdapterOutcome(
        AdapterStatus.PASS if matched else AdapterStatus.FAIL,
        CheckReason.VERIFIED if matched else CheckReason.MISMATCH,
    )


def plugin() -> PluginDeclaration:
    return PluginDeclaration(
        api_version=API_VERSION,
        plugin_id="synthetic.pack",
        plugin_version="1.0.0",
        adapters=(
            AdapterDeclaration(
                adapter_id="checks.alpha",
                summary="Synthetic availability check",
                execute=verify_alpha,
            ),
        ),
    )
```

The expected value in this example is plugin-owned data kept in memory. It is
never put in a declaration, binding, result summary, exception, log, or report.
`equal_without_disclosure` returns only a boolean and does not create a
deterministic hash.

An adapter may list other adapter ids in `prerequisites`. The framework
validates that every dependency exists, rejects cycles, and executes checks in
stable prerequisite order. Use prerequisites only for runtime conditions that
can be satisfied by another declared check. Do not use them as a backend
capability manifest or a substitute for missing coverage.

## Select installed code explicitly

`discover_plugins()` reads only installed distribution and entry-point
metadata in `ENTRY_POINT_GROUP`; it does not import candidates. Select by exact
distribution name, installed version, and entry-point name:

```python
from shared.scenario_verification import (
    PluginSelection,
    discover_plugins,
    load_plugin,
)

candidates = discover_plugins()
loaded_plugin = load_plugin(
    candidates,
    PluginSelection(
        distribution="synthetic-verification",
        version="1.0.0",
        entry_point="synthetic",
    ),
)
```

The distribution should be reviewed and pinned by version and artifact digest
when the operator environment is built. Installation plus exact selection is
the code-loading authorization boundary. The framework never installs a
package, follows a URL, scans a directory or namespace, changes `sys.path`, or
accepts an arbitrary module path. When exactly one candidate is installed,
`load_plugin(candidates)` may select it; explicit selection is preferred for
repeatable operator evidence.

Discovery, factory, and declaration failures raise `PluginDiscoveryError`.
Diagnostics identify bounded distribution/entry-point metadata and the
exception class where useful, never the raw exception message. These failures
occur before a `VerificationReport` exists; the operator entry point must catch
them and exit non-zero.

## Inject a runner and bindings

The operator owns the concrete `Runner`. Its `run` method receives:

- an opaque `target_id` resolved from a declared binding;
- an argv tuple, never a shell command string;
- optional string stdin;
- an explicit timeout bounded by the remaining whole-run deadline.

It returns a bounded `ExecResult(exit_code, stdout, stderr, duration_ms)`.
`stdout` and `stderr` are available to the selected adapter in memory but are
never report fields. The concrete runner must validate its target namespace,
constrain output before buffering, avoid broad inherited environments, and
terminate or cancel remote work when the run budget expires. It raises
`RunnerExecutionError` for a transport fault and `TimeoutError` for a command
timeout; raw transport messages never enter the report.

Build `Binding` values from operator-controlled non-secret configuration:

```python
from shared.scenario_verification import Binding

bindings = (
    Binding(name="synthetic.primary", target_id="target-a"),
)
```

Bindings map logical names to opaque runner targets. They must not contain
credentials, provider objects, network details for reporting, settings,
environment maps, or scenario answer material. Adapter code calls
`AdapterContext.run(binding_name, argv, stdin=..., timeout_seconds=...)`; it
cannot choose an undeclared target.

## Run and interpret verification

`run_verification(plugin, context, *, selected_adapter_ids=None)` receives the
validated `LoadedPlugin` and an `AdapterContext` that already owns the injected
runner, bindings, whole-run deadline, cancellation signal, and monotonic clock.
The loaded wrapper binds the declaration to the exact installed distribution,
version, and entry point selected during discovery. The call returns one
immutable `VerificationReport`. An explicit selection is a tuple of adapter
ids; it must be non-empty and prerequisite-closed or validation fails before
adapter execution with `VerificationConfigurationError`. The optional
`monotonic` callable exists for deterministic duration tests; production callers
normally omit it.

```python
import time

from shared.scenario_verification import (
    AdapterContext,
    aggregate_exit_code,
    render_human,
    render_json,
    run_verification,
)

context = AdapterContext(
    runner=operator_runner,
    bindings=bindings,
    deadline=time.monotonic() + 300,
    cancellation=operator_cancellation_token,
)
report = run_verification(
    loaded_plugin,
    context,
    selected_adapter_ids=("checks.alpha",),
)
human_output = render_human(report)
json_output = render_json(report)
exit_code = aggregate_exit_code(report)
```

The operator decides where the rendered strings go and exits with `exit_code`.
The framework does not write files or print on the caller's behalf.

Adapters return only:

- `AdapterOutcome(AdapterStatus.PASS, CheckReason.VERIFIED)`; or
- `AdapterOutcome(AdapterStatus.FAIL, CheckReason.MISMATCH)`.

The framework maps execution into the closed report statuses:

| Status | Meaning |
| --- | --- |
| `pass` | The adapter ran and returned the verified verdict. |
| `fail` | The adapter ran and returned the mismatch verdict. |
| `blocked` | A declared prerequisite was unsatisfied, so the dependent adapter did not run. |
| `error` | Prerequisite execution, runner, timeout, cancellation, invalid-result, or adapter execution faulted after selection. |

The closed `CheckReason` values are `verified`, `mismatch`,
`prerequisite_unsatisfied`, `prerequisite_error`, `adapter_error`,
`runner_error`, `timeout`, `cancelled`, `deadline_exceeded`, and
`invalid_result`. Plugins cannot add free-form report reasons.

`blocked` is a non-success result. It is not the status for absent adapter
coverage, an unsupported API version, an admission/realizability failure, or an
exception. Every `fail`, `blocked`, or `error` makes
`aggregate_exit_code(report)` non-zero. Discovery and execution-configuration
exceptions happen before a report and must also produce a non-zero process
exit.

Render operator output only through `render_human(report)` or
`render_json(report)`. Both consume the same DTO, so redaction and status
semantics cannot diverge between formats.

## Report schema and redaction

The JSON report has exactly these top-level fields: `schema_version`,
`selection`, `checks`, `summary`, `duration_ms`, and `exit_code`. `selection`
contains `distribution`, `distribution_version`, `entry_point`, `plugin_id`,
and `plugin_version`, binding the report to both installed metadata and the
factory declaration. Each check contains `adapter_id`, `status`, `reason`, and
`duration_ms`; `summary` contains pass/fail/blocked/error/total counts. Treat
the rendered document as ephemeral operator evidence. The framework does not
persist it or write a database, audit event, or artifact record.

Neither report format includes:

- expected or produced values, flags, credentials, keys, or tokens;
- deterministic value hashes or fingerprints;
- argv, stdin, stdout, stderr, environment values, or raw evidence;
- exception messages or tracebacks;
- internal hostnames, addresses, provider payloads, or deployment settings.

Plugin-authored ids and declaration summaries are untrusted input. The contract
validates and sanitizes them before execution; summaries are not copied into
the report. Do not add a debug/raw-output report mode; inspect sensitive
failures only inside the controlled plugin/runner process.

## Boundaries

Scenario verification observes one realized run. It does not parse scenario
SDL, declare required capabilities, select a backend, or change launchability.
Scenario SDL remains demand, the backend manifest remains supply, and the
runtime-target, ingest-compatibility, and realizability gates reconcile them
before dispatch.

Challenge-board or scoring-system readback, provider topology, persistence,
deployment configuration, service APIs, and platform lifecycle status are also
outside this ABI. Keep any optional readback in explicit operator tooling, and
pass only the minimal non-secret bindings and least-privilege runner needed by
the selected adapters.
