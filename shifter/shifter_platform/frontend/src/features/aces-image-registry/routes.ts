/**
 * ACES image registry client-route paths (#1566).
 *
 * Greenfield SPA-only surface: there is no legacy Django page at this path. The
 * Django host serves the SPA shell for `/aces-image-registry/*` GET paths only
 * when `PLATFORM_SPA_ENABLED` and `SHIFTER_ACES_NATIVE_PROVISIONING` are both on
 * (see `config/urls.py`), so a client-router deep link or refresh resolves the
 * same page. Keeping the prefix in one place means a future re-mount changes one
 * file.
 */
export const ACES_IMAGE_REGISTRY_BASE = "/aces-image-registry";

export const acesImageRegistryPath = (): string => `${ACES_IMAGE_REGISTRY_BASE}/`;
