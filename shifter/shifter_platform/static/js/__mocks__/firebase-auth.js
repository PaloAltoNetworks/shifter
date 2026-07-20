// Test double for the Firebase modular auth SDK. Each export is a jest mock so
// tests can drive sign-in, registration, email-verification, and TOTP MFA flows
// and assert how the auth module reacts.
export const browserSessionPersistence = { type: "SESSION" };

// onAuthStateChanged stores the most recent observer so a test can simulate the
// SDK firing an auth-state change.
export let lastAuthObserver = null;
export const onAuthStateChanged = jest.fn((auth, observer) => {
    lastAuthObserver = observer;
    return () => {};
});

// Shared auth instance so a test can mutate currentUser after the module under
// test has captured the reference at import time.
export const authInstance = { currentUser: null };
export const getAuth = jest.fn(() => authInstance);
export const setPersistence = jest.fn(async () => {});
export const signInWithEmailAndPassword = jest.fn(async () => ({ user: {} }));
export const createUserWithEmailAndPassword = jest.fn(async () => ({ user: {} }));
export const signOut = jest.fn(async () => {});
export const reload = jest.fn(async () => {});
export const sendEmailVerification = jest.fn(async () => {});
export const multiFactor = jest.fn(() => ({
    enrolledFactors: [],
    getSession: jest.fn(async () => ({ session: "s" })),
    enroll: jest.fn(async () => {}),
}));
export const getMultiFactorResolver = jest.fn(() => ({
    hints: [],
    resolveSignIn: jest.fn(async () => ({ user: {} })),
}));
export const TotpMultiFactorGenerator = {
    FACTOR_ID: "totp",
    generateSecret: jest.fn(async () => ({
        generateQrCodeUrl: () => "otpauth://totp/Shifter",
        secretKey: "SECRETKEY234567",
    })),
    assertionForEnrollment: jest.fn(() => ({ assertion: "enroll" })),
    assertionForSignIn: jest.fn(() => ({ assertion: "signin" })),
};
