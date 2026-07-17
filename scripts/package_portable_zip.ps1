$ErrorActionPreference = "Stop"

$workspace = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$outputs = Join-Path $workspace "outputs"
$portableName = -join (0x51c0, 0x5e27, 0x5de5, 0x574a, 0x2d, 0x514d, 0x5b89, 0x88c5, 0x7248 | ForEach-Object { [char]$_ })
$portable = Join-Path $outputs $portableName
$archive = Join-Path $outputs ($portableName + ".zip")

if (-not (Test-Path -LiteralPath $portable -PathType Container)) {
    throw "Portable directory is missing: $portable"
}
$mainExecutable = Get-ChildItem -LiteralPath $portable -File -Filter "*.exe" | Select-Object -First 1
if (-not $mainExecutable) {
    throw "Portable directory does not contain the main executable"
}
if (-not (Test-Path -LiteralPath (Join-Path $portable "SHA256SUMS.txt") -PathType Leaf)) {
    throw "Portable directory does not contain SHA256SUMS.txt"
}

if (Test-Path -LiteralPath $archive) {
    Remove-Item -LiteralPath $archive -Force
}
Compress-Archive -LiteralPath $portable -DestinationPath $archive -CompressionLevel Optimal

if (-not (Test-Path -LiteralPath $archive -PathType Leaf)) {
    throw "ZIP creation failed"
}
Write-Output $archive
