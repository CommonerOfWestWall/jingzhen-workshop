param(
    [Parameter(Mandatory = $true)]
    [string]$ExePath,
    [Parameter(Mandatory = $true)]
    [string]$DistPath
)

$ErrorActionPreference = "Stop"
$exe = [IO.Path]::GetFullPath($ExePath)
$dist = [IO.Path]::GetFullPath($DistPath)
$index = Join-Path $dist "index.html"

if (-not (Test-Path -LiteralPath $exe -PathType Leaf)) {
    throw "桌面 EXE 不存在：$exe"
}
if (-not (Test-Path -LiteralPath $index -PathType Leaf)) {
    throw "前端入口不存在：$index"
}

$html = Get-Content -LiteralPath $index -Raw
$assets = [regex]::Matches($html, '(?:src|href)="([^"]+)"') |
    ForEach-Object { [IO.Path]::GetFileName($_.Groups[1].Value) } |
    Where-Object { $_ } |
    Sort-Object -Unique
if (-not $assets) {
    throw "dist/index.html 没有可验证的前端资源引用"
}

$binary = [Text.Encoding]::GetEncoding(28591).GetString(
    [IO.File]::ReadAllBytes($exe)
)
$missing = @($assets | Where-Object { -not $binary.Contains($_) })
if ($missing.Count -gt 0) {
    throw "桌面 EXE 未内嵌当前 dist 资源，拒绝封装：$($missing -join ', ')。请运行：npm run tauri -- build --no-bundle"
}

Write-Output "embedded_frontend=PASS assets=$($assets -join ',')"
