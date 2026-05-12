"""Tests for cyberscript.script_context — execution-layer sanitization boundary.

This module owns the Pydantic-validated context that funnels every value
flowing from user input into the experiment script execution layer
(orchestrator → ECS → SSM). Tests cover every validator's positive and
negative paths, plus injection-shaped negatives for each target
representation (path segment, S3 key, instance ID, IP, prompt text).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError


# ---------------------------------------------------------------------------
# InstanceIdValue — strict EC2 instance-id whitelist
# ---------------------------------------------------------------------------


class TestInstanceIdValue:
    """Strict AWS EC2 contract — matches the SSM RunCommand target shape."""

    @pytest.mark.parametrize(
        "value",
        [
            "i-abc12345",                # legacy 8-hex
            "i-0123456789abcdef0",       # 17-hex
            "i-deadbeef",
            "i-00000000",
        ],
    )
    def test_accepts_valid_instance_ids(self, value: str) -> None:
        from cyberscript.script_context import InstanceValues

        v = InstanceValues(name="Workstation", instance_id=value)
        assert v.instance_id == value

    @pytest.mark.parametrize(
        "value",
        [
            "",                                  # empty
            "abc12345",                          # missing i- prefix
            "I-abc12345",                        # wrong case prefix
            "i-",                                # prefix only
            "i-abc123",                          # 6 hex (too short)
            "i-0123456789abcdef01",              # 18 hex (too long)
            "i-ABCD1234",                        # uppercase hex not allowed
            "i-zzzzzzzz",                        # non-hex chars
            "my-gcp-vm-01",                      # non-EC2 shape
            "host01.example.com",                # hostname
            "i-abc12345 ; rm -rf /",             # injection
            "i-abc12345\nmalice",                # newline injection
            "i-abc12345$(whoami)",               # command substitution
            "i-abc12345`id`",                    # backticks
            "i-abc/12345",                       # slash
            "i-abc.12345",                       # dot (not in hex)
        ],
    )
    def test_rejects_invalid_instance_ids(self, value: str) -> None:
        from cyberscript.script_context import InstanceValues

        with pytest.raises(ValidationError) as exc:
            InstanceValues(name="Workstation", instance_id=value)
        assert "instance_id" in str(exc.value)


# ---------------------------------------------------------------------------
# PrivateIpValue — IPv4 only; None / unset allowed
# ---------------------------------------------------------------------------


class TestPrivateIpValue:
    """RFC 791 IPv4 dotted-quad; None means the instance hasn't reported one."""

    @pytest.mark.parametrize(
        "value",
        ["10.0.0.1", "192.168.1.1", "172.16.42.42", "0.0.0.0", "255.255.255.255"],
    )
    def test_accepts_valid_ipv4(self, value: str) -> None:
        from cyberscript.script_context import InstanceValues

        v = InstanceValues(name="Workstation", instance_id="i-abc12345", private_ip=value)
        assert v.private_ip == value

    def test_accepts_none(self) -> None:
        from cyberscript.script_context import InstanceValues

        v = InstanceValues(name="Workstation", instance_id="i-abc12345", private_ip=None)
        assert v.private_ip is None

    def test_defaults_to_none(self) -> None:
        from cyberscript.script_context import InstanceValues

        v = InstanceValues(name="Workstation", instance_id="i-abc12345")
        assert v.private_ip is None

    @pytest.mark.parametrize(
        "value",
        [
            "10.0.0",                     # only 3 octets
            "10.0.0.0.0",                 # 5 octets
            "999.0.0.1",                  # octet out of range
            "10.0.0.1; rm -rf /",         # injection
            "10.0.0.1\nbad",              # newline
            "$(whoami)",                  # command substitution
            "fe80::1",                    # IPv6 not allowed
            "hostname.example.com",       # not an IP
            "10.0.0.01",                  # leading zero (canonicalisation guard)
        ],
    )
    def test_rejects_invalid_ip(self, value: str) -> None:
        from cyberscript.script_context import InstanceValues

        with pytest.raises(ValidationError) as exc:
            InstanceValues(name="Workstation", instance_id="i-abc12345", private_ip=value)
        assert "private_ip" in str(exc.value)


