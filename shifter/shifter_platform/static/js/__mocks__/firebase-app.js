// Test double for the Firebase modular app SDK (loaded in production from the
// gstatic CDN). Mapped in via jest moduleNameMapper so the auth module's
// gstatic imports resolve to controllable jest mocks.
export const initializeApp = jest.fn(() => ({ name: "[DEFAULT]" }));
export const getApps = jest.fn(() => []);
export const getApp = jest.fn(() => ({ name: "[DEFAULT]" }));
