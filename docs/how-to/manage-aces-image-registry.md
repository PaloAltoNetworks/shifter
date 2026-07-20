# Manage the ACES Image Registry

The ACES image registry maps an authored ACES image `source` (a name and an
optional version) to a concrete provider image used at range realization. An
ACES scenario names its images by source; a tenant operator maps each source to
a real provider image here. Without a matching, enabled mapping (and no already
concrete image reference), realization fails loud.

This surface is part of the ACES native provisioning path. Every entry point is
gated by `SHIFTER_ACES_NATIVE_PROVISIONING`: with the flag off, the API and the
management command refuse and the SPA page is not served.

## Before You Start

You need:

- `SHIFTER_ACES_NATIVE_PROVISIONING=true` on the tenant.
- CMS authoring access (staff or the Threat Research group). The same access
  gates the Scenario Editor.
- The authored image `source` name and version from the scenario or package, and
  the concrete provider image reference to map it to (a GCE `source_image` or
  image family URL, or an AWS AMI id).

## Register or Update a Mapping

Registering is idempotent: it creates the mapping, or updates the existing one
for the same `(provider, source_name, source_version)`. A blank version is the
any-version fallback for that source name.

Choose one of the three surfaces. All three delegate to the same validated
service write path, so they behave identically.

### SPA (Author area)

1. Enable the platform SPA (`PLATFORM_SPA_ENABLED`) and open the portal.
2. Go to **Author > ACES Images**.
3. Fill in the provider, source name, optional version, and image reference,
   then choose **Register mapping**. Optional sizing fields (machine type, disk
   size, disk type) set backend defaults for that mapping.

### API

```sh
curl -sS -X POST https://<host>/api/v1/cms/aces-image-mappings/ \
    -H "Content-Type: application/json" \
    --cookie "sessionid=<session>" -H "X-CSRFToken: <token>" \
    -d '{"provider": "gce", "source_name": "alpine", "source_version": "3.19",
         "image_ref": "projects/<project>/global/images/family/<alpine-family>"}'
```

### Management command

```sh
python manage.py aces_image_registry --action register \
    --provider gce --source-name alpine --source-version 3.19 \
    --image-ref projects/<project>/global/images/family/<alpine-family>
```

## List Mappings

```sh
python manage.py aces_image_registry --action list
```

Add `--enabled-only` to hide disabled rows, or `--provider <name>` to filter to
one provider. The API is `GET /api/v1/cms/aces-image-mappings/` (query parameter
`include_disabled=false` to hide disabled rows); the SPA lists mappings on the
same **ACES Images** page.

## Disable a Mapping

Disabling keeps the row for audit and stops it from resolving at realization.
Use disable instead of deleting a mapping.

```sh
python manage.py aces_image_registry --action disable \
    --provider gce --source-name alpine --source-version 3.19
```

The API is `POST /api/v1/cms/aces-image-mappings/disable/`; the SPA has a
**Disable** action on each enabled row. Re-enable a mapping by registering it
again with the same natural key.

## Validation Package Mapping

The in-repo validation pack (`scenario-dev/shifter-aces-validation/`) authors a
single image with `source: {name: alpine, version: "3.19"}`. Before running the
ACES backend validation, register a `gce` mapping for `source_name=alpine`,
`source_version=3.19` pointing at a concrete Alpine-compatible GCE image or
image family. See
[aces-cutover-evidence-1264](../architecture/aces-cutover-evidence-1264.md) for
the full validation evidence contract.
