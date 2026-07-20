/**
 * Risk Register client-route paths.
 *
 * The Risk Register is rehomed under the unified platform router (#1369): the
 * client router now runs at basename `/`, so Risk Register links are absolute
 * paths under the `/risk-register` prefix rather than root-relative paths. These
 * helpers keep the prefix in one place so a future re-mount changes one file.
 */
export const RISK_REGISTER_BASE = "/risk-register";

export const riskListPath = (): string => RISK_REGISTER_BASE;
export const riskCreatePath = (): string => `${RISK_REGISTER_BASE}/risks/create`;
export const riskPath = (id: number | string): string => `${RISK_REGISTER_BASE}/risks/${id}`;
export const riskEditPath = (id: number | string): string => `${RISK_REGISTER_BASE}/risks/${id}/edit`;
