// Intentional no-op replacement for node-forge.
//
// node-forge is pulled in only transitively by gcip-cloud-functions and is never
// imported by the SDK runtime (package/lib/** contains no require('node-forge'))
// or by this function: the inbound Identity Platform event JWT is verified via
// jsonwebtoken (Node's built-in crypto), not node-forge.
//
// The published node-forge (<= 1.4.0, currently the latest) carries an unpatched
// HIGH advisory, CVE-2026-85393 / GHSA-86w9-cpqp-85rv (an incomplete fix for
// CVE-2026-33894), with no fixed release available. Rather than ship dormant,
// vulnerable crypto, the unused implementation is replaced with this empty module:
// package.json declares node-forge as a direct `file:` dependency on this folder,
// so npm installs only this local copy and no vulnerable node-forge enters the
// tree. See README.md for the version rationale and removal path.
//
// If a future gcip-cloud-functions version actually imports node-forge, resolving
// it to this empty object will fail loudly and this must be revisited.
module.exports = {};