# ---------------------------------------------------------------------------
# S3KeySegment — AWS S3 key whitelist for safe shell interpolation
# ---------------------------------------------------------------------------


class TestS3KeySegment:
    """`[A-Za-z0-9._/=+-]{1,1024}`; no leading '/', no '..', no control chars."""

    @pytest.mark.parametrize(
        "key",
        [
            "scripts/1/abc123_my-script.py",
            "a",
            "scripts/42/0123456789ab_helper.py",
            "deep/nested/path/file.txt",
            "a.b.c",
            "with-dashes_and_underscores",
            "equals=allowed/plus+allowed",
        ],
    )
    def test_accepts_valid_s3_keys(self, key: str) -> None:
        from cyberscript.script_context import ScriptExecutionContext

        ctx = ScriptExecutionContext(
            script_type="python",
            instance={"name": "Workstation", "instance_id": "i-abc12345"},
            script_s3_key=key,
        )
        assert ctx.script_s3_key == key

    @pytest.mark.parametrize(
        "key",
        [
            "",                                 # empty
            "/leading-slash",                   # absolute
            "scripts/../../etc/passwd",         # traversal
            "scripts/../secret",                # traversal
            "scripts/..",                       # traversal
            "scripts/.. ",                      # traversal padded
            "scripts/.\\file",                  # backslash
            "scripts/file with space.py",       # space
            "scripts/file\x00.py",              # null
            "scripts/file\n.py",                # newline
            "scripts/file;rm -rf /",            # semicolon
            "scripts/file$(id)",                # command substitution
            "scripts/file`whoami`",             # backticks
            "scripts/file'quote",               # single quote
            "scripts/file\"quote",              # double quote
            "scripts/file|pipe",                # pipe
            "scripts/file&background",          # ampersand
            "scripts/file>redir",               # redirect
            "scripts/" + ("a" * 1100),          # too long
        ],
    )
    def test_rejects_invalid_s3_keys(self, key: str) -> None:
        from cyberscript.script_context import ScriptExecutionContext

        with pytest.raises(ValidationError) as exc:
            ScriptExecutionContext(
                script_type="python",
                instance={"name": "Workstation", "instance_id": "i-abc12345"},
                script_s3_key=key,
            )
        assert "script_s3_key" in str(exc.value)


# ---------------------------------------------------------------------------
# DisplayName — instance.name (metadata only; relaxed but no control bytes)
# ---------------------------------------------------------------------------


class TestDisplayName:
    """Display name for an instance — used in metadata, not in shell text."""

    @pytest.mark.parametrize(
        "name",
        [
            "Workstation",
            "Workstation 1",
            "Domain Controller",
            "Cortex Host",
            "host-01.region",
            "Box (primary)",
            "Hôst Wîth Üñîcode",     # unicode accepted
        ],
    )
    def test_accepts_valid_display_names(self, name: str) -> None:
        from cyberscript.script_context import InstanceValues

        v = InstanceValues(name=name, instance_id="i-abc12345")
        assert v.name == name

    @pytest.mark.parametrize(
        "name",
        [
            "",                                  # empty
            " ",                                 # whitespace only
            "name\x00with-null",                 # null byte
            "name\x07with-bell",                 # control char
            "name\x1bwith-escape",               # ESC
            "a" * 101,                           # > 100 chars
        ],
    )
    def test_rejects_invalid_display_names(self, name: str) -> None:
        from cyberscript.script_context import InstanceValues

        with pytest.raises(ValidationError) as exc:
            InstanceValues(name=name, instance_id="i-abc12345")
        assert "name" in str(exc.value)

    @pytest.mark.parametrize(
        "name",
        [
            "line one\nline two",  # newline accepted (multi-line display)
            "tab\there",
            "carriage\rreturn",
        ],
    )
    def test_accepts_whitespace_controls(self, name: str) -> None:
        from cyberscript.script_context import InstanceValues

        v = InstanceValues(name=name, instance_id="i-abc12345")
        assert v.name == name


