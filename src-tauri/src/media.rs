use crate::resources::PortablePaths;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::path::Path;
use std::process::Command;
use tauri::Manager;

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct StreamSummary {
    index: u64,
    codec: String,
    language: Option<String>,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct MediaInfo {
    path: String,
    name: String,
    width: u64,
    height: u64,
    duration: f64,
    frame_count: u64,
    fps: f64,
    pixel_format: String,
    rotation: i64,
    audio_streams: Vec<StreamSummary>,
    subtitle_streams: Vec<StreamSummary>,
    warnings: Vec<String>,
}

#[derive(Debug, Deserialize)]
struct ProbeOutput {
    streams: Vec<Value>,
    format: Value,
}

fn fraction(value: Option<&str>) -> f64 {
    value
        .and_then(|rate| rate.split_once('/'))
        .and_then(|(left, right)| Some((left.parse::<f64>().ok()?, right.parse::<f64>().ok()?)))
        .filter(|(_, right)| *right != 0.0)
        .map(|(left, right)| left / right)
        .unwrap_or(0.0)
}

pub fn probe_one(path: &Path, ffprobe: &Path) -> Result<MediaInfo, String> {
    let output = Command::new(ffprobe)
        .args([
            "-v",
            "error",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
        ])
        .arg(path)
        .output()
        .map_err(|error| format!("无法启动 ffprobe：{error}"))?;
    if !output.status.success() {
        return Err(String::from_utf8_lossy(&output.stderr).trim().to_string());
    }
    let probe: ProbeOutput = serde_json::from_slice(&output.stdout)
        .map_err(|error| format!("ffprobe 输出无效：{error}"))?;
    let video = probe
        .streams
        .iter()
        .find(|stream| stream.get("codec_type").and_then(Value::as_str) == Some("video"))
        .ok_or_else(|| "文件没有视频流".to_string())?;
    let fps = fraction(video.get("avg_frame_rate").and_then(Value::as_str));
    let nominal = fraction(video.get("r_frame_rate").and_then(Value::as_str));
    let duration = probe
        .format
        .get("duration")
        .and_then(Value::as_str)
        .and_then(|value| value.parse().ok())
        .unwrap_or(0.0);
    let pixel_format = video
        .get("pix_fmt")
        .and_then(Value::as_str)
        .unwrap_or_default()
        .to_string();
    let transfer = video
        .get("color_transfer")
        .and_then(Value::as_str)
        .unwrap_or_default();
    let mut rotation = video
        .get("tags")
        .and_then(|tags| tags.get("rotate"))
        .and_then(Value::as_str)
        .and_then(|value| value.parse().ok())
        .unwrap_or(0);
    if let Some(side_data) = video.get("side_data_list").and_then(Value::as_array) {
        for item in side_data {
            if let Some(value) = item.get("rotation").and_then(Value::as_i64) {
                rotation = value;
            }
        }
    }
    let mut warnings = Vec::new();
    if matches!(transfer, "smpte2084" | "arib-std-b67") {
        warnings.push("HDR 输入首版默认阻止处理".to_string());
    }
    if ["10", "12", "p010"]
        .iter()
        .any(|token| pixel_format.contains(token))
    {
        warnings.push("10/12-bit 输入首版默认阻止处理".to_string());
    }
    if fps > 0.0 && nominal > 0.0 && (fps - nominal).abs() > 0.01 {
        warnings.push(
            "检测到可变帧率：已默认启用 AI 视频兼容模式，保留全部帧并按平均帧率重建时间轴"
                .to_string(),
        );
    }
    if rotation % 360 != 0 {
        warnings.push("检测到旋转元数据，需先烘焙方向".to_string());
    }
    let summaries = |stream_type: &str| {
        probe
            .streams
            .iter()
            .filter(|stream| stream.get("codec_type").and_then(Value::as_str) == Some(stream_type))
            .map(|stream| StreamSummary {
                index: stream.get("index").and_then(Value::as_u64).unwrap_or(0),
                codec: stream
                    .get("codec_name")
                    .and_then(Value::as_str)
                    .unwrap_or("unknown")
                    .to_string(),
                language: stream
                    .get("tags")
                    .and_then(|tags| tags.get("language"))
                    .and_then(Value::as_str)
                    .map(str::to_string),
            })
            .collect::<Vec<_>>()
    };
    Ok(MediaInfo {
        path: path.display().to_string(),
        name: path
            .file_name()
            .and_then(|value| value.to_str())
            .unwrap_or("video")
            .to_string(),
        width: video.get("width").and_then(Value::as_u64).unwrap_or(0),
        height: video.get("height").and_then(Value::as_u64).unwrap_or(0),
        duration,
        frame_count: video
            .get("nb_frames")
            .and_then(Value::as_str)
            .and_then(|value| value.parse().ok())
            .unwrap_or_else(|| (duration * fps).round() as u64),
        fps,
        pixel_format,
        rotation,
        audio_streams: summaries("audio"),
        subtitle_streams: summaries("subtitle"),
        warnings,
    })
}

#[tauri::command]
pub async fn probe_videos(
    app: tauri::AppHandle,
    paths: Vec<String>,
) -> Result<Vec<MediaInfo>, String> {
    for path in &paths {
        app.asset_protocol_scope()
            .allow_file(path)
            .map_err(|error| format!("无法授权预览视频 {path}：{error}"))?;
    }
    tauri::async_runtime::spawn_blocking(move || {
        let resources = PortablePaths::discover()?;
        paths
            .iter()
            .map(|path| probe_one(Path::new(path), &resources.ffprobe))
            .collect()
    })
    .await
    .map_err(|error| format!("媒体探测任务失败：{error}"))?
}

#[cfg(test)]
mod tests {
    use super::fraction;

    #[test]
    fn parses_fractional_fps() {
        assert!((fraction(Some("30000/1001")) - 29.970_029).abs() < 0.0001);
        assert_eq!(fraction(Some("0/0")), 0.0);
    }
}
