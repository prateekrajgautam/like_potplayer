<#
.SYNOPSIS
  One command to build the Windows release: a portable .zip and a setup .exe installer.

.DESCRIPTION
  Run in PowerShell from this folder:   .\build-windows.ps1
  Needs: Python 3.10+ (python.org or `winget install Python.Python.3.12`) and
         Inno Setup 6.3+ (`winget install JRSoftware.InnoSetup`), unless -SkipInstaller.
  libmpv-2.dll is downloaded automatically (shinchiro/mpv-winbuild-cmake, GPL build) unless you pass -LibMpv.

.PARAMETER LibMpv         Path to your own libmpv-2.dll (skips the download).
.PARAMETER SkipInstaller  Build only the portable zip.
.PARAMETER Msi            Also build an .msi (needs the WiX tool: `winget install Microsoft.DotNet.SDK.8`, then `dotnet tool install --global wix`).
                  Without this switch the MSI is built automatically when `wix` is installed; -NoMsi never builds it.
.PARAMETER Refreeze       Rebuild the PyInstaller bundle even if dist\like_potplayer already exists.

.EXAMPLE
  .\build-windows.ps1
  .\build-windows.ps1 -LibMpv C:\libs\libmpv-2.dll -SkipInstaller
#>
[CmdletBinding()]
param(
  [string]$LibMpv = "",
  [switch]$SkipInstaller,
  [switch]$Msi,
  [switch]$NoMsi,
  [switch]$Refreeze
)
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"      # progress bars make Invoke-WebRequest very slow in PowerShell 5.1
try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 } catch { }
Set-Location $PSScriptRoot

function Say($m) { Write-Host ""; Write-Host "==> $m" -ForegroundColor Cyan }
function Die($m) { Write-Host ""; Write-Host "ERROR: $m" -ForegroundColor Red; exit 1 }
# Run a native program. Windows PowerShell 5.1 turns anything a program writes to stderr (pip and PyInstaller do) into a
# terminating error under $ErrorActionPreference = "Stop"; so relax it for the call and judge success by the exit code.
function Run([string]$exe, [string[]]$arguments, [string]$log = "") {
  $old = $ErrorActionPreference; $ErrorActionPreference = "Continue"
  try {
    if ($log) { & $exe @arguments 2>&1 | ForEach-Object { "$_" } | Out-File -FilePath $log -Encoding utf8 }
    else      { & $exe @arguments 2>&1 | ForEach-Object { "$_" } | Write-Host }
  } finally { $ErrorActionPreference = $old }
  if ($LASTEXITCODE -ne 0) {
    if ($log) { Get-Content $log -Tail 25 }
    Die "'$exe $($arguments -join ' ')' failed (exit code $LASTEXITCODE)$(if ($log) { " - full log: $log" })"
  }
}

# Newest 64-bit libmpv "dev" archive from shinchiro/mpv-winbuild-cmake. Uses the GitHub API (token optional, avoids rate
# limits) and falls back to reading the release page, so it still works when the API says "rate limit exceeded".
function Get-LibMpvAsset {
  $repo = "shinchiro/mpv-winbuild-cmake"
  try {
    $h = @{ "User-Agent" = "like_potplayer-build" }
    if ($env:GITHUB_TOKEN) { $h["Authorization"] = "Bearer $($env:GITHUB_TOKEN)" }
    $rel = Invoke-RestMethod "https://api.github.com/repos/$repo/releases/latest" -Headers $h
    $a = $rel.assets | Where-Object { $_.name -match '^mpv-dev-x86_64-\d' } | Select-Object -First 1
    if ($a) { return @{ name = $a.name; url = $a.browser_download_url; tag = $rel.tag_name } }
  } catch { Write-Host "(GitHub API unavailable: $($_.Exception.Message.Split([char]10)[0]); reading the release page instead)" }
  try {
    $page = Invoke-WebRequest "https://github.com/$repo/releases/latest" -UseBasicParsing
    $tag = ([string]$page.BaseResponse.RequestMessage.RequestUri).Split("/")[-1]
    $html = (Invoke-WebRequest "https://github.com/$repo/releases/expanded_assets/$tag" -UseBasicParsing).Content
    $m = [regex]::Match($html, 'href="([^"]*/(mpv-dev-x86_64-\d[^"/]*\.7z))"')
    if ($m.Success) { return @{ name = $m.Groups[2].Value; url = "https://github.com" + $m.Groups[1].Value; tag = $tag } }
  } catch { Write-Host "(release page also failed: $($_.Exception.Message))" }
  return $null
}

# ---------------------------------------------------------------- [1/6] prerequisites
Say "[1/6] Checking prerequisites"
$py = $null
foreach ($cand in @("py", "python")) {
  if (Get-Command $cand -ErrorAction SilentlyContinue) { $py = $cand; break }
}
if (-not $py) { Die "Python not found. Install it:  winget install Python.Python.3.12   (then open a new PowerShell)" }
$pyArgs = @(); if ($py -eq "py") { $pyArgs = @("-3") }
& $py @pyArgs -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)"
if ($LASTEXITCODE -ne 0) { Die "Python 3.10 or newer is required" }