# ---------------------------------------------------------------------------
# PromptText — Claude prompt body (post-resolution)
# ---------------------------------------------------------------------------


class TestPromptText:
    """Resolved prompt text. Encoded by render_claude_command, not validated for shell-safety."""

    @pytest.mark.parametrize(
        "text",
        [
            "Attack the box at 10.0.0.1",
            "Multi\nline\nprompt",
            "Has 'quotes' and \"double\" and `backticks`",  # shell metas allowed inside the encoded arg
            "Pipes | and semicolons ; and ampersands & — all fine pre-encoding",
            "$(echo not-actually-executed-because-of-single-quote-wrap)",
            "x" * 8192,                                       # exactly 8 KiB
        ],
    )
    def test_accepts_reasonable_prompts(self, text: str) -> None:
        from cyberscript.script_context import ScriptExecutionContext

        ctx = ScriptExecutionContext(
            script_type="claude_code",
            instance={"name": "Workstation", "instance_id": "i-abc12345"},
            claude_prompt_resolved=text,
        )
        assert ctx.claude_prompt_resolved == text

    @pytest.mark.parametrize(
        "text",
        [
            "",                                  # empty
            "prompt\x00with-null",               # null
            "prompt\x07with-bell",               # bell
            "prompt\x1bwith-escape",             # ESC
            "x" * 8193,                          # > 8 KiB
        ],
    )
    def test_rejects_bad_prompts(self, text: str) -> None:
        from cyberscript.script_context import ScriptExecutionContext

        with pytest.raises(ValidationError) as exc:
            ScriptExecutionContext(
                script_type="claude_code",
                instance={"name": "Workstation", "instance_id": "i-abc12345"},
                claude_prompt_resolved=text,
            )
        assert "claude_prompt_resolved" in str(exc.value)


# ---------------------------------------------------------------------------
# ScriptExecutionContext — discriminator + payload completeness
# ---------------------------------------------------------------------------


class TestScriptExecutionContextDiscriminator:

    def test_python_requires_s3_key(self) -> None:
        from cyberscript.script_context import ScriptExecutionContext

        with pytest.raises(ValidationError) as exc:
            ScriptExecutionContext(
                script_type="python",
                instance={"name": "Workstation", "instance_id": "i-abc12345"},
            )
        assert "script_s3_key" in str(exc.value)

    def test_python_rejects_claude_prompt_field(self) -> None:
        from cyberscript.script_context import ScriptExecutionContext

        with pytest.raises(ValidationError) as exc:
            ScriptExecutionContext(
                script_type="python",
                instance={"name": "Workstation", "instance_id": "i-abc12345"},
                script_s3_key="scripts/1/x.py",
                claude_prompt_resolved="extra prompt",
            )
        assert "claude_prompt_resolved" in str(exc.value)

    def test_claude_requires_prompt(self) -> None:
        from cyberscript.script_context import ScriptExecutionContext

        with pytest.raises(ValidationError) as exc:
            ScriptExecutionContext(
                script_type="claude_code",
                instance={"name": "Workstation", "instance_id": "i-abc12345"},
            )
        assert "claude_prompt_resolved" in str(exc.value)

    def test_claude_rejects_s3_key_field(self) -> None:
        from cyberscript.script_context import ScriptExecutionContext

        with pytest.raises(ValidationError) as exc:
            ScriptExecutionContext(
                script_type="claude_code",
                instance={"name": "Workstation", "instance_id": "i-abc12345"},
                claude_prompt_resolved="do the thing",
                script_s3_key="scripts/1/x.py",
            )
        assert "script_s3_key" in str(exc.value)

    def test_unknown_script_type_rejected(self) -> None:
        from cyberscript.script_context import ScriptExecutionContext

        with pytest.raises(ValidationError):
            ScriptExecutionContext(
                script_type="bash",  # type: ignore[arg-type]
                instance={"name": "Workstation", "instance_id": "i-abc12345"},
                script_s3_key="scripts/1/x.py",
            )

    def test_frozen(self) -> None:
        from cyberscript.script_context import ScriptExecutionContext

        ctx = ScriptExecutionContext(
            script_type="python",
            instance={"name": "Workstation", "instance_id": "i-abc12345"},
            script_s3_key="scripts/1/x.py",
        )
        with pytest.raises(ValidationError):
            ctx.script_s3_key = "scripts/2/y.py"  # type: ignore[misc]

    def test_extra_fields_forbidden(self) -> None:
        from cyberscript.script_context import ScriptExecutionContext

        with pytest.raises(ValidationError):
            ScriptExecutionContext(
                script_type="python",
                instance={"name": "Workstation", "instance_id": "i-abc12345"},
                script_s3_key="scripts/1/x.py",
                extra_field="should-not-be-here",  # type: ignore[call-arg]
            )


