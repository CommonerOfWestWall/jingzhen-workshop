param(
    [string]$Cache = "",
    [string]$Destination = ""
)

$ErrorActionPreference = "Stop"
$workspace = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$outputs = [IO.Path]::GetFullPath((Join-Path $workspace "outputs"))
if (-not $Cache) { $Cache = Join-Path $outputs "validation\gpu-component-probe\wheels" }
if (-not $Destination) { $Destination = Join-Path $outputs "validation\gpu-component-probe\runtime" }
$Cache = [IO.Path]::GetFullPath($Cache)
$Destination = [IO.Path]::GetFullPath($Destination)
foreach ($path in @($Cache, $Destination)) {
    if (-not $path.StartsWith($outputs + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        throw "验证目录必须位于 outputs 内：$path"
    }
}
$manifest = Get-Content -Raw (Join-Path $workspace "engine\gpu-component-manifest.json") | ConvertFrom-Json
if (Test-Path -LiteralPath $Destination) {
    Remove-Item -LiteralPath $Destination -Recurse -Force
}
$site = Join-Path $Destination "site-packages"
$modelDir = Join-Path $Destination "model"
New-Item -ItemType Directory -Force $site, $modelDir | Out-Null
foreach ($artifact in $manifest.artifacts) {
    $source = Join-Path $Cache $artifact.filename
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) { throw "缺少缓存文件：$source" }
    $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $source).Hash.ToLowerInvariant()
    if ((Get-Item -LiteralPath $source).Length -ne $artifact.size -or $hash -ne $artifact.sha256) {
        throw "校验失败：$($artifact.name)"
    }
    if ($artifact.kind -eq "wheel") {
        & tar.exe -xf $source -C $site
        if ($LASTEXITCODE -ne 0) { throw "无法解压：$($artifact.name)" }
    } else {
        Copy-Item -LiteralPath $source -Destination (Join-Path $modelDir "lama_fp32.onnx")
    }
}
$launcher = Join-Path $workspace "engine\dist\lama-gpu-launcher.exe"
$env:JINGZHEN_GPU_RUNTIME = $Destination
try {
    & $launcher --model (Join-Path $modelDir "lama_fp32.onnx") --check --require-provider CUDAExecutionProvider
    if ($LASTEXITCODE -ne 0) { throw "GPU 启动器自检失败：$LASTEXITCODE" }
} finally {
    Remove-Item Env:JINGZHEN_GPU_RUNTIME -ErrorAction SilentlyContinue
}
