use std::{fs, path::Path};

pub fn read(data_dir: &Path, path: &Path) -> Result<String, String> {
    let directory = fs::canonicalize(data_dir.join(".koi-model-responses"))
        .map_err(|error| format!("模型响应目录不可用: {error}"))?;
    let data_dir = fs::canonicalize(data_dir).map_err(|error| error.to_string())?;
    if directory.parent() != Some(data_dir.as_path()) {
        return Err("模型响应目录不属于当前应用数据目录".into());
    }
    let resolved =
        fs::canonicalize(path).map_err(|error| format!("模型响应文件不可用: {error}"))?;
    if resolved.parent() != Some(directory.as_path())
        || resolved
            .extension()
            .is_none_or(|extension| extension != "json")
    {
        return Err("只能读取当前应用保存的模型响应".into());
    }
    let metadata = fs::metadata(&resolved).map_err(|error| error.to_string())?;
    if !metadata.is_file() || metadata.len() > 64 * 1024 * 1024 {
        return Err("模型响应文件无效或过大".into());
    }
    fs::read_to_string(resolved).map_err(|error| format!("读取模型响应失败: {error}"))
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn full_response_read_preserves_long_output_and_rejects_private_paths() {
        let root =
            std::env::temp_dir().join(format!("koi-model-response-read-{}", std::process::id()));
        let folder = root.join(".koi-model-responses");
        fs::create_dir_all(&folder).unwrap();
        let path = folder.join("response.json");
        let text = format!("{{\"plan\":\"{}\"}}", "长响应".repeat(40_000));
        fs::write(&path, &text).unwrap();
        fs::write(root.join("config.json"), "private-data").unwrap();
        assert_eq!(read(&root, &path).unwrap(), text);
        assert!(read(&root, &folder.join("../config.json")).is_err());
        fs::remove_dir_all(root).unwrap();
    }
}
