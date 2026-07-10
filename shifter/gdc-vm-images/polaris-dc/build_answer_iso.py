#!/usr/bin/env python3
"""Build the polaris-dc answer ISO for a headless install-on-virtio GDC build.

The answer ISO carries three things Windows Setup needs to install Server 2022
directly onto the virtio boot disk, unattended:

  /autounattend.xml            - the unattended answer file (Setup auto-reads it
                                 from the root of any removable drive)
  /$WinPEDriver$/viostor/      - W10 viostor (virtio storage) driver. Setup scans
  /$WinPEDriver$/NetKVM/         every removable drive for a $WinPEDriver$ folder
                                 and auto-installs the drivers under it, with NO
                                 drive letters and NO autounattend <DriverPaths>.
                                 viostor is boot-critical, so the boot disk stays
                                 virtio and there is no SATA->virtio bus switch
                                 (hence no hardware-change OOBE, no sysprep).
  /polaris/bake.ps1            - FirstLogon bake: NetKVM, guest agent, promote
  /polaris/a2_setup.ps1          BOREAS.LOCAL, seed the AD content.

WS2022 (build 20348) uses the *W10* virtio driver -- kubevirt's virtio-win ships
no 2k22 folder, and pointing at one is what silently breaks the install.

Drivers are extracted from the kubevirt virtio-container-disk (no Windows host
needed). Fetch it once with:

    crane export quay.io/kubevirt/virtio-container-disk:latest - \\
        | tar -xO disk/downloaded > virtio.iso

then pass --virtio-iso virtio.iso.

Usage:
    python3 build_answer_iso.py --virtio-iso virtio.iso --out polaris-answer.iso

To stamp a different domain, edit Install-ADDSForest -DomainName in bake.ps1 and
the domain references in a2_setup.ps1 before building; the $WinPEDriver$ drivers
are unchanged.
"""
import argparse
import io
import os

import pycdlib

HERE = os.path.dirname(os.path.abspath(__file__))
# W10\amd64 is correct for Windows Server 2022 (build 20348); this virtio-win
# ships no 2k22 directory.
DRIVER_FILES = {
    "viostor": ("VIOSTOR.INF", "VIOSTOR.SYS", "VIOSTOR.CAT"),
    "NetKVM": ("NETKVM.INF", "NETKVM.SYS", "NETKVM.CAT", "NETKVMCO.DLL"),
}
DRIVER_SRC = {"viostor": "/VIOSTOR/W10/AMD64", "NetKVM": "/NETKVM/W10/AMD64"}


def extract_drivers(virtio_iso):
    """Return {driver: {filename: bytes}} pulled from the virtio-win ISO."""
    src = pycdlib.PyCdlib()
    src.open(virtio_iso)
    out = {}
    for drv, files in DRIVER_FILES.items():
        out[drv] = {}
        for fn in files:
            buf = io.BytesIO()
            src.get_file_from_iso_fp(buf, iso_path=f"{DRIVER_SRC[drv]}/{fn};1")
            out[drv][fn] = buf.getvalue()
    src.close()
    return out


def build(virtio_iso, autounattend, bake, a2_setup, out):
    drivers = extract_drivers(virtio_iso)
    iso = pycdlib.PyCdlib()
    iso.new(joliet=3, vol_ident="POLARIS_ANSWER")

    iso.add_file(autounattend, "/AUTOUNAT.XML;1", joliet_path="/autounattend.xml")

    # $WinPEDriver$: the ISO-9660 name cannot contain '$', so use WINPEDRV; the
    # Joliet name (what Windows reads) must be exactly $WinPEDriver$.
    iso.add_directory("/WINPEDRV", joliet_path="/$WinPEDriver$")
    for drv, files in drivers.items():
        d9660 = f"/WINPEDRV/{drv.upper()}"
        iso.add_directory(d9660, joliet_path=f"/$WinPEDriver$/{drv}")
        for fn, data in files.items():
            iso.add_fp(io.BytesIO(data), len(data), f"{d9660}/{fn};1",
                       joliet_path=f"/$WinPEDriver$/{drv}/{fn}")

    iso.add_directory("/POLARIS", joliet_path="/polaris")
    iso.add_file(bake, "/POLARIS/BAKE.PS1;1", joliet_path="/polaris/bake.ps1")
    iso.add_file(a2_setup, "/POLARIS/A2SETUP.PS1;1", joliet_path="/polaris/a2_setup.ps1")

    iso.write(out)
    iso.close()
    print(f"built {out} ({os.path.getsize(out)} bytes) "
          f"[viostor+NetKVM W10, autounattend, bake, a2_setup]")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--virtio-iso", required=True, help="virtio-win ISO (see module docstring)")
    ap.add_argument("--autounattend", default=os.path.join(HERE, "autounattend.xml"))
    ap.add_argument("--bake", default=os.path.join(HERE, "bake.ps1"))
    ap.add_argument("--a2-setup",
                    default=os.path.normpath(os.path.join(HERE, "..", "..", "..",
                                             "scripts", "polaris-aws-range", "a2_setup.ps1")))
    ap.add_argument("--out", default="polaris-answer.iso")
    a = ap.parse_args()
    build(a.virtio_iso, a.autounattend, a.bake, a.a2_setup, a.out)
