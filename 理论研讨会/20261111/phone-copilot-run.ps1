# Phone Copilot launcher.
# Uses the DeepSeek API key that opencode already saved in auth.json.
# Verified vision model on this gateway: deepseek-chat.
# Usage:  powershell -ExecutionPolicy Bypass -File .\phone-copilot-run.ps1 [-MaxSteps 8] "<task>"
param(
    [Parameter(Position = 0, ValueFromRemainingArguments = $true)]
    [string[]]$Task,
    [int]$MaxSteps = 10
)

$ErrorActionPreference = "Stop"
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"

$exe = Join-Path $PSScriptRoot "phone-copilot-env\Scripts\phone-copilot.exe"
$authPath = Join-Path $env:USERPROFILE ".local\share\opencode\auth.json"
$apiKey = (Get-Content $authPath -Raw | ConvertFrom-Json).deepseek.key

if (-not $Task -or $Task.Count -eq 0) {
    Write-Host 'Usage:   .\phone-copilot-run.ps1 [-MaxSteps 8] "<task>"'
    Write-Host 'Example: .\phone-copilot-run.ps1 -MaxSteps 8 "Open Calculator and compute 12*34"'
    exit 1
}

$taskText = ($Task -join " ").Trim()

& $exe $taskText `
    --base-url "https://api.deepseek.com" `
    --model "deepseek-chat" `
    --api-key $apiKey `
    --lang zh `
    --max-steps $MaxSteps `
    --ccf 1000 `
    --json "phone-copilot-report.json" `
    --html "phone-copilot-report.html"
