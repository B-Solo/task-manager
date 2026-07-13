# Launch the Controller (the operator's Windows laptop).
# Activates the repo's virtualenv and starts the full-screen touch UI + client.
#
# Usage (from the VS Code PowerShell terminal, at the repo root):
#   .\run-controller.ps1                 # connect to BESOLOMO-M-WDKQ.local
#   .\run-controller.ps1 192.168.1.42    # or a raw IP / other host
#
# If PowerShell blocks the script ("running scripts is disabled"), either run
# it for this session:   powershell -ExecutionPolicy Bypass -File .\run-controller.ps1
# or allow local scripts: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

# The Viewer (macOS) is reachable over the LAN by its Bonjour/mDNS name.
$Viewer = if ($args.Count -ge 1) { $args[0] } else { "BESOLOMO-M-WDKQ.local" }

$Activate = Join-Path $PSScriptRoot ".venv\Scripts\Activate.ps1"
if (-not (Test-Path $Activate)) {
    Write-Host "No virtualenv at .venv. Create it once with:"
    Write-Host "  python -m venv .venv"
    Write-Host "  .venv\Scripts\Activate.ps1"
    Write-Host "  pip install -r controller\requirements.txt"
    exit 1
}

& $Activate
python controller\src\app.py --host $Viewer
