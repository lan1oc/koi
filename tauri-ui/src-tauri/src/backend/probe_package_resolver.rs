//! On-demand PyPI wheel resolution for a single probe environment.
use super::*;
use regex::Regex;
use serde_json::Value;
use std::collections::VecDeque;

#[derive(Clone, Debug)]
struct Requirement {
    name: String,
    constraints: String,
    extras: Vec<String>,
}
fn requirement(value: &str) -> Result<Requirement, WheelError> {
    let pattern = Regex::new(r"^\s*([A-Za-z0-9][A-Za-z0-9_.-]*)(?:\[([^\]]*)\])?\s*(.*)$")
        .expect("package requirement");
    let capture = pattern.captures(value).ok_or_else(|| {
        WheelError::new(
            "resolve",
            format!("Invalid PyPI package requirement: {value}"),
        )
    })?;
    let name = normalize_name(&capture[1])?;
    let constraints = capture[3].trim().trim_matches(['(', ')']).to_string();
    if constraints.contains('@') || constraints.contains('/') || constraints.contains(':') {
        return Err(WheelError::new(
            "resolve",
            "Use a PyPI distribution name and version requirement, not a local path or URL",
        ));
    }
    let extras = capture
        .get(2)
        .map(|m| {
            m.as_str()
                .split(',')
                .map(|v| v.trim().to_string())
                .collect()
        })
        .unwrap_or_default();
    Ok(Requirement {
        name,
        constraints,
        extras,
    })
}
fn version_key(value: &str) -> Vec<u64> {
    value
        .split('.')
        .map(|part| {
            part.chars()
                .take_while(char::is_ascii_digit)
                .collect::<String>()
                .parse()
                .unwrap_or(0)
        })
        .collect()
}
fn compare_versions(a: &str, b: &str) -> std::cmp::Ordering {
    let (mut a, mut b) = (version_key(a), version_key(b));
    let length = a.len().max(b.len());
    a.resize(length, 0);
    b.resize(length, 0);
    a.cmp(&b)
}
fn matches_version(version: &str, constraints: &str) -> bool {
    constraints.split(',').all(|rule| {
        let rule = rule.trim();
        if rule.is_empty() {
            return true;
        }
        let Some((op, wanted)) = ["===", "==", "!=", ">=", "<=", "~=", ">", "<"]
            .into_iter()
            .find_map(|op| rule.strip_prefix(op).map(|wanted| (op, wanted.trim())))
        else {
            return false;
        };
        if let Some(prefix) = wanted.strip_suffix(".*") {
            return if op == "!=" {
                !(version == prefix || version.starts_with(&format!("{prefix}.")))
            } else {
                version == prefix || version.starts_with(&format!("{prefix}."))
            };
        }
        let cmp = compare_versions(version, wanted);
        match op {
            "==" => cmp.is_eq(),
            "===" => version == wanted,
            "!=" => !cmp.is_eq(),
            ">=" => cmp.is_ge(),
            "<=" => cmp.is_le(),
            ">" => cmp.is_gt(),
            "<" => cmp.is_lt(),
            "~=" => {
                let key = version_key(wanted);
                cmp.is_ge()
                    && version_key(version)
                        .iter()
                        .take(key.len().saturating_sub(1).max(1))
                        .eq(key.iter().take(key.len().saturating_sub(1).max(1)))
            }
            _ => false,
        }
    })
}
fn marker_enabled(marker: &str, extras: &[String]) -> Result<bool, WheelError> {
    fn strip_group(text: &str) -> &str {
        let text = text.trim();
        if text.starts_with('(') && text.ends_with(')') {
            let mut depth = 0;
            let mut quote = None;
            for (index, character) in text.char_indices() {
                if let Some(current) = quote {
                    if character == current {
                        quote = None;
                    }
                    continue;
                }
                if matches!(character, '\'' | '"') {
                    quote = Some(character);
                } else if character == '(' {
                    depth += 1;
                } else if character == ')' {
                    depth -= 1;
                    if depth == 0 && index + 1 < text.len() {
                        return text;
                    }
                }
            }
            strip_group(&text[1..text.len() - 1])
        } else {
            text
        }
    }
    fn split<'a>(text: &'a str, separator: &str) -> Option<Vec<&'a str>> {
        let mut depth = 0;
        let mut quote = None;
        let mut start = 0;
        let mut pieces = Vec::new();
        for (index, character) in text.char_indices() {
            if let Some(current) = quote {
                if character == current {
                    quote = None;
                }
                continue;
            }
            if matches!(character, '\'' | '"') {
                quote = Some(character);
            } else if character == '(' {
                depth += 1;
            } else if character == ')' {
                depth -= 1;
            }
            if depth == 0 && text[index..].starts_with(separator) {
                pieces.push(text[start..index].trim());
                start = index + separator.len();
            }
        }
        if pieces.is_empty() {
            None
        } else {
            pieces.push(text[start..].trim());
            Some(pieces)
        }
    }
    let marker = strip_group(marker);
    if marker.is_empty() {
        return Ok(true);
    }
    if let Some(parts) = split(marker, " or ") {
        let mut result = false;
        for part in parts {
            result |= marker_enabled(part, extras)?;
        }
        return Ok(result);
    }
    if let Some(parts) = split(marker, " and ") {
        let mut result = true;
        for part in parts {
            result &= marker_enabled(part, extras)?;
        }
        return Ok(result);
    }
    let re = Regex::new(r#"^\s*([a-z_]+)\s*(not\s+in|in|==|!=|<=|>=|<|>)\s*['"]([^'"]+)['"]\s*$"#)
        .expect("dependency marker");
    let captures = re.captures(marker).ok_or_else(|| {
        WheelError::new(
            "resolve",
            format!("Unsupported dependency marker; no dependency was silently omitted: {marker}"),
        )
    })?;
    let value = match &captures[1] {
        "python_version" => "3.13",
        "python_full_version" => "3.13.15",
        "sys_platform" => "win32",
        "platform_system" => "Windows",
        "platform_machine" => "AMD64",
        "implementation_name" => "cpython",
        "platform_python_implementation" => "CPython",
        "os_name" => "nt",
        "extra" => "",
        other => {
            return Err(WheelError::new(
                "resolve",
                format!("Unsupported dependency environment variable: {other}"),
            ))
        }
    };
    let compare = |value: &str| match &captures[2] {
        "in" => captures[3].contains(value),
        "not in" => !captures[3].contains(value),
        operator if captures[1].starts_with("python") => {
            matches_version(value, &format!("{operator}{}", &captures[3]))
        }
        "==" => value == &captures[3],
        "!=" => value != &captures[3],
        "<" => value < &captures[3],
        ">" => value > &captures[3],
        "<=" => value <= &captures[3],
        ">=" => value >= &captures[3],
        _ => false,
    };
    Ok(if &captures[1] == "extra" {
        if extras.is_empty() {
            compare("")
        } else {
            extras.iter().any(|extra| compare(extra))
        }
    } else {
        compare(value)
    })
}

