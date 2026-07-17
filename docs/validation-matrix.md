# 净帧工坊 0.1 公开验证摘要

最后更新：2026-07-16。详细的内部样片文件名、路径和截图未放入公开仓库；本页只保留可复现的技术结论。

## 开发环境

| 项目 | 实测值 |
| --- | --- |
| 系统 | Windows 10.0.19045 |
| GPU | NVIDIA GeForce RTX 5070 Ti，16 GB，驱动 610.74 |
| 工具链 | Rust 1.95.0、Tauri CLI 2.11.4、Node 24.13.0、npm 11.6.2、Python 3.12.8 |
| CPU 模型 | OpenCV LaMa ONNX，Apache-2.0 |
| 可选 GPU 模型 | Carve LaMa FP32 ONNX，Apache-2.0 |
| FFmpeg | 8.1.1 GPL v3 Windows build |

## 自动化检查

| 检查 | 结果 |
| --- | --- |
| Python 语法检查与 pytest | 33 passed |
| 前端 Vitest | 21 passed |
| TypeScript 与 Vite production build | 通过 |
| Rust `cargo fmt --check` | 通过 |
| Rust `cargo test` | 11 passed |
| Tauri release `--no-bundle` | 通过；未生成安装包 |
| 内嵌前端检查 | 通过；Release EXE 不依赖 Vite 开发服务器 |

Rust 测试覆盖唯一命名、结构化错误、可变帧率解析、GPU 清单一致性、SHA-256、ZIP 路径穿越拒绝、安装标记完整性，以及真实本机 HTTP `Range` 断点续传。

## 视频结构回归

测试矩阵覆盖：

- 横屏与竖屏。
- 24、25、30、60 fps。
- 固定标记、移动目标、缩放/旋转目标、透明度周期变化和遮挡后重新出现。
- 无音频、单音轨、多音轨和文本字幕。
- H.264 与 H.265。
- VFR、HDR、10-bit 和旋转元数据的检测与警告。

已验证输出保持分辨率和方向，帧时间戳严格递增，不覆盖原文件；兼容音频和文本字幕通过显式 FFmpeg `-map` 保留。固定位置批量复用只应用到同分辨率、同方向的任务。

## 可选 NVIDIA GPU 组件

| 检查 | 实测结果 |
| --- | --- |
| 下载清单 | 2,162,245,136 bytes；安装前要求约 4.5 GiB 可用空间 |
| 独立性 | 运行库只安装到 `engine/gpu-runtime/`，不使用系统 CUDA 或系统 PATH |
| 断点续传 | `.part` 文件触发 `Range: bytes=N-`，完成后重新核对长度和 SHA-256 |
| 严格 CUDA 自检 | 禁用 ONNX Runtime CPU 回退后返回 `CUDAExecutionProvider` |
| RTX 5070 Ti 自检 | 模型加载约 8.3 s，自检推理约 0.49 s，设备级显存观测增量约 1.2 GiB |
| 完整短片导出 | 720×1280、15 帧、AAC；修复阶段约 5.21 帧/s，结构保持一致 |
| CPU 基线 | 没有 `gpu-runtime` 时，最终便携目录使用 `CPUExecutionProvider` |

最终 WebView 中实际点击过“继续安装”。Rust 完成缓存校验、解包、真实 CUDA 自检、安装标记写入和成功缓存清理后，界面切换为“GPU 加速已启用”。

## 已知边界

- SAM 2 尚未集成；当前移动目标使用内置双向光流/仿射传播，并明确显示低置信区间。
- ProPainter 与 E2FGVI-HQ 的上游许可证限制非商业使用，因此不随发行版分发。
- 尚未在多种 NVIDIA 型号上验证 GPU 组件，也未实现按显存自动调整参考帧数量。
- HDR、10/12-bit 和复杂旋转元数据当前以阻止或警告为主，不能静默假定颜色和同步安全。
- 不兼容音频自动转码、图形字幕和多容器组合仍需扩大覆盖面。
- 已知重复图案支持平移模板匹配；尺度、旋转和透明度联合估计尚未完成。
