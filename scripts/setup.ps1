[CmdletBinding()]
param(
    [switch]$CheckOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path

function Refresh-ProcessPath {
    $machinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$machinePath;$userPath;$env:Path"
}

function Install-WingetPackage([string]$packageId, [switch]$Upgrade) {
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if ($null -eq $winget) {
        throw "Windows Package Manager (winget) is required. Install Microsoft App Installer, then run this script again."
    }

    $wingetArguments = @(
        $(if ($Upgrade) { "upgrade" } else { "install" }),
        "--id", $packageId,
        "--exact",
        "--source", "winget",
        "--silent",
        "--accept-package-agreements",
        "--accept-source-agreements",
        "--disable-interactivity"
    )
    if (-not $Upgrade) {
        $wingetArguments += "--no-upgrade"
    }
    & $winget.Source @wingetArguments
    if ($LASTEXITCODE -ne 0) {
        throw "winget could not install $packageId (exit $LASTEXITCODE)."
    }
    Refresh-ProcessPath
}

function Ensure-Command([string]$name, [string]$packageId) {
    if ($null -eq (Get-Command $name -ErrorAction SilentlyContinue)) {
        Install-WingetPackage $packageId
    }
    if ($null -eq (Get-Command $name -ErrorAction SilentlyContinue)) {
        throw "$name was installed but is not available in this process. Open a new terminal and run setup again."
    }
}

function Invoke-Checked([string]$command, [string[]]$arguments) {
    & $command @arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$command failed with exit code $LASTEXITCODE."
    }
}

Push-Location -LiteralPath $repoRoot
try {
    foreach ($requiredFile in @("pyproject.toml", "uv.lock", "package.json", "package-lock.json")) {
        if (-not (Test-Path -LiteralPath (Join-Path $repoRoot $requiredFile) -PathType Leaf)) {
            throw "Run this script from a complete Proms repository checkout; $requiredFile is missing."
        }
    }

    if ($CheckOnly) {
        $missing = @(
            @("uv", "node", "npm", "npx") | Where-Object {
                $null -eq (Get-Command $_ -ErrorAction SilentlyContinue)
            }
        )
        if ($missing.Count -gt 0) {
            throw "Missing prerequisites: $($missing -join ', '). Run scripts/setup.ps1 without -CheckOnly."
        }
        $nodeVersion = [version]((& node --version).TrimStart("v"))
        if ($nodeVersion -lt [version]"20.9.0") {
            throw "Node.js 20.9 or newer is required; found $nodeVersion."
        }
        Write-Output "READY: setup prerequisites are available"
        exit 0
    }

    Ensure-Command "uv" "astral-sh.uv"
    Ensure-Command "node" "OpenJS.NodeJS.LTS"
    Ensure-Command "npm" "OpenJS.NodeJS.LTS"
    Ensure-Command "npx" "OpenJS.NodeJS.LTS"

    $nodeVersion = [version]((& node --version).TrimStart("v"))
    if ($nodeVersion -lt [version]"20.9.0") {
        Install-WingetPackage "OpenJS.NodeJS.LTS" -Upgrade
        $nodeVersion = [version]((& node --version).TrimStart("v"))
        if ($nodeVersion -lt [version]"20.9.0") {
            throw "Node.js 20.9 or newer is required; found $nodeVersion."
        }
    }

    Invoke-Checked "uv" @("sync", "--locked")
    Invoke-Checked "npm" @("ci")
    Invoke-Checked "npx" @("playwright", "install", "chromium")
    Invoke-Checked "uv" @("run", "--locked", "playwright", "install", "chromium")
    Invoke-Checked "npm" @("run", "build")

    $proxyPath = Join-Path $repoRoot "proxies.txt"
    if (-not (Test-Path -LiteralPath $proxyPath)) {
        New-Item -ItemType File -Path $proxyPath | Out-Null
    }

    Write-Output "READY: dependencies, Chromium, and the local control panel are installed"
    Write-Output "NEXT: run 'uv run --locked proms', then open http://127.0.0.1:8000/control/"
}
finally {
    Pop-Location
}
