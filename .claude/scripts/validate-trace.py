#!/usr/bin/env python3
"""AST-based validation for code trace analysis.

Extracts ground truth from Python source files to validate LLM-generated
code analysis. Compares claimed signatures, calls, and structure against
actual AST.

Usage:
    # Extract function info as JSON
    python validate-trace.py extract <file> <function>

    # Validate a claim against source
    python validate-trace.py validate <file> <function> '<json_claim>'

    # Batch validate from a trace file
    python validate-trace.py batch <trace_file>

Examples:
    python validate-trace.py extract cms/services.py create_range
    python validate-trace.py validate cms/services.py create_range '{"returns": "RangeContext"}'
"""

from __future__ import annotations

import ast
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class FunctionInfo:
    """Ground truth extracted from AST."""

    name: str
    file: str
    lineno: int
    end_lineno: int | None
    args: list[str]
    annotations: dict[str, str]
    returns: str | None
    defaults: dict[str, str]
    decorators: list[str]
    calls: list[dict[str, Any]]
    raises: list[str]
    docstring: str | None
    is_async: bool = False
    is_method: bool = False
    class_name: str | None = None


@dataclass
class ValidationResult:
    """Result of validating a claim against ground truth."""

    valid: bool
    field: str
    claimed: Any
    actual: Any
    message: str


@dataclass
class TraceValidationReport:
    """Full validation report for a trace file."""

    total_functions: int = 0
    validated: int = 0
    passed: int = 0
    failed: int = 0
    not_found: int = 0
    results: list[dict[str, Any]] = field(default_factory=list)


def get_annotation_str(node: ast.expr | None) -> str | None:
    """Convert AST annotation node to string."""
    if node is None:
        return None
    try:
        return ast.unparse(node)
    except Exception:
        return None


