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
  if (!normalizedEmail || !normalizedEmail.includes("@")) {
    return false;
  }

  if (allowedEmails().has(normalizedEmail)) {
    return true;
  }

  return normalizedEmail.endsWith(`@${allowedDomain()}`);
}

async function beforeCreateImpl(user) {
  if (!isAllowedEmail(user.email)) {
    throw new gcipCloudFunctions.https.HttpsError(
      "permission-denied",
      `Only @${allowedDomain()} users may self-register for corporate access.`
    );
  }

  return {};
}

exports.beforeCreateImpl = beforeCreateImpl;
exports.beforeCreate = authClient.functions().beforeCreateHandler(beforeCreateImpl);
