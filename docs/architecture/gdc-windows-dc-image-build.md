# Building Windows DC Images for GDC VM Runtime (native ISO install)

How Shifter builds a Windows Server 2022 domain-controller image (for example the
polaris `BOREAS.LOCAL` DC) that **boots and runs on GDC VM Runtime**, and why it
uses a native ISO install rather than the GCE-packer-export path used for the
Linux guests.

This is the Windows counterpart to [gcp-guest-images.md](./gcp-guest-images.md).
Read that first for the general GCP image flow.

## Why not GCE packer + export (the Linux path)

The Linux guests (Kali, Ubuntu) are built with `googlecompute` packer, exported
to `gs://…/<type>.qcow2`, and imported by the range provisioner. **That path
does not work for Windows.** A GCE-built image is tuned for GCE's hypervisor
(gVNIC, GCE guest environment, GCE boot config, Shielded-VM Secure Boot). GDC VM
Runtime is a *different* hypervisor—KubeVirt/QEMU on bare metal—so a
GCE-exported Windows qcow2 will not boot on it:

- GDC boots the VM with **legacy SeaBIOS** by default; the GCE Windows image is
  UEFI/GPT → `No bootable device`.
- With UEFI enabled, GDC's OVMF has **no Microsoft UEFI CA keys enrolled**, so
  Secure Boot rejects the signed Windows bootloader → `Access Denied`.
- The exported image loses its NVRAM boot entries, so OVMF falls back to
  `\EFI\Boot\bootx64.efi`, which Windows install media does not populate.
- The image carries no virtio drivers, so KubeVirt's virtio disk/NIC are
  invisible to the guest.

