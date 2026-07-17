param(
    [string]$Destination = ""
)

$ErrorActionPreference = "Stop"
$workspace = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
if (-not $Destination) {
    $Destination = Join-Path $workspace "outputs\validation\gpu-component-probe\wheels"
}
$Destination = [IO.Path]::GetFullPath($Destination)
$allowedRoot = [IO.Path]::GetFullPath((Join-Path $workspace "outputs"))
if (-not $Destination.StartsWith($allowedRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw "下载目录必须位于 outputs 内：$Destination"
}
$manifest = Get-Content -Raw (Join-Path $workspace "engine\gpu-component-manifest.json") | ConvertFrom-Json
New-Item -ItemType Directory -Force $Destination | Out-Null
foreach ($artifact in $manifest.artifacts) {
    $target = Join-Path $Destination $artifact.filename
    if (Test-Path -LiteralPath $target) {
        $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $target).Hash.ToLowerInvariant()
        if ((Get-Item -LiteralPath $target).Length -eq $artifact.size -and $hash -eq $artifact.sha256) {
            Write-Output "已缓存：$($artifact.name)"
            continue
        }
    }
    & curl.exe -L --fail --retry 5 --continue-at - --output $target $artifact.url
    if ($LASTEXITCODE -ne 0) { throw "下载失败：$($artifact.name)" }
    $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $target).Hash.ToLowerInvariant()
    if ((Get-Item -LiteralPath $target).Length -ne $artifact.size -or $hash -ne $artifact.sha256) {
        throw "校验失败：$($artifact.name)"
    }
    Write-Output "下载并校验：$($artifact.name)"
}
