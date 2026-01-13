---
description: Line-by-line, function-by-function code flow analysis with AST validation
argument-hint: <entry-point> -o [output-file]
---

# Code Flow Trace Analysis (with Ground Truth Validation)

## Input

- **Entry Point**: `$1` (required) - File path with function name (e.g., `cms/services.py:create_range`)
- **Output File**: `-o` (optional) - Analysis document path (default: `temp/trace-analysis.md`)

## Operating Mode: STRICTLY INCREMENTAL + VALIDATED. NO BATCHING.

You MUST:
1. Update the analysis document AFTER EACH FUNCTION before moving to the next. Do not batch analysis document updates.
2. Run AST validation AFTER documenting each function
3. Record any issues in the analysis document
4. DO NOT correct any issues. This is an analysis only task, not a code fix task.

This is NON-NEGOTIABLE. The purpose is to build understanding incrementally AND ensure accuracy.

## Boundaries

- **Stop at framework code**: Do NOT trace into Django ORM, views base classes, stdlib, or third-party libraries
- **Max depth**: 10 levels. Beyond that, summarize remaining calls without full trace
- **Direction**: Forward only (entry point → called functions, depth-first)

## Execution Protocol

### Phase 0: Initialize

1. Parse entry point from `$1` (format: `path/to/file.py:function_name` or `path/to/file.py:ClassName.method`)
2. Determine output file from `$2` or default to `temp/trace-analysis.md`
3. Get current git branch via `git branch --show-current`
4. Verify validation script exists: `.claude/scripts/validate-trace.py`
5. Create/overwrite output file with header:

```markdown
# Code Flow Trace: {entry_point}

**Generated**: {YYYY-MM-DD HH:MM}
**Branch**: {git_branch}
**Entry**: {file}:{function}
**Validation**: AST-grounded

---

## Validation Summary

| # | Function | Status | Issues |
|---|----------|--------|--------|

---

## Call Sequence
```

### Phase 1: Entry Point Analysis

1. **EXTRACT GROUND TRUTH FIRST**:
   ```bash
   python .claude/scripts/validate-trace.py extract {file} {function}
   ```
   Parse the JSON output - this is your authoritative source for:
   - Exact function signature
   - Exact parameter names and types
   - Exact return type
   - Actual calls made (with line numbers)
   - Exceptions raised

2. Read the entry point file to understand context and logic

3. Document in output file using ground truth data:
   - Function signature (FROM AST OUTPUT - do not paraphrase)
   - Purpose (1-2 sentences max - your interpretation)
   - Parameters (FROM AST - names, types; you add validation notes)
   - Return type (FROM AST)
   - Calls list (FROM AST - you can add context)

4. **EMIT VALIDATION BLOCK** immediately after the section:
   ```markdown
   <!-- VALIDATION_BLOCK
   {
     "file": "{file_path}",
     "function": "{func_name}",
     "lineno": {line_number},
     "returns": "{return_type}",
     "args": ["arg1", "arg2"],
     "annotations": {"arg1": "Type1", "arg2": "Type2"},
     "calls": ["func1", "func2"]
   }
   END_VALIDATION_BLOCK -->
   ```

5. **CHECKPOINT**: Write section to output file NOW

### Phase 2: Trace Each Call (REPEAT for each called function)

For EACH function/method called from current scope, in order of appearance:

1. **IDENTIFY**: What is being called? Note line number in caller (from AST calls list)

2. **LOCATE**: Find the definition file and line number

3. **BOUNDARY CHECK**: Is this in your app code?
   - If Django/stdlib/third-party → Note as "EXTERNAL: {module}" and skip
   - If app code → Continue

4. **DEPTH CHECK**: Are we at depth 10+?
   - If yes → Note as "DEPTH LIMIT: summarize only" and don't recurse

5. **EXTRACT GROUND TRUTH**:
   ```bash
   python .claude/scripts/validate-trace.py extract {file} {function}
   ```

6. **READ**: Read the called function to understand logic

7. **DOCUMENT** using ground truth + your analysis:
   - Sequence number and file:line (FROM AST)
   - Function signature (FROM AST - verbatim)
   - What it does (your interpretation)
   - Side effects (your analysis)
   - Error handling (FROM AST raises + your analysis)
   - Data transformations (your analysis)
   - What it calls (FROM AST)

8. **EMIT VALIDATION BLOCK**

9. **CHECKPOINT**: Append section to output file NOW

10. **RECURSE**: Process this function's calls before returning to caller's next call

### Phase 3: Validation Report

After all functions traced:

1. **RUN BATCH VALIDATION**:
   ```bash
   python .claude/scripts/validate-trace.py batch {output_file}
   ```

2. Parse the JSON report and update the Validation Summary table at the top

3. If any FAIL results:
   - Go back and correct the documented information
   - Re-run validation until all pass

### Phase 4: Summary

Append to output file:

1. **Call Graph** (text-based tree showing call hierarchy)
2. **Files Touched** (list of all files read during trace)
3. **Data Flow** (how data transforms from entry to exit)
4. **Validation Results**: X/Y functions validated, all passed/N failures
5. **Potential Issues** (if any observed):
   - Missing error handling
   - Type mismatches
   - Inconsistent return types
   - Unvalidated inputs

## Output Document Format

Each function section follows this template:

```markdown
---

### {N}. `{file}:{line}` - `{function_name}`

**Signature**:
```python
def function_name(param: Type, ...) -> ReturnType:
```

**Purpose**: Brief description of what this function does.

**Parameters**:
| Name | Type | Default | Description |
|------|------|---------|-------------|
| param | Type | - | What it represents |

**Returns**: `ReturnType` - Description of return value and conditions

**Calls** (in order, from AST):
1. Line {X}: `other_function()` → #{next_seq} (or EXTERNAL)
2. Line {Y}: `Model.objects.filter()` → EXTERNAL: Django ORM

**Side Effects**: None / List any DB writes, API calls, file I/O

**Error Handling**:
- Raises `ExceptionType` when {condition}
- Catches `ExceptionType` and {behavior}

**Notes**: Any observations about code quality, edge cases, or concerns

<!-- VALIDATION_BLOCK
{
  "file": "path/to/file.py",
  "function": "function_name",
  "lineno": 123,
  "returns": "ReturnType",
  "args": ["param"],
  "annotations": {"param": "Type"},
  "calls": ["other_function"]
}
END_VALIDATION_BLOCK -->
```

## Rules (MUST follow)

1. **AST IS AUTHORITATIVE** - For signatures, types, args, calls - use the validation script output
2. **ONE function, ONE update** - Never analyze multiple functions before writing to output
3. **VALIDATE AFTER EACH** - Run validation after documenting each function
5. **Preserve exact signatures** - Copy function signatures verbatim from AST output
6. **Include line numbers** - Every reference includes file:line (from AST)
7. **Flag unknowns** - If you can't find a definition, note it explicitly as "NOT FOUND"
8. **Mark boundaries** - Clearly label EXTERNAL calls (don't trace into them)
9. **Respect depth limit** - At depth 10, summarize remaining calls without recursing
10. **Sequential numbering** - Number each function section for cross-referencing

## Example Usage

```bash
# Trace a service function
/code-trace cms/services.py:create_range

# Trace with custom output location
/code-trace cms/services.py:create_range temp/create-range-trace.md

# Trace a view method
/code-trace mission_control/views.py:RangeCreateView.post
```

## Now Execute

Entry point: `$1`
Output file: `$2` (or `temp/trace-analysis.md` if not provided)

Begin Phase 0 immediately. Remember: AST output is ground truth for all structural claims.
