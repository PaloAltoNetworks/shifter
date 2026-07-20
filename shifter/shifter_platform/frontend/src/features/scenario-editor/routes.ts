/**
 * Scenario Editor client-route paths (#1371).
 *
 * The Scenario Editor still has a live legacy Django app at these same paths
 * (`cms/scenario_editor/urls.py`); every path builder here matches its page
 * paths exactly, trailing slash included, so a client-router deep link or
 * refresh resolves the same page the Django host would have served (the backend
 * catch-all serves the SPA shell for any non-action `/scenario-editor/*` path
 * once both SPA flags are on). Keeping the prefix in one place means a future
 * re-mount changes one file.
 */
export const SCENARIO_EDITOR_BASE = "/scenario-editor";

export const scenarioListPath = (): string => `${SCENARIO_EDITOR_BASE}/`;
export const scenarioCreatePath = (): string => `${SCENARIO_EDITOR_BASE}/create/`;
export const scenarioYamlCreatePath = (): string => `${SCENARIO_EDITOR_BASE}/create/yaml/`;
export const scenarioPath = (id: string): string => `${SCENARIO_EDITOR_BASE}/${id}/`;
export const scenarioEditPath = (id: string): string => `${SCENARIO_EDITOR_BASE}/${id}/edit/`;
export const scenarioYamlEditPath = (id: string): string => `${SCENARIO_EDITOR_BASE}/${id}/editor/`;
