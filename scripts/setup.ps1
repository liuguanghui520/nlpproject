# 同步已锁定依赖并验证本地环境；不调用模型，也不覆盖已有.env。
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
$taskUvCommand = Get-Command uv -ErrorAction SilentlyContinue
$taskUvPath = if ($taskUvCommand) { $taskUvCommand.Source } else {
    Join-Path $env:USERPROFILE '.local/bin/uv.exe'
}
if (-not (Test-Path -LiteralPath $taskUvPath)) {
    throw 'uv was not found. Install uv from https://docs.astral.sh/uv/getting-started/installation/.'
}

Push-Location -LiteralPath $taskRoot
try {
    if (-not (Test-Path -LiteralPath '.env')) {
        Copy-Item -LiteralPath '.env.example' -Destination '.env'
    }
    # frozen避免日常同步意外更新版本；升级时显式更新uv.lock并复验。
    & $taskUvPath sync --frozen
    if ($LASTEXITCODE -ne 0) { throw 'Dependency synchronization failed.' }
    & $taskUvPath run --frozen python scripts/check_environment.py
    if ($LASTEXITCODE -ne 0) { throw 'Environment checks failed.' }
}
finally {
    Pop-Location
}
