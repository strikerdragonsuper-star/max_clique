param(
    [switch]$SkipBenchmark,
    [switch]$FullCliqueAI
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$CliqueRoot = Join-Path (Split-Path $ProjectRoot -Parent) "CliqueAI"
$VenvDir = Join-Path $ProjectRoot "venv"

Write-Host "Installing model-upgrade for CliqueAI subnet 83..."
Write-Host "Project root: $ProjectRoot"
Write-Host "CliqueAI root: $CliqueRoot"

if (-not (Test-Path $CliqueRoot)) {
    throw "CliqueAI repo not found at $CliqueRoot"
}

if (-not (Get-Command cargo -ErrorAction SilentlyContinue)) {
    throw "Rust toolchain not found. Install from https://rustup.rs/"
}

if (-not (Test-Path $VenvDir)) {
    python -m venv $VenvDir
}

$Python = Join-Path $VenvDir "Scripts\python.exe"
$Pip = Join-Path $VenvDir "Scripts\pip.exe"

& $Python -m pip install --upgrade pip
& $Pip install -e $ProjectRoot
& $Pip install pydantic

Write-Host "Building Rust solver extension (maturin)..."
& $Pip install maturin
$Maturin = Join-Path $VenvDir "Scripts\maturin.exe"
Push-Location (Join-Path $ProjectRoot "crates\model_upgrade_py")
try {
    & $Maturin develop --release
} finally {
    Pop-Location
}

if ($FullCliqueAI) {
    Write-Host "Installing full CliqueAI stack (requires Linux or OpenSSL dev libs on Windows)..."
    & $Pip install -e $CliqueRoot
} else {
    Write-Host "Solver-only install complete (benchmark uses CliqueAI source via PYTHONPATH)."
    Write-Host "For production mining, deploy on Linux and run: ./install.sh"
}

Write-Host ""
Write-Host "Solver: rust (model_upgrade_rs)"
Write-Host "Activate with: .\venv\Scripts\Activate.ps1"

if (-not $SkipBenchmark) {
    Write-Host ""
    Write-Host "Running benchmark..."
    & $Python (Join-Path $ProjectRoot "scripts\benchmark.py")
}
