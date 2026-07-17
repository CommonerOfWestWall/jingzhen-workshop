use std::path::{Path, PathBuf};

pub fn unique_output_path(input: &Path, output_dir: Option<&Path>) -> Result<PathBuf, String> {
    let stem = input
        .file_stem()
        .and_then(|value| value.to_str())
        .ok_or_else(|| "输入文件名无效".to_string())?;
    let extension = input
        .extension()
        .and_then(|value| value.to_str())
        .unwrap_or("mp4");
    let directory = output_dir
        .map(Path::to_path_buf)
        .or_else(|| input.parent().map(Path::to_path_buf))
        .ok_or_else(|| "无法确定输出目录".to_string())?;
    for index in 1..=9_999 {
        let suffix = if index == 1 {
            "_clean".to_string()
        } else {
            format!("_clean_{index:02}")
        };
        let candidate = directory.join(format!("{stem}{suffix}.{extension}"));
        if !candidate.exists() {
            return Ok(candidate);
        }
    }
    Err("输出目录中同名版本过多".to_string())
}

#[tauri::command]
pub fn suggest_output_path(input: String, output_dir: Option<String>) -> Result<String, String> {
    unique_output_path(Path::new(&input), output_dir.as_deref().map(Path::new))
        .map(|path| path.display().to_string())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;

    #[test]
    fn increments_without_overwriting() {
        let directory = tempfile::tempdir().unwrap();
        let input = directory.path().join("片段.mp4");
        fs::write(&input, b"input").unwrap();
        assert_eq!(
            unique_output_path(&input, None).unwrap(),
            directory.path().join("片段_clean.mp4")
        );
        fs::write(directory.path().join("片段_clean.mp4"), b"first").unwrap();
        assert_eq!(
            unique_output_path(&input, None).unwrap(),
            directory.path().join("片段_clean_02.mp4")
        );
    }
}
