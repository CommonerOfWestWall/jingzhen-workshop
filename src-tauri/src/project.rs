use serde::Serialize;
use serde_json::Value;
use std::fs::File;
use std::io::{Read, Write};
use std::path::Path;
use tauri::Manager;

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct TrackingAnalysis {
    low_confidence_ranges: Vec<(u64, u64)>,
    keyframe_count: usize,
    ready: bool,
}

#[tauri::command]
pub fn save_project(path: String, project: Value) -> Result<(), String> {
    let target = Path::new(&path);
    if target.extension().and_then(|value| value.to_str()) != Some("jzf") {
        return Err("项目文件必须使用 .jzf 扩展名".to_string());
    }
    let payload =
        serde_json::to_vec_pretty(&project).map_err(|error| format!("项目序列化失败：{error}"))?;
    let mut file = File::create(target).map_err(|error| format!("无法创建项目：{error}"))?;
    file.write_all(&payload)
        .map_err(|error| format!("无法写入项目：{error}"))?;
    file.sync_all()
        .map_err(|error| format!("无法同步项目：{error}"))
}

#[tauri::command]
pub fn load_project(app: tauri::AppHandle, path: String) -> Result<Value, String> {
    let mut file = File::open(&path).map_err(|error| format!("无法打开项目：{error}"))?;
    let mut payload = String::new();
    file.read_to_string(&mut payload)
        .map_err(|error| format!("无法读取项目：{error}"))?;
    let project: Value =
        serde_json::from_str(&payload).map_err(|error| format!("项目格式无效：{error}"))?;
    if project.get("version").and_then(Value::as_u64) != Some(1) {
        return Err("不支持的项目版本".to_string());
    }
    if let Some(tasks) = project
        .get("state")
        .and_then(|state| state.get("tasks"))
        .and_then(Value::as_array)
    {
        for media_path in tasks.iter().filter_map(|task| {
            task.get("media")
                .and_then(|media| media.get("path"))
                .and_then(Value::as_str)
        }) {
            app.asset_protocol_scope()
                .allow_file(media_path)
                .map_err(|error| format!("无法授权项目视频 {media_path}：{error}"))?;
        }
    }
    Ok(project)
}

#[tauri::command]
pub fn analyze_project(project: Value, frame_count: u64) -> Result<TrackingAnalysis, String> {
    let keyframes = project
        .get("keyframes")
        .and_then(Value::as_array)
        .ok_or_else(|| "项目缺少关键帧".to_string())?;
    let mut frames = keyframes
        .iter()
        .filter_map(|keyframe| keyframe.get("frame").and_then(Value::as_u64))
        .collect::<Vec<_>>();
    frames.sort_unstable();
    frames.dedup();
    let low_gap = project
        .get("lowConfidenceGap")
        .and_then(Value::as_u64)
        .unwrap_or(12);
    let strategy = project
        .get("strategy")
        .and_then(Value::as_str)
        .unwrap_or("fixed");
    let mut ranges = Vec::new();
    if strategy != "fixed" {
        for pair in frames.windows(2) {
            if pair[1] - pair[0] > low_gap * 2 {
                ranges.push((pair[0] + low_gap, pair[1].saturating_sub(low_gap)));
            }
        }
    }
    let has_shapes = keyframes.iter().any(|keyframe| {
        keyframe
            .get("shapes")
            .and_then(Value::as_array)
            .is_some_and(|shapes| !shapes.is_empty())
    });
    Ok(TrackingAnalysis {
        low_confidence_ranges: ranges,
        keyframe_count: frames.len(),
        ready: has_shapes && frame_count > 0,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn moving_gap_is_reported() {
        let analysis = analyze_project(
            json!({
                "strategy": "moving",
                "lowConfidenceGap": 10,
                "keyframes": [
                    {"frame": 0, "shapes": [{"kind": "rect"}]},
                    {"frame": 40, "shapes": [{"kind": "rect"}]}
                ]
            }),
            50,
        )
        .unwrap();
        assert!(analysis.ready);
        assert_eq!(analysis.low_confidence_ranges, vec![(10, 30)]);
    }
}
