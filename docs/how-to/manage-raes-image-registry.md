# Manage the RAES Image Registry

The RAES image registry maps an authored RAES image `source` (a name and an
optional version) to a concrete provider image used at range realization. An
RAES scenario names its images by source; a tenant operator maps each source to
a real provider image here. Without a matching, enabled mapping (and no already
concrete image reference), realization fails loud.

This surface is part of the only supported range-provisioning path. The API,
management command, and SPA page are always available to authorized operators.

## Before You Start

You need:

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

1. Open the portal and go to **Author > RAES Images**.
2. Fill in the provider, source name, optional version, and image reference,
   then choose **Register mapping**. Optional sizing fields (machine type, disk
   size, disk type) set backend defaults for that mapping.

### API

```sh
curl -sS -X POST https://<host>/api/v1/cms/raes-image-mappings/ \
    -H "Content-Type: application/json" \
    --cookie "sessionid=<session>" -H "X-CSRFToken: <token>" \
    -d '{"provider": "gce", "source_name": "alpine", "source_version": "3.19",
         "image_ref": "projects/<project>/global/images/family/<alpine-family>"}'
```

### Management command

```sh
python manage.py raes_image_registry --action register \
    --provider gce --source-name alpine --source-version 3.19 \
    --image-ref projects/<project>/global/images/family/<alpine-family>
```

## List Mappings

```sh
python manage.py raes_image_registry --action list
```

Add `--enabled-only` to hide disabled rows, or `--provider <name>` to filter to
one provider. The API is `GET /api/v1/cms/raes-image-mappings/` (query parameter
`include_disabled=false` to hide disabled rows); the SPA lists mappings on the
same **RAES Images** page.

## Disable a Mapping

Disabling keeps the row for audit and stops it from resolving at realization.
Use disable instead of deleting a mapping.

```sh
python manage.py raes_image_registry --action disable \
    --provider gce --source-name alpine --source-version 3.19
```

The API is `POST /api/v1/cms/raes-image-mappings/disable/`; the SPA has a
**Disable** action on each enabled row. Re-enable a mapping by registering it
again with the same natural key.

## Validation Package Mapping

The in-repo validation pack (`scenario-dev/shifter-raes-validation/`) authors a
single image with `source: {name: alpine, version: "3.19"}`. Before running the
RAES backend validation, register a `gce` mapping for `source_name=alpine`,
`source_version=3.19` pointing at a concrete Alpine-compatible GCE image or
image family. See
[the architecture registry](../adr/index.yaml) for
the full validation evidence contract.
