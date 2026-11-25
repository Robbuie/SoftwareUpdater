"""The PowerShell this application runs, as text, in one place.

Kept as strings rather than `.ps1` files beside the executable: they are sent
with `-EncodedCommand`, which execution policy does not apply to, so a
machine set to `AllSigned` or `Restricted` still answers, and nothing has to
be found on disk at run time. Values are put in with `fill`, which quotes for
PowerShell's single-quoted strings; nothing typed by a person ever reaches
one of these.

Every script writes one JSON document to standard output (or to a result
file, for the elevated one), always an object at the top so an empty list
and a single item read the same way. Failures are an object with `error` and
`hresult`, never a PowerShell error record on standard error that would have
to be scraped.

PowerShell 5.1 is assumed -- it is on every Windows 10 and 11 machine. None
of this needs PowerShell 7.
"""

from __future__ import annotations

PRELUDE = """\
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
"""

#: Every signed driver bound to a device. One row per device; `core/drivers.py`
#: groups them by package.
DRIVERS = PRELUDE + """\
try {
  $items = Get-CimInstance -ClassName Win32_PnPSignedDriver |
    Where-Object { $_.DeviceName -and $_.DriverVersion } |
    ForEach-Object {
      [pscustomobject]@{
        DeviceName = $_.DeviceName
        DeviceClass = $_.DeviceClass
        Manufacturer = $_.Manufacturer
        DriverProviderName = $_.DriverProviderName
        DriverVersion = $_.DriverVersion
        DriverDate = $(if ($_.DriverDate) { $_.DriverDate.ToString('yyyy-MM-dd') } else { '' })
        InfName = $_.InfName
        DeviceID = $_.DeviceID
        HardWareID = $_.HardWareID
      }
    }
  [pscustomobject]@{ drivers = @($items) } | ConvertTo-Json -Depth 4 -Compress
} catch {
  [pscustomobject]@{ error = $_.Exception.Message; hresult = $_.Exception.HResult } |
    ConvertTo-Json -Compress
  exit 3
}
"""

#: The machine: who made it, which model, which firmware. Decides which
#: manufacturer's update tool to suggest.
SYSTEM = PRELUDE + """\
try {
  $cs = Get-CimInstance -ClassName Win32_ComputerSystem
  $bios = Get-CimInstance -ClassName Win32_BIOS
  $os = Get-CimInstance -ClassName Win32_OperatingSystem
  [pscustomobject]@{
    manufacturer = $cs.Manufacturer
    model = $cs.Model
    bios = $bios.SMBIOSBIOSVersion
    biosDate = $(if ($bios.ReleaseDate) { $bios.ReleaseDate.ToString('yyyy-MM-dd') } else { '' })
    os = $os.Caption
    osVersion = $os.Version
    build = $os.BuildNumber
    lastBoot = $(if ($os.LastBootUpTime) { $os.LastBootUpTime.ToString('yyyy-MM-dd HH:mm') } else { '' })
  } | ConvertTo-Json -Compress
} catch {
  [pscustomobject]@{ error = $_.Exception.Message; hresult = $_.Exception.HResult } |
    ConvertTo-Json -Compress
  exit 3
}
"""

