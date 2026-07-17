# 参与贡献

感谢参与净帧工坊。提交代码前请确认改动只用于处理用户拥有或已获授权的素材，并且没有加入平台专用规避逻辑、私人视频、模型权重或构建产物。

## 本地检查

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

提交 Pull Request 时请说明：改动目的、用户可见影响、验证方法、涉及的模型或第三方资源许可证。UI 改动请附桌面与窄窗口截图；算法改动请提供不包含私人素材的可复现测试。

## 不要提交

- `outputs/`、`work/` 和任何用户视频。
- ONNX、PyTorch 等模型权重。
- FFmpeg、Python、CUDA 或其他第三方二进制。
- API 密钥、Cookie、本机绝对路径或个人信息。
