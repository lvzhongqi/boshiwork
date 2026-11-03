param(
  [Parameter(Mandatory=$true)][string]$PvExe,
  [Parameter(Mandatory=$true)][string]$Model,
  [int]$TimeoutSec = 600
)
$logDir = Split-Path -Parent $Model
$name = [System.IO.Path]::GetFileNameWithoutExtension($Model)
$outLog = Join-Path $logDir ("{0}.out.txt" -f $name)
$errLog = Join-Path $logDir ("{0}.err.txt" -f $name)
if (Test-Path $outLog) { Remove-Item -Force $outLog }
if (Test-Path $errLog) { Remove-Item -Force $errLog }

$sw = [System.Diagnostics.Stopwatch]::StartNew()
$p = Start-Process -FilePath $PvExe -ArgumentList @("`"$Model`"") -NoNewWindow -PassThru `
     -RedirectStandardOutput $outLog -RedirectStandardError $errLog
$finished = $p.WaitForExit($TimeoutSec * 1000)
if (-not $finished) {
  try { $p.Kill() } catch { }
  Write-Output "TIMEOUT after $TimeoutSec s"
  exit 124
}
$sw.Stop()
Write-Output ("EXITCODE {0} in {1:N1}s" -f $p.ExitCode, $sw.Elapsed.TotalSeconds)
Write-Output "--- stdout ---"
Get-Content -LiteralPath $outLog -Encoding UTF8
Write-Output "--- stderr ---"
Get-Content -LiteralPath $errLog -Encoding UTF8

