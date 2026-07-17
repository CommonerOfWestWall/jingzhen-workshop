param(
    [string]$ModelId = "opencv-lama-inpainting-2025jan"
)

$ErrorActionPreference = "Stop"

$workspace = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$modelsRoot = Join-Path $workspace "models"
$manifestPath = Join-Path $modelsRoot "manifest.json"
$manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
$model = $manifest.models | Where-Object { $_.id -eq $ModelId } | Select-Object -First 1
if (-not $model) {
    throw "Model is not present in models/manifest.json: $ModelId"
}

$destination = Join-Path $modelsRoot $model.filename
if (Test-Path -LiteralPath $destination -PathType Leaf) {
    $existing = Get-Item -LiteralPath $destination
    $hash = (Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($existing.Length -eq [long]$model.size -and $hash -eq $model.sha256) {
        Write-Output $destination
        exit 0
    }
}

$partial = "$destination.part"
Remove-Item -LiteralPath $partial -Force -ErrorAction SilentlyContinue
Write-Host "Downloading model from its pinned manifest URL: $($model.name)"
Invoke-WebRequest -Uri $model.url -OutFile $partial -UseBasicParsing

$downloaded = Get-Item -LiteralPath $partial
if ($downloaded.Length -ne [long]$model.size) {
    throw "Model size check failed. Expected $($model.size), got $($downloaded.Length)."
}
$hash = (Get-FileHash -LiteralPath $partial -Algorithm SHA256).Hash.ToLowerInvariant()
if ($hash -ne $model.sha256) {
    throw "Model SHA-256 check failed: $hash"
}
Move-Item -LiteralPath $partial -Destination $destination -Force
Write-Output $destination
