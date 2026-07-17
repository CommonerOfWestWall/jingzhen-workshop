use crate::jobs::engine_command;
use crate::resources::PortablePaths;
use serde::Deserialize;
use serde_json::{Value, json};
use std::fs;
use std::io::{BufRead, BufReader};
use std::path::PathBuf;
use std::process::Stdio;
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::{SystemTime, UNIX_EPOCH};
use tauri::Emitter;

static TRACKING_COUNTER: AtomicU64 = AtomicU64::new(1);

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct TrackingRequest {
    input: String,
    project: Value,
}

fn tracking_id() -> String {
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis();
    let sequence = TRACKING_COUNTER.fetch_add(1, Ordering::Relaxed);
    format!("{now}-{sequence}")
}

#[tauri::command]
pub async fn track_video(app: tauri::AppHandle, request: TrackingRequest) -> Result<Value, String> {
    let input = PathBuf::from(&request.input);
    if !input.is_file() {
        return Err("跟踪视频不存在或无法访问".to_string());
    }
    let keyframes = request
        .project
        .get("keyframes")
        .and_then(Value::as_array)
        .ok_or_else(|| "项目缺少关键帧".to_string())?;
    if !keyframes.iter().any(|item| {
        item.get("shapes")
            .and_then(Value::as_array)
            .is_some_and(|shapes| !shapes.is_empty())
    }) {
        return Err("请先在关键帧标记需要跟踪的目标".to_string());
    }

    tauri::async_runtime::spawn_blocking(move || {
        let work_dir = std::env::temp_dir()
            .join("jingzhen-workshop-tracking")
            .join(tracking_id());
        fs::create_dir_all(&work_dir).map_err(|error| format!("无法创建跟踪目录：{error}"))?;
        let project_path = work_dir.join("input-project.json");
        let output_path = work_dir.join("tracked-project.json");
        let outcome = (|| -> Result<Value, String> {
            fs::write(
                &project_path,
                serde_json::to_vec(&request.project)
                    .map_err(|error| format!("跟踪项目序列化失败：{error}"))?,
            )
            .map_err(|error| format!("无法写入跟踪项目：{error}"))?;
            let resources = PortablePaths::discover()?;
            let mut command = engine_command(&resources)?;
            let mut child = command
                .arg("track-video")
                .arg("--input")
                .arg(&input)
                .arg("--project")
                .arg(&project_path)
                .arg("--output-project")
                .arg(&output_path)
                .stdout(Stdio::piped())
                .stderr(Stdio::piped())
                .spawn()
                .map_err(|error| format!("无法启动移动跟踪：{error}"))?;
            let mut engine_error = None;
            if let Some(stdout) = child.stdout.take() {
                for line in BufReader::new(stdout).lines().map_while(Result::ok) {
                    if let Ok(detail) = serde_json::from_str::<Value>(&line) {
                        if detail.get("event").and_then(Value::as_str)
                            == Some("tracking-progress")
                        {
                            let _ = app.emit("tracking-progress", detail.clone());
                        }
                        if detail.get("ok").and_then(Value::as_bool) == Some(false) {
                            engine_error = detail
                                .get("error")
                                .and_then(Value::as_str)
                                .map(str::to_string);
                        }
                    }
                }
            }
            let output = child
                .wait_with_output()
                .map_err(|error| format!("等待移动跟踪失败：{error}"))?;
            if !output.status.success() {
                let stderr = String::from_utf8_lossy(&output.stderr).trim().to_string();
                return Err(engine_error
                    .or_else(|| (!stderr.is_empty()).then_some(stderr))
                    .unwrap_or_else(|| format!("移动跟踪异常退出：{}", output.status)));
            }
            let tracked: Value = serde_json::from_slice(
                &fs::read(&output_path).map_err(|error| format!("无法读取跟踪结果：{error}"))?,
            )
            .map_err(|error| format!("跟踪结果格式无效：{error}"))?;
            Ok(json!({
                "keyframes": tracked.get("keyframes").cloned().unwrap_or_else(|| json!([])),
                "trackingConfidence": tracked.get("trackingConfidence").cloned().unwrap_or_else(|| json!([])),
                "lowConfidenceRanges": tracked.get("lowConfidenceRanges").cloned().unwrap_or_else(|| json!([])),
                "activeRange": tracked.get("activeRange").cloned().unwrap_or_else(|| json!([0, 0])),
                "trackingEngine": tracked.get("trackingEngine").cloned().unwrap_or_else(|| json!("opencv-bidirectional-affine-v1")),
            }))
        })();
        if work_dir.starts_with(std::env::temp_dir()) {
            let _ = fs::remove_dir_all(&work_dir);
        }
        outcome
    })
    .await
    .map_err(|error| format!("移动跟踪任务失败：{error}"))?
}