# ---------------------------------------------------------------------------
# Render methods — exact shell-string shape; nothing slips past the encoder
# ---------------------------------------------------------------------------


class TestRenderPythonCommand:

    def test_uses_instance_id_as_path_segment(self) -> None:
        """`instance_name` must NOT be interpolated — `instance_id` is the safe segment."""
        from cyberscript.script_context import ScriptExecutionContext

        ctx = ScriptExecutionContext(
            script_type="python",
            instance={"name": "Workstation 1", "instance_id": "i-abc12345"},
            script_s3_key="scripts/42/abc_my-script.py",
        )
        cmd = ctx.render_command()

        # Path segment is the instance_id, not the display name.
        assert "/tmp/script_i-abc12345.py" in cmd
        assert "/tmp/output_i-abc12345.log" in cmd
        # The display name with its embedded space must NOT appear in the shell text.
        assert "Workstation 1" not in cmd
        assert "Workstation" not in cmd

    def test_renders_full_pipeline(self) -> None:
        from cyberscript.script_context import ScriptExecutionContext

        ctx = ScriptExecutionContext(
            script_type="python",
            instance={"name": "Workstation", "instance_id": "i-abc12345"},
            script_s3_key="scripts/1/script.py",
        )
        expected = (
            "aws s3 cp s3://${BUCKET_NAME}/scripts/1/script.py /tmp/script_i-abc12345.py "
            "&& python3 /tmp/script_i-abc12345.py "
            "2>&1 | tee /tmp/output_i-abc12345.log"
        )
        assert ctx.render_command() == expected


class TestRenderClaudeCommand:

    @pytest.mark.parametrize(
        "prompt, expected_arg",
        [
            ("simple prompt", "'simple prompt'"),
            ("with 'quote'", "'with '\\''quote'\\'''"),
            ("two 'a' and 'b'", "'two '\\''a'\\'' and '\\''b'\\'''"),
            ("no quotes here", "'no quotes here'"),
            # Shell metas survive inside the single-quoted arg — that's correct,
            # because `claude -p` receives the prompt as a literal string.
            ("$(injected)", "'$(injected)'"),
            ("`backticks`", "'`backticks`'"),
            ("pipes | and ; semis", "'pipes | and ; semis'"),
        ],
    )
    def test_posix_single_quote_encoding(self, prompt: str, expected_arg: str) -> None:
        from cyberscript.script_context import ScriptExecutionContext

        ctx = ScriptExecutionContext(
            script_type="claude_code",
            instance={"name": "Workstation", "instance_id": "i-abc12345"},
            claude_prompt_resolved=prompt,
        )
        cmd = ctx.render_command()
        assert f" -p {expected_arg} " in cmd

    def test_full_shape(self) -> None:
        from cyberscript.script_context import (
            AI_EXPERIMENT_EXECUTION_POLICY_VERSION,
            ScriptExecutionContext,
        )

        ctx = ScriptExecutionContext(
            script_type="claude_code",
            instance={"name": "Workstation", "instance_id": "i-abc12345"},
            claude_prompt_resolved="attack the box",
        )
        expected = (
            "claude --dangerously-skip-permissions "
            "--output-format stream-json "
            "-p 'attack the box' "
            "2>&1 | tee /tmp/claude_output.json"
        )
        assert ctx.render_command() == expected
        assert AI_EXPERIMENT_EXECUTION_POLICY_VERSION == "ai-experiment-execution-v1"

    def test_policy_payload_pins_allowed_claude_boundary(self) -> None:
        from cyberscript.script_context import build_ai_execution_policy_payload

        policy = build_ai_execution_policy_payload()
        claude = policy["claude_code"]

        assert policy["version"] == "ai-experiment-execution-v1"
        assert claude["prompt_delivery"] == "validated_single_argument"
        assert claude["transcript_artifact_required"] is True