#: Facts for the Security page (`core/security.py` judges them). Read-only,
#: and runs without administrator rights: every fact is fetched on its own so
#: one that is refused leaves the rest. Secrets are never read -- for
#: automatic sign-in, only whether a stored password *exists* is asked.
SECURITY = PRELUDE + """\
$f = [ordered]@{}
function Fact($name, [scriptblock]$block) {
  try { $f[$name] = & $block } catch { $f[$name + 'Error'] = $_.Exception.Message }
}
function Reg($path, $name) {
  try { (Get-ItemProperty -LiteralPath $path -Name $name -ErrorAction Stop).$name } catch { $null }
}
Fact 'os' {
  $cv = 'HKLM:\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion'
  @{ caption = (Get-CimInstance Win32_OperatingSystem).Caption
     build = [int](Reg $cv 'CurrentBuildNumber'); ubr = [int](Reg $cv 'UBR')
     displayVersion = (Reg $cv 'DisplayVersion'); edition = (Reg $cv 'EditionID') }
}
Fact 'defender' {
  $s = Get-MpComputerStatus
  @{ enabled = [bool]$s.AntivirusEnabled; realtime = [bool]$s.RealTimeProtectionEnabled
     service = [bool]$s.AMServiceEnabled; signatureAge = [int]$s.AntivirusSignatureAge
     tamper = [bool]$s.IsTamperProtected; version = [string]$s.AntivirusSignatureVersion }
}
Fact 'antivirus' {
  @(Get-CimInstance -Namespace root/SecurityCenter2 -ClassName AntiVirusProduct |
    ForEach-Object { [string]$_.displayName })
}
Fact 'firewall' {
  @(Get-NetFirewallProfile -PolicyStore ActiveStore |
    ForEach-Object { @{ name = [string]$_.Name; enabled = ([string]$_.Enabled -eq 'True') } })
}
Fact 'bitlocker' {
  $shell = New-Object -ComObject Shell.Application
  [int]$shell.NameSpace("$env:SystemDrive\\").Self.ExtendedProperty('System.Volume.BitLockerProtection')
}
Fact 'secureBoot' { Reg 'HKLM:\\SYSTEM\\CurrentControlSet\\Control\\SecureBoot\\State' 'UEFISecureBootEnabled' }
Fact 'uac' {
  $p = 'HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Policies\\System'
  @{ enableLua = (Reg $p 'EnableLUA'); consentAdmin = (Reg $p 'ConsentPromptBehaviorAdmin')
     secureDesktop = (Reg $p 'PromptOnSecureDesktop') }
}
Fact 'smb1' {
  @{ clientStart = (Reg 'HKLM:\\SYSTEM\\CurrentControlSet\\Services\\mrxsmb10' 'Start')
     server = (Reg 'HKLM:\\SYSTEM\\CurrentControlSet\\Services\\LanmanServer\\Parameters' 'SMB1') }
}
Fact 'rdp' {
  @{ deny = (Reg 'HKLM:\\SYSTEM\\CurrentControlSet\\Control\\Terminal Server' 'fDenyTSConnections')
     nla = (Reg 'HKLM:\\SYSTEM\\CurrentControlSet\\Control\\Terminal Server\\WinStations\\RDP-Tcp' 'UserAuthentication') }
}
Fact 'lsa' { Reg 'HKLM:\\SYSTEM\\CurrentControlSet\\Control\\Lsa' 'RunAsPPL' }
Fact 'wdigest' { Reg 'HKLM:\\SYSTEM\\CurrentControlSet\\Control\\SecurityProviders\\WDigest' 'UseLogonCredential' }
Fact 'autologon' {
  $w = 'HKLM:\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\Winlogon'
  @{ enabled = [string](Reg $w 'AutoAdminLogon')
     storedPassword = ((Get-Item -LiteralPath $w).Property -contains 'DefaultPassword') }
}
Fact 'admins' {
  @(Get-LocalGroupMember -SID 'S-1-5-32-544' -ErrorAction Stop | ForEach-Object { [string]$_.Name })
}
Fact 'userIsAdmin' {
  [bool]([Security.Principal.WindowsIdentity]::GetCurrent().Groups |
    Where-Object { $_.Value -eq 'S-1-5-32-544' })
}
Fact 'guest' {
  $g = Get-LocalUser | Where-Object { $_.SID.Value -like '*-501' } | Select-Object -First 1
  [bool]($g -and $g.Enabled)
}
Fact 'pendingReboot' {
  (Test-Path 'HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\WindowsUpdate\\Auto Update\\RebootRequired') -or
  (Test-Path 'HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Component Based Servicing\\RebootPending')
}
Fact 'lastPatch' {
  $h = Get-HotFix | Where-Object { $_.InstalledOn } | Sort-Object InstalledOn -Descending |
    Select-Object -First 1
  if ($h) { $h.InstalledOn.ToString('yyyy-MM-dd') } else { '' }
}
Fact 'updateService' { [string](Get-Service -Name wuauserv).StartType }
[pscustomobject]$f | ConvertTo-Json -Depth 5 -Compress
"""

