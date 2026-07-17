use serde::Serialize;
use std::path::{Path, PathBuf};

#[derive(Debug, Clone)]
pub struct PortablePaths {
    pub root: PathBuf,
    pub ffmpeg: PathBuf,
    pub ffprobe: PathBuf,
    pub engine: Option<PathBuf>,
    pub lama_engine: Option<PathBuf>,
    pub lama_model: Option<PathBuf>,
    pub development_python: Option<PathBuf>,
    pub development_engine_root: Option<PathBuf>,
    pub models: PathBuf,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ResourceStatus {
    root: String,
    ffmpeg: bool,
    ffprobe: bool,
    engine: bool,
    quality_engine: bool,
    models_directory: bool,
    execution_mode: &'static str,
    gpu_acceleration: bool,
    gpu_name: Option<String>,
}

fn executable_root() -> Result<PathBuf, String> {
    std::env::current_exe()
        .map_err(|error| format!("无法定位程序目录：{error}"))?
        .parent()
        .map(Path::to_path_buf)
        .ok_or_else(|| "程序路径没有父目录".to_string())
}

impl PortablePaths {
    pub fn discover() -> Result<Self, String> {
        let root = executable_root()?;
        let portable_ffmpeg = root.join("ffmpeg").join("ffmpeg.exe");
        let portable_ffprobe = root.join("ffmpeg").join("ffprobe.exe");
        let portable_engine = root.join("engine").join("jingzhen-engine.exe");
        let portable_lama_engine = root.join("engine").join("lama-frame-engine.exe");

        let manifest_root = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
        let workspace_root = manifest_root
            .parent()
            .map(Path::to_path_buf)
            .unwrap_or(manifest_root);
        let development_python = workspace_root
            .join("engine")
            .join(".venv")
            .join("Scripts")
            .join("python.exe");
        let development_engine_root = workspace_root.join("engine");
        let development_lama_engine = development_engine_root
            .join("dist")
            .join("lama-frame-engine.exe");

        let portable_mode = portable_engine.is_file();
        let models = if portable_mode {
            root.join("models")
        } else {
            workspace_root.join("models")
        };
        let cpu_lama_engine = if portable_mode {
            portable_lama_engine
                .is_file()
                .then_some(portable_lama_engine)
        } else {
            development_lama_engine
                .is_file()
                .then_some(development_lama_engine)
        };
        let lama_model_path = models.join("inpainting_lama_2025jan.onnx");
        let cpu_lama_model = lama_model_path.is_file().then_some(lama_model_path);
        let (lama_engine, lama_model) = crate::gpu_acceleration::active_gpu_resources()
            .map(|(engine, model)| (Some(engine), Some(model)))
            .unwrap_or((cpu_lama_engine, cpu_lama_model));
        Ok(Self {
            ffmpeg: if portable_ffmpeg.is_file() {
                portable_ffmpeg
            } else {
                PathBuf::from("ffmpeg")
            },
            ffprobe: if portable_ffprobe.is_file() {
                portable_ffprobe
            } else {
                PathBuf::from("ffprobe")
            },
            engine: portable_engine.is_file().then_some(portable_engine),
            lama_engine,
            lama_model,
            development_python: development_python.is_file().then_some(development_python),
            development_engine_root: development_engine_root
                .is_dir()
                .then_some(development_engine_root),
            models,
            root,
        })
    }
}

#[tauri::command]
pub fn resource_status() -> Result<ResourceStatus, String> {
    let paths = PortablePaths::discover()?;
    let gpu = crate::gpu_acceleration::status_for_current_root().ok();
    Ok(ResourceStatus {
        root: paths.root.display().to_string(),
        ffmpeg: paths.ffmpeg.is_file() || paths.ffmpeg == PathBuf::from("ffmpeg"),
        ffprobe: paths.ffprobe.is_file() || paths.ffprobe == PathBuf::from("ffprobe"),
        engine: paths.engine.is_some() || paths.development_python.is_some(),
        quality_engine: paths.lama_engine.is_some() && paths.lama_model.is_some(),
        models_directory: paths.models.is_dir(),
        execution_mode: if paths.engine.is_some() {
            "portable"
        } else {
            "development"
        },
        gpu_acceleration: gpu.as_ref().is_some_and(|status| status.installed),
        gpu_name: gpu.and_then(|status| status.gpu_name),
    })
}
