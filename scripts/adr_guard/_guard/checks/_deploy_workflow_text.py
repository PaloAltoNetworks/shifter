"""Line-oriented readers for GitHub Actions workflow text.

The deploy/workflow checks assert on the *authored* workflow text (indentation,
comments, and step ordering) rather than on parsed YAML, so these helpers slice
raw workflow text into job, step, and paths-filter blocks. Semantic,
workflow-as-data checks use ``_workflow_model`` instead.
"""
from __future__ import annotations

import re


def _paths_filter_block(deploy_text: str, filter_name: str) -> list[str]:
    """Return the stripped lines of the named `dorny/paths-filter` filter block."""
    block: list[str] = []
    in_block = False
    block_indent: int | None = None
    for raw_line in deploy_text.splitlines():
        stripped = raw_line.strip()
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        if stripped == f"{filter_name}:":
            in_block = True
            block_indent = indent
            continue
        if not in_block:
            continue
        if stripped and block_indent is not None and indent <= block_indent:
            break
        block.append(stripped)
    return block


def _workflow_job_block(workflow_text: str, job_name: str) -> list[str]:
    """Return the stripped lines of the named job's block, or [] when absent."""
    block: list[str] = []
    in_block = False
    for raw_line in workflow_text.splitlines():
        stripped = raw_line.strip()
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        if indent == 2 and stripped == f"{job_name}:":
            in_block = True
            continue
        if in_block and stripped and indent == 2 and not stripped.startswith("- "):
            break
        if in_block:
            block.append(stripped)
    return block


def _block_contains_glob(block: list[str], glob: str) -> bool:
    """True when the block's path list contains the exact glob."""
    return glob in _filter_globs(block)


def _filter_globs(block: list[str]) -> list[str]:
    """Return the unquoted glob entries of a stripped paths-filter block."""
    globs: list[str] = []
    for line in block:
        if not line.startswith("- "):
            continue
        glob = line[2:].strip()
        if len(glob) >= 2 and glob[0] == glob[-1] and glob[0] in {"'", '"'}:
            glob = glob[1:-1]
        if glob:
            globs.append(glob)
    return globs


def _active_line_contains(block: list[str], needle: str) -> bool:
    """True when a non-comment line of the block contains the needle."""
    return any(needle in line for line in block if not line.lstrip().startswith("#"))


def _extract_job_if(block: list[str]) -> str:
    """Return the ``if:`` expression for a stripped workflow job block."""
    active = [line for line in block if not line.lstrip().startswith("#")]
    for idx, line in enumerate(active):
        if not line.startswith("if:"):
            continue
        rest = line[3:].strip()
        if rest == "|":
            body: list[str] = []
            for follow in active[idx + 1 :]:
                if re.match(r"^[A-Za-z0-9_-]+:", follow):
                    break
                body.append(follow)
            return " ".join(body)
        return rest
    return ""


def _workflow_step_block(workflow_text: str, step_name: str) -> list[str]:
    """Return the raw lines of the named step, including its `run:` script.

    A step is the `- name: <step_name>` list item and every more-indented line
    beneath it, up to the next list item at the same indent or a dedent out of
    the step list. Returns [] when the step is not found.
    """
    block: list[str] = []
    in_block = False
    step_indent: int | None = None
    target = f"- name: {step_name}"
    for raw_line in workflow_text.splitlines():
        stripped = raw_line.strip()
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        if not in_block:
            if stripped == target:
                in_block = True
                step_indent = indent
            continue
        # End the step at the next sibling list item or any dedent to/under it.
        if stripped and step_indent is not None and indent <= step_indent:
            break
        block.append(raw_line)
    return block


def _noncomment_contains(lines: list[str], needle: str) -> bool:
    """True when a non-comment line among ``lines`` contains the needle."""
    return any(needle in line for line in lines if not line.lstrip().startswith("#"))
