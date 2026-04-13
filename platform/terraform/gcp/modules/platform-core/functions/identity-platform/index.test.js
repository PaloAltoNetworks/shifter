const test = require("node:test");
const assert = require("node:assert/strict");

const { beforeCreateImpl, beforeSignInImpl } = require("./index");

test("beforeCreateImpl allows paloaltonetworks.com registrations", async () => {
  process.env.ALLOWED_EMAIL_DOMAIN = "paloaltonetworks.com";
  process.env.ALLOWED_EMAILS = "";

  await assert.doesNotReject(async () => {
    await beforeCreateImpl({ email: "analyst@paloaltonetworks.com" });
  });
});

test("beforeCreateImpl allows explicitly whitelisted emails", async () => {
  process.env.ALLOWED_EMAIL_DOMAIN = "paloaltonetworks.com";
  process.env.ALLOWED_EMAILS = "external@example.com";

  await assert.doesNotReject(async () => {
    await beforeCreateImpl({ email: "external@example.com" });
  });
});

test("beforeCreateImpl rejects non-corporate registrations", async () => {
  process.env.ALLOWED_EMAIL_DOMAIN = "paloaltonetworks.com";
  process.env.ALLOWED_EMAILS = "";

  await assert.rejects(
    async () => {
      await beforeCreateImpl({ email: "intruder@example.com" });
    },
    (error) => {
      assert.equal(error.code, 403);
      assert.match(error.message, /Only @paloaltonetworks\.com users may self-register/);
      return true;
    }
  );
});

test("beforeSignInImpl allows paloaltonetworks.com sign-ins", async () => {
  process.env.ALLOWED_EMAIL_DOMAIN = "paloaltonetworks.com";
  process.env.ALLOWED_EMAILS = "";

  await assert.doesNotReject(async () => {
    await beforeSignInImpl({ email: "analyst@paloaltonetworks.com" });
  });
});

test("beforeSignInImpl allows whitelisted non-PAN sign-ins", async () => {
  process.env.ALLOWED_EMAIL_DOMAIN = "paloaltonetworks.com";
  process.env.ALLOWED_EMAILS = "external@example.com";

  await assert.doesNotReject(async () => {
    await beforeSignInImpl({ email: "external@example.com" });
  });
});

test("beforeSignInImpl rejects non-corporate sign-ins (even if already created)", async () => {
  process.env.ALLOWED_EMAIL_DOMAIN = "paloaltonetworks.com";
  process.env.ALLOWED_EMAILS = "";

  await assert.rejects(
    async () => {
      await beforeSignInImpl({ email: "stale@example.com" });
    },
    (error) => {
      assert.equal(error.code, 403);
      assert.match(error.message, /Only @paloaltonetworks\.com users may access/);
      return true;
    }
  );
});