#: Search the Windows Update Agent for everything not installed and not
#: hidden. Searching needs no administrator rights; installing does.
WU_SEARCH = PRELUDE + """\
try {
  $session = New-Object -ComObject Microsoft.Update.Session
  $session.ClientApplicationID = 'Software Updater'
  $searcher = $session.CreateUpdateSearcher()
  $searcher.Online = $true
  if (__SERVER__ -eq 'windows-update') { $searcher.ServerSelection = 2 }
  $found = $searcher.Search("IsInstalled=0 and IsHidden=0")
  $list = foreach ($u in $found.Updates) {
    $o = [ordered]@{
      id = $u.Identity.UpdateID
      rev = $u.Identity.RevisionNumber
      title = $u.Title
      type = [int]$u.Type
      kb = (@($u.KBArticleIDs) -join ',')
      size = [int64]$u.MaxDownloadSize
      categories = (@($u.Categories | ForEach-Object { $_.Name }) -join '; ')
      severity = $u.MsrcSeverity
      browseOnly = [bool]$u.BrowseOnly
    }
    if ([int]$u.Type -eq 2) {
      $o.driverModel = $u.DriverModel
      $o.driverManufacturer = $u.DriverManufacturer
      $o.driverClass = $u.DriverClass
      $o.hardwareId = $u.DriverHardwareID
      if ($u.DriverVerDate) { $o.driverDate = ([datetime]$u.DriverVerDate).ToString('yyyy-MM-dd') }
    }
    [pscustomobject]$o
  }
  [pscustomobject]@{ updates = @($list) } | ConvertTo-Json -Depth 4 -Compress
} catch {
  [pscustomobject]@{ error = $_.Exception.Message; hresult = $_.Exception.HResult } |
    ConvertTo-Json -Compress
  exit 3
}
"""

#: Elevated scripts (`io/elevated.py`) get the result file's path as
#: $args[0] and write one JSON object there; their data is written into the
#: script text with `embed`, so the hash that guards the script covers it.
RESULT = """\
$resultPath = $args[0]
function Write-Result($obj) {
  # Written as administrator: never through a folder that has become a link,
  # and never over a file that already exists.
  $dir = Split-Path -LiteralPath $resultPath
  foreach ($d in @($dir, (Split-Path -LiteralPath $dir))) {
    if ((Get-Item -LiteralPath $d -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) { return }
  }
  if (Test-Path -LiteralPath $resultPath) { return }
  $obj | ConvertTo-Json -Depth 5 -Compress | Set-Content -LiteralPath $resultPath -Encoding UTF8
}
"""

#: Run elevated. Searches again for the chosen update ids (an update object
#: cannot cross processes), downloads and installs those.
WU_INSTALL = PRELUDE + RESULT + """\
try {
  $request = __REQUEST__
  $session = New-Object -ComObject Microsoft.Update.Session
  $session.ClientApplicationID = 'Software Updater'
  $searcher = $session.CreateUpdateSearcher()
  $searcher.Online = $true
  if ($request.server -eq 'windows-update') { $searcher.ServerSelection = 2 }
  $wanted = @{}
  foreach ($id in @($request.ids)) { $wanted[[string]$id] = $true }
  $found = $searcher.Search("IsInstalled=0")
  $coll = New-Object -ComObject Microsoft.Update.UpdateColl
  foreach ($u in $found.Updates) {
    if ($wanted.ContainsKey([string]$u.Identity.UpdateID)) {
      if (-not $u.EulaAccepted) { $u.AcceptEula() }
      [void]$coll.Add($u)
    }
  }
  if ($coll.Count -eq 0) {
    Write-Result @{ error = 'None of the chosen updates are offered any more.'; results = @() }
    exit 0
  }
  $downloader = $session.CreateUpdateDownloader()
  $downloader.Updates = $coll
  [void]$downloader.Download()
  $installer = $session.CreateUpdateInstaller()
  $installer.Updates = $coll
  $r = $installer.Install()
  $results = for ($i = 0; $i -lt $coll.Count; $i++) {
    $one = $r.GetUpdateResult($i)
    @{ id = $coll.Item($i).Identity.UpdateID; title = $coll.Item($i).Title;
       code = [int]$one.ResultCode; hresult = $one.HResult }
  }
  Write-Result @{ results = @($results); reboot = [bool]$r.RebootRequired; code = [int]$r.ResultCode }
} catch {
  Write-Result @{ error = $_.Exception.Message; hresult = $_.Exception.HResult; results = @() }
  exit 1
}
"""

