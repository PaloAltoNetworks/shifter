"""Behavioral tests for the AWS environment teardown orchestrator (#1287).

Integration-style: one stateful fake models Terraform state per stack and the
handful of AWS CLI queries the teardown makes, so a single run exercises the
ordered destroy, pre-destroy handling, verify, and sweep together instead of a
swarm of inline-mock micro-tests.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import aws_env_destroy as aed


def _ns(returncode: int = 0, stdout: str = "", stderr: str = "") -> SimpleNamespace:
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


def _stack_of(cmd: list[str]) -> str:
    """Extract the stack dir (relative to platform/terraform) from a -chdir arg."""
    for arg in cmd:
        if arg.startswith("-chdir="):
            return arg.split("platform/terraform/", 1)[1]
    return ""


def _flag_value(cmd: list[str], flag: str) -> str:
    return cmd[cmd.index(flag) + 1]


class FakeAws:
    """Stateful fake for terraform + aws CLI calls made by the teardown."""

    def __init__(
        self,
        *,
        state: dict[str, list[str]],
        s3_state_buckets: dict[str, str] | None = None,
        ecr_repo_names: dict[str, str] | None = None,
        state_arns: dict[str, str] | None = None,
        protection_owned_arns: tuple[str, ...] | None = None,
        bucket_tags: dict[str, dict] | None = None,
        ecr_unowned: tuple[str, ...] = (),
        ecr_missing: tuple[str, ...] = (),
        ecr_delete_fail: tuple[str, ...] = (),
        verify_arns: tuple[str, ...] = (),
        versions: dict[str, dict] | None = None,
        uploads: dict[str, dict] | None = None,
        ecr_images: dict[str, list] | None = None,
        destroy_failures: dict[str, int] | None = None,
        keep_state: tuple[str, ...] = (),
        state_list_fail: tuple[str, ...] = (),
        state_show: dict[str, str] | None = None,
    ) -> None:
        self.state = {k: list(v) for k, v in state.items()}
        self.s3_state_buckets = s3_state_buckets or {}
        self.ecr_repo_names = ecr_repo_names or {}
        self.state_arns = state_arns or {}
        # None => every state ARN is owned; else exactly the listed ARNs.
        self.protection_owned_arns = protection_owned_arns
        # None => every bucket is owned; a dict => only listed buckets are owned.
        self.bucket_tags = bucket_tags
        self.ecr_unowned = set(ecr_unowned)
        self.ecr_missing = set(ecr_missing)
        self.ecr_delete_fail = set(ecr_delete_fail)
        self.verify_arns = list(verify_arns)
        self.versions = versions or {}
        self.uploads = uploads or {}
        self.ecr_images = ecr_images or {}
        self.destroy_failures = dict(destroy_failures or {})
        self.keep_state = set(keep_state)
        self.state_list_fail = set(state_list_fail)
        # Raw `terraform state show` output per address (runner network attrs).
        self.state_show = state_show or {}
        self.calls: list[list[str]] = []
        self.last_verify_filters: list[str] = []

    def __call__(self, cmd, dry_run=False, check=True, capture=False, profile=None):
        self.calls.append(cmd)
        if dry_run:  # mirror run_cmd: dry-run returns None without side effects
            return None
        if cmd[0] == "terraform":
            return self._terraform(cmd)
        if cmd[0] == "aws":
            return self._aws(cmd)
        return _ns(0)

    # -- terraform -------------------------------------------------------- #
    def _terraform(self, cmd: list[str]) -> SimpleNamespace:
        stack = _stack_of(cmd)
        sub = cmd[2]
        if sub == "state" and cmd[3] == "list":
            if stack in self.state_list_fail:
                return _ns(1)
            return _ns(0, "\n".join(self.state.get(stack, [])))
        if sub == "state" and cmd[3] == "rm":
            self.state[stack] = [a for a in self.state.get(stack, []) if a != cmd[4]]
            return _ns(0)
        if sub == "state" and cmd[3] == "show":
            addr = cmd[-1]
            if addr in self.state_show:
                return _ns(0, self.state_show[addr])
            if addr in self.s3_state_buckets:
                return _ns(0, f'  bucket = "{self.s3_state_buckets[addr]}"\n')
            if addr in self.ecr_repo_names:
                return _ns(0, f'  name = "{self.ecr_repo_names[addr]}"\n')
            if addr in self.state_arns:
                return _ns(0, f'  arn = "{self.state_arns[addr]}"\n')
            return _ns(0, "")
        if sub in ("init", "apply"):
            return _ns(0)
        if sub == "destroy":
            pending = self.destroy_failures.get(stack, 0)
            if pending > 0:
                self.destroy_failures[stack] = pending - 1
                return _ns(1)
            if stack not in self.keep_state:
                self.state[stack] = []
            return _ns(0)
        return _ns(0)

    # -- aws -------------------------------------------------------------- #
    def _aws(self, cmd: list[str]) -> SimpleNamespace:
        if "resourcegroupstaggingapi" in cmd and "get-resources" in cmd:
            idx = cmd.index("--resource-type-filters")
            run: list[str] = []
            for tok in cmd[idx + 1 :]:
                if tok.startswith("--"):
                    break
                run.append(tok)
            if set(run) == set(aed._PROTECTION_RESOURCE_TYPES):
                arns = (
                    list(self.state_arns.values())
                    if self.protection_owned_arns is None
                    else list(self.protection_owned_arns)
                )
            else:
                self.last_verify_filters = run
                arns = self.verify_arns
            return _ns(0, json.dumps({"ResourceTagMappingList": [{"ResourceARN": a} for a in arns]}))
        if "s3api" in cmd and "get-bucket-tagging" in cmd:
            return self._bucket_tagging(_flag_value(cmd, "--bucket"))
        if "s3api" in cmd and "list-object-versions" in cmd:
            return _ns(0, json.dumps(self.versions.get(_flag_value(cmd, "--bucket"), {})))
        if "s3api" in cmd and "list-multipart-uploads" in cmd:
            return _ns(0, json.dumps(self.uploads.get(_flag_value(cmd, "--bucket"), {})))
        if "s3api" in cmd and cmd_has(cmd, ("delete-objects", "abort-multipart-upload")):
            return _ns(0)
        if "ecr" in cmd:
            return self._ecr(cmd)
        return _ns(0)

    def _bucket_tagging(self, bucket: str) -> SimpleNamespace:
        if self.bucket_tags is None:
            tags = {"Project": "shifter", "Environment": "proof"}
        else:
            tags = self.bucket_tags.get(bucket)
            if tags is None:
                return _ns(1)
        return _ns(0, json.dumps({"TagSet": [{"Key": k, "Value": v} for k, v in tags.items()]}))

    def _ecr(self, cmd: list[str]) -> SimpleNamespace:
        if "describe-repositories" in cmd:
            repo = _flag_value(cmd, "--repository-names")
            if repo in self.ecr_missing:
                return _ns(254, stderr="RepositoryNotFoundException")
            return _ns(0, f"arn:aws:ecr:us-east-2:111122223333:repository/{repo}\n")
        if "list-tags-for-resource" in cmd:
            repo = _flag_value(cmd, "--resource-arn").split("/")[-1]
            tags = {"Project": "other"} if repo in self.ecr_unowned else {"Project": "shifter", "Environment": "proof"}
            return _ns(0, json.dumps({"tags": [{"Key": k, "Value": v} for k, v in tags.items()]}))
        if "list-images" in cmd:
            return _ns(0, json.dumps(self.ecr_images.get(_flag_value(cmd, "--repository-name"), [])))
        if "batch-delete-image" in cmd:
            return _ns(1) if _flag_value(cmd, "--repository-name") in self.ecr_delete_fail else _ns(0)
        return _ns(0)

    # -- assertions helpers ---------------------------------------------- #
    def destroys(self) -> list[str]:
        return [_stack_of(c) for c in self.calls if c[0] == "terraform" and c[2] == "destroy"]

    def find(self, predicate) -> list[list[str]]:
        return [c for c in self.calls if predicate(c)]


def cmd_has(cmd: list[str], needles: tuple[str, ...]) -> bool:
    return any(n in cmd for n in needles)


def _ctx(tmp_path: Path, **overrides) -> aed.TeardownContext:
    defaults = {
        "env": "proof",
        "region": "us-east-2",
        "repo_root": tmp_path / "repo",
        "backend_dir": tmp_path / "backend",
        "state_bucket": "shifter-proof-infra-uuid",
        "profile": "",
        "dry_run": False,
    }
    defaults.update(overrides)
    return aed.TeardownContext(**defaults)


_RDS_ADDR = "module.rds.aws_db_instance.portal"
_RDS_ARN = "arn:aws:rds:us-east-2:111122223333:db:proof-portal"


def _full_state() -> dict[str, list[str]]:
    return {
        "environments/proof/eks": [],  # parked -> empty -> skipped
        "environments/proof/portal": [
            _RDS_ADDR,
            "module.vpc.aws_vpc.this",
            "module.log_aggregation.aws_s3_bucket.logs",
        ],
        "environments/proof/range": ["module.range.aws_vpc.range"],
        "environments/proof": [
            "module.ecr.aws_ecr_repository.portal",
            "module.engine_state.aws_s3_bucket.engine_state",
        ],
        "global/github-runner": ["aws_instance.runner", "data.aws_subnets.default[0]"],
        "global/iam": ["aws_iam_role.github_actions"],
    }


_STATE_BUCKETS = {
    "module.log_aggregation.aws_s3_bucket.logs": "proof-portal-logs",
    "module.engine_state.aws_s3_bucket.engine_state": "proof-engine-state",
}
_ECR_REPOS = {"module.ecr.aws_ecr_repository.portal": "shifter-proof-portal"}
_STATE_ARNS = {_RDS_ADDR: _RDS_ARN}


def _fake(**overrides) -> FakeAws:
    base = {
        "state": _full_state(),
        "s3_state_buckets": _STATE_BUCKETS,
        "ecr_repo_names": _ECR_REPOS,
        "state_arns": _STATE_ARNS,
    }
    base.update(overrides)
    return FakeAws(**base)


@pytest.fixture
def sweep_ok(monkeypatch):
    monkeypatch.setattr(
        aed,
        "account_recovery",
        lambda env, profile, *, sweep, dry_run: SimpleNamespace(render=lambda: "clean", failures=[]),
    )


def _wire(monkeypatch, fake):
    monkeypatch.setattr(aed, "run_cmd", fake)


def test_happy_path_orders_layers_and_runs_pre_destroy_handling(tmp_path, monkeypatch, sweep_ok):
    fake = _fake(
        versions={"proof-portal-logs": {"Versions": [{"Key": "a", "VersionId": "v1"}]}},
        ecr_images={"shifter-proof-portal": [{"imageDigest": "sha256:x"}]},
    )
    _wire(monkeypatch, fake)

    aed.teardown(_ctx(tmp_path))

    # EKS empty -> skipped; the rest destroy Portal -> Range -> Core -> runner -> iam.
    assert fake.destroys() == [
        "environments/proof/portal",
        "environments/proof/range",
        "environments/proof",
        "global/github-runner",
        "global/iam",
    ]
    portal = fake.find(
        lambda c: c[0] == "terraform" and c[2] == "destroy" and _stack_of(c) == "environments/proof/portal"
    )[0]
    assert "-var=terraform_state_bucket=shifter-proof-infra-uuid" in portal
    assert "-lock-timeout=5m" in portal
    # data.aws_subnets.default in state -> the default-VPC opt-in was applied.
    runner = fake.find(lambda c: c[0] == "terraform" and c[2] == "destroy" and _stack_of(c) == "global/github-runner")[
        0
    ]
    assert "-var=allow_default_vpc=true" in runner
    iam = fake.find(lambda c: c[0] == "terraform" and c[2] == "destroy" and _stack_of(c) == "global/iam")[0]
    assert "-var=environment=proof" in iam


def test_runner_uses_managed_vpc_var_when_network_module_in_state(tmp_path, monkeypatch, sweep_ok):
    state = _full_state()
    state["global/github-runner"] = ["module.runner_network[0].aws_vpc.this", "aws_instance.runner"]
    fake = _fake(state=state)
    _wire(monkeypatch, fake)

    aed.teardown(_ctx(tmp_path))

    runner = fake.find(lambda c: c[0] == "terraform" and c[2] == "destroy" and _stack_of(c) == "global/github-runner")[
        0
    ]
    assert "-var=create_runner_network=true" in runner
    assert "-var=allow_default_vpc=true" not in runner


def test_runner_managed_vpc_wins_over_stale_default_subnet_discovery(tmp_path, monkeypatch, sweep_ok):
    """A managed network in state resolves managed even if discovery also ran."""
    state = _full_state()
    state["global/github-runner"] = [
        "module.runner_network[0].aws_vpc.this",
        "data.aws_subnets.default[0]",
        "aws_instance.runner",
    ]
    fake = _fake(state=state)
    _wire(monkeypatch, fake)

    aed.teardown(_ctx(tmp_path))

    runner = fake.find(lambda c: c[0] == "terraform" and c[2] == "destroy" and _stack_of(c) == "global/github-runner")[
        0
    ]
    assert "-var=create_runner_network=true" in runner
    assert "-var=allow_default_vpc=true" not in runner


_EXTERNAL_RUNNER_STATE = [
    "data.aws_vpcs.default",
    "aws_security_group.runner",
    "aws_instance.runner[0]",
    "aws_instance.runner[1]",
]


def _default_vpcs_show(*ids: str) -> str:
    """`terraform state show data.aws_vpcs.default` output recording ``ids``."""
    listed = "".join(f'        "{i}",\n' for i in ids)
    return f'data "aws_vpcs" "default" {{\n    id  = "us-east-2"\n    ids = [\n{listed}    ]\n}}\n'


_EXTERNAL_RUNNER_SHOW = {
    "data.aws_vpcs.default": _default_vpcs_show("vpc-zzzzzzzzzzzzzzzzz"),
    "aws_security_group.runner": '    vpc_id = "vpc-xxxxxxxxxxxxxxxxx"\n',
    "aws_instance.runner[0]": '    subnet_id = "subnet-xxxxxxxxxxxxxxxxx"\n',
    "aws_instance.runner[1]": '    subnet_id = "subnet-xxxxxxxxxxxxxxxxx"\n',
}


@pytest.mark.parametrize(
    ("default_vpcs", "expect_default_exception"),
    [
        # Applied VPC is not the account default VPC: an explicit external network.
        (_default_vpcs_show("vpc-zzzzzzzzzzzzzzzzz"), False),
        # Account had no default VPC at apply time.
        (_default_vpcs_show(), False),
        # Applied VPC IS the recorded default VPC: the precondition only admits that
        # under allow_default_vpc, so the exception was applied with an explicit
        # subnet_id (which skips discovery) and destroy must retain the opt-in.
        (_default_vpcs_show("vpc-xxxxxxxxxxxxxxxxx"), True),
    ],
)
def test_runner_explicit_network_reproduced_from_state(
    tmp_path, monkeypatch, sweep_ok, default_vpcs, expect_default_exception
):
    """Neither marker means an explicit vpc_id/subnet_id was applied.

    Absence of the managed module or discovery is not evidence of the topology,
    so the destroy reproduces the applied network from the security group's and
    instances' own state attributes, and asserts the ADR-004-R20 exception only
    when that VPC is the default VPC recorded in state.
    """
    state = _full_state()
    state["global/github-runner"] = list(_EXTERNAL_RUNNER_STATE)
    fake = _fake(state=state, state_show={**_EXTERNAL_RUNNER_SHOW, "data.aws_vpcs.default": default_vpcs})
    _wire(monkeypatch, fake)

    aed.teardown(_ctx(tmp_path))

    runner = fake.find(lambda c: c[0] == "terraform" and c[2] == "destroy" and _stack_of(c) == "global/github-runner")[
        0
    ]
    assert "-var=vpc_id=vpc-xxxxxxxxxxxxxxxxx" in runner
    assert "-var=subnet_id=subnet-xxxxxxxxxxxxxxxxx" in runner
    assert ("-var=allow_default_vpc=true" in runner) is expect_default_exception
    assert "-var=create_runner_network=true" not in runner


@pytest.mark.parametrize(
    ("state_addrs", "show", "match"),
    [
        # Security group gone or carrying no vpc_id: the VPC cannot be evidenced.
        (
            ["aws_instance.runner[0]"],
            {"aws_instance.runner[0]": '    subnet_id = "subnet-xxxxxxxxxxxxxxxxx"\n'},
            "vpc_id",
        ),
        # No runner instance left in state: the subnet cannot be evidenced.
        (
            ["aws_security_group.runner"],
            {"aws_security_group.runner": '    vpc_id = "vpc-xxxxxxxxxxxxxxxxx"\n'},
            "subnet_id",
        ),
        # Instances disagree on subnet: ambiguous, never pick one.
        (
            _EXTERNAL_RUNNER_STATE,
            {**_EXTERNAL_RUNNER_SHOW, "aws_instance.runner[1]": '    subnet_id = "subnet-yyyyyyyyyyyyyyyyy"\n'},
            "subnet_id",
        ),
        # Default-VPC lookup absent from state: default placement cannot be ruled out.
        (
            _EXTERNAL_RUNNER_STATE[1:],
            _EXTERNAL_RUNNER_SHOW,
            "default VPC",
        ),
    ],
)
def test_runner_unresolvable_external_network_fails_closed(tmp_path, monkeypatch, sweep_ok, state_addrs, show, match):
    state = _full_state()
    state["global/github-runner"] = list(state_addrs)
    fake = _fake(state=state, state_show=show)
    _wire(monkeypatch, fake)

    ctx = _ctx(tmp_path)
    with pytest.raises(aed.TeardownError, match=match):
        aed.teardown(ctx)

    # Fails before the runner destroy and, crucially, before global/iam, so the
    # deploy role survives for a re-dispatch.
    assert "global/github-runner" not in fake.destroys()
    assert "global/iam" not in fake.destroys()


def test_protection_lift_targets_only_ownership_verified_rds(tmp_path, monkeypatch, sweep_ok):
    fake = _fake()
    _wire(monkeypatch, fake)

    ctx = _ctx(tmp_path)
    aed.teardown(ctx)

    override = ctx.repo_root / "platform/terraform/environments/proof/portal" / aed._PROTECTION_OVERRIDE_FILE
    assert override.exists()
    assert "db_deletion_protection            = false" in override.read_text()

    applies = fake.find(lambda c: c[0] == "terraform" and c[2] == "apply")
    assert len(applies) == 1
    assert f"-target={_RDS_ADDR}" in applies[0]
    assert not any(a.startswith("-target=module.vpc") for a in applies[0])
    assert "-var=terraform_state_bucket=shifter-proof-infra-uuid" in applies[0]
    assert "-input=false" in applies[0]


def test_protection_lift_skips_unowned_target(tmp_path, monkeypatch, sweep_ok):
    # The RDS address is in state but its live ARN is not env-owned.
    fake = _fake(protection_owned_arns=())
    _wire(monkeypatch, fake)

    aed.teardown(_ctx(tmp_path))

    assert not fake.find(lambda c: c[0] == "terraform" and c[2] == "apply")  # nothing lifted


def test_s3_empty_deletes_versions_and_markers_and_aborts_multipart(tmp_path, monkeypatch, sweep_ok):
    fake = _fake(
        versions={
            "proof-portal-logs": {
                "Versions": [{"Key": "k", "VersionId": "v1"}],
                "DeleteMarkers": [{"Key": "k", "VersionId": "v2"}],
            }
        },
        uploads={"proof-portal-logs": {"Uploads": [{"Key": "big", "UploadId": "u1"}]}},
    )
    _wire(monkeypatch, fake)

    aed.teardown(_ctx(tmp_path))

    deletes = fake.find(lambda c: "delete-objects" in c and _flag_value(c, "--bucket") == "proof-portal-logs")
    assert deletes
    keys = {(o["Key"], o["VersionId"]) for c in deletes for o in json.loads(_flag_value(c, "--delete"))["Objects"]}
    assert ("k", "v1") in keys
    assert ("k", "v2") in keys
    assert fake.find(lambda c: "abort-multipart-upload" in c)


def test_s3_empty_skips_unowned_and_state_bucket(tmp_path, monkeypatch, sweep_ok):
    state = _full_state()
    state["environments/proof/portal"].append("module.x.aws_s3_bucket.state")
    fake = _fake(
        state=state,
        s3_state_buckets={**_STATE_BUCKETS, "module.x.aws_s3_bucket.state": "shifter-proof-infra-uuid"},
        bucket_tags={"proof-portal-logs": {"Project": "shifter", "Environment": "proof"}},  # engine-state not owned
        versions={"proof-portal-logs": {"Versions": [{"Key": "k", "VersionId": "v1"}]}},
    )
    _wire(monkeypatch, fake)

    aed.teardown(_ctx(tmp_path))

    emptied = {_flag_value(c, "--bucket") for c in fake.find(lambda c: "list-object-versions" in c)}
    assert emptied == {"proof-portal-logs"}


def test_ecr_from_state_batches_at_100_and_runs_before_core_destroy(tmp_path, monkeypatch, sweep_ok):
    images = [{"imageDigest": f"sha256:{i}"} for i in range(150)]
    fake = _fake(ecr_images={"shifter-proof-portal": images})
    _wire(monkeypatch, fake)

    aed.teardown(_ctx(tmp_path))

    batches = fake.find(lambda c: "batch-delete-image" in c)
    assert [len(json.loads(_flag_value(c, "--image-ids"))) for c in batches] == [100, 50]

    order = [
        ("ecr" if "batch-delete-image" in c else "core-destroy")
        for c in fake.calls
        if "batch-delete-image" in c
        or (c[0] == "terraform" and c[2] == "destroy" and _stack_of(c) == "environments/proof")
    ]
    assert order
    assert order.index("ecr") < order.index("core-destroy")


def test_ecr_delete_failure_fails_closed(tmp_path, monkeypatch, sweep_ok):
    fake = _fake(
        ecr_images={"shifter-proof-portal": [{"imageDigest": "sha256:x"}]}, ecr_delete_fail=("shifter-proof-portal",)
    )
    _wire(monkeypatch, fake)

    ctx = _ctx(tmp_path)
    with pytest.raises(aed.TeardownError, match="batch-delete-image"):
        aed.teardown(ctx)


def test_ecr_unowned_repo_is_skipped(tmp_path, monkeypatch, sweep_ok):
    fake = _fake(
        ecr_images={"shifter-proof-portal": [{"imageDigest": "sha256:x"}]}, ecr_unowned=("shifter-proof-portal",)
    )
    _wire(monkeypatch, fake)

    aed.teardown(_ctx(tmp_path))
    assert not fake.find(lambda c: "batch-delete-image" in c)


def test_ecr_absent_repo_is_skipped(tmp_path, monkeypatch, sweep_ok):
    fake = _fake(ecr_missing=("shifter-proof-portal",))
    _wire(monkeypatch, fake)

    aed.teardown(_ctx(tmp_path))
    assert not fake.find(lambda c: "batch-delete-image" in c)


def test_empty_state_layers_are_skipped(tmp_path, monkeypatch, sweep_ok):
    # eks starts empty; assert it is skipped, not destroyed.
    fake = _fake()
    _wire(monkeypatch, fake)

    aed.teardown(_ctx(tmp_path))
    assert "environments/proof/eks" not in fake.destroys()


def test_rerun_after_stacks_phase_is_idempotent(tmp_path, monkeypatch):
    fake = _fake()
    _wire(monkeypatch, fake)

    aed.teardown(_ctx(tmp_path), phase="stacks")  # clears env-stack state
    first = list(fake.destroys())
    fake.calls.clear()
    aed.teardown(_ctx(tmp_path), phase="stacks")  # rerun: everything already destroyed

    assert first == ["environments/proof/portal", "environments/proof/range", "environments/proof"]
    assert fake.destroys() == []  # nothing re-entered on the retry


def test_postcondition_fails_closed_when_state_remains(tmp_path, monkeypatch, sweep_ok):
    fake = _fake(keep_state=("environments/proof/range",))
    _wire(monkeypatch, fake)

    ctx = _ctx(tmp_path)
    with pytest.raises(aed.TeardownError, match="range"):
        aed.teardown(ctx)


def test_state_list_failure_fails_closed(tmp_path, monkeypatch, sweep_ok):
    fake = _fake(state_list_fail=("environments/proof/eks",))
    _wire(monkeypatch, fake)

    ctx = _ctx(tmp_path)
    with pytest.raises(aed.TeardownError, match="state list"):
        aed.teardown(ctx)


def test_transient_destroy_failure_recovers_on_retry_without_state_rm(tmp_path, monkeypatch, sweep_ok):
    fake = _fake(destroy_failures={"environments/proof": 1})  # first core destroy fails, retry succeeds
    _wire(monkeypatch, fake)

    aed.teardown(_ctx(tmp_path))  # must not raise
    assert not fake.find(lambda c: c[0] == "terraform" and c[2] == "state" and len(c) > 3 and c[3] == "rm")


def test_persistent_destroy_failure_fails_closed(tmp_path, monkeypatch, sweep_ok):
    fake = _fake(destroy_failures={"environments/proof/range": 2})  # initial + retry both fail
    _wire(monkeypatch, fake)

    ctx = _ctx(tmp_path)
    with pytest.raises(aed.TeardownError, match="range"):
        aed.teardown(ctx)
    assert not fake.find(lambda c: c[0] == "terraform" and c[2] == "state" and len(c) > 3 and c[3] == "rm")


def test_verify_uses_a_single_resource_type_filter_option(tmp_path, monkeypatch, sweep_ok):
    fake = _fake()
    _wire(monkeypatch, fake)

    aed.teardown(_ctx(tmp_path))

    # The verify query supplies every type under one flag; a repeated flag would
    # silently narrow the AWS CLI to the last value.
    verify_calls = [
        c
        for c in fake.find(lambda c: "resourcegroupstaggingapi" in c and "get-resources" in c)
        if set(aed._VERIFY_RESOURCE_TYPES).issubset(set(c))
    ]
    assert verify_calls
    for c in verify_calls:
        assert c.count("--resource-type-filters") == 1
    assert set(fake.last_verify_filters) == set(aed._VERIFY_RESOURCE_TYPES)


def test_verify_fails_closed_on_residual_resource(tmp_path, monkeypatch, sweep_ok):
    fake = _fake(verify_arns=("arn:aws:ec2:us-east-2:1:instance/i-123",))
    _wire(monkeypatch, fake)

    ctx = _ctx(tmp_path)
    with pytest.raises(aed.TeardownError, match="remain"):
        aed.teardown(ctx)


def test_verify_excludes_preserved_state_bucket(tmp_path, monkeypatch, sweep_ok):
    fake = _fake(verify_arns=("arn:aws:s3:::shifter-proof-infra-uuid",))
    _wire(monkeypatch, fake)

    aed.teardown(_ctx(tmp_path))  # must not raise


def test_account_recovery_failure_fails_closed(tmp_path, monkeypatch):
    fake = _fake()
    _wire(monkeypatch, fake)
    monkeypatch.setattr(
        aed,
        "account_recovery",
        lambda env, profile, *, sweep, dry_run: SimpleNamespace(render=lambda: "boom", failures=["x"]),
    )

    ctx = _ctx(tmp_path)
    with pytest.raises(aed.TeardownError, match="failed check"):
        aed.teardown(ctx)


def test_verify_query_error_fails_closed(tmp_path, monkeypatch, sweep_ok):
    fake = _fake()

    def failing(cmd, dry_run=False, check=True, capture=False, profile=None):
        # Only the verify inventory query fails (not the protection ownership one).
        if "resourcegroupstaggingapi" in cmd and "s3" in cmd:
            return _ns(1)
        return fake(cmd, dry_run=dry_run, check=check, capture=capture, profile=profile)

    _wire(monkeypatch, failing)

    ctx = _ctx(tmp_path)
    with pytest.raises(aed.TeardownError):
        aed.teardown(ctx)


def test_phase_stacks_runs_only_env_stacks_and_no_sweep_or_verify(tmp_path, monkeypatch):
    fake = _fake()
    _wire(monkeypatch, fake)
    monkeypatch.setattr(aed, "account_recovery", lambda *a, **k: pytest.fail("sweep ran in stacks phase"))

    aed.teardown(_ctx(tmp_path), phase="stacks")

    assert fake.destroys() == ["environments/proof/portal", "environments/proof/range", "environments/proof"]
    assert not fake.find(lambda c: "resourcegroupstaggingapi" in c and set(aed._VERIFY_RESOURCE_TYPES).issubset(set(c)))


def test_phase_finalize_destroys_iam_last_after_sweep_and_verify(tmp_path, monkeypatch, sweep_ok):
    fake = _fake()
    _wire(monkeypatch, fake)

    aed.teardown(_ctx(tmp_path), phase="finalize")

    assert fake.destroys() == ["global/github-runner", "global/iam"]
    # IAM (this run's own deploy role) must be the terminal op: the fallible
    # verify inventory runs before it, so a verify failure leaves the role intact.
    labels = [
        ("iam-destroy" if (c[0] == "terraform" and c[2] == "destroy" and _stack_of(c) == "global/iam") else "verify")
        for c in fake.calls
        if (c[0] == "terraform" and c[2] == "destroy" and _stack_of(c) == "global/iam")
        or ("resourcegroupstaggingapi" in c and set(aed._VERIFY_RESOURCE_TYPES).issubset(set(c)))
    ]
    assert labels
    assert labels.index("verify") < labels.index("iam-destroy")


def test_main_rejects_prod():
    with pytest.raises(SystemExit):
        aed.main(["--env", "prod", "--state-bucket", "shifter-prod-infra-uuid"])


def test_main_requires_state_bucket():
    with pytest.raises(SystemExit):
        aed.main(["--env", "proof", "--state-bucket", "  "])


def test_dry_run_makes_no_mutations(tmp_path, monkeypatch, sweep_ok):
    fake = _fake()
    _wire(monkeypatch, fake)

    aed.teardown(_ctx(tmp_path, dry_run=True))

    assert fake.state == _full_state()  # nothing actually destroyed
