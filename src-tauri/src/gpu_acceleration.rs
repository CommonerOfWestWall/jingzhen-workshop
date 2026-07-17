use fs2::available_space;
use futures_util::StreamExt;
use reqwest::{StatusCode, header};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::fs::{self, File, OpenOptions};
use std::io::{Read, Write};
use std::path::{Path, PathBuf};
use std::process::Command;
use std::sync::atomic::{AtomicBool, Ordering};
use std::time::Instant;
use tauri::{AppHandle, Emitter, State};
use zip::ZipArchive;

const CUDA_PROVIDER: &str = "CUDAExecutionProvider";

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct ComponentManifest {
    schema_version: u32,
    component_version: String,
    download_bytes: u64,
    required_free_bytes: u64,
    provider: String,
    cuda_license_url: String,
    cudnn_license_url: String,
    artifacts: Vec<Artifact>,
}

#[derive(Debug, Deserialize)]
struct Artifact {
    name: String,
    filename: String,
    kind: String,
    size: u64,
    sha256: String,
    url: String,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
struct InstalledInfo {
    component_version: String,
    provider: String,
    gpu_name: String,
    driver_version: String,
    model_sha256: String,
    load_ms: u64,
    inference_ms: u64,
}

#[derive(Debug)]
struct ComponentPaths {
    root: PathBuf,
    engine: PathBuf,
    manifest: PathBuf,
    launcher: PathBuf,
    runtime: PathBuf,
    cache: PathBuf,
}

#[derive(Debug)]
struct NvidiaGpu {
    name: String,
    driver_version: String,
    vram_mb: u64,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct GpuStatus {
    pub compatible: bool,
    pub installed: bool,
    pub gpu_name: Option<String>,
    pub driver_version: Option<String>,
    pub vram_mb: Option<u64>,
    pub provider: Option<String>,
    pub download_bytes: u64,
    pub downloaded_bytes: u64,
    pub required_free_bytes: u64,
    pub available_free_bytes: Option<u64>,
    pub cuda_license_url: Option<String>,
    pub cudnn_license_url: Option<String>,
    pub reason: Option<String>,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct InstallProgress {
    stage: &'static str,
    artifact: Option<String>,
    downloaded_bytes: u64,
    total_bytes: u64,
    bytes_per_second: u64,
    remaining_seconds: Option<u64>,
    message: String,
}

#[derive(Default)]
pub struct GpuInstallControl {
    paused: AtomicBool,
    running: AtomicBool,
}

#[derive(Debug)]
enum InstallError {
    Paused,
    Message(String),
}

impl From<std::io::Error> for InstallError {
    fn from(error: std::io::Error) -> Self {
        Self::Message(error.to_string())
    }
}

fn component_paths() -> Result<ComponentPaths, String> {
    let executable_root = std::env::current_exe()
        .map_err(|error| format!("无法定位程序目录：{error}"))?
        .parent()
        .map(Path::to_path_buf)
        .ok_or_else(|| "程序路径没有父目录".to_string())?;
    let portable_engine = executable_root.join("engine");
    let (root, engine, launcher) = if portable_engine
        .join("gpu-component-manifest.json")
        .is_file()
    {
        (
            executable_root,
            portable_engine.clone(),
            portable_engine.join("lama-gpu-launcher.exe"),
        )
    } else {
        let workspace = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .map(Path::to_path_buf)
            .ok_or_else(|| "无法定位开发目录".to_string())?;
        let engine = workspace.join("engine");
        (
            workspace,
            engine.clone(),
            engine.join("dist").join("lama-gpu-launcher.exe"),
        )
    };
    Ok(ComponentPaths {
        root,
        manifest: engine.join("gpu-component-manifest.json"),
        launcher,
        runtime: engine.join("gpu-runtime"),
        cache: engine.join("gpu-cache"),
        engine,
    })
}

fn read_manifest(path: &Path) -> Result<ComponentManifest, String> {
    let content = fs::read_to_string(path)
        .map_err(|error| format!("缺少 GPU 组件清单：{}（{error}）", path.display()))?;
    let manifest: ComponentManifest =
        serde_json::from_str(&content).map_err(|error| format!("GPU 组件清单格式错误：{error}"))?;
    validate_manifest(&manifest)?;
    Ok(manifest)
}

fn validate_manifest(manifest: &ComponentManifest) -> Result<(), String> {
    if manifest.schema_version != 1 || manifest.provider != CUDA_PROVIDER {
        return Err("GPU 组件清单版本或推理设备不受支持".to_string());
    }
    if manifest.artifacts.is_empty() {
        return Err("GPU 组件清单没有下载文件".to_string());
    }
    let sum = manifest
        .artifacts
        .iter()
        .try_fold(0_u64, |total, artifact| {
            if artifact.filename.contains(['/', '\\'])
                || artifact.filename.is_empty()
                || !matches!(artifact.kind.as_str(), "wheel" | "model")
                || artifact.sha256.len() != 64
                || !artifact.url.starts_with("https://")
            {
                return Err(format!("GPU 组件文件定义无效：{}", artifact.name));
            }
            total
                .checked_add(artifact.size)
                .ok_or_else(|| "GPU 组件总大小溢出".to_string())
        })?;
    if sum != manifest.download_bytes {
        return Err("GPU 组件清单总大小不一致".to_string());
    }
    Ok(())
}

fn detect_nvidia_gpu() -> Option<NvidiaGpu> {
    let mut command = Command::new("nvidia-smi");
    command.args([
        "--query-gpu=name,driver_version,memory.total",
        "--format=csv,noheader,nounits",
    ]);
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x08000000);
    }
    let output = command.output().ok()?;
    if !output.status.success() {
        return None;
    }
    let line = String::from_utf8_lossy(&output.stdout)
        .lines()
        .next()?
        .trim()
        .to_string();
    let fields = line.split(',').map(str::trim).collect::<Vec<_>>();
    if fields.len() < 3 {
        return None;
    }
    Some(NvidiaGpu {
        name: fields[0].to_string(),
        driver_version: fields[1].to_string(),
        vram_mb: fields[2].parse().ok()?,
    })
}

fn read_installed(paths: &ComponentPaths, manifest: &ComponentManifest) -> Option<InstalledInfo> {
    let marker = paths.runtime.join("installed.json");
    let info: InstalledInfo = serde_json::from_slice(&fs::read(marker).ok()?).ok()?;
    let model = paths.runtime.join("model").join("lama_fp32.onnx");
    let site = paths.runtime.join("site-packages");
    (info.component_version == manifest.component_version
        && info.provider == CUDA_PROVIDER
        && paths.launcher.is_file()
        && model.is_file()
        && site.join("onnxruntime").is_dir()
        && site.join("cv2").is_dir())
    .then_some(info)
}

fn cached_bytes(paths: &ComponentPaths, manifest: &ComponentManifest) -> u64 {
    manifest
        .artifacts
        .iter()
        .map(|artifact| {
            let complete = paths.cache.join(&artifact.filename);
            let partial = paths.cache.join(format!("{}.part", artifact.filename));
            fs::metadata(complete)
                .or_else(|_| fs::metadata(partial))
                .map(|metadata| metadata.len().min(artifact.size))
                .unwrap_or(0)
        })
        .sum()
}

pub fn status_for_current_root() -> Result<GpuStatus, String> {
    let paths = component_paths()?;
    let gpu = detect_nvidia_gpu();
    let manifest = read_manifest(&paths.manifest);
    let (download_bytes, downloaded_bytes, required_free_bytes, cuda_url, cudnn_url) =
        match manifest.as_ref() {
            Ok(manifest) => (
                manifest.download_bytes,
                cached_bytes(&paths, manifest),
                manifest.required_free_bytes,
                Some(manifest.cuda_license_url.clone()),
                Some(manifest.cudnn_license_url.clone()),
            ),
            Err(_) => (0, 0, 0, None, None),
        };
    let installed = manifest
        .as_ref()
        .ok()
        .and_then(|manifest| read_installed(&paths, manifest));
    let reason = if gpu.is_none() {
        Some("未检测到可用的 NVIDIA 驱动；CPU 模式仍可直接使用".to_string())
    } else if !paths.launcher.is_file() {
        Some("当前压缩包缺少 GPU 启动器，请重新解压完整版本".to_string())
    } else if let Err(error) = manifest.as_ref() {
        Some(error.clone())
    } else {
        None
    };
    Ok(GpuStatus {
        compatible: gpu.is_some() && paths.launcher.is_file() && manifest.is_ok(),
        installed: installed.is_some() && gpu.is_some(),
        gpu_name: gpu.as_ref().map(|item| item.name.clone()),
        driver_version: gpu.as_ref().map(|item| item.driver_version.clone()),
        vram_mb: gpu.as_ref().map(|item| item.vram_mb),
        provider: installed.map(|item| item.provider),
        download_bytes,
        downloaded_bytes,
        required_free_bytes,
        available_free_bytes: available_space(&paths.root).ok(),
        cuda_license_url: cuda_url,
        cudnn_license_url: cudnn_url,
        reason,
    })
}

pub fn active_gpu_resources() -> Option<(PathBuf, PathBuf)> {
    let paths = component_paths().ok()?;
    let manifest = read_manifest(&paths.manifest).ok()?;
    detect_nvidia_gpu()?;
    read_installed(&paths, &manifest)?;
    Some((
        paths.launcher,
        paths.runtime.join("model").join("lama_fp32.onnx"),
    ))
}

#[tauri::command]
pub fn gpu_status() -> Result<GpuStatus, String> {
    status_for_current_root()
}

#[tauri::command]
pub fn pause_gpu_install(control: State<'_, GpuInstallControl>) {
    control.paused.store(true, Ordering::SeqCst);
}

fn emit_progress(app: &AppHandle, progress: InstallProgress) {
    let _ = app.emit("gpu-install-progress", progress);
}

fn verify_file(path: &Path, expected_size: u64, expected_sha256: &str) -> Result<(), String> {
    let metadata = fs::metadata(path)
        .map_err(|error| format!("无法读取下载文件 {}：{error}", path.display()))?;
    if metadata.len() != expected_size {
        return Err(format!(
            "文件大小校验失败：期望 {expected_size}，实际 {}",
            metadata.len()
        ));
    }
    let mut file = File::open(path).map_err(|error| error.to_string())?;
    let mut hasher = Sha256::new();
    let mut buffer = vec![0_u8; 1024 * 1024];
    loop {
        let count = file.read(&mut buffer).map_err(|error| error.to_string())?;
        if count == 0 {
            break;
        }
        hasher.update(&buffer[..count]);
    }
    let actual = format!("{:x}", hasher.finalize());
    if !actual.eq_ignore_ascii_case(expected_sha256) {
        return Err(format!("SHA-256 校验失败：{actual}"));
    }
    Ok(())
}

async fn download_artifact(
    client: &reqwest::Client,
    app: Option<&AppHandle>,
    control: &GpuInstallControl,
    paths: &ComponentPaths,
    manifest: &ComponentManifest,
    artifact: &Artifact,
    completed_before: u64,
) -> Result<PathBuf, InstallError> {
    fs::create_dir_all(&paths.cache)?;
    let complete = paths.cache.join(&artifact.filename);
    if verify_file(&complete, artifact.size, &artifact.sha256).is_ok() {
        return Ok(complete);
    }
    if complete.exists() {
        fs::remove_file(&complete)?;
    }
    let partial = paths.cache.join(format!("{}.part", artifact.filename));
    let mut offset = fs::metadata(&partial).map(|item| item.len()).unwrap_or(0);
    if offset > artifact.size {
        fs::remove_file(&partial)?;
        offset = 0;
    }
    if offset == artifact.size {
        if verify_file(&partial, artifact.size, &artifact.sha256).is_ok() {
            fs::rename(&partial, &complete)?;
            return Ok(complete);
        }
        fs::remove_file(&partial)?;
        offset = 0;
    }
    let mut request = client.get(&artifact.url);
    if offset > 0 {
        request = request.header(header::RANGE, format!("bytes={offset}-"));
    }
    let response = request
        .send()
        .await
        .map_err(|error| InstallError::Message(format!("下载失败：{error}")))?;
    let append = offset > 0 && response.status() == StatusCode::PARTIAL_CONTENT;
    if !response.status().is_success() {
        return Err(InstallError::Message(format!(
            "下载服务器返回 {}：{}",
            response.status(),
            artifact.name
        )));
    }
    if offset > 0 && !append {
        offset = 0;
    }
    let mut file = OpenOptions::new()
        .create(true)
        .write(true)
        .append(append)
        .truncate(!append)
        .open(&partial)?;
    let started = Instant::now();
    let starting_offset = offset;
    let mut stream = response.bytes_stream();
    while let Some(chunk) = stream.next().await {
        if control.paused.load(Ordering::SeqCst) {
            file.flush()?;
            return Err(InstallError::Paused);
        }
        let chunk =
            chunk.map_err(|error| InstallError::Message(format!("下载连接中断：{error}")))?;
        file.write_all(&chunk)?;
        offset += chunk.len() as u64;
        if offset > artifact.size {
            return Err(InstallError::Message(format!(
                "下载内容超出清单大小：{}",
                artifact.name
            )));
        }
        let elapsed = started.elapsed().as_secs_f64().max(0.1);
        let speed = ((offset - starting_offset) as f64 / elapsed) as u64;
        let overall = completed_before + offset;
        let remaining = (speed > 0).then(|| (manifest.download_bytes - overall) / speed);
        if let Some(app) = app {
            emit_progress(
                app,
                InstallProgress {
                    stage: "downloading",
                    artifact: Some(artifact.name.clone()),
                    downloaded_bytes: overall,
                    total_bytes: manifest.download_bytes,
                    bytes_per_second: speed,
                    remaining_seconds: remaining,
                    message: format!("正在下载 {}", artifact.name),
                },
            );
        }
    }
    file.flush()?;
    drop(file);
    if let Some(app) = app {
        emit_progress(
            app,
            InstallProgress {
                stage: "verifying",
                artifact: Some(artifact.name.clone()),
                downloaded_bytes: completed_before + offset,
                total_bytes: manifest.download_bytes,
                bytes_per_second: 0,
                remaining_seconds: None,
                message: format!("正在校验 {}", artifact.name),
            },
        );
    }
    verify_file(&partial, artifact.size, &artifact.sha256)
        .map_err(|error| InstallError::Message(format!("{}：{error}", artifact.name)))?;
    fs::rename(&partial, &complete)?;
    Ok(complete)
}

fn extract_wheel(wheel: &Path, destination: &Path) -> Result<(), String> {
    let file = File::open(wheel).map_err(|error| format!("无法打开组件包：{error}"))?;
    let mut archive = ZipArchive::new(file).map_err(|error| format!("组件包格式错误：{error}"))?;
    for index in 0..archive.len() {
        let mut entry = archive
            .by_index(index)
            .map_err(|error| format!("无法读取组件包：{error}"))?;
        let relative = entry
            .enclosed_name()
            .ok_or_else(|| "组件包包含不安全路径".to_string())?;
        let output = destination.join(relative);
        if entry.is_dir() {
            fs::create_dir_all(&output).map_err(|error| error.to_string())?;
            continue;
        }
        if let Some(parent) = output.parent() {
            fs::create_dir_all(parent).map_err(|error| error.to_string())?;
        }
        let mut target = File::create(&output).map_err(|error| error.to_string())?;
        std::io::copy(&mut entry, &mut target).map_err(|error| error.to_string())?;
    }
    Ok(())
}

fn run_gpu_check(
    paths: &ComponentPaths,
    manifest: &ComponentManifest,
) -> Result<InstalledInfo, String> {
    let model_artifact = manifest
        .artifacts
        .iter()
        .find(|artifact| artifact.kind == "model")
        .ok_or_else(|| "GPU 清单缺少浮点模型".to_string())?;
    let model = paths.runtime.join("model").join("lama_fp32.onnx");
    let mut command = Command::new(&paths.launcher);
    command.args([
        "--model",
        &model.display().to_string(),
        "--check",
        "--require-provider",
        CUDA_PROVIDER,
    ]);
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x08000000);
    }
    let output = command
        .output()
        .map_err(|error| format!("无法启动 GPU 自检：{error}"))?;
    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr).trim().to_string();
        return Err(if stderr.is_empty() {
            "GPU 自检未通过，已继续使用 CPU".to_string()
        } else {
            format!("GPU 自检未通过：{stderr}")
        });
    }
    #[derive(Deserialize)]
    #[serde(rename_all = "camelCase")]
    struct CheckResult {
        ready: bool,
        provider: String,
        load_ms: u64,
        inference_ms: u64,
    }
    let result: CheckResult = serde_json::from_slice(&output.stdout)
        .map_err(|error| format!("GPU 自检结果无法读取：{error}"))?;
    if !result.ready || result.provider != CUDA_PROVIDER {
        return Err(format!("GPU 自检实际使用了 {}", result.provider));
    }
    let gpu = detect_nvidia_gpu().ok_or_else(|| "GPU 自检后驱动不可用".to_string())?;
    Ok(InstalledInfo {
        component_version: manifest.component_version.clone(),
        provider: result.provider,
        gpu_name: gpu.name,
        driver_version: gpu.driver_version,
        model_sha256: model_artifact.sha256.clone(),
        load_ms: result.load_ms,
        inference_ms: result.inference_ms,
    })
}

