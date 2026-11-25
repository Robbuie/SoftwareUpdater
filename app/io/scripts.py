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

#: Run elevated. Reads the chosen update ids from a request file, searches
#: again (an update object cannot cross processes), downloads and installs
#: those, and writes the outcome to a result file -- standard output of an
#: elevated process is not ours to read.
WU_INSTALL = PRELUDE + """\
$resultPath = __RESULT__
function Write-Result($obj) {
  $obj | ConvertTo-Json -Depth 5 -Compress | Set-Content -LiteralPath $resultPath -Encoding UTF8
}
try {
  $request = Get-Content -LiteralPath __REQUEST__ -Raw -Encoding UTF8 | ConvertFrom-Json
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

#: Runs a script file by reading it, which execution policy does not govern.
RUN_FILE = "& ([scriptblock]::Create((Get-Content -LiteralPath __PATH__ -Raw -Encoding UTF8)))\n"


def quote(value: str) -> str:
    """A PowerShell single-quoted string literal: nothing inside expands, and
    a quote is written twice."""
    return "'" + value.replace("'", "''") + "'"


def fill(script: str, **values: str) -> str:
    for name, value in values.items():
        script = script.replace(f"__{name.upper()}__", quote(value))
    return script
