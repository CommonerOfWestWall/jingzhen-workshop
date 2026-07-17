use crate::jobs::engine_command;
use crate::resources::PortablePaths;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::fs;
use std::path::PathBuf;
use std::time::{SystemTime, UNIX_EPOCH};
use tauri::Manager;

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct PreviewRequest {
    input: String,
    project: Value,
    current_frame: u64,
    frame_count: u64,
    fps: f64,
    #[serde(default = "default_repair_mode")]
    repair_mode: String,
}

fn default_repair_mode() -> String {
    "quality".to_string()
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct PreviewResult {
    output: String,
    start_frame: u64,
    end_frame: u64,
}

fn preview_root() -> PathBuf {
    std::env::temp_dir().join("jingzhen-workshop-preview")
}

pub fn cleanup_preview_root() {
    let root = preview_root();
    if root.starts_with(std::env::temp_dir()) {
        let _ = fs::remove_dir_all(root);
    }
}

#[tauri::command]
pub async fn create_preview(
    app: tauri::AppHandle,
    request: PreviewRequest,
) -> Result<PreviewResult, String> {
    if request.frame_count == 0 || request.fps <= 0.0 {
        return Err("视频帧信息无效".to_string());
    }
    if !matches!(request.repair_mode.as_str(), "quality" | "fast") {
        return Err("不支持的修复质量".to_string());
    }
    cleanup_preview_root();
    let timestamp = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis();
    let work_dir = preview_root().join(timestamp.to_string());
    fs::create_dir_all(&work_dir).map_err(|error| format!("无法创建预览目录：{error}"))?;
    let project_path = work_dir.join("project.jzf.json");
    fs::write(
        &project_path,
        serde_json::to_vec_pretty(&request.project)
            .map_err(|error| format!("预览项目序列化失败：{error}"))?,
    )
    .map_err(|error| format!("无法写入预览项目：{error}"))?;
    let radius = (request.fps * 1.5).round() as u64;
    let start = request.current_frame.saturating_sub(radius);
    let end = request
        .current_frame
        .saturating_add(radius)
        .min(request.frame_count - 1);
    let output = work_dir.join("preview.mp4");
    let resources = PortablePaths::discover()?;
    if request.repair_mode == "quality"
        && (resources.lama_engine.is_none() || resources.lama_model.is_none())
    {
        return Err("缺少 LaMa 高清修复资源，请重新解压完整免安装版".to_string());
    }
    let mut command = engine_command(&resources)?;
    let command_output = tauri::async_runtime::spawn_blocking(move || {
        command
            .arg("preview-video")
            .arg("--input")
            .arg(&request.input)
            .arg("--project")
            .arg(&project_path)
            .arg("--output")
            .arg(&output)
            .arg("--start-frame")
            .arg(start.to_string())
            .arg("--end-frame")
            .arg(end.to_string())
            .arg("--ffmpeg")
            .arg(&resources.ffmpeg)
            .arg("--ffprobe")
            .arg(&resources.ffprobe)
            .arg("--repair-mode")
            .arg(&request.repair_mode)
            .args(
                resources
                    .lama_engine
                    .as_ref()
                    .map(|path| vec!["--lama-engine".into(), path.as_os_str().to_owned()])
                    .unwrap_or_default(),
            )
            .args(
                resources
                    .lama_model
                    .as_ref()
                    .map(|path| vec!["--lama-model".into(), path.as_os_str().to_owned()])
                    .unwrap_or_default(),
            )
            .output()
            .map(|result| (result, output))
    })
    .await
    .map_err(|error| format!("预览任务异常：{error}"))?
    .map_err(|error| format!("无法启动预览引擎：{error}"))?;
    if !command_output.0.status.success() {
        let error = String::from_utf8_lossy(&command_output.0.stderr)
            .trim()
            .to_string();
        cleanup_preview_root();
        return Err(if error.is_empty() {
            String::from_utf8_lossy(&command_output.0.stdout)
                .trim()
                .to_string()
        } else {
            error
        });
    }
    app.asset_protocol_scope()
        .allow_file(&command_output.1)
        .map_err(|error| format!("无法授权修复预览文件：{error}"))?;
    Ok(PreviewResult {
        output: command_output.1.display().to_string(),
        start_frame: start,
        end_frame: end,
    })
}
