# Install the virtio-win paravirtualized drivers into the Windows driver store.
#
# GDC VM Runtime (KubeVirt/QEMU) presents the guest a virtio NIC (macvtap
# binding) and virtio block devices. GCE Windows images ship Google's own
# network stack (gVNIC), not the upstream virtio-net (NetKVM) driver, so on GDC
# the guest comes up with no usable NIC and never gets a DHCP lease -- the root
# cause of the polaris-dc having no network. Stage the upstream virtio-win
# drivers so Windows binds them when the virtio devices appear on GDC.
#
# pnputil /add-driver /install adds the packages to the driver store now (on the
# GCE builder the virtio devices are absent, so nothing is displaced); Windows
# loads them when the matching device enumerates on the GDC host.
$ErrorActionPreference = "Stop"
Start-Transcript -Path "C:\install-virtio.log" -Append -Force
Write-Host "=== install-virtio $(Get-Date -Format o) ==="

$isoUrl = "https://fedorapeople.org/groups/virt/virtio-win/direct-downloads/stable-virtio/virtio-win.iso"
$isoPath = "C:\virtio-win.iso"

Write-Host "Downloading virtio-win.iso..."
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
Invoke-WebRequest -Uri $isoUrl -OutFile $isoPath -UseBasicParsing

Write-Host "Mounting ISO..."
$mount = Mount-DiskImage -ImagePath $isoPath -PassThru
$drive = ($mount | Get-Volume).DriveLetter + ":"
Write-Host "Mounted at $drive"

# 2k22 = Windows Server 2022 driver subdir; amd64 architecture. Install the
# network (NetKVM), block (viostor/vioscsi), balloon and serial (vioserial, used
# by the guest agent) drivers.
$os = "2k22"
$arch = "amd64"
$drivers = @("NetKVM", "viostor", "vioscsi", "Balloon", "vioserial", "qemupciserial")
foreach ($drv in $drivers) {
    $dir = "$drive\$drv\$os\$arch"
    $inf = Get-ChildItem -Path $dir -Filter "*.inf" -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -ne $inf) {
        Write-Host ("  pnputil add-driver " + $inf.FullName)
        pnputil /add-driver $inf.FullName /install | Out-Null
    }
    else {
        Write-Host ("  no inf for " + $drv + " under " + $dir + "; skipping")
    }
}

Dismount-DiskImage -ImagePath $isoPath -ErrorAction SilentlyContinue
Remove-Item $isoPath -Force -ErrorAction SilentlyContinue
Write-Host "=== install-virtio complete ==="
Stop-Transcript
