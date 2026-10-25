# Access credentials

Open **Operate → Access credentials** to manage personal tokens or, when
authorized, independent service identities. These are platform API credentials,
not the SCM/deployment credentials under Assets.

Temporary participants continue using their isolated account login and established
password recovery/reset controls, without requiring email. The old CTF magic-link
login was retired in migration 0033 (#1206). It is not restored by this change.

## Personal tokens

A normal human session can list and revoke its own credentials. Issuing or
rotating also requires the live `installation.use_personal_tokens` grant and
current authority for every requested action on the selected target. Staff or
superuser status alone does not grant issuance. The API checks the token-use
grant again whenever a personal token authenticates.

Choose a name, action, target UUID where required, and expiration. The server
enforces `API_TOKEN_MAX_TTL_DAYS` (default 365, supported range 1–365 days).
Copy the returned secret into your approved credential store: it is shown only
once, is not recoverable, and is not placed in browser storage or query caches.
Never put it in URLs, logs, screenshots, shell command arguments or tickets.
The UI exposes one action per issuance; the API accepts an explicit action list
for one target. No wildcard scopes are accepted.

Rotation issues a replacement and revokes the selected token atomically. Update
the consuming client with the one-time replacement. Revocation remains available
after loss of issuance rights. A bearer cannot issue or rotate personal tokens.
The Django token admin is metadata-only; Knox's stock credential admin is absent.

Legacy custom tokens are displayed as requiring reissue. They cannot be converted
into Knox secrets, and this source contains no compatibility verifier. Apply the
coordinated ADR-066 S8 cutover, reissue authorized personal credentials, and replace
automation credentials with independent native service identities as appropriate.

## Independent service identities

An authorized administrator registers the Google service account's immutable
numeric unique ID, an independent Shifter principal and a credential action
ceiling. To obtain the non-secret ID:

```bash
gcloud iam service-accounts describe agent@synthetic-project.iam.gserviceaccount.com \
  --format='value(uniqueId)'
```

Email is not an identity key. The portal accepts an exact Google issuer/subject
binding and the configured application audience, not a cloud access token or a
human Firebase token. Disable an admission to stop that credential configuration;
disable the principal to stop all its admissions. Register a replacement admission
against the existing principal UUID after disabling the old one to change ceilings
without replacing the service identity.

Admission grants no application permission or cloud IAM role. Assign application
policies to the service principal UUID and cloud IAM roles to the Google identity
separately. Removing its human creator/contact does not transfer or destroy the
service's authority. Services can receive event participation through the existing
CTF participation lifecycle; they do not require dummy human accounts.

See [native client setup and security contracts](../technical/shifter_platform/access-credentials.md)
for attached workloads, local impersonation, external federation and renewal limits.
