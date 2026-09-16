const gcipCloudFunctions = require("gcip-cloud-functions");

const authClient = new gcipCloudFunctions.Auth();

function normalize(value) {
  return (value || "").trim().toLowerCase();
}

function allowedDomain() {
  return normalize(process.env.ALLOWED_EMAIL_DOMAIN || "paloaltonetworks.com");
}

function allowedEmails() {
  return new Set(
    (process.env.ALLOWED_EMAILS || "")
      .split(",")
      .map((item) => normalize(item))
      .filter(Boolean)
  );
}

function isAllowedEmail(email) {
  const normalizedEmail = normalize(email);
  if (!normalizedEmail?.includes("@")) {
    return false;
  }

  if (allowedEmails().has(normalizedEmail)) {
    return true;
  }

  return normalizedEmail.endsWith(`@${allowedDomain()}`);
}

async function beforeCreateImpl(user) {
  if (!isAllowedEmail(user?.email)) {
    // Keep the rejection generic: it must not disclose the approved domain to
    // an unauthenticated registrant (issue #1920).
    throw new gcipCloudFunctions.https.HttpsError(
      "permission-denied",
      "This email address is not permitted to self-register for corporate access."
    );
  }

  return {};
}

exports.beforeCreateImpl = beforeCreateImpl;
exports.beforeCreate = authClient.functions().beforeCreateHandler(beforeCreateImpl);