$iscc = $null
if (-not $SkipInstaller) {
  $iscc = (Get-Command iscc -ErrorAction SilentlyContinue).Source
  if (-not $iscc) {
    foreach ($dir in @("${env:ProgramFiles(x86)}\Inno Setup 6", "$env:ProgramFiles\Inno Setup 6", "$env:LOCALAPPDATA\Programs\Inno Setup 6")) {
      if (Test-Path "$dir\ISCC.exe") { $iscc = "$dir\ISCC.exe"; break }
    }
  }
  if (-not $iscc) { Die "Inno Setup not found. Install it:  winget install JRSoftware.InnoSetup   (or run with -SkipInstaller)" }
}
if ((-not $LibMpv) -and (-not (Get-Command tar -ErrorAction SilentlyContinue))) {
  Die "tar.exe not found (needed to unpack the libmpv download; it ships with Windows 10 1803+). Or pass -LibMpv path\libmpv-2.dll"
}
Write-Host "ok"

# ---------------------------------------------------------------- [2/6] python environment
Say "[2/6] Preparing the Python environment (.venv-build)"
if (-not (Test-Path ".venv-build\Scripts\python.exe")) { Run $py ($pyArgs + @("-m", "venv", ".venv-build")) }
$vpy = (Resolve-Path ".venv-build\Scripts\python.exe").Path
Run $vpy @("-m", "pip", "install", "-q", "--upgrade", "pip")
Run $vpy @("-m", "pip", "install", "-q", ".", "pyinstaller", "pillow")
$name = (& $vpy tools\brand.py app_name).Trim()
$ver  = (& $vpy tools\brand.py version).Trim()
Write-Host "building '$name' $ver"
New-Item -ItemType Directory -Force build, dist | Out-Null
Run $vpy @("tools\make_icons.py")

# ---------------------------------------------------------------- [3/6] libmpv
Say "[3/6] Getting libmpv-2.dll"
$dll = ""
if ($LibMpv) {
  if (-not (Test-Path $LibMpv)) { Die "-LibMpv file not found: $LibMpv" }
  $dll = (Resolve-Path $LibMpv).Path
} else {
  $cache = "build\libmpv\libmpv-2.dll"
  if (-not (Test-Path $cache)) {
    New-Item -ItemType Directory -Force build\libmpv, build\libmpv-extract | Out-Null
    $asset = Get-LibMpvAsset
    if (-not $asset) { Die "Could not find an mpv-dev-x86_64 archive in the latest shinchiro/mpv-winbuild-cmake release. Download libmpv-2.dll yourself and pass -LibMpv." }
    Write-Host "downloading $($asset.name) (release $($asset.tag))"
    Invoke-WebRequest $asset.url -OutFile "build\libmpv-extract\$($asset.name)"
    Run "tar" @("-xf", "build\libmpv-extract\$($asset.name)", "-C", "build\libmpv-extract")
    $found = Get-ChildItem build\libmpv-extract -Recurse -Filter "libmpv-2.dll" | Select-Object -First 1
    if (-not $found) { Die "libmpv-2.dll was not inside $($asset.name)" }
    Copy-Item $found.FullName $cache
    "$($asset.tag) / $($asset.name)" | Set-Content build\libmpv\SOURCE.txt
  }
  $dll = (Resolve-Path $cache).Path
}
if ((Get-Item $dll).Length -lt 1MB) { Die "$dll looks too small to be libmpv" }
Write-Host "using $dll"

# ---------------------------------------------------------------- [4/6] freeze + self-test
Say "[4/6] Freezing with PyInstaller"
$exe = "dist\like_potplayer\like_potplayer.exe"
if ($Refreeze -or -not (Test-Path $exe)) {
  if (Test-Path dist\like_potplayer) { Remove-Item -Recurse -Force dist\like_potplayer }
  $pyi = @("-m", "PyInstaller", "--noconfirm", "--clean", "--windowed", "--name", "like_potplayer",
    "--distpath", "dist", "--workpath", "build\pyi", "--specpath", "build\pyi",
    "--icon", "$PSScriptRoot\like_potplayer\assets\build\app.ico",
    "--add-data", "$PSScriptRoot\like_potplayer\defaults;like_potplayer\defaults",
    "--add-data", "$PSScriptRoot\like_potplayer\assets;like_potplayer\assets",
    "--add-binary", "$dll;.",
    "$PSScriptRoot\packaging\entry.py")
  Run $vpy $pyi "build\pyinstaller.log"
}
if (-not (Test-Path $exe)) { Die "$exe was not produced" }

