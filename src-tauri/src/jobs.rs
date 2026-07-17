use crate::naming::unique_output_path;
use crate::resources::PortablePaths;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::HashMap;
use std::fs;
use std::io::{BufRead, BufReader};
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::sync::Mutex;
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::{SystemTime, UNIX_EPOCH};
use tauri::{Emitter, Manager};

static JOB_COUNTER: AtomicU64 = AtomicU64::new(1);

#[derive(Default)]
pub struct JobRegistry(Mutex<HashMap<String, PathBuf>>);

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ExportRequest {
    input: String,
    output_dir: Option<String>,
    project: Value,
    codec: String,
    crf: u8,
    #[serde(default)]
    allow_unsafe: bool,
    target_fps: Option<f64>,
    #[serde(default = "default_interpolation")]
    interpolation: String,
    #[serde(default = "default_repair_mode")]
    repair_mode: String,
}

fn default_interpolation() -> String {
    "fast".to_string()
}

fn default_repair_mode() -> String {
    "quality".to_string()
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct StartExportResult {
    job_id: String,
    output: String,
}

#[derive(Debug, Serialize, Clone)]
#[serde(rename_all = "camelCase")]
struct JobEvent {
    job_id: String,
    status: String,
    output: String,
    detail: Option<Value>,
    error: Option<String>,
}

fn structured_engine_error(detail: &Value) -> Option<String> {
    (detail.get("ok").and_then(Value::as_bool) == Some(false))
        .then(|| {
            detail
                .get("error")
                .and_then(Value::as_str)
                .unwrap_or_default()
                .trim()
        })
        .filter(|message| !message.is_empty())
        .map(str::to_string)
}

fn job_id() -> String {
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis();
    let sequence = JOB_COUNTER.fetch_add(1, Ordering::Relaxed);
    format!("{now}-{sequence}")
}

pub(crate) fn engine_command(resources: &PortablePaths) -> Result<Command, String> {
    let mut command = if let Some(engine) = &resources.engine {
        Command::new(engine)
    } else {
        let python = resources
            .development_python
            .as_ref()
            .ok_or_else(|| "未找到便携引擎或开发 Python".to_string())?;
        let mut development = Command::new(python);
        development.args(["-m", "jingzhen_engine.cli"]);
        if let Some(engine_root) = &resources.development_engine_root {
            development.env("PYTHONPATH", engine_root);
        }
        development
    };
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x0800_0000);
    }
    Ok(command)
}