# ---------------------------------------------------------------------------
# Factory methods — pull-through to template_vars.resolve_template
# ---------------------------------------------------------------------------


class TestForPython:

    def test_constructs_python_context(self) -> None:
        from cyberscript.script_context import ScriptExecutionContext

        ctx = ScriptExecutionContext.for_python(
            instance_name="Workstation",
            instance_id="i-abc12345",
            private_ip="10.0.0.1",
            script_s3_key="scripts/1/x.py",
        )
        assert ctx.script_type == "python"
        assert ctx.instance.name == "Workstation"
        assert ctx.instance.instance_id == "i-abc12345"
        assert ctx.instance.private_ip == "10.0.0.1"
        assert ctx.script_s3_key == "scripts/1/x.py"
        assert ctx.claude_prompt_resolved is None

    def test_propagates_instance_id_validation_error(self) -> None:
        from cyberscript.script_context import ScriptExecutionContext

        with pytest.raises(ValidationError):
            ScriptExecutionContext.for_python(
                instance_name="Workstation",
                instance_id="bad id; rm -rf /",
                private_ip=None,
                script_s3_key="scripts/1/x.py",
            )

    def test_propagates_s3_key_validation_error(self) -> None:
        from cyberscript.script_context import ScriptExecutionContext

        with pytest.raises(ValidationError):
            ScriptExecutionContext.for_python(
                instance_name="Workstation",
                instance_id="i-abc12345",
                private_ip=None,
                script_s3_key="scripts/../../etc/passwd",
            )


