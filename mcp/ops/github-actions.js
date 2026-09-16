// GitHub Actions workflow-dispatch helpers for the shifter-ops MCP
// server (AMI build/promote — issue #411; GCE image build/promote —
// issue #505, PLAT-001.10).
//
// User-controlled values land as literal argv elements via
// buildGhWorkflowRunArgs; no shell interpolation (ADR-010). The GitHub
// token stays child-environment-only (resolved inside ghExec).

import {
  DEFAULT_GITHUB_REPO,
  buildGhWorkflowRunArgs,
  ghExec,
  resolveProtectedAmiRef,
} from "./lib.js";

export function triggerAmiWorkflow(
  { workflow, ami_type, ref, actionsPath },
  ghOptions = {},
) {
  // Base/DC AMI builds and prod promotions run only from a protected ref
  // (dev|main); reject a working-tree feature branch rather than dispatch a
  // workflow copy that could weaken its own inline protected-ref gate (#1656).
  const branch = resolveProtectedAmiRef(ref);
  ghExec(
    buildGhWorkflowRunArgs({
      workflow,
      repo: DEFAULT_GITHUB_REPO,
      ref: branch,
      inputs: { ami_type },
    }),
    ghOptions,
  );
  return (
    `Triggered ${workflow} for ${ami_type} on ref ${branch}. ` +
    `View at: https://github.com/${DEFAULT_GITHUB_REPO}/actions/workflows/${actionsPath}`
  );
}

// GCE image build/promote (issue #505, PLAT-001.10). Parallel to
// triggerAmiWorkflow but passes the GCP-scoped `image_type` workflow input
// (the GCE workflows never use the AWS `ami_type` input name). The dispatch
// `--ref` is the single source of truth for the built branch and is restricted
// to dev/main before dispatch: the GCE
// workflows check out the dispatched ref (github.sha) rather than a separate
// free-form input, so the branch reported here is the branch actually built.
export function triggerGceImageWorkflow({
  workflow,
  inputs,
  ref,
  actionsPath,
}, ghOptions = {}) {
  const branch = resolveProtectedAmiRef(ref);
  ghExec(
    buildGhWorkflowRunArgs({
      workflow,
      repo: DEFAULT_GITHUB_REPO,
      ref: branch,
      inputs,
    }),
    ghOptions,
  );
  const releaseIdentity = inputs.image_type ?? inputs.source_image;
  return (
    `Triggered ${workflow} for ${releaseIdentity} on ref ${branch}. ` +
    `View at: https://github.com/${DEFAULT_GITHUB_REPO}/actions/workflows/${actionsPath}`
  );
}
