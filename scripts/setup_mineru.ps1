param(
    [string]$Python = "python"
)

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$runtimeRoot = Join-Path $projectRoot 'mineru_runtime'
$backendPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
$mineruPython = Join-Path $runtimeRoot '.venv\Scripts\python.exe'
$mineruSource = Join-Path $projectRoot 'vendor\MinerU'

if (-not (Test-Path -LiteralPath (Join-Path $mineruSource 'pyproject.toml'))) {
    throw 'MinerU source missing: vendor/MinerU/pyproject.toml'
}
if (-not (Test-Path -LiteralPath $backendPython) -or -not (Test-Path -LiteralPath $mineruPython)) {
    & $Python -c 'import sys; assert sys.version_info[:2] == (3, 12), "Python 3.12 is required"'
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.12 unavailable. Pass -Python with a working python.exe path.' }
}
New-Item -ItemType Directory -Force -Path $runtimeRoot | Out-Null
$env:TEMP = Join-Path $runtimeRoot 'tmp'
$env:TMP = $env:TEMP
$env:TMPDIR = $env:TEMP
$env:PIP_CACHE_DIR = Join-Path $runtimeRoot 'cache\pip'
$env:HF_HOME = Join-Path $runtimeRoot 'cache\huggingface'
$env:MODELSCOPE_CACHE = Join-Path $runtimeRoot 'cache\modelscope'
$env:MINERU_HOME = Join-Path $runtimeRoot '.mineru'
$env:MINERU_MODEL_SOURCE = 'modelscope'
$env:MINERU_MODEL_SMALL_BACKEND = 'onnx'
foreach ($directory in @($env:TEMP, $env:PIP_CACHE_DIR, $env:HF_HOME, $env:MODELSCOPE_CACHE, $env:MINERU_HOME)) {
    New-Item -ItemType Directory -Force -Path $directory | Out-Null
}

if (-not (Test-Path -LiteralPath $backendPython)) {
    & $Python -m venv (Join-Path $projectRoot '.venv')
    if ($LASTEXITCODE -ne 0) { throw 'Could not create backend environment. Supply a working Python 3.12 with -Python.' }
}
& $backendPython -m pip install -r (Join-Path $projectRoot 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'Backend dependency installation failed.' }

if (-not (Test-Path -LiteralPath $mineruPython)) {
    & $Python -m venv (Join-Path $runtimeRoot '.venv')
    if ($LASTEXITCODE -ne 0) { throw 'Could not create MinerU environment. Supply a working Python 3.12 with -Python.' }
}
& $mineruPython -m pip install -e $mineruSource
if ($LASTEXITCODE -ne 0) { throw 'MinerU installation failed.' }

$mineruKit = Join-Path $runtimeRoot '.venv\Scripts\mineru-kit.exe'
& $mineruKit models download --tier basic --small-backend onnx --source modelscope
if ($LASTEXITCODE -ne 0) { throw 'MinerU model download failed.' }
& $mineruKit models verify --tier basic --small-backend onnx
if ($LASTEXITCODE -ne 0) { throw 'MinerU model verification failed.' }
Write-Host 'MinerU basic is ready. Start with: .\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000'