class TestForClaude:

    def test_resolves_template_variables(self) -> None:
        from cyberscript.script_context import ScriptExecutionContext

        ctx = ScriptExecutionContext.for_claude(
            instance_name="Workstation",
            instance_id="i-abc12345",
            private_ip="10.0.0.1",
            claude_prompt_template="Attack {{Target.ip}} from {{Source.ip}}",
            instance_data={
                "Target": {"ip": "10.0.0.5", "name": "Target", "instance_id": "i-def67890"},
                "Source": {"ip": "10.0.0.6", "name": "Source", "instance_id": "i-09876543"},
            },
        )
        assert ctx.script_type == "claude_code"
        assert ctx.claude_prompt_resolved == "Attack 10.0.0.5 from 10.0.0.6"

    def test_raises_when_template_references_unknown_instance(self) -> None:
        from cyberscript.script_context import ScriptExecutionContext

        with pytest.raises(ValidationError) as exc:
            ScriptExecutionContext.for_claude(
                instance_name="Workstation",
                instance_id="i-abc12345",
                private_ip=None,
                claude_prompt_template="hit {{Ghost.ip}}",
                instance_data={
                    "Workstation": {"ip": "10.0.0.1", "name": "Workstation", "instance_id": "i-abc12345"},
                },
            )
        assert "claude_prompt_template" in str(exc.value)

    def test_raises_when_template_references_unknown_property(self) -> None:
        from cyberscript.script_context import ScriptExecutionContext

        with pytest.raises(ValidationError) as exc:
            ScriptExecutionContext.for_claude(
                instance_name="Workstation",
                instance_id="i-abc12345",
                private_ip=None,
                claude_prompt_template="hit {{Workstation.hostname}}",
                instance_data={
                    "Workstation": {"ip": "10.0.0.1", "name": "Workstation", "instance_id": "i-abc12345"},
                },
            )
        assert "claude_prompt_template" in str(exc.value)

    def test_post_resolution_prompt_is_validated(self) -> None:
        """A template variable whose value carries a control char must be rejected."""
        from cyberscript.script_context import ScriptExecutionContext

        # Construct instance_data with a deliberately-poisoned value to confirm
        # the post-resolution prompt still goes through PromptText validation.
        with pytest.raises(ValidationError) as exc:
            ScriptExecutionContext.for_claude(
                instance_name="Workstation",
                instance_id="i-abc12345",
                private_ip=None,
                claude_prompt_template="value: {{Target.name}}",
                instance_data={
                    "Target": {"ip": "10.0.0.5", "name": "bad\x00name", "instance_id": "i-def67890"},
                },
            )
        # Either the template_vars resolver or the PromptText validator catches it.
        assert "claude_prompt_resolved" in str(exc.value) or "claude_prompt_template" in str(exc.value)

    def test_passes_template_unchanged_when_no_variables(self) -> None:
        from cyberscript.script_context import ScriptExecutionContext

        ctx = ScriptExecutionContext.for_claude(
            instance_name="Workstation",
            instance_id="i-abc12345",
            private_ip=None,
            claude_prompt_template="run the experiment",
            instance_data={},
        )
        assert ctx.claude_prompt_resolved == "run the experiment"

    def test_rejects_malformed_substitution_ip(self) -> None:
        """An ip in instance_data that fails the IPv4 validator must surface as a ValidationError."""
        from cyberscript.script_context import ScriptExecutionContext

        with pytest.raises(ValidationError) as exc:
            ScriptExecutionContext.for_claude(
                instance_name="Workstation",
                instance_id="i-abc12345",
                private_ip=None,
                claude_prompt_template="hit {{Target.ip}}",
                instance_data={
                    "Target": {"ip": "evil; rm -rf /", "name": "Target", "instance_id": "i-def67890"},
                },
            )
        assert "claude_prompt_template" in str(exc.value)

    def test_rejects_malformed_substitution_instance_id(self) -> None:
        """An instance_id in instance_data that fails the EC2 regex must surface as a ValidationError."""
        from cyberscript.script_context import ScriptExecutionContext

        with pytest.raises(ValidationError) as exc:
            ScriptExecutionContext.for_claude(
                instance_name="Workstation",
                instance_id="i-abc12345",
                private_ip=None,
                claude_prompt_template="hit {{Target.instance_id}}",
                instance_data={
                    "Target": {"ip": "10.0.0.5", "name": "Target", "instance_id": "not-an-ec2-id"},
                },
            )
        assert "claude_prompt_template" in str(exc.value)

    def test_rejects_unresolved_placeholder_with_space(self) -> None:
        """A `{{Domain Controller.ip}}` placeholder passes through resolve_template
        unchanged because the `\\w+\\.\\w+` regex doesn't match names with spaces;
        the context must reject the run rather than dispatching a literal placeholder.
        """
        from cyberscript.script_context import ScriptExecutionContext

        with pytest.raises(ValidationError) as exc:
            ScriptExecutionContext.for_claude(
                instance_name="Workstation",
                instance_id="i-abc12345",
                private_ip=None,
                claude_prompt_template="Attack {{Domain Controller.ip}}",
                instance_data={
                    "Domain Controller": {"ip": "10.0.0.5", "name": "Domain Controller", "instance_id": "i-def67890"},
                },
            )
        assert "unresolved placeholder" in str(exc.value)

    def test_does_not_validate_unreferenced_instances(self) -> None:
        """A prompt that references only `{{Target.ip}}` must not fail because a
        DIFFERENT provisioned instance has a malformed value (cycle-4 Finding #2).
        """
        from cyberscript.script_context import ScriptExecutionContext

        ctx = ScriptExecutionContext.for_claude(
            instance_name="Workstation",
            instance_id="i-abc12345",
            private_ip=None,
            claude_prompt_template="hit {{Target.ip}}",
            instance_data={
                "Target": {"ip": "10.0.0.5", "name": "Target", "instance_id": "i-def67890"},
                # This entry is malformed but NOT referenced by the prompt:
                "Unrelated": {"ip": "evil; rm -rf /", "name": "x", "instance_id": "not-an-id"},
            },
        )
        assert ctx.claude_prompt_resolved == "hit 10.0.0.5"

    def test_no_variables_does_not_validate_anything(self) -> None:
        """A prompt with no template variables must succeed regardless of
        instance_data quality (cycle-4 Finding #2)."""
        from cyberscript.script_context import ScriptExecutionContext

        ctx = ScriptExecutionContext.for_claude(
            instance_name="Workstation",
            instance_id="i-abc12345",
            private_ip=None,
            claude_prompt_template="just do the experiment",
            instance_data={
                "Garbage": {"ip": "not-an-ip", "name": "n\x00ame", "instance_id": "bad"},
            },
        )
        assert ctx.claude_prompt_resolved == "just do the experiment"

    def test_rejects_malformed_substitution_display_name(self) -> None:
        """A name in instance_data carrying control bytes must fail validation."""
        from cyberscript.script_context import ScriptExecutionContext

        with pytest.raises(ValidationError) as exc:
            ScriptExecutionContext.for_claude(
                instance_name="Workstation",
                instance_id="i-abc12345",
                private_ip=None,
                claude_prompt_template="hit {{Target.name}}",
                instance_data={
                    "Target": {"ip": "10.0.0.5", "name": "bad\x00name", "instance_id": "i-def67890"},
                },
            )
        assert "claude_prompt_template" in str(exc.value)


