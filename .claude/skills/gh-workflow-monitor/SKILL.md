---
name: gh-workflow-monitor
description: "Monitor GitHub Actions workflow runs for the current branch, diagnose failures from logs, propose fixes, and report CI/CD status. Use when the user asks about pipeline failures, build status, workflow errors, or wants to check if CI is green."
disable-model-invocation: true
---

# GitHub Workflow Monitor

Monitor GitHub Actions runs, diagnose failures, and propose fixes using `gh` CLI.

## Step 1: Identify Branch and Workflow Runs

1. Get the current branch: `git branch --show-current`
2. List recent runs: `gh run list --branch <branch> --limit 5 --json status,conclusion,databaseId,name,event,createdAt`
3. If no runs found, tell the user and stop.

## Step 2: Check Run Status

1. Find the latest run from Step 1.
2. If the run is **in progress**, watch it: `gh run watch <id>`
3. If the run **succeeded**, skip to Step 5.
4. If the run **failed**, proceed to Step 3.

## Step 3: Diagnose Failures

1. Get the failed job logs: `gh run view <id> --log-failed`
2. If logs are too large, narrow to a specific job: `gh run view <id> --job <job-id> --log-failed`
3. Identify the root cause from the log output (compile error, test failure, linting, timeout, permissions, etc.).
4. Check if the failure is in application code or CI configuration (`.github/workflows/*.yml`).

## Step 4: Propose Fix

1. Based on the diagnosis, propose a specific fix:
   - **Code failure**: identify the file and line, suggest the change.
   - **CI config issue**: identify the workflow file and the failing step.
   - **Flaky/transient failure**: suggest a re-run: `gh run rerun <id> --failed`
2. If a code fix is applied, remind the user to commit, push, and re-run from Step 1.

## Step 5: Report Status

Summarize:
- Branch name
- Workflow run URL: `gh run view <id> --web` (or print the URL)
- Status and conclusion
- If failed: root cause and proposed fix
- If passed: "CI is green — ready to proceed."
