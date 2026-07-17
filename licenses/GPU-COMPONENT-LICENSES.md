# NVIDIA GPU 可选组件许可说明

GPU 加速组件不随基础压缩包分发。用户点击“安装 NVIDIA GPU 加速”后，软件从清单中固定的官方地址下载并校验以下内容：

- ONNX Runtime GPU：MIT License，Microsoft 官方 PyPI 包。
- LaMa FP32 ONNX 模型：Apache-2.0，Carve/LaMa-ONNX。
- NumPy、OpenCV、FlatBuffers、Packaging、Protobuf：各项目的开源许可，以下载包内的元数据和许可文件为准。
- NVIDIA CUDA、cuBLAS、cuFFT、cuRAND、nvJitLink 与 cuDNN 运行库：NVIDIA 专有软件许可。

点击安装表示用户同意当时随下载内容适用的 NVIDIA 许可。官方条款：

- CUDA：https://docs.nvidia.com/cuda/eula/index.html
- cuDNN：https://docs.nvidia.com/deeplearning/cudnn/backend/latest/reference/eula.html

组件仅解压到 `engine/gpu-runtime/` 私有目录，不写入系统 CUDA 目录，也不改变系统 `PATH`。