Say "Self-test of the built program"
$selftest = Join-Path $env:TEMP "like_potplayer-selftest.txt"
Remove-Item $selftest -ErrorAction SilentlyContinue
$p = Start-Process $exe -ArgumentList "--self-test" -Wait -PassThru
if (Test-Path $selftest) { Get-Content $selftest }
if ($p.ExitCode -ne 0) { Die "self-test failed: Qt or libmpv did not load (see lines above)" }
Write-Host "PASS  Qt and libmpv load from the bundle"
$env:LIKE_POTPLAYER_NO_PROMPT = "1"
$gui = Start-Process $exe -PassThru
Start-Sleep -Seconds 6
if ($gui.HasExited) { Die "the program exited by itself within 6 seconds (exit code $($gui.ExitCode))" }
Stop-Process -Id $gui.Id -Force
Write-Host "PASS  the window starts and stays open"
Remove-Item Env:\LIKE_POTPLAYER_NO_PROMPT

# ---------------------------------------------------------------- [5/6] portable zip
Say "[5/6] Portable zip"
$stage = "build\portable\$name-$ver"
if (Test-Path build\portable) { Remove-Item -Recurse -Force build\portable }
New-Item -ItemType Directory -Force $stage | Out-Null
Copy-Item dist\like_potplayer\* $stage -Recurse
New-Item "$stage\portable.flag" -ItemType File | Out-Null     # keeps all settings in .\data next to the exe
"$name $ver (portable)`r`nRun like_potplayer.exe. Settings are stored in the 'data' folder next to it.`r`nDelete 'portable.flag' to use %APPDATA% instead." |
  Set-Content "$stage\README.txt"
$zip = "dist\$name-$ver-windows-portable.zip"
if (Test-Path $zip) { Remove-Item $zip }
Compress-Archive -Path "$stage\*" -DestinationPath $zip
Write-Host "built $zip"

# ---------------------------------------------------------------- [6/6] installer
if ($SkipInstaller) {
  Say "[6/6] Installer skipped (-SkipInstaller)"
} else {
  Say "[6/6] Building the installer with Inno Setup"
  Run $vpy @("tools\gen_iss.py")
  Run $iscc @("/Q", "packaging\windows\like_potplayer.iss")
}

# ---------------------------------------------------------------- MSI (WiX)
$wix = (Get-Command wix -ErrorAction SilentlyContinue).Source
if (-not $NoMsi -and -not $SkipInstaller) {
  if (-not $wix) {
    if ($Msi) { Die "WiX not found. Install it:  winget install Microsoft.DotNet.SDK.8   then   dotnet tool install --global wix   (reopen PowerShell)" }
    Write-Host "(MSI skipped: WiX is not installed. See -Msi in the script help to enable it)" -ForegroundColor Yellow
  } else {
    Say "Building the MSI with WiX"
    Run $vpy @("tools\gen_wxs.py")
    $msiOut = "dist\$name-$ver-x64.msi"
    Run $wix @("build", "-arch", "x64", "-d", "DistDir=$PSScriptRoot\dist\like_potplayer",
               "-d", "IconFile=$PSScriptRoot\like_potplayer\assets\build\app.ico", "-o", $msiOut, "build\windows\like_potplayer.wxs")
  }
}

# optional code signing: set WIN_SIGN_PFX (and WIN_SIGN_PASSWORD) to sign the exe and msi installers
if ($env:WIN_SIGN_PFX) {
  $signtool = (Get-Command signtool -ErrorAction SilentlyContinue).Source
  if (-not $signtool) { Write-Host "WIN_SIGN_PFX is set but signtool.exe was not found: files left unsigned" -ForegroundColor Yellow }
  else {
    Get-ChildItem dist -File | Where-Object { $_.Name -like "*-setup.exe" -or $_.Extension -eq ".msi" } | ForEach-Object {
      Run $signtool @("sign", "/f", $env:WIN_SIGN_PFX, "/p", $env:WIN_SIGN_PASSWORD, "/fd", "SHA256", "/tr", "http://timestamp.digicert.com", "/td", "SHA256", $_.FullName)
    }
  }
}

Say "Done. Files in .\dist:"
Get-ChildItem dist -File | Where-Object { $_.Extension -in ".exe", ".zip", ".msi" } | ForEach-Object {
  $h = (Get-FileHash $_.FullName -Algorithm SHA256).Hash
  "{0,-52} {1,6} MB   sha256 {2}" -f $_.Name, [math]::Round($_.Length / 1MB), $h.Substring(0, 16)
}
Write-Host @"

Install:   run dist\$name-$ver-setup.exe  (per-user, no admin needed; tick 'Open video and audio files with $name')
           then, once, pick $name in Windows Settings > Default apps (the installer offers to open it).
Portable:  unzip dist\$name-$ver-windows-portable.zip anywhere and run like_potplayer.exe
Silent:    dist\$name-$ver-setup.exe /VERYSILENT /TASKS=assoc
MSI:       msiexec /i dist\$name-$ver-x64.msi /qn      (per-machine, needs admin; no wizard, meant for IT deployment)
"@
