# polaris-dc—GDC-native Windows DC image tooling

Build assets for a Windows Server 2022 domain controller (`BOREAS.LOCAL`) that
installs and runs natively on **GDC VM Runtime**, producing a not-sysprepped
golden qcow2 that ranges boot directly for fast spin-ups.

A GCE-built Windows image cannot boot on GDC's KubeVirt/QEMU, so this uses the
documented native ISO-install flow instead of the Linux GCE-packer-export path.

## Files

| File | Purpose |
|---|---|
| `autounattend.xml` | Fully unattended WS2022 install answer file (tuned for GDC's headless VMs). |
| `bake.ps1` | FirstLogon bake: full virtio driver store → GDC guest agent → OpenSSH → AD DS/DNS → promote `BOREAS.LOCAL` → (SYSTEM AtStartup task) `a2_setup` content seed → `BAKE_DONE`. |

`a2_setup.ps1` (the BOREAS.LOCAL content: OUs/users/groups/SPNs/flags) is shared
with the AWS build and lives in `scripts/polaris-aws-range/`.

## How it works, gotchas, and the full debugging history

See **[docs/architecture/gdc-windows-dc-image-build.md](../../../docs/architecture/gdc-windows-dc-image-build.md)**
for the complete build pipeline (ISO repack, install VM on cluster1, export),
the non-obvious `autounattend.xml` requirements, the GDC guest-agent mechanism,
the cluster-storage/scheduling gotchas, the headless-VM observability channels,
and the layer-by-layer debugging lessons.

## Making a DC with a different domain

The domain is currently hard-coded (`BOREAS.LOCAL`). To stamp per-event DCs with
different domains, parameterize the domain in `bake.ps1`
(`Install-ADDSForest -DomainName …`) and in `a2_setup.ps1`, then rebuild the
answer ISO and re-run the build to produce a new golden qcow2.