fn metadata(client: &Client, name: &str, version: Option<&str>) -> Result<Value, WheelError> {
    let url = match version {
        Some(version) => format!("https://pypi.org/pypi/{name}/{version}/json"),
        None => format!("https://pypi.org/pypi/{name}/json"),
    };
    let response = client
        .get(url)
        .send()
        .map_err(|e| WheelError::new("resolve", format!("PyPI metadata for {name} failed: {e}")))?;
    if !response.status().is_success() {
        return Err(WheelError::new(
            "resolve",
            format!("PyPI package {name} returned {}", response.status()),
        ));
    }
    let mut bytes = Vec::new();
    response
        .take(16 * 1024 * 1024 + 1)
        .read_to_end(&mut bytes)
        .map_err(|e| WheelError::new("resolve", e.to_string()))?;
    if bytes.len() > 16 * 1024 * 1024 {
        return Err(WheelError::new("resolve", "PyPI metadata exceeds 16 MiB"));
    }
    serde_json::from_slice(&bytes)
        .map_err(|e| WheelError::new("resolve", format!("Invalid PyPI metadata: {e}")))
}
fn selected_artifact(data: &Value, req: &Requirement) -> Option<LockedWheelArtifact> {
    let version = data["info"]["version"].as_str()?;
    if !matches_version(version, &req.constraints) {
        return None;
    }
    if let Some(python) = data["info"]["requires_python"].as_str() {
        if !matches_version("3.13.15", python) {
            return None;
        }
    }
    let mut candidates = data["urls"]
        .as_array()?
        .iter()
        .filter(|item| item["packagetype"] == "bdist_wheel" && item["yanked"] != true)
        .filter_map(|item| {
            let filename = item["filename"].as_str()?;
            validate_wheel_compatibility(&req.name, version, filename).ok()?;
            Some(LockedWheelArtifact {
                filename: filename.into(),
                url: item["url"].as_str()?.into(),
                sha256: item["digests"]["sha256"].as_str()?.into(),
                size: item["size"].as_u64(),
            })
        })
        .collect::<Vec<_>>();
    candidates.sort_by_key(|artifact| {
        (
            !artifact.filename.ends_with("win_amd64.whl"),
            artifact.filename.clone(),
        )
    });
    candidates.into_iter().next()
}
fn find_release(
    client: &Client,
    req: &Requirement,
) -> Result<(Value, LockedWheelArtifact), WheelError> {
    let latest = metadata(client, &req.name, None)?;
    if let Some(artifact) = selected_artifact(&latest, req) {
        return Ok((latest, artifact));
    }
    let mut versions = latest["releases"]
        .as_object()
        .map(|items| {
            items
                .keys()
                .filter(|v| {
                    v.chars().all(|c| c.is_ascii_digit() || c == '.')
                        && matches_version(v, &req.constraints)
                })
                .cloned()
                .collect::<Vec<_>>()
        })
        .unwrap_or_default();
    versions.sort_by(|a, b| compare_versions(b, a));
    for version in versions.into_iter().take(30) {
        let data = metadata(client, &req.name, Some(&version))?;
        if let Some(artifact) = selected_artifact(&data, req) {
            return Ok((data, artifact));
        }
    }
    Err(WheelError::new("resolve",format!("No CPython 3.13 Windows x64 wheel satisfies {} {}; specify a compatible version or use an alternative library",req.name,req.constraints)))
}
fn wheel_imports(file: &Path) -> Result<Vec<String>, WheelError> {
    let mut zip =
        ZipArchive::new(File::open(file).map_err(|e| WheelError::new("resolve", e.to_string()))?)
            .map_err(|e| WheelError::new("resolve", e.to_string()))?;
    let mut roots = BTreeSet::new();
    for i in 0..zip.len() {
        let name = zip
            .by_index(i)
            .map_err(|e| WheelError::new("resolve", e.to_string()))?
            .name()
            .to_string();
        let components = name.split('/').collect::<Vec<_>>();
        let root = if components[0].ends_with(".data")
            && components.len() > 2
            && matches!(components[1], "purelib" | "platlib")
        {
            components[2]
        } else {
            components[0]
        };
        if root.contains(".dist-info")
            || root.ends_with(".data")
            || root.starts_with('_')
                && root.contains('.')
                && !root.ends_with(".py")
                && !root.ends_with(".pyd")
        {
            continue;
        }
        let module = if root.ends_with(".py") {
            root.trim_end_matches(".py")
        } else if root.ends_with(".pyd") {
            root.split('.').next().unwrap_or(root)
        } else if components.len() > 1 && !root.contains('.') {
            root
        } else {
            continue;
        };
        if validate_import_name(module).is_ok() {
            roots.insert(module.to_string());
        }
    }
    Ok(roots.into_iter().collect())
}
pub fn download_probe_packages(
    application_dir: &Path,
    cache_dir: &Path,
    requested: &[String],
) -> Result<Vec<DownloadedWheel>, WheelError> {
    if requested.is_empty() {
        return Ok(Vec::new());
    }
    let lock = load_lock(application_dir)?;
    if requested
        .iter()
        .all(|name| lock.packages.iter().any(|package| package.name == *name))
    {
        return download_packages(application_dir, cache_dir, requested);
    }
    ensure_cache_dir(cache_dir)?;
    let client = artifact_client()?;
    let mut combined = BTreeMap::<String, Requirement>::new();
    for requested in requested {
        let requirement = requirement(requested)?;
        match combined.entry(requirement.name.clone()) {
            std::collections::btree_map::Entry::Vacant(slot) => {
                slot.insert(requirement);
            }
            std::collections::btree_map::Entry::Occupied(mut slot) => {
                let saved = slot.get_mut();
                if !requirement.constraints.is_empty() {
                    if !saved.constraints.is_empty() {
                        saved.constraints.push(',');
                    }
                    saved.constraints.push_str(&requirement.constraints);
                }
                saved.extras.extend(requirement.extras);
                saved.extras.sort();
                saved.extras.dedup();
            }
        }
    }
    let mut pending = combined.into_values().collect::<VecDeque<_>>();
    let mut dependency_specs = BTreeMap::<String, Vec<String>>::new();
    let mut expanded_extras = BTreeMap::<String, BTreeSet<String>>::new();
    let mut resolved = BTreeMap::<String, DownloadedWheel>::new();
    while let Some(req) = pending.pop_front() {
        if let Some(existing) = resolved.get(&req.name) {
            if !matches_version(&existing.package.version, &req.constraints) {
                return Err(WheelError::new(
                    "resolve",
                    format!(
                        "Dependency version conflict for {}: {} does not satisfy {}",
                        req.name, existing.package.version, req.constraints
                    ),
                ));
            }
            let expanded = expanded_extras.entry(req.name.clone()).or_default();
            let added = req.extras.iter().any(|extra| !expanded.contains(extra));
            if added {
                expanded.extend(req.extras.iter().cloned());
                let extras = expanded.iter().cloned().collect::<Vec<_>>();
                for dependency in dependency_specs.get(&req.name).into_iter().flatten() {
                    let (spec, marker) = dependency
                        .split_once(';')
                        .unwrap_or((dependency.as_str(), ""));
                    if marker_enabled(marker, &extras)? {
                        pending.push_back(requirement(spec)?);
                    }
                }
            }
            continue;
        }
        if resolved.len() >= 64 {
            return Err(WheelError::new(
                "resolve",
                "Probe package dependency closure exceeds 64 distributions",
            ));
        }
        let (data, artifact) = find_release(&client, &req)?;
        validate_artifact(&artifact, false)?;
        let path = ensure_cached_artifact(&client, cache_dir, &artifact)?;
        let imports = wheel_imports(&path)?;
        let version = data["info"]["version"]
            .as_str()
            .ok_or_else(|| WheelError::new("resolve", "PyPI release version missing"))?
            .to_string();
        let dependencies = data["info"]["requires_dist"]
            .as_array()
            .into_iter()
            .flatten()
            .filter_map(Value::as_str)
            .map(str::to_string)
            .collect::<Vec<_>>();
        for dependency in &dependencies {
            let (spec, marker) = dependency
                .split_once(';')
                .unwrap_or((dependency.as_str(), ""));
            if marker_enabled(marker, &req.extras)? {
                pending.push_back(requirement(spec)?);
            }
        }
        dependency_specs.insert(req.name.clone(), dependencies);
        expanded_extras.insert(req.name.clone(), req.extras.iter().cloned().collect());
        resolved.insert(
            req.name.clone(),
            DownloadedWheel {
                package: ResolvedWheel {
                    name: req.name,
                    version,
                    artifact,
                    imports,
                },
                path,
            },
        );
    }
    let wheels = resolved.into_values().collect::<Vec<_>>();
    let manifest = serde_json::json!({"format":"koi-probe-session-packages-v1","source":PYPI_SIMPLE_SOURCE,"requested":requested,"packages":wheels.iter().map(|wheel|serde_json::json!({"name":wheel.package.name,"version":wheel.package.version,"sha256":wheel.package.artifact.sha256,"url":wheel.package.artifact.url,"imports":wheel.package.imports})).collect::<Vec<_>>()});
    let bytes = serde_json::to_vec_pretty(&manifest)
        .map_err(|e| WheelError::new("resolve", e.to_string()))?;
    let digest = hex_digest(Sha256::digest(&bytes));
    fs::write(
        cache_dir.join(format!("session-{}.json", &digest[..16])),
        bytes,
    )
    .map_err(|e| WheelError::new("resolve", e.to_string()))?;
    Ok(wheels)
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn tool_audit_dependency_markers_preserve_groups_membership_and_version_boundaries() {
        assert!(marker_enabled(
            "(sys_platform == 'win32' or sys_platform == 'linux') and python_version >= '3.10'",
            &[]
        )
        .unwrap());
        assert!(!marker_enabled(
            "sys_platform == 'linux' or (sys_platform == 'win32' and python_version < '3.10')",
            &[]
        )
        .unwrap());
        assert!(marker_enabled("sys_platform in 'win32,darwin'", &[]).unwrap());
        assert!(marker_enabled("extra != 'source'", &[]).unwrap());
        assert!(marker_enabled("extra == 'socks'", &["socks".into()]).unwrap());
        assert!(marker_enabled("unknown_environment == 'x'", &[]).is_err());
        assert!(matches_version("1.10", "!=1.1.*"));
        assert!(matches_version("1.0.0", "==1.0"));
    }

    #[test]
    fn requirements_and_markers_preserve_runtime_compatibility() {
        let r = requirement("beautifulsoup4>=4.12,<5").unwrap();
        assert_eq!(r.name, "beautifulsoup4");
        assert!(matches_version("4.13.4", &r.constraints));
        assert!(!matches_version("5.0", &r.constraints));
        assert!(
            marker_enabled("python_version >= '3.9' and sys_platform == 'win32'", &[]).unwrap()
        );
        assert!(!marker_enabled("python_version < '3.8'", &[]).unwrap());
        assert!(!marker_enabled("extra == 'test'", &[]).unwrap());
        assert!(requirement("custom @ https://other.test/package.whl").is_err());
    }
}