async fn perform_install(app: &AppHandle, control: &GpuInstallControl) -> Result<(), InstallError> {
    let paths = component_paths().map_err(InstallError::Message)?;
    let manifest = read_manifest(&paths.manifest).map_err(InstallError::Message)?;
    if !paths.launcher.is_file() {
        return Err(InstallError::Message(
            "当前压缩包缺少 GPU 启动器".to_string(),
        ));
    }
    let gpu = detect_nvidia_gpu()
        .ok_or_else(|| InstallError::Message("未检测到可用的 NVIDIA 驱动".to_string()))?;
    let free = available_space(&paths.root)
        .map_err(|error| InstallError::Message(format!("无法检查磁盘空间：{error}")))?;
    if free < manifest.required_free_bytes {
        return Err(InstallError::Message(format!(
            "磁盘空间不足：至少需要 {:.1} GB，目前可用 {:.1} GB",
            manifest.required_free_bytes as f64 / 1_000_000_000.0,
            free as f64 / 1_000_000_000.0
        )));
    }
    emit_progress(
        app,
        InstallProgress {
            stage: "checking",
            artifact: None,
            downloaded_bytes: cached_bytes(&paths, &manifest),
            total_bytes: manifest.download_bytes,
            bytes_per_second: 0,
            remaining_seconds: None,
            message: format!("已检测到 {}，准备下载", gpu.name),
        },
    );
    let client = reqwest::Client::builder()
        .user_agent("JingzhenWorkshop/0.1 GPU Component Installer")
        .build()
        .map_err(|error| InstallError::Message(format!("无法创建下载连接：{error}")))?;
    let mut completed = 0_u64;
    let mut files = Vec::with_capacity(manifest.artifacts.len());
    for artifact in &manifest.artifacts {
        let file = download_artifact(
            &client,
            Some(app),
            control,
            &paths,
            &manifest,
            artifact,
            completed,
        )
        .await?;
        completed += artifact.size;
        files.push(file);
    }
    let staging = paths.engine.join("gpu-runtime.staging");
    if staging.exists() {
        fs::remove_dir_all(&staging)?;
    }
    let site = staging.join("site-packages");
    fs::create_dir_all(&site)?;
    fs::create_dir_all(staging.join("model"))?;
    for (artifact, file) in manifest.artifacts.iter().zip(&files) {
        if control.paused.load(Ordering::SeqCst) {
            return Err(InstallError::Paused);
        }
        emit_progress(
            app,
            InstallProgress {
                stage: "installing",
                artifact: Some(artifact.name.clone()),
                downloaded_bytes: manifest.download_bytes,
                total_bytes: manifest.download_bytes,
                bytes_per_second: 0,
                remaining_seconds: None,
                message: format!("正在安装 {}", artifact.name),
            },
        );
        if artifact.kind == "wheel" {
            extract_wheel(file, &site).map_err(InstallError::Message)?;
        } else {
            fs::copy(file, staging.join("model").join("lama_fp32.onnx"))?;
        }
    }
    if paths.runtime.exists() {
        fs::remove_dir_all(&paths.runtime)?;
    }
    fs::rename(&staging, &paths.runtime)?;
    emit_progress(
        app,
        InstallProgress {
            stage: "testing",
            artifact: None,
            downloaded_bytes: manifest.download_bytes,
            total_bytes: manifest.download_bytes,
            bytes_per_second: 0,
            remaining_seconds: None,
            message: "正在用真实 LaMa 模型验证 GPU".to_string(),
        },
    );
    let installed = run_gpu_check(&paths, &manifest).map_err(InstallError::Message)?;
    fs::write(
        paths.runtime.join("installed.json"),
        serde_json::to_vec_pretty(&installed)
            .map_err(|error| InstallError::Message(error.to_string()))?,
    )?;
    for file in files {
        let _ = fs::remove_file(file);
    }
    emit_progress(
        app,
        InstallProgress {
            stage: "ready",
            artifact: None,
            downloaded_bytes: manifest.download_bytes,
            total_bytes: manifest.download_bytes,
            bytes_per_second: 0,
            remaining_seconds: None,
            message: format!("{} GPU 加速已启用", installed.gpu_name),
        },
    );
    Ok(())
}