#: Run elevated: the system-wide cleanup targets. `__REQUEST__` is
#: {targets: [{id, method, paths, days, pattern}]}. Every path is checked
#: against the system folders below before anything is deleted, links are
#: never followed, and files in use are skipped.
CLEAN = PRELUDE + RESULT + """\
$request = __REQUEST__
$allowed = @(
  (Join-Path $env:SystemRoot 'Temp'),
  (Join-Path $env:SystemRoot 'Minidump'),
  (Join-Path $env:SystemRoot 'SoftwareDistribution\\Download'),
  (Join-Path $env:ProgramData 'Microsoft\\Windows\\WER')
)
function Test-Allowed($path) {
  $full = [IO.Path]::GetFullPath($path).TrimEnd('\\')
  foreach ($root in $allowed) {
    if ($full -eq $root -or $full.StartsWith($root + '\\', [StringComparison]::OrdinalIgnoreCase)) { return $true }
  }
  return $false
}
function Remove-Old($root, $days, $pattern) {
  $r = @{ bytes = 0; files = 0; skipped = 0 }
  if (-not (Test-Path -LiteralPath $root)) { return $r }
  $limit = (Get-Date).AddDays(-[double]$days)
  $stack = New-Object System.Collections.Stack
  $stack.Push($root)
  while ($stack.Count -gt 0) {
    $dir = $stack.Pop()
    try { $entries = [IO.Directory]::GetFileSystemEntries($dir) } catch { continue }
    foreach ($e in $entries) {
      try { $info = Get-Item -LiteralPath $e -Force -ErrorAction Stop } catch { $r.skipped++; continue }
      if ($info.Attributes -band [IO.FileAttributes]::ReparsePoint) { continue }
      if ($info.PSIsContainer) { $stack.Push($e); continue }
      if ([double]$days -gt 0 -and $info.LastWriteTime -gt $limit) { continue }
      if ($pattern -and -not ($info.Name -like $pattern)) { continue }
      $len = $info.Length
      try { Remove-Item -LiteralPath $e -Force -ErrorAction Stop; $r.bytes += $len; $r.files++ }
      catch { $r.skipped++ }
    }
  }
  return $r
}
function Free-Bytes() { (Get-PSDrive -Name $env:SystemDrive.TrimEnd(':')).Free }
$results = @()
foreach ($t in @($request.targets)) {
  $one = @{ target = $t.id; bytes = 0; files = 0; skipped = 0; error = '' }
  try {
    if ($t.method -eq 'files') {
      foreach ($p in @($t.paths)) {
        if (-not (Test-Allowed $p)) { $one.error = "Refused: $p"; continue }
        $r = Remove-Old $p $t.days $t.pattern
        $one.bytes += $r.bytes; $one.files += $r.files; $one.skipped += $r.skipped
      }
    } elseif ($t.method -eq 'delivery') {
      $before = Free-Bytes
      Delete-DeliveryOptimizationCache -Force
      $one.bytes = [math]::Max(0, (Free-Bytes) - $before)
    } elseif ($t.method -eq 'dism') {
      $before = Free-Bytes
      $dism = Join-Path $env:SystemRoot 'System32\\dism.exe'
      & $dism /Online /Cleanup-Image /StartComponentCleanup /Quiet | Out-Null
      if ($LASTEXITCODE -ne 0) { $one.error = "DISM exited with $LASTEXITCODE" }
      $one.bytes = [math]::Max(0, (Free-Bytes) - $before)
    }
  } catch { $one.error = $_.Exception.Message }
  $results += $one
}
Write-Result @{ results = $results }
"""

#: Run elevated: fetch Defender's newest definitions.
DEFENDER_UPDATE = PRELUDE + RESULT + """\
try {
  Update-MpSignature -ErrorAction Stop
  $s = Get-MpComputerStatus
  Write-Result @{ ok = $true; version = $s.AntivirusSignatureVersion; age = $s.AntivirusSignatureAge }
} catch {
  Write-Result @{ ok = $false; error = $_.Exception.Message }
}
"""


def quote(value: str) -> str:
    """A PowerShell single-quoted string literal: nothing inside expands, and
    a quote is written twice."""
    return "'" + value.replace("'", "''") + "'"


def fill(script: str, **values: str) -> str:
    """Put quoted string values in for `__NAME__` placeholders."""
    for name, value in values.items():
        script = script.replace(f"__{name.upper()}__", quote(value))
    return script


def embed(script: str, **values) -> str:
    """Put JSON values in, as PowerShell objects, for `__NAME__` placeholders."""
    import json

    for name, value in values.items():
        expression = f"({quote(json.dumps(value))} | ConvertFrom-Json)"
        script = script.replace(f"__{name.upper()}__", expression)
    return script
