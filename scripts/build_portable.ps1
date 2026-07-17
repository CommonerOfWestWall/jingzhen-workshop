$ErrorActionPreference = "Stop"

$workspace = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$outputsRoot = [IO.Path]::GetFullPath((Join-Path $workspace "outputs"))
$target = [IO.Path]::GetFullPath((Join-Path $outputsRoot "净帧工坊-免安装版"))
$ffmpegRoot = if ([string]::IsNullOrWhiteSpace($env:JINGZHEN_FFMPEG_ROOT)) {
    "C:\ffmpeg"
} else {
    [IO.Path]::GetFullPath($env:JINGZHEN_FFMPEG_ROOT)
}

if (-not $target.StartsWith($outputsRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw "拒绝清理 outputs 目录以外的路径：$target"
}

$required = @(
    (Join-Path $workspace "src-tauri\target\release\jingzhen-workshop.exe"),
    (Join-Path $workspace "engine\dist\jingzhen-engine.exe"),
    (Join-Path $ffmpegRoot "bin\ffmpeg.exe"),
    (Join-Path $ffmpegRoot "bin\ffprobe.exe"),
    (Join-Path $workspace "engine\dist\lama-frame-engine.exe"),
    (Join-Path $workspace "engine\dist\lama-gpu-launcher.exe"),
    (Join-Path $workspace "engine\gpu-component-manifest.json"),
    (Join-Path $workspace "models\inpainting_lama_2025jan.onnx")
)
foreach ($path in $required) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "缺少便携版必需文件：$path"
    }
}

& "$PSScriptRoot\assert_tauri_media_protocol.ps1" | Out-Null
& "$PSScriptRoot\assert_tauri_embedded_frontend.ps1" `
    -ExePath $required[0] `
    -DistPath (Join-Path $workspace "dist") | Out-Null

if (Test-Path -LiteralPath $target) {
    Remove-Item -LiteralPath $target -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $target, "$target\engine", "$target\models", "$target\ffmpeg", "$target\licenses" | Out-Null

Copy-Item -LiteralPath $required[0] -Destination "$target\净帧工坊.exe"
Copy-Item -LiteralPath $required[1] -Destination "$target\engine\jingzhen-engine.exe"
Copy-Item -LiteralPath $required[4] -Destination "$target\engine\lama-frame-engine.exe"
Copy-Item -LiteralPath $required[5] -Destination "$target\engine\lama-gpu-launcher.exe"
Copy-Item -LiteralPath $required[6] -Destination "$target\engine\gpu-component-manifest.json"
Copy-Item -LiteralPath $required[7] -Destination "$target\models\inpainting_lama_2025jan.onnx"
Copy-Item -LiteralPath $required[2] -Destination "$target\ffmpeg\ffmpeg.exe"
Copy-Item -LiteralPath $required[3] -Destination "$target\ffmpeg\ffprobe.exe"
Copy-Item -LiteralPath "$workspace\models\manifest.json" -Destination "$target\models\manifest.json"
Copy-Item -LiteralPath "$workspace\licenses\MODEL-LICENSES.md" -Destination "$target\licenses\MODEL-LICENSES.md"
Copy-Item -LiteralPath "$workspace\LICENSE" -Destination "$target\licenses\OpenCV-LaMa-Apache-2.0.txt"
Copy-Item -LiteralPath "$workspace\licenses\FFmpeg-BUILD.md" -Destination "$target\licenses\FFmpeg-BUILD.md"
Copy-Item -LiteralPath "$workspace\licenses\GPU-COMPONENT-LICENSES.md" -Destination "$target\licenses\GPU-COMPONENT-LICENSES.md"
Copy-Item -LiteralPath "$ffmpegRoot\LICENSE" -Destination "$target\licenses\FFmpeg-GPL-3.0.txt"
Copy-Item -LiteralPath "$ffmpegRoot\README.txt" -Destination "$target\licenses\FFmpeg-Windows-Build-README.txt"
Copy-Item -LiteralPath "$workspace\docs\research\upstream-models.md" -Destination "$target\licenses\上游模型研究.md"
Copy-Item -LiteralPath "$workspace\使用说明.md" -Destination "$target\使用说明.md"
Copy-Item -LiteralPath "$workspace\docs\validation-matrix.md" -Destination "$target\测试报告.md"

Get-ChildItem -LiteralPath $target -Recurse -File |
    Get-FileHash -Algorithm SHA256 |
    ForEach-Object {
        $relative = $_.Path.Substring($target.Length).TrimStart([char[]]"\/")
        "{0}  {1}" -f $_.Hash.ToLowerInvariant(), $relative
    } |
    Set-Content -LiteralPath "$target\SHA256SUMS.txt" -Encoding utf8

Write-Output $target