def extract_calls(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[dict[str, Any]]:
    """Extract all function/method calls from a function body."""
    calls = []
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            call_info = {
                "lineno": child.lineno,
                "col_offset": child.col_offset,
            }
            # Get the function being called
            if isinstance(child.func, ast.Name):
                call_info["name"] = child.func.id
                call_info["type"] = "function"
            elif isinstance(child.func, ast.Attribute):
                call_info["name"] = child.func.attr
                call_info["type"] = "method"
                # Try to get the object
                if isinstance(child.func.value, ast.Name):
                    call_info["object"] = child.func.value.id
                else:
                    try:
                        call_info["object"] = ast.unparse(child.func.value)
                    except Exception:
                        call_info["object"] = "<complex>"
            else:
                try:
                    call_info["name"] = ast.unparse(child.func)
                    call_info["type"] = "complex"
                except Exception:
                    call_info["name"] = "<unknown>"
                    call_info["type"] = "unknown"
            calls.append(call_info)
    return calls


def extract_raises(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    """Extract all exception types raised in a function."""
    raises = []
    for child in ast.walk(node):
        if isinstance(child, ast.Raise):
            if child.exc is not None:
                if isinstance(child.exc, ast.Call):
                    if isinstance(child.exc.func, ast.Name):
                        raises.append(child.exc.func.id)
                    elif isinstance(child.exc.func, ast.Attribute):
                        raises.append(child.exc.func.attr)
                elif isinstance(child.exc, ast.Name):
                    raises.append(child.exc.id)
    return list(set(raises))  # Dedupe


def extract_function_info(
    file_path: str,
    func_name: str,
    class_name: str | None = None,
) -> FunctionInfo | None:
    """Extract function information from source file using AST.

    Args:
        file_path: Path to Python source file
        func_name: Name of function to extract
        class_name: If method, the class name (optional)

    Returns:
        FunctionInfo with ground truth, or None if not found
    """
    path = Path(file_path)
    if not path.exists():
        return None

    try:
        source = path.read_text()
        tree = ast.parse(source)
    except (SyntaxError, UnicodeDecodeError):
        return None

    # Search for the function
    for node in ast.walk(tree):
        # Handle methods in classes
        if class_name and isinstance(node, ast.ClassDef) and node.name == class_name:
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if item.name == func_name:
                        return _build_function_info(
                            item, file_path, is_method=True, class_name=class_name
                        )

        # Handle top-level functions
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == func_name:
                # Check it's not inside a class (unless we're looking for a method)
                if class_name is None:
                    return _build_function_info(node, file_path)

    return None


def _build_function_info(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    file_path: str,
    is_method: bool = False,
    class_name: str | None = None,
) -> FunctionInfo:
    """Build FunctionInfo from AST node."""
    # Extract arguments
    args = []
    annotations = {}
    defaults = {}

    # Calculate default offset
    num_defaults = len(node.args.defaults)
    num_args = len(node.args.args)
    default_offset = num_args - num_defaults

    for i, arg in enumerate(node.args.args):
        args.append(arg.arg)
        if arg.annotation:
            annotations[arg.arg] = get_annotation_str(arg.annotation) or ""
        # Check for default value
        if i >= default_offset:
            default_idx = i - default_offset
            try:
                defaults[arg.arg] = ast.unparse(node.args.defaults[default_idx])
            except Exception:
                defaults[arg.arg] = "<complex>"

    # Handle *args
    if node.args.vararg:
        args.append(f"*{node.args.vararg.arg}")
        if node.args.vararg.annotation:
            annotations[f"*{node.args.vararg.arg}"] = (
                get_annotation_str(node.args.vararg.annotation) or ""
            )

    # Handle **kwargs
    if node.args.kwarg:
        args.append(f"**{node.args.kwarg.arg}")
        if node.args.kwarg.annotation:
            annotations[f"**{node.args.kwarg.arg}"] = (
                get_annotation_str(node.args.kwarg.annotation) or ""
            )

    # Extract decorators
    decorators = []
    for decorator in node.decorator_list:
        try:
            decorators.append(ast.unparse(decorator))
        except Exception:
            decorators.append("<complex>")

    # Extract docstring
    docstring = ast.get_docstring(node)

    return FunctionInfo(
        name=node.name,
        file=file_path,
        lineno=node.lineno,
        end_lineno=getattr(node, "end_lineno", None),
        args=args,
        annotations=annotations,
        returns=get_annotation_str(node.returns),
        defaults=defaults,
        decorators=decorators,
        calls=extract_calls(node),
        raises=extract_raises(node),
        docstring=docstring,
        is_async=isinstance(node, ast.AsyncFunctionDef),
        is_method=is_method,
        class_name=class_name,
    )


def validate_claim(
    ground_truth: FunctionInfo,
    claim: dict[str, Any],
) -> list[ValidationResult]:
    """Validate a claim against ground truth.

    Args:
        ground_truth: Extracted function info from AST
        claim: Dict with claimed properties to validate

    Returns:
        List of ValidationResults (one per field checked)
    """
    results = []

    # Validate return type
    if "returns" in claim:
        claimed = claim["returns"]
        actual = ground_truth.returns
        # Normalize for comparison (handle None vs "None" vs missing)
        claimed_norm = str(claimed) if claimed else None
        actual_norm = str(actual) if actual else None
        valid = claimed_norm == actual_norm
        results.append(
            ValidationResult(
                valid=valid,
                field="returns",
                claimed=claimed,
                actual=actual,
                message="" if valid else f"Return type mismatch",
            )
        )

    # Validate arguments
    if "args" in claim:
        claimed = set(claim["args"])
        actual = set(ground_truth.args)
        valid = claimed == actual
        results.append(
            ValidationResult(
                valid=valid,
                field="args",
                claimed=sorted(claim["args"]),
                actual=sorted(ground_truth.args),
                message="" if valid else f"Missing: {actual - claimed}, Extra: {claimed - actual}",
            )
        )

    # Validate annotations
    if "annotations" in claim:
        for arg, claimed_type in claim["annotations"].items():
            actual_type = ground_truth.annotations.get(arg)
            valid = str(claimed_type) == str(actual_type)
            results.append(
                ValidationResult(
                    valid=valid,
                    field=f"annotation:{arg}",
                    claimed=claimed_type,
                    actual=actual_type,
                    message="" if valid else f"Type annotation mismatch for {arg}",
                )
            )

    # Validate calls (check if claimed calls exist)
    if "calls" in claim:
        actual_call_names = {c["name"] for c in ground_truth.calls}
        for claimed_call in claim["calls"]:
            call_name = claimed_call if isinstance(claimed_call, str) else claimed_call.get("name")
            valid = call_name in actual_call_names
            results.append(
                ValidationResult(
                    valid=valid,
                    field="calls",
                    claimed=call_name,
                    actual=sorted(actual_call_names) if not valid else call_name,
                    message="" if valid else f"Call '{call_name}' not found in function",
                )
            )

    # Validate line number
    if "lineno" in claim:
        valid = claim["lineno"] == ground_truth.lineno
        results.append(
            ValidationResult(
                valid=valid,
                field="lineno",
                claimed=claim["lineno"],
                actual=ground_truth.lineno,
                message="" if valid else "Line number mismatch",
            )
        )

    # Validate raises
    if "raises" in claim:
        claimed_raises = set(claim["raises"])
        actual_raises = set(ground_truth.raises)
        valid = claimed_raises <= actual_raises  # Claimed should be subset of actual
        results.append(
            ValidationResult(
                valid=valid,
                field="raises",
                claimed=sorted(claimed_raises),
                actual=sorted(actual_raises),
                message="" if valid else f"Raises mismatch - not found: {claimed_raises - actual_raises}",
            )
        )

    return results


def parse_validation_block(content: str) -> list[dict[str, Any]]:
    """Extract VALIDATION_BLOCK JSON from markdown content."""
    pattern = r'<!-- VALIDATION_BLOCK\s*(\{.*?\})\s*END_VALIDATION_BLOCK -->'
    matches = re.findall(pattern, content, re.DOTALL)
    blocks = []
    for match in matches:
        try:
            blocks.append(json.loads(match))
        except json.JSONDecodeError:
            continue
    return blocks


def validate_trace_file(trace_path: str) -> TraceValidationReport:
    """Validate all functions documented in a trace file.

    Args:
        trace_path: Path to markdown trace file with VALIDATION_BLOCKs

    Returns:
        TraceValidationReport with all results
    """
    path = Path(trace_path)
    if not path.exists():
        return TraceValidationReport()

    content = path.read_text()
    blocks = parse_validation_block(content)

    report = TraceValidationReport(total_functions=len(blocks))

    for block in blocks:
        file_path = block.get("file")
        func_name = block.get("function")
        class_name = block.get("class")

        if not file_path or not func_name:
            continue

        report.validated += 1

        ground_truth = extract_function_info(file_path, func_name, class_name)
        if ground_truth is None:
            report.not_found += 1
            report.results.append({
                "function": f"{file_path}:{func_name}",
                "status": "NOT_FOUND",
                "message": "Could not extract function from source",
            })
            continue

        results = validate_claim(ground_truth, block)

        all_passed = all(r.valid for r in results)
        if all_passed:
            report.passed += 1
        else:
            report.failed += 1

        report.results.append({
            "function": f"{file_path}:{func_name}",
            "status": "PASS" if all_passed else "FAIL",
            "validations": [asdict(r) for r in results],
        })

    return report


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    command = sys.argv[1]

    if command == "extract":
        if len(sys.argv) < 4:
            print("Usage: validate-trace.py extract <file> <function> [class]")
            sys.exit(1)

        file_path = sys.argv[2]
        func_name = sys.argv[3]
        class_name = sys.argv[4] if len(sys.argv) > 4 else None

        info = extract_function_info(file_path, func_name, class_name)
        if info is None:
            print(json.dumps({"error": "Function not found"}))
            sys.exit(1)

        print(json.dumps(asdict(info), indent=2))

    elif command == "validate":
        if len(sys.argv) < 5:
            print("Usage: validate-trace.py validate <file> <function> '<json_claim>'")
            sys.exit(1)

        file_path = sys.argv[2]
        func_name = sys.argv[3]
        claim_json = sys.argv[4]

        try:
            claim = json.loads(claim_json)
        except json.JSONDecodeError as e:
            print(json.dumps({"error": f"Invalid JSON: {e}"}))
            sys.exit(1)

        info = extract_function_info(file_path, func_name)
        if info is None:
            print(json.dumps({"error": "Function not found"}))
            sys.exit(1)

        results = validate_claim(info, claim)
        output = {
            "valid": all(r.valid for r in results),
            "results": [asdict(r) for r in results],
        }
        print(json.dumps(output, indent=2))

    elif command == "batch":
        if len(sys.argv) < 3:
            print("Usage: validate-trace.py batch <trace_file>")
            sys.exit(1)

        trace_path = sys.argv[2]
        report = validate_trace_file(trace_path)
        print(json.dumps(asdict(report), indent=2))

    else:
        print(f"Unknown command: {command}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