Linux survives cross-porting because Linux images are hypervisor-portable;
Windows is not. The supported approach (per Google's
[Create a Windows VM from ISO](https://docs.cloud.google.com/kubernetes-engine/distributed-cloud/bare-metal/docs/vm-runtime/windows-vm))
is to **install Windows natively on GDC from an ISO**, so the installer lays
down a correct UEFI/GPT/ESP layout and binds virtio drivers by construction. We
automate that documented (interactive) flow into a repeatable golden-image
build.

## Pipeline overview

```
Windows Server 2022 eval ISO ──(repack)──► noprompt+UDF ISO ──► gs://…/iso/ws2022-noprompt.iso
                                                                        │
answer ISO (autounattend.xml + $WinPEDriver$/{viostor,NetKVM} + bake.ps1 + a2_setup.ps1)
                                                        └─► gs://…/iso/polaris-answer.iso
                                                                        │
     build VM on cluster1 (empty VIRTIO boot disk + windows-iso + virtio-driver + answer)
                                                                        │
   Setup auto-loads viostor from $WinPEDriver$ → installs on virtio → OOBE auto-skip →
   FirstLogon bake.ps1 → NetKVM, guest agent, OpenSSH, promote BOREAS.LOCAL,
   (SYSTEM AtStartup task) a2_setup content seed → BAKE_DONE → clean shutdown
                                                                        │
             export the boot disk → gs://…/polaris-dc.qcow2  (the golden image)
                                                                        │
             range provisioner boots the golden qcow2 (fast, not sysprepped)
```

The golden image is **not sysprepped**: every range gets an identical
`BOREAS.LOCAL` DC. That is correct here—each range is isolated on its own vxlan
so identical DCs never collide, and the scenario expects `BOREAS.LOCAL`.
Sysprep would only add first-boot delay.

## Artifacts (`shifter/gdc-vm-images/polaris-dc/`)

| File | Purpose |
|---|---|
| `autounattend.xml` | Fully unattended WS2022 install answer file (see gotchas below). |
| `bake.ps1` | FirstLogon bake: virtio drivers → guest agent → OpenSSH → AD DS/DNS → promote → (RunOnce) `a2_setup` → `BAKE_DONE`. |
| `a2_setup.ps1` | (Shared with the AWS build, `scripts/polaris-aws-range/`) creates the BOREAS.LOCAL OUs/users/groups/SPNs/flags. |

## Building the ISOs

### 1. The Windows ISO (noprompt + UDF)

The stock Windows ISO cannot be used as-is for a headless unattended install:
it prompts *"Press any key to boot from CD or DVD…"* which nobody can answer,
and a plain repack loses the UDF filesystem Setup needs to read the >4 GB
`install.wim`. Repack it:

```bash
# Mount the MS ISO (it is UDF; xorriso -osirrox only sees the tiny ISO9660 view)
sudo mount -o loop,ro ws2022.iso /mnt/iso
cp -rL /mnt/iso/. iso-root/ && chmod -R u+w iso-root
sudo umount /mnt/iso

# (optional) split install.wim so it also fits ISO9660 tooling limits
wimlib-imagex split iso-root/sources/install.wim iso-root/sources/install.swm 3800
rm iso-root/sources/install.wim

# Rebuild with UDF (Windows install media is UDF) + the NON-prompting UEFI boot
# image (efisys_noprompt.bin ships on the ISO next to efisys.bin).
genisoimage -iso-level 3 -J -joliet-long -D -relaxed-filenames \
  -allow-limited-size -udf -V "SSS_X64FREE_EN_US_DV9" \
  -b boot/etfsboot.com -no-emul-boot -boot-load-size 8 -boot-info-table \
  -eltorito-alt-boot -e efi/microsoft/boot/efisys_noprompt.bin -no-emul-boot \
  -o ws2022-noprompt.iso iso-root
gcloud storage cp ws2022-noprompt.iso gs://<project>-gcp-dev-gdc-vm-images/iso/
```

> `xorriso -as mkisofs` in this environment rejects `-udf`; use `genisoimage`.
> UDF matters: without it Setup reports *"Windows cannot find the Microsoft
> Software License Terms / installation sources are not valid"* when it tries to
> read the install image.

### 2. The answer ISO

A tiny ISO with `autounattend.xml` at the root and the `polaris/` scripts. Keep
it as a **separate disk** from the Windows ISO so answer-file iterations rebuild
in seconds instead of repacking 5.5 GB:

```python
import pycdlib
iso = pycdlib.PyCdlib(); iso.new(joliet=3, vol_ident='POLARIS_ANSWER')
iso.add_file("autounattend.xml", "/AUTOUNAT.XML;1", joliet_path="/autounattend.xml")
iso.add_directory("/POLARIS", joliet_path="/polaris")
iso.add_file("bake.ps1",     "/POLARIS/BAKE.PS1;1",   joliet_path="/polaris/bake.ps1")
iso.add_file("a2_setup.ps1", "/POLARIS/A2SETUP.PS1;1", joliet_path="/polaris/a2_setup.ps1")
iso.write("polaris-answer.iso"); iso.close()
```

Windows Setup searches all removable media for `autounattend.xml`, so the
separate answer disk is found automatically. **The answer ISO must also carry a
`$WinPEDriver$` folder** with the W10 viostor + NetKVM drivers so Setup can see
the virtio boot disk—see [Boot bus](#boot-bus-install-directly-on-virtio-via-winpedriver-the-critical-gotcha)
below. That is the whole reason the install works headless on virtio.

## Boot bus: install directly on virtio via `$WinPEDriver$` (the critical gotcha)

Install Windows **directly on the virtio boot disk** so build-hardware ==
range-hardware. Then there is **no bus switch → no hardware-change OOBE re-run**,
and **no sysprep** (which would destroy a promoted DC's identity/SID). This is
the AWS-AMI model: build and run on identical virtual hardware. The one
requirement is that WinPE has the virtio storage driver (viostor) so Setup can
see the disk.

**Do NOT use autounattend `<DriverPaths>`.** Two things make it fail here:

1. **Drive letters.** `<DriverPaths>` lists explicit paths like `E:\viostor\…`;
   the virtio cdrom's letter is assigned at runtime, so the path rarely matches.
2. **The folder name.** kubevirt's `virtio-container-disk` ships
   `VIOSTOR/{2k12..2k19, w10, …}`—there is **no `2k22` folder**. Windows Server
   2022 (build 20348) uses the **`w10`** driver. A `\viostor\2k22\amd64` path
   points at nothing, viostor never loads, and Setup aborts with *"could not
   apply the DiskConfiguration setting"* (= no target disk visible). This single
   wrong path caused the entire multi-week boot-loop/OOBE detour.

**Use `$WinPEDriver$` instead.** Windows Setup automatically scans the root of
every removable drive for a folder named exactly `$WinPEDriver$` and installs all
drivers under it—**no drive letters, no `<DriverPaths>`**. Put the W10 viostor
+ NetKVM there, on the answer ISO:

```
/$WinPEDriver$/viostor/{VIOSTOR.INF,VIOSTOR.SYS,VIOSTOR.CAT}      # from VIOSTOR/w10/amd64
/$WinPEDriver$/NetKVM/{NETKVM.INF,NETKVM.SYS,NETKVM.CAT,NETKVMCO.DLL}
```

Extract the drivers from the container disk (no Windows needed):

```
crane export quay.io/kubevirt/virtio-container-disk:latest - | tar -xO disk/downloaded > virtio.iso
# then pull /VIOSTOR/W10/AMD64/* and /NETKVM/W10/AMD64/* out of virtio.iso with pycdlib
```

Build the answer ISO with pycdlib. The `$WinPEDriver$` folder needs an ISO-9660
name without `$` (for example `WINPEDRV`), but its **Joliet** name must be
`$WinPEDriver$` (Joliet is what Windows reads):

```python
iso.add_directory("/WINPEDRV",         joliet_path="/$WinPEDriver$")
iso.add_directory("/WINPEDRV/VIOSTOR", joliet_path="/$WinPEDriver$/viostor")
iso.add_file("VIOSTOR.INF", "/WINPEDRV/VIOSTOR/VIOSTOR.INF;1", joliet_path="/$WinPEDriver$/viostor/VIOSTOR.INF")
# …same for .SYS/.CAT and the NetKVM files
```

viostor is boot-critical, so it is retained in the installed OS and the boot disk
stays virtio for good. bake.ps1 then installs NetKVM into the OS (for the NIC)
from the virtio cdrom's `w10\amd64` folder.

> Verified 2026-07-04: WS2022 installs on virtio, autologons, promotes
> BOREAS.LOCAL, and a2_setup seeds it—fully headless, no bus switch, no OOBE,
> no sysprep. The boot disk is `virtio` in `VirtualMachine.spec.disks[]` the
> whole time (never `driver: sata`).

## Observability: use `virtctl`, not hand-rolled clients

Install the official **`virtctl`** matching the cluster's KubeVirt version
(`kubectl get kubevirt -n vm-system kubevirt -o
jsonpath='{...observedKubeVirtVersion}'`; download the matching
`virtctl-vX-linux-amd64`). `virtctl vnc --proxy-only` and `virtctl console` both
work on GDC against the cluster1 kubeconfig. (A hand-rolled RFB websocket 404 responses—
that was a client bug, not a platform limitation. The HTTP `vnc/screenshot`
subresource is fine for read-only screenshots.)

## autounattend.xml—the non-obvious requirements

GDC VMs are **headless** (no VNC input, no serial console for Setup), so the
answer file must be *perfectly* non-interactive—any missed prompt hangs
forever. Each of these was required to get Setup to complete:

| Requirement | Why |
|---|---|
| `Microsoft-Windows-International-Core-WinPE` in the `windowsPE` pass (`SetupUILanguage`/`InputLocale`/…) | Supplies the WinPE language the interactive language screen collects; without it Setup cannot resolve the language-specific license terms and aborts. |
| Install onto a **SATA** boot disk (`VirtualMachine.spec.disks[].driver: sata`) | WinPE has no virtio-blk (viostor) driver, and there is no console to load it. SATA is native to WinPE. Virtio drivers are baked into the OS afterward (see bake.ps1) so the golden image still boots on the virtio bus ranges use. |
| Select the image by **`/IMAGE/INDEX`** (`2` = Standard Desktop Eval), not `/IMAGE/NAME` | Robust against name/edition mismatches. |
| **No `<ProductKey>` element** (keep `<AcceptEula>true`) | An empty `<ProductKey><Key></Key>` makes Setup fail edition/license resolution and abort at *"Setup is starting"* with *"cannot find the Microsoft Software License Terms"*. The edition is already chosen by `ImageInstall`. |
| `<AutoLogon>` + skipped `<OOBE>` + `<FirstLogonCommands>` running `bake.ps1` | Drives the post-install bake unattended. |

## bake.ps1—the post-install bake

Runs at FirstLogon (and re-runs once via a RunOnce for the post-promotion seed):

1. **Install all virtio drivers** (`pnputil /add-driver … /install`) from the
   attached virtio-container-disk—found by a `\viostor` probe because GDC
   attaches several `kubevm-agent-*` cdroms that shift drive letters. This lets
   the SATA-installed golden image boot on the **virtio** bus that ranges use.
2. **Install the GDC guest agent** (see next section)—required for the DC's
   NIC to get its range-assigned IP.
3. Enable OpenSSH (operator access), install AD DS + DNS, promote
   `BOREAS.LOCAL` (`Install-ADDSForest`, which reboots).
4. After the reboot a RunOnce re-enters bake.ps1 in its `seed` phase, waits for
   AD DS, runs `a2_setup.ps1` (the BOREAS.LOCAL content), and writes
   `C:\polaris\BAKE_DONE`.

The domain is currently hard-coded (`BOREAS.LOCAL`). To stamp per-event DCs with
different domains, parameterize the domain in `bake.ps1`
(`Install-ADDSForest -DomainName …`) and `a2_setup.ps1`.

## The GDC guest agent (how the DC gets its NIC IP)

On GDC, Windows has **no cloud-init**. The range provisioner sets the desired IP
on the VM interface (`interfaces[].ipAddresses`), but the thing that *applies*
it inside the guest is the **GDC guest agent**. A prepared GDC image runs the
agent installer via a sysprep/specialize hook; a raw ISO install bypasses that,
so `bake.ps1` runs it explicitly.

The agent ships as a containerDisk
`gcr.io/anthos-baremetal-release/kubevm/kubevm-guest-agent-win:<ver>`, attached
to every VM (with a SA-token disk and a config configMap) when
`autoInstallGuestAgent` is on. Inspect it with:

```bash
DOCKER_CONFIG=/tmp/.docker crane auth login gcr.io -u oauth2accesstoken -p "$(gcloud auth print-access-token)"
crane export gcr.io/anthos-baremetal-release/kubevm/kubevm-guest-agent-win:<ver> - | tar -xO disk/disk.iso > agent.iso
# agent.iso contains: install.ps1, guest-agent.exe, run-launcher.ps1, guest-agent-launcher.ps1
```

`install.ps1` registers a SYSTEM **AtStartup scheduled task** (`guest-agent-launcher`)
and starts it. On every boot the task finds three disks **by volume label**—
`"guest agent"` (installer), `"cfgdata"` (SA: ca.crt/namespace/token),
`"kubevm-agent-cfg"` (`guest_agent_config`: name/namespace/`k8sAPIServerURL`)—
copies them locally, and runs `guest-agent.exe install; start`. The agent then
applies `ipAddresses` to the NIC.

So `bake.ps1` only needs to run `install.ps1` **once**:

```powershell
$agentCd = (Get-Volume -FileSystemLabel "guest agent").DriveLetter
& "${agentCd}:\install.ps1"
```

The scheduled task persists in the golden image and re-installs against **each
range's own** SA/config disks at boot. NetKVM must be installed *before* the
agent so the virtio NIC exists for it to configure.

## Building the VM on cluster1 (storage + scheduling gotchas)

`cluster1` (the GDC bare-metal cluster) has **only node-local storage**—all
StorageClasses are `kubernetes.io/no-provisioner`, `WaitForFirstConsumer`, no
shared/networked class. Two consequences when driving the build via the API:

1. Every `VirtualMachineDisk` needs an explicit `storageClassName`
   (`local-shared`); there is no default StorageClass (else `ErrorConfiguration`).
2. A multi-disk VM's disks bind wherever each importer lands, so they scatter
   across workers and the VM cannot co-schedule. **Cordon all-but-one worker**
   so every disk imports on the same node, and pin the VM there with
   `spec.scheduling.nodeSelector: { kubernetes.io/hostname: <node> }`. Uncordon
   once the PVCs are bound.

(`cluster1` nodes: 3 tainted control-plane + 2 workers `cluster1-abm-w{1,2}-001`.)

## Observability (headless Windows on GDC)

These VMs have no graphics device you can VNC into interactively, and no network
until the agent runs. Use these external channels:

- **Screenshots**—the KubeVirt HTTP screenshot subresource works even though
  the RFB/VNC websocket 404 responses on GDC:
  `GET /apis/subresources.kubevirt.io/v1/namespaces/<ns>/virtualmachineinstances/<vmi>/vnc/screenshot`
  returns a PNG. This is the primary way to watch/debug Setup and the bake.
- **UEFI console**—OVMF (unlike legacy-BIOS Windows) writes boot/BdsDxe
  messages to the `guest-console-log` container of the `virt-launcher` pod;
  useful for boot-order/firmware debugging.
- **`guestOSInfo`**—populates in the VMI status once the guest agent connects;
  the external signal that the agent installed and networked successfully.

## Debugging chain (lessons learned)

Every failure below was diagnosed from a screenshot or the UEFI console, then
fixed at root cause:

| Symptom | Root cause | Fix |
|---|---|---|
| `No bootable device` | GDC boots Windows on legacy SeaBIOS | `firmware.bootloader.type: uefi` for Windows |
| `Access Denied` / `No bootable option` | OVMF Secure Boot, no MS keys enrolled | `enableSecureBoot: false` |
| `Press any key to boot from CD…` (times out → UEFI shell) | prompting El Torito boot image | repack ISO with `efisys_noprompt.bin` |
| `installation sources are not valid` | plain ISO9660 repack; Setup needs UDF | rebuild with `genisoimage -udf` |
| `cannot find the Microsoft Software License Terms` (aborts at *Setup is starting*) | empty `<ProductKey>` in the answer file | remove `<ProductKey>`; keep `<AcceptEula>` |
| Setup aborts *"could not apply the DiskConfiguration setting"* (no target disk) | viostor never loaded in WinPE—`<DriverPaths>` pointed at `\viostor\2k22\amd64`, a folder that **does not exist** (WS2022 uses the `w10` driver); drive letters are also unreliable | drop `<DriverPaths>`; auto-load W10 viostor via a **`$WinPEDriver$`** folder on the answer ISO |
| DC promotes but is **never seeded** and never shuts down (BAKE_DONE never written) | bake's seed phase runs from `C:\polaris\bake.ps1`, so `Copy-Item (Join-Path $src a2_setup.ps1) C:\polaris\a2_setup.ps1` copies the file onto itself → throws under `ErrorActionPreference=Stop` → halts before a2_setup runs | guard the copy to run only when `$src` is the answer cdrom |
| DC boots but **no network** ("no route to host") | Windows has no cloud-init; NIC IP applied by the GDC guest agent, which a raw install never ran | run the agent `install.ps1` in `bake.ps1` |

## Status

Windows Server 2022 installs **directly on virtio**, autologons, promotes
`BOREAS.LOCAL`, and `a2_setup` seeds the AD content—fully headless on GDC, no
bus switch, no OOBE, no sysprep (verified 2026-07-04: `boreas.local`, 18 users,
`admin_flag`/`badgelogs` shares confirmed live via the SAC serial console).
Remaining work: export the golden boot disk → qcow2, wire
`GDC_POLARIS_DC_IMAGE_URL`, and validate a live range. See `#1170`.

To stamp a **different domain**, change `Install-ADDSForest -DomainName` in
`bake.ps1` and the domain references in `a2_setup.ps1`, rebuild the answer ISO
(same `$WinPEDriver$` drivers), and re-run the build for a new golden qcow2.
