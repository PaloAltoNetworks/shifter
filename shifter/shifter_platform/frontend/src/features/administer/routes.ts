/**
 * Administer workspace client-route paths (#1373).
 *
 * The workspace runs under the unified platform router (basename `/`) at the
 * `/administer` prefix. Django admin stays at `/admin/` and is never linked from
 * here as a SPA-native workflow. Keeping the prefix in one place means a future
 * re-mount changes one file.
 */
export const ADMINISTER_BASE = "/administer";

export const usersListPath = (): string => ADMINISTER_BASE;
export const userPath = (id: number | string): string => `${ADMINISTER_BASE}/users/${id}`;
export const costPath = (): string => `${ADMINISTER_BASE}/cost`;
export const platformSettingsPath = (): string => `${ADMINISTER_BASE}/settings`;
