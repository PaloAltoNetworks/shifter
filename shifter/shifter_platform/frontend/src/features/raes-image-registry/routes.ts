/**
 * RAES image registry client-route paths (#1566).
 *
 * The Django host serves the SPA shell for `/raes-image-registry/*` GET paths,
 * so client-router deep links and refreshes resolve the same page. Keeping the
 * prefix in one place means a future re-mount changes one file.
 */
export const RAES_IMAGE_REGISTRY_BASE = "/raes-image-registry";

export const raesImageRegistryPath = (): string => `${RAES_IMAGE_REGISTRY_BASE}/`;
