# 上游技术与许可证研究

研究日期：2026-07-14。这里只记录从官方仓库、论文和官方网站核验的事实；社区 issue 中的显存数据会单独标注，不能当作官方保证。

固定审阅版本：ProPainter `e870e79321c31b733e2031af5aa2fb1fe3ac7eec`、E2FGVI `709cbe319edc21b8a365a28e14cba595a93d62cf`、SAM 2 `2b90b9f5ceec907a1c18123530e92e794ad901a4`、FFmpeg `597036b692b8c39198fe572aad027eeb4c13da35`。实际读取文件包括两个修复项目的推理入口与环境清单、SAM 2 的 `build_sam.py`/`sam2_video_predictor.py`、FFmpeg 的 `ffmpeg_opt.c`/`ffmpeg_mux_init.c` 以及四者许可证。

## ProPainter

- 官方代码：https://github.com/sczhou/ProPainter
- 论文：https://arxiv.org/abs/2309.03897
- 许可证：https://github.com/sczhou/ProPainter/blob/main/LICENSE
- 官方依赖基线：Python 3.8、CUDA >= 9.2、PyTorch >= 1.7.1、Torchvision >= 0.8.2。
- 官方权重：GitHub Release `ProPainter V0.1.0`；上游也支持首次推理自动下载。
- 时序方法：双域传播、光流补全和掩膜引导稀疏视频 Transformer；不是逐帧独立图像修复。
- 长视频/显存参数：`neighbor_length` 默认 10、`ref_stride` 默认 10、`subvideo_length` 默认 80、`resize_ratio`、宽高和 `fp16`。
- 代码核验：光流补全子视频使用前后 5 帧上下文，图像传播子视频使用前后 10 帧上下文；修复阶段按局部邻帧加全局参考帧推理。此处会指导净帧工坊的分段重叠，而不是逐帧独立修复。
- 官方显存表：720p、50 帧约 28GB(fp32)/19GB(fp16)，80 帧 fp32 OOM/fp16 25GB；720×480、80 帧约 13GB/8GB；320×240、80 帧约 4GB/3GB。
- 许可结论：NTU S-Lab License 1.0，代码和模型仅限非商业用途。不得放入默认可商业分发包；应用只能提供显式许可提示后的用户自助下载/外部目录接入，商业用户必须先向作者取得许可。

## E2FGVI-HQ

- 官方代码：https://github.com/MCG-NKU/E2FGVI
- 论文：https://arxiv.org/abs/2204.02663
- 许可证：https://github.com/MCG-NKU/E2FGVI/blob/master/LICENSE
- 官方依赖基线：Python >= 3.7、PyTorch >= 1.5、CUDA >= 9.2，并依赖 `mmcv-full`。
- 模型要求：E2FGVI 会固定缩放到 432×240；E2FGVI-HQ 支持任意分辨率，也可显式设置输出宽高。
- 官方性能点：432×240 在 Titan XP 上约 0.12 秒/帧。上游没有发布正式显存需求表，因此不得臆造显存门槛。
- 许可结论：CC BY-NC 4.0，仅限非商业用途，商业使用需要正式授权。处理方式与 ProPainter 相同，不进入默认便携包。

## Meta SAM 2

- 官方代码：https://github.com/facebookresearch/sam2
- 论文：https://arxiv.org/abs/2408.00714
- 官方项目页：https://ai.meta.com/research/sam2/
- 许可证：https://github.com/facebookresearch/sam2/blob/main/LICENSE
- 官方依赖基线：Python >= 3.10、PyTorch >= 2.5.1、Torchvision >= 0.20.1；官方强烈建议 Windows 使用 WSL。自定义 CUDA 扩展构建失败时可继续使用，但部分后处理能力可能受限。
- SAM 2.1 模型规模：tiny 38.9M、small 46M、base+ 80.8M、large 224.4M 参数；官方速度 91.2/84.8/64.1/39.5 FPS，测量环境为 A100、Torch 2.5.1、CUDA 12.4，不能外推成本机速度。
- 能力：支持点、框、掩膜提示，多对象视频传播，传播中添加修正提示；流式记忆适合向前/向后分段传播。
- 代码核验：`propagate_in_video(..., reverse=True)` 原生支持反向传播；`add_new_points_or_box` 与 `add_new_mask` 支持关键帧修正；视频帧和推理状态可分别 offload 到 CPU，后者以降低 FPS 为代价节省显存。
- 许可结论：代码、训练代码、演示代码和模型检查点均为 Apache-2.0，可用于商业分发，保留许可证和 NOTICE 即可。
- 显存说明：官方 README/论文未给出通用显存表。社区 issue #118 的数据不是官方保证，只能作为自动档位的初始保守参考，最终必须以本机探测和实测峰值为准。

## FFmpeg / ffprobe

- 官方源码：https://git.ffmpeg.org/ffmpeg.git
- 官方文档：https://ffmpeg.org/ffmpeg.html
- 官方下载：https://ffmpeg.org/download.html
- 官方法律说明：https://ffmpeg.org/legal.html
- 当前官方稳定版（研究日）：8.1.2；FFmpeg 官方只发布源码，Windows 可执行文件页面链接到 gyan.dev 与 BtbN 构建。
- 流映射：显式 `-map` 会关闭默认自动映射；可用 `-map 0:v:0 -map 0:a? -map 0:s? -map_metadata 0 -map_chapters 0` 保留首视频、全部音频、可选字幕、全局元数据和章节。字幕是否能进入 MP4 必须逐流检查，不能假设可复制。
- 音频策略：容器兼容时 `-c:a copy`；不兼容时提示并转 AAC。字幕策略：兼容文本字幕可转 `mov_text`，图形字幕或不兼容流必须提示并提供 MKV 或不复制选项。
- 许可结论：FFmpeg 默认 LGPL-2.1-or-later，但启用 GPL 组件后整个 FFmpeg 构建受 GPL 约束。本机 gyan.dev 8.1.1 构建含 `--enable-gpl --enable-version3 --enable-libx264 --enable-libx265`，最终便携包必须带完整许可证、构建配置和对应源码获取信息。商业分发还需独立评估 H.264/H.265 专利许可。

## 产品合规决策

1. 默认便携包不包含 ProPainter/E2FGVI-HQ 代码或权重。
2. SAM 2.1 许可证兼容，但官方 Windows 路径建议 WSL，当前构建机仅 PyTorch/CUDA 运行时就约 4.25 GiB；只下载检查点不能让桌面软件可用，因此发行版移除首次下载入口，不提供半集成功能。
3. 默认移动目标路径使用内置双向光流、前后误差校验和仿射 RANSAC 跟踪；遮挡和失配区间必须以低置信提示暴露，不能冒充 SAM 2。
4. 三种策略的高清修复均使用可重新分发的 OpenCV LaMa；快速草稿明确标注可能产生模糊色块。
5. ProPainter/E2FGVI 仅作为研究与质量对照记录，不出现在便携版的可用功能和模型清单中。
