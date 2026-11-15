param(
  [string]$Pv = "C:\Users\10092\Desktop\boshiwork\wifi标准\proverifcode\proverifbin2.05\proverif.exe",
  [string]$Dir = "C:\Users\10092\Desktop\boshiwork\wifi标准\proverifcode",
  [int]$TimeoutSec = 600
)
$report = Join-Path $Dir "REVERIFY_$(Get-Date -Format yyyyMMdd_HHmmss).txt"
"# reverify report $(Get-Date -Format s)" | Out-File -FilePath $report -Encoding utf8
$rows = @()
foreach ($f in (Get-ChildItem -LiteralPath $Dir -Filter "*.pv" | Sort-Object Name)) {
  if ($f.Name -eq "FILS_PK_old.pv") { continue }
  $sw = [System.Diagnostics.Stopwatch]::StartNew()
  $out = Join-Path $Dir ("_run_{0}.out" -f $f.BaseName)
  $err = Join-Path $Dir ("_run_{0}.err" -f $f.BaseName)
  $p = Start-Process -FilePath $Pv -ArgumentList @("`"$($f.FullName)`"") -NoNewWindow -PassThru `
       -RedirectStandardOutput $out -RedirectStandardError $err
  $ok = $p.WaitForExit($TimeoutSec * 1000)
  if (-not $ok) { try { $p.Kill() } catch {} }
  $sw.Stop()
  $res = @()
  if ($ok -and (Test-Path $out)) {
    $res = (Get-Content -LiteralPath $out -Encoding UTF8) | Where-Object { $_ -match '^RESULT ' }
  }
  $status = if (-not $ok) { "TIMEOUT" } elseif ($res.Count -eq 0) { "NO-RESULT" } else { "OK" }
  $rows += [pscustomobject]@{ Model=$f.Name; Status=$status; Sec=[math]::Round($sw.Elapsed.TotalSeconds,1); Results=$res }
  "[{0}] {1} {2}s  {3} result lines" -f $status, $f.Name, [math]::Round($sw.Elapsed.TotalSeconds,1), $res.Count | Out-File -FilePath $report -Append -Encoding utf8
  foreach ($r in $res) { "    $r" | Out-File -FilePath $report -Append -Encoding utf8 }
  $errLen = if (Test-Path $err) { (Get-Item $err).Length } else { 0 }
  "{0,-28} {1,-8} {2,7}s  results={3,-3} err={4}B" -f $f.Name, $status, [math]::Round($sw.Elapsed.TotalSeconds,1), $res.Count, $errLen
  Remove-Item $out, $err -ErrorAction SilentlyContinue
}
"REPORT: $report"
