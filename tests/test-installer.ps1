<#
.SYNOPSIS  Installs the built setup .exe silently into a temp folder, checks it, then uninstalls it.
.EXAMPLE   .\tests\test-installer.ps1            # uses the newest dist\*-setup.exe
#>
param([string]$Setup = "", [switch]$Msi)
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
if (-not $Setup) { $Setup = (Get-ChildItem dist -Filter "*-setup.exe" | Sort-Object LastWriteTime -Descending | Select-Object -First 1).FullName }
if (-not $Setup -or -not (Test-Path $Setup)) { Write-Host "no setup .exe found: run .\build-windows.ps1 first"; exit 1 }
$script:fails = 0
function Check($ok, $msg) { if ($ok) { Write-Host "PASS  $msg" } else { Write-Host "FAIL  $msg"; $script:fails++ } }
function RegDefault($path) { try { (Get-ItemProperty -Path $path -ErrorAction Stop).'(default)' } catch { $null } }

$dir = Join-Path $env:TEMP "like_potplayer-install-test"
if (Test-Path $dir) { Remove-Item -Recurse -Force $dir }
Write-Host "installing $Setup -> $dir"
$p = Start-Process $Setup -ArgumentList @("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CURRENTUSER", "/TASKS=assoc", "/DIR=`"$dir`"", "/LOG=`"$env:TEMP\like_potplayer-install.log`"") -Wait -PassThru
Check ($p.ExitCode -eq 0) "installer exit code 0"
$exe = Join-Path $dir "like_potplayer.exe"
Check (Test-Path $exe) "program installed: $exe"

$cmd = RegDefault "HKCU:\Software\Classes\like_potplayer.Media\shell\open\command"
Check ($cmd -and $cmd.Contains("like_potplayer.exe") -and $cmd.Contains('"%1"')) "double-click command registered: $cmd"
foreach ($ext in @(".mp4", ".mkv", ".mp3", ".flac", ".avi")) {
  $v = Get-ItemProperty -Path "HKCU:\Software\Classes\$ext\OpenWithProgids" -Name "like_potplayer.Media" -ErrorAction SilentlyContinue
  Check ($null -ne $v) "$ext offers like_potplayer under 'Open with'"
}
$ra = Get-ItemProperty -Path "HKCU:\Software\RegisteredApplications" -Name "like_potplayer" -ErrorAction SilentlyContinue
Check ($null -ne $ra) "listed under Settings > Default apps (RegisteredApplications)"

Remove-Item (Join-Path $env:TEMP "like_potplayer-selftest.txt") -ErrorAction SilentlyContinue
$t = Start-Process $exe -ArgumentList "--self-test" -Wait -PassThru
Check ($t.ExitCode -eq 0) "installed program starts and loads Qt + libmpv"

$un = Get-ChildItem $dir -Filter "unins*.exe" | Select-Object -First 1
Start-Process $un.FullName -ArgumentList @("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART") -Wait
Start-Sleep -Seconds 2
Check (-not (Test-Path $exe)) "uninstall removed the program"
Check (-not (Test-Path "HKCU:\Software\Classes\like_potplayer.Media")) "uninstall removed the file-type registration"
Check (-not (Test-Path "HKCU:\Software\like_potplayer")) "uninstall removed the Default-apps capabilities"
if ($script:fails -gt 0) { Write-Host "`n$($script:fails) check(s) failed"; exit 1 }
Write-Host "`nInstaller checks passed"

if ($Msi) {
  Write-Host "`n--- MSI (needs an elevated PowerShell) ---"
  $msiFile = (Get-ChildItem dist -Filter "*.msi" | Sort-Object LastWriteTime -Descending | Select-Object -First 1).FullName
  if (-not $msiFile) { Write-Host "no .msi in dist"; exit 1 }
  $m = Start-Process msiexec.exe -ArgumentList @("/i", "`"$msiFile`"", "/qn", "/norestart", "/l*v", "`"$env:TEMP\like_potplayer-msi.log`"") -Wait -PassThru
  Check ($m.ExitCode -eq 0) "msi installs (exit code $($m.ExitCode); log: $env:TEMP\like_potplayer-msi.log)"
  $mexe = Join-Path $env:ProgramFiles "like_potplayer\like_potplayer.exe"
  Check (Test-Path $mexe) "msi installed $mexe"
  $c = (Get-ItemProperty -Path "HKLM:\Software\Classes\like_potplayer.Media\shell\open\command" -ErrorAction SilentlyContinue).'(default)'
  Check ($c -and $c.Contains("like_potplayer.exe")) "msi registered the double-click command: $c"
  $mt = Start-Process $mexe -ArgumentList "--self-test" -Wait -PassThru
  Check ($mt.ExitCode -eq 0) "msi-installed program loads Qt + libmpv"
  $u = Start-Process msiexec.exe -ArgumentList @("/x", "`"$msiFile`"", "/qn", "/norestart") -Wait -PassThru
  Check ($u.ExitCode -eq 0 -and -not (Test-Path $mexe)) "msi uninstalls cleanly"
  if ($script:fails -gt 0) { Write-Host "`n$($script:fails) check(s) failed"; exit 1 }
  Write-Host "`nMSI checks passed"
}
