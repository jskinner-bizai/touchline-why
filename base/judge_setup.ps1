param([string]$Python = 'python')
$ErrorActionPreference = 'Stop'
$env:PYTHONDONTWRITEBYTECODE = '1'
$packageRoot = $PSScriptRoot
& $Python -c "import sys,platform; assert sys.implementation.name=='cpython' and sys.version_info[:3]==(3,12,2) and sys.platform=='win32' and platform.machine().upper()=='AMD64', 'Requires exact CPython 3.12.2 Windows AMD64'"
if ($LASTEXITCODE -ne 0) { throw 'Unsupported Python runtime' }
& $Python (Join-Path $packageRoot 'verify_package.py')
if ($LASTEXITCODE -ne 0) { throw 'Package verification failed' }
if (-not (Test-Path -LiteralPath (Join-Path $packageRoot 'wheelhouse') -PathType Container)) { throw 'This source bundle has no wheels. Use the companion judge ZIP for the full offline SDK setup; the recorded demo needs no SDK install.' }
# Keep mutable runtime and verification logs outside the immutable package.
$runtimeRoot = Join-Path (Split-Path -Parent $packageRoot) ($([IO.Path]::GetFileName($packageRoot)) + '-runtime')
if (Test-Path -LiteralPath $runtimeRoot) { throw 'Runtime directory already exists; select a fresh extraction folder' }
& $Python -m venv (Join-Path $runtimeRoot '.venv')
if ($LASTEXITCODE -ne 0) { throw 'venv creation failed' }
$runtimePython = Join-Path $runtimeRoot '.venv\Scripts\python.exe'
& $runtimePython -m pip --isolated --disable-pip-version-check install --no-index --no-cache-dir --require-hashes --only-binary=:all: --find-links (Join-Path $packageRoot 'wheelhouse') -r (Join-Path $packageRoot 'requirements.lock')
if ($LASTEXITCODE -ne 0) { throw 'Offline install failed' }
& $runtimePython -m pip --isolated --disable-pip-version-check check
if ($LASTEXITCODE -ne 0) { throw 'pip check failed' }
Write-Output "Offline SDK dependencies installed. Runtime Python: $runtimePython"
Write-Output 'No model has been called. Follow README.md and TESTING_INSTRUCTIONS.md for the recorded default demo and fixed test capsule.'
