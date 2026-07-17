# 净帧工坊

[![CI](https://github.com/CommonerOfWestWall/jingzhen-workshop/actions/workflows/ci.yml/badge.svg)](https://github.com/CommonerOfWestWall/jingzhen-workshop/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

净帧工坊是一款面向 Windows 的离线视频画面修复编辑器，用于处理用户拥有或已获授权的视频素材。它不是某个平台的专用水印工具。

## 功能

- 固定区域、移动目标和透明度变化三种范围策略。
- 画笔、矩形、套索、减去选区、关键帧和低置信区间提示。
- 内置双向光流/仿射移动掩膜传播，支持关键帧修正。
- OpenCV LaMa 高清修复，固定层与移动层可在一次导出中处理。
- FFmpeg 显式流映射，尽量保留兼容音频、文本字幕和必要元数据。
- 项目保存、批量队列、安全取消、唯一输出命名和竖屏素材。
- 基础 CPU 模式直接可用；兼容 NVIDIA 用户可在程序内安装独立 CUDA 组件，支持断点续传和 SHA-256 校验。
- 所有视频处理均在本机完成。

当前限制和公开测试摘要见 [验证记录](docs/validation-matrix.md)，上游模型与许可证研究见 [模型研究](docs/research/upstream-models.md)。

## 技术结构

- `src/`：React/TypeScript 编辑界面。
- `src-tauri/`：Rust/Tauri 2 文件管理、任务队列、进度、取消、FFmpeg 调度和 GPU 组件管理。
- `engine/`：Python/OpenCV/ONNX Runtime sidecar 与 PyInstaller 配置。
- `models/manifest.json`：模型来源、大小和 SHA-256；模型二进制不提交到 Git。
- `scripts/`：模型下载、检查、Release 和免安装目录打包脚本。

## 开发环境

需要 Windows、Rust、Node.js 24、Python 3.12、WebView2 和 FFmpeg。先安装依赖：

```powershell
git clone https://github.com/CommonerOfWestWall/jingzhen-workshop.git
cd jingzhen-workshop

npm ci
python -m venv engine\.venv
.\engine\.venv\Scripts\python.exe -m pip install -e ".\engine[dev]"
```

启动开发界面：

```powershell
npm run tauri -- dev
```

## 运行检查

```powershell
cd engine
.\.venv\Scripts\python.exe -m pytest -q

cd ..
npm test -- --run
npm run build

cd src-tauri
cargo fmt --all -- --check
cargo test
```

## 构建 Windows 免安装版

源码仓库不提交模型、FFmpeg、Python/CUDA 运行库或生成的 EXE。先按清单下载并校验 CPU 模型：

```powershell
.\scripts\download_models.ps1
```

准备一个包含 `bin/ffmpeg.exe`、`bin/ffprobe.exe`、`LICENSE` 和 `README.txt` 的 FFmpeg Windows 目录。默认路径是 `C:\ffmpeg`，也可设置：

```powershell
$env:JINGZHEN_FFMPEG_ROOT = "D:\tools\ffmpeg"
```

然后构建 sidecar、Tauri Release 和免安装目录：

```powershell
cd engine
.\.venv\Scripts\pyinstaller.exe --clean --noconfirm jingzhen-engine.spec
.\.venv\Scripts\pyinstaller.exe --clean --noconfirm lama-frame-engine.spec
.\.venv\Scripts\pyinstaller.exe --clean --noconfirm lama-gpu-launcher.spec

cd ..
npm run tauri -- build --no-bundle
.\scripts\build_portable.ps1
.\scripts\package_portable_zip.ps1
```

不要用普通 `cargo build --release` 的产物直接封装；打包脚本会检查生产前端是否真正内嵌，防止 EXE 打开开发服务器地址。

## 模型与许可证

项目代码采用 [Apache-2.0](LICENSE)。第三方模型、FFmpeg、ONNX Runtime 和 NVIDIA 组件保留各自许可证，详情见 `licenses/`。

- OpenCV LaMa CPU 模型：Apache-2.0，可按清单下载并放入便携成品。
- LaMa FP32 GPU 模型：Apache-2.0，由兼容 NVIDIA 用户首次安装 GPU 组件时下载。
- ProPainter 与 E2FGVI-HQ：上游限制非商业使用，不随本项目发行版分发。
- NVIDIA CUDA/cuDNN：不随基础源码或基础 ZIP 预装；用户主动安装时接受 NVIDIA 条款。

请只处理自己拥有或已经获得授权的视频。贡献和分发不得暗示对第三方平台、内容或商标的授权。

## 贡献与安全

参见 [CONTRIBUTING.md](CONTRIBUTING.md) 和 [SECURITY.md](SECURITY.md)。