#[tauri::command]
pub fn start_export(
    app: tauri::AppHandle,
    registry: tauri::State<'_, JobRegistry>,
    request: ExportRequest,
) -> Result<StartExportResult, String> {
    if !matches!(request.codec.as_str(), "h264" | "h265") {
        return Err("不支持的编码器".to_string());
    }
    if !(0..=51).contains(&request.crf) {
        return Err("质量值必须在 0–51 之间".to_string());
    }
    if request
        .target_fps
        .is_some_and(|fps| !fps.is_finite() || !(1.0..=120.0).contains(&fps))
    {
        return Err("输出帧率必须在 1–120 fps 之间".to_string());
    }
    if !matches!(request.interpolation.as_str(), "fast" | "motion") {
        return Err("不支持的补帧方式".to_string());
    }
    if !matches!(request.repair_mode.as_str(), "quality" | "fast") {
        return Err("不支持的修复质量".to_string());
    }
    let input = PathBuf::from(&request.input);
    let output_dir = request.output_dir.as_deref().map(Path::new);
    let output = unique_output_path(&input, output_dir)?;
    let id = job_id();
    let work_dir = std::env::temp_dir().join("jingzhen-workshop").join(&id);
    fs::create_dir_all(&work_dir).map_err(|error| format!("无法创建任务目录：{error}"))?;
    let project_path = work_dir.join("project.jzf.json");
    fs::write(
        &project_path,
        serde_json::to_vec_pretty(&request.project)
            .map_err(|error| format!("项目序列化失败：{error}"))?,
    )
    .map_err(|error| format!("无法写入任务项目：{error}"))?;
    let cancel_file = work_dir.join("cancel.requested");
    registry
        .0
        .lock()
        .map_err(|_| "任务表已损坏".to_string())?
        .insert(id.clone(), cancel_file.clone());

    let id_for_thread = id.clone();
    let output_for_thread = output.clone();
    std::thread::spawn(move || {
        let result =
            (|| -> Result<(), String> {
                let resources = PortablePaths::discover()?;
                let mut command = engine_command(&resources)?;
                command
                    .arg("repair-video")
                    .arg("--input")
                    .arg(&input)
                    .arg("--project")
                    .arg(&project_path)
                    .arg("--output")
                    .arg(&output_for_thread)
                    .arg("--ffmpeg")
                    .arg(&resources.ffmpeg)
                    .arg("--ffprobe")
                    .arg(&resources.ffprobe)
                    .arg("--codec")
                    .arg(&request.codec)
                    .arg("--crf")
                    .arg(request.crf.to_string())
                    .args(request.allow_unsafe.then_some("--allow-unsafe"))
                    .args(
                        request
                            .target_fps
                            .map(|fps| vec!["--target-fps".to_string(), fps.to_string()])
                            .unwrap_or_default(),
                    )
                    .arg("--interpolation")
                    .arg(&request.interpolation)
                    .arg("--repair-mode")
                    .arg(&request.repair_mode)
                    .arg("--cancel-file")
                    .arg(&cancel_file)
                    .stdout(Stdio::piped())
                    .stderr(Stdio::piped());
                if request.repair_mode == "quality" {
                    let lama_engine = resources.lama_engine.as_ref().ok_or_else(|| {
                        "缺少 LaMa 高清修复引擎，请重新解压完整免安装版".to_string()
                    })?;
                    let lama_model = resources.lama_model.as_ref().ok_or_else(|| {
                        "缺少 LaMa 高清修复模型，请重新解压完整免安装版".to_string()
                    })?;
                    command
                        .arg("--lama-engine")
                        .arg(lama_engine)
                        .arg("--lama-model")
                        .arg(lama_model);
                }
                let mut child = command
                    .spawn()
                    .map_err(|error| format!("无法启动修复引擎：{error}"))?;
                let mut reported_error = None;
                if let Some(stdout) = child.stdout.take() {
                    for line in BufReader::new(stdout).lines().map_while(Result::ok) {
                        if let Ok(detail) = serde_json::from_str::<Value>(&line) {
                            if let Some(error) = structured_engine_error(&detail) {
                                reported_error = Some(error);
                                continue;
                            }
                            let _ = app.emit(
                                "job-progress",
                                JobEvent {
                                    job_id: id_for_thread.clone(),
                                    status: "running".to_string(),
                                    output: output_for_thread.display().to_string(),
                                    detail: Some(detail),
                                    error: None,
                                },
                            );
                        }
                    }
                }
                let output_status = child
                    .wait_with_output()
                    .map_err(|error| format!("等待引擎失败：{error}"))?;
                if !output_status.status.success() {
                    let stderr = String::from_utf8_lossy(&output_status.stderr)
                        .trim()
                        .to_string();
                    return Err(reported_error
                        .filter(|error| !error.is_empty())
                        .or_else(|| (!stderr.is_empty()).then_some(stderr))
                        .unwrap_or_else(|| format!("修复引擎异常退出：{}", output_status.status)));
                }
                Ok(())
            })();
        let cancelled = cancel_file.exists();
        let (status, error) = match result {
            Ok(()) => ("completed", None),
            Err(error) if cancelled => ("cancelled", Some(error)),
            Err(error) => ("failed", Some(error)),
        };
        let _ = app.emit(
            "job-complete",
            JobEvent {
                job_id: id_for_thread.clone(),
                status: status.to_string(),
                output: output_for_thread.display().to_string(),
                detail: None,
                error,
            },
        );
        if let Some(registry_handle) = app.try_state::<JobRegistry>() {
            if let Ok(mut jobs) = registry_handle.0.lock() {
                jobs.remove(&id_for_thread);
            }
        }
        let _ = fs::remove_dir_all(work_dir);
    });

    Ok(StartExportResult {
        job_id: id,
        output: output.display().to_string(),
    })
}

#[tauri::command]
pub fn cancel_job(registry: tauri::State<'_, JobRegistry>, job_id: String) -> Result<(), String> {
    let cancel_file = registry
        .0
        .lock()
        .map_err(|_| "任务表已损坏".to_string())?
        .get(&job_id)
        .cloned()
        .ok_or_else(|| "任务不存在或已经结束".to_string())?;
    fs::write(cancel_file, b"cancel").map_err(|error| format!("无法请求取消任务：{error}"))
}

#[cfg(test)]
mod tests {
    use super::{default_repair_mode, structured_engine_error};
    use serde_json::json;

    #[test]
    fn extracts_structured_engine_failure_from_stdout() {
        assert_eq!(
            structured_engine_error(&json!({
                "ok": false,
                "error": "检测到可变帧率，已阻止导出"
            })),
            Some("检测到可变帧率，已阻止导出".to_string())
        );
        assert_eq!(structured_engine_error(&json!({"event": "progress"})), None);
    }

    #[test]
    fn high_quality_is_the_default_export_mode() {
        assert_eq!(default_repair_mode(), "quality");
    }
}
