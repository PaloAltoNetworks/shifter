const test = require("node:test");
const assert = require("node:assert/strict");

const { beforeCreateImpl } = require("./index");

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