#[tauri::command]
pub async fn install_gpu_component(
    app: AppHandle,
    control: State<'_, GpuInstallControl>,
) -> Result<GpuStatus, String> {
    if control
        .running
        .compare_exchange(false, true, Ordering::SeqCst, Ordering::SeqCst)
        .is_err()
    {
        return Err("GPU 加速组件正在安装".to_string());
    }
    control.paused.store(false, Ordering::SeqCst);
    let result = perform_install(&app, &control).await;
    control.running.store(false, Ordering::SeqCst);
    match result {
        Ok(()) => status_for_current_root(),
        Err(InstallError::Paused) => {
            emit_progress(
                &app,
                InstallProgress {
                    stage: "paused",
                    artifact: None,
                    downloaded_bytes: status_for_current_root()
                        .map(|status| status.downloaded_bytes)
                        .unwrap_or(0),
                    total_bytes: status_for_current_root()
                        .map(|status| status.download_bytes)
                        .unwrap_or(0),
                    bytes_per_second: 0,
                    remaining_seconds: None,
                    message: "下载已暂停，已保留当前进度".to_string(),
                },
            );
            status_for_current_root()
        }
        Err(InstallError::Message(error)) => {
            emit_progress(
                &app,
                InstallProgress {
                    stage: "failed",
                    artifact: None,
                    downloaded_bytes: 0,
                    total_bytes: 0,
                    bytes_per_second: 0,
                    remaining_seconds: None,
                    message: error.clone(),
                },
            );
            Err(error)
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::net::TcpListener;
    use std::thread;
    use tempfile::tempdir;
    use zip::write::SimpleFileOptions;

    fn manifest_with(artifacts: Vec<Artifact>, total: u64) -> ComponentManifest {
        ComponentManifest {
            schema_version: 1,
            component_version: "test".to_string(),
            download_bytes: total,
            required_free_bytes: 1,
            provider: CUDA_PROVIDER.to_string(),
            cuda_license_url: "https://example.com/cuda".to_string(),
            cudnn_license_url: "https://example.com/cudnn".to_string(),
            artifacts,
        }
    }

    #[test]
    fn shipped_manifest_is_self_consistent() {
        let path = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .unwrap()
            .join("engine")
            .join("gpu-component-manifest.json");
        let manifest = read_manifest(&path).unwrap();
        assert_eq!(manifest.download_bytes, 2_162_245_136);
        assert_eq!(manifest.provider, CUDA_PROVIDER);
    }

    #[test]
    fn manifest_rejects_size_mismatch_and_unsafe_filename() {
        let artifact = Artifact {
            name: "bad".to_string(),
            filename: "../bad.whl".to_string(),
            kind: "wheel".to_string(),
            size: 10,
            sha256: "a".repeat(64),
            url: "https://example.com/bad.whl".to_string(),
        };
        assert!(validate_manifest(&manifest_with(vec![artifact], 11)).is_err());
    }

    #[test]
    fn sha256_verification_rejects_modified_file() {
        let directory = tempdir().unwrap();
        let path = directory.path().join("payload");
        fs::write(&path, b"hello").unwrap();
        assert!(verify_file(&path, 5, &"0".repeat(64)).is_err());
        assert!(
            verify_file(
                &path,
                5,
                "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
            )
            .is_ok()
        );
    }

    #[test]
    fn wheel_extraction_rejects_path_traversal() {
        let directory = tempdir().unwrap();
        let wheel = directory.path().join("bad.whl");
        let file = File::create(&wheel).unwrap();
        let mut writer = zip::ZipWriter::new(file);
        writer
            .start_file("../outside.dll", SimpleFileOptions::default())
            .unwrap();
        writer.write_all(b"bad").unwrap();
        writer.finish().unwrap();
        assert!(extract_wheel(&wheel, &directory.path().join("site")).is_err());
        assert!(!directory.path().join("outside.dll").exists());
    }

    #[test]
    fn download_resumes_from_existing_partial_file() {
        let payload = (0..256 * 1024)
            .map(|index| (index % 251) as u8)
            .collect::<Vec<_>>();
        let resume_at = 37_019_usize;
        let sha256 = format!("{:x}", Sha256::digest(&payload));
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let address = listener.local_addr().unwrap();
        let server_payload = payload.clone();
        let server = thread::spawn(move || {
            let (mut stream, _) = listener.accept().unwrap();
            let mut request = Vec::new();
            let mut buffer = [0_u8; 1024];
            while !request.windows(4).any(|window| window == b"\r\n\r\n") {
                let count = stream.read(&mut buffer).unwrap();
                assert!(count > 0, "HTTP request ended before its headers");
                request.extend_from_slice(&buffer[..count]);
            }
            let headers = String::from_utf8_lossy(&request).to_ascii_lowercase();
            assert!(headers.contains(&format!("range: bytes={resume_at}-")));
            let body = &server_payload[resume_at..];
            write!(
                stream,
                "HTTP/1.1 206 Partial Content\r\nContent-Length: {}\r\nContent-Range: bytes {}-{}/{}\r\nConnection: close\r\n\r\n",
                body.len(),
                resume_at,
                server_payload.len() - 1,
                server_payload.len()
            )
            .unwrap();
            stream.write_all(body).unwrap();
        });

        let directory = tempdir().unwrap();
        let engine = directory.path().join("engine");
        let cache = engine.join("gpu-cache");
        fs::create_dir_all(&cache).unwrap();
        fs::write(cache.join("payload.whl.part"), &payload[..resume_at]).unwrap();
        let paths = ComponentPaths {
            root: directory.path().to_path_buf(),
            engine: engine.clone(),
            manifest: engine.join("gpu-component-manifest.json"),
            launcher: engine.join("lama-gpu-launcher.exe"),
            runtime: engine.join("gpu-runtime"),
            cache,
        };
        let manifest = manifest_with(
            vec![Artifact {
                name: "test payload".to_string(),
                filename: "payload.whl".to_string(),
                kind: "wheel".to_string(),
                size: payload.len() as u64,
                sha256,
                url: format!("http://{address}/payload.whl"),
            }],
            payload.len() as u64,
        );
        let client = reqwest::Client::builder().build().unwrap();
        let output = tauri::async_runtime::block_on(download_artifact(
            &client,
            None,
            &GpuInstallControl::default(),
            &paths,
            &manifest,
            &manifest.artifacts[0],
            0,
        ))
        .unwrap();
        server.join().unwrap();
        assert_eq!(fs::read(output).unwrap(), payload);
        assert!(!paths.cache.join("payload.whl.part").exists());
    }

    #[test]
    fn installed_marker_requires_complete_runtime_layout() {
        let directory = tempdir().unwrap();
        let engine = directory.path().join("engine");
        let runtime = engine.join("gpu-runtime");
        let paths = ComponentPaths {
            root: directory.path().to_path_buf(),
            engine: engine.clone(),
            manifest: engine.join("gpu-component-manifest.json"),
            launcher: engine.join("lama-gpu-launcher.exe"),
            runtime: runtime.clone(),
            cache: engine.join("gpu-cache"),
        };
        fs::create_dir_all(runtime.join("model")).unwrap();
        fs::create_dir_all(runtime.join("site-packages").join("onnxruntime")).unwrap();
        fs::create_dir_all(runtime.join("site-packages").join("cv2")).unwrap();
        fs::write(&paths.launcher, b"launcher").unwrap();
        fs::write(runtime.join("model").join("lama_fp32.onnx"), b"model").unwrap();
        let info = InstalledInfo {
            component_version: "test".to_string(),
            provider: CUDA_PROVIDER.to_string(),
            gpu_name: "Test GPU".to_string(),
            driver_version: "1.0".to_string(),
            model_sha256: "a".repeat(64),
            load_ms: 10,
            inference_ms: 20,
        };
        fs::write(
            runtime.join("installed.json"),
            serde_json::to_vec(&info).unwrap(),
        )
        .unwrap();
        let manifest = manifest_with(Vec::new(), 0);
        assert!(read_installed(&paths, &manifest).is_some());
        fs::remove_dir_all(runtime.join("site-packages").join("cv2")).unwrap();
        assert!(read_installed(&paths, &manifest).is_none());
    }
}
