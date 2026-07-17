# 模型许可证说明

## OpenCV LaMa Inpainting

固定区域、移动目标和透明度变化的“高清修复”模式使用 OpenCV 发布的 `inpainting_lama_2025jan.onnx`。OpenCV 模型页明确声明该目录文件采用 Apache License 2.0，允许重新分发和商业使用，因此模型与许可证全文随免安装版提供。

- 官方模型页：https://huggingface.co/opencv/inpainting_lama
- 官方模型文件：https://huggingface.co/opencv/inpainting_lama/blob/main/inpainting_lama_2025jan.onnx
- SHA-256：`7df918ac3921d3daf0aae1d219776cf0dc4e4935f035af81841b40adcf74fdf2`
- 许可证全文：`OpenCV-LaMa-Apache-2.0.txt`

## SAM 2 / SAM 2.1

代码、演示、训练代码和官方模型检查点由 Meta 以 Apache License 2.0 发布。当前便携包不包含其代码、PyTorch/CUDA 运行时或权重，也不提供只有检查点、无法实际推理的下载入口；移动目标使用内置跟踪器，软件不会把该结果标为 SAM 2。

- 官方仓库：https://github.com/facebookresearch/sam2
- 官方许可证：https://github.com/facebookresearch/sam2/blob/main/LICENSE

## ProPainter

代码和模型受 NTU S-Lab License 1.0 约束，仅限非商业用途。净帧工坊不分发其代码或权重，也不默认自动下载。外部接入仅适用于符合上游许可证的用户；商业使用必须先取得作者正式许可。

- 官方仓库：https://github.com/sczhou/ProPainter
- 官方许可证：https://github.com/sczhou/ProPainter/blob/main/LICENSE

## E2FGVI-HQ

代码和模型受 CC BY-NC 4.0 约束，仅限非商业用途。净帧工坊不分发其代码或权重，也不默认自动下载。商业使用必须先取得作者正式许可。

- 官方仓库：https://github.com/MCG-NKU/E2FGVI
- 官方许可证：https://github.com/MCG-NKU/E2FGVI/blob/master/LICENSE
