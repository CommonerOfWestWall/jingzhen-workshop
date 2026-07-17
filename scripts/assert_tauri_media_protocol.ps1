param(
    [string]$ConfigPath = (Join-Path $PSScriptRoot "..\src-tauri\tauri.conf.json"),
    [string]$CargoPath = (Join-Path $PSScriptRoot "..\src-tauri\Cargo.toml")
)

$ErrorActionPreference = "Stop"

$config = Get-Content -LiteralPath $ConfigPath -Raw | ConvertFrom-Json
$assetProtocol = $config.app.security.assetProtocol
if ($null -eq $assetProtocol -or $assetProtocol.enable -ne $true) {
    throw "Tauri assetProtocol 未启用，convertFileSrc 生成的本地视频 URL 无法加载"
}

$cargo = Get-Content -LiteralPath $CargoPath -Raw
if ($cargo -notmatch 'tauri\s*=\s*\{[^\r\n]*features\s*=\s*\[[^\]]*"protocol-asset"') {
    throw "Cargo.toml 未启用 Tauri protocol-asset feature"
}

Write-Output "Tauri 本地媒体协议配置检查通过"