# ---------------------------------------------------------------------------
# Injection battery — end-to-end: bad input never reaches a render method
# ---------------------------------------------------------------------------


class TestInjectionBattery:
    """Catch-all: every injection-shaped input must be refused before render."""

    @pytest.mark.parametrize(
        "instance_id",
        [
            "i-abc12345; rm -rf /",
            "i-abc12345 && curl evil.example",
            "i-abc12345|tee /tmp/loot",
            "$(/bin/sh -c 'curl evil')",
            "`whoami`",
        ],
    )
    def test_injection_in_instance_id_is_refused(self, instance_id: str) -> None:
        from cyberscript.script_context import ScriptExecutionContext

        with pytest.raises(ValidationError):
            ScriptExecutionContext.for_python(
                instance_name="Workstation",
                instance_id=instance_id,
                private_ip=None,
                script_s3_key="scripts/1/x.py",
            )

    @pytest.mark.parametrize(
        "s3_key",
        [
            "scripts/1/x.py; rm -rf /",
            "scripts/1/x.py && curl evil",
            "scripts/../../etc/shadow",
            "$(/bin/sh)",
            "`id`",
            "scripts/1/x.py'\nrm -rf /",
        ],
    )
    def test_injection_in_s3_key_is_refused(self, s3_key: str) -> None:
        from cyberscript.script_context import ScriptExecutionContext

        with pytest.raises(ValidationError):
            ScriptExecutionContext.for_python(
                instance_name="Workstation",
                instance_id="i-abc12345",
                private_ip=None,
                script_s3_key=s3_key,
            )

    def test_injection_inside_quoted_prompt_does_not_escape(self) -> None:
        """Even when the prompt contains `'` and shell metas, the rendered command
        must keep them inside a single quoted argument — no break-out possible.
        """
        from cyberscript.script_context import ScriptExecutionContext

        evil = "'; rm -rf / ; echo '"
        ctx = ScriptExecutionContext(
            script_type="claude_code",
            instance={"name": "Workstation", "instance_id": "i-abc12345"},
            claude_prompt_resolved=evil,
        )
        cmd = ctx.render_command()
        # The argument starts and ends with one literal single quote — every other
        # quote in the rendered string is part of `'\''` escape sequences.
        prefix = " -p '"
        suffix = "' 2>&1 | tee "
        assert prefix in cmd and suffix in cmd
        # Count of bare-quote *boundaries*: exactly the opener and the closer.
        between = cmd.split(prefix, 1)[1].rsplit(suffix, 1)[0]
        # The argument body must not contain a raw "'" that isn't part of "'\''".
        # Replace every "'\''" with sentinel, then no "'" should remain.
        sanitized = between.replace("'\\''", "\x01")
        assert "'" not in sanitized, f"unescaped single quote leaked: {between!r}"
