"""Render concrete image overrides into a GCP kustomization file."""

from __future__ import annotations

import argparse
import re
from pathlib import Path


def render_images_block(*, portal_image: str, guacd_image: str, guacamole_client_image: str, tag: str) -> str:
    return (
        "images:\n"
        "  - name: us-docker.pkg.dev/placeholder-project/shifter/portal\n"
        f"    newName: {portal_image}\n"
        f"    newTag: {tag}\n"
        "  - name: us-docker.pkg.dev/placeholder-project/shifter/guacd\n"
        f"    newName: {guacd_image}\n"
        f"    newTag: {tag}\n"
        "  - name: us-docker.pkg.dev/placeholder-project/shifter/guacamole-client\n"
        f"    newName: {guacamole_client_image}\n"
        f"    newTag: {tag}\n"
    )


def render_kustomization(
    source: str,
    *,
    portal_image: str,
    guacd_image: str,
    guacamole_client_image: str,
    tag: str,
) -> str:
    pattern = re.compile(r"^images:\n.*?(?=^patches:)", flags=re.MULTILINE | re.DOTALL)
    replacement = render_images_block(
        portal_image=portal_image,
        guacd_image=guacd_image,
        guacamole_client_image=guacamole_client_image,
        tag=tag,
    )
    rendered, count = pattern.subn(replacement, source)
    if count != 1:
        raise ValueError("Expected exactly one images block in kustomization.yaml")
    return rendered


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kustomization", required=True, help="Path to the kustomization.yaml file to update.")
    parser.add_argument("--portal-image", required=True, help="Full Artifact Registry image root for the Shifter portal image.")
    parser.add_argument("--guacd-image", required=True, help="Full Artifact Registry image root for the guacd image.")
    parser.add_argument(
        "--guacamole-client-image",
        required=True,
        help="Full Artifact Registry image root for the Guacamole client image.",
    )
    parser.add_argument("--tag", required=True, help="Image tag to apply to all rendered image roots.")
    args = parser.parse_args()

    path = Path(args.kustomization)
    rendered = render_kustomization(
        path.read_text(),
        portal_image=args.portal_image,
        guacd_image=args.guacd_image,
        guacamole_client_image=args.guacamole_client_image,
        tag=args.tag,
    )
    path.write_text(rendered)


if __name__ == "__main__":
    main()
