use serde::Serialize;
use serde_json::Value;
use std::env;
use std::ffi::OsString;
use std::fmt;
use std::fs;
use std::path::{Component, Path, PathBuf};

pub const USER_DATA_DIR_ENV: &str = "KOI_USER_DATA_DIR";
pub const TEST_MODE_ENV: &str = "KOI_TEST_MODE";
const PORTABLE_MARKER_FILE: &str = "koi-portable.marker";
const PORTABLE_MARKER_FORMAT: &str = "koi-portable-v1";
const PORTABLE_DATA_DIRECTORY: &str = "koi-data";
const INSTALLED_DATA_DIRECTORY: &str = "Koi";

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum BuildProfile {
    Debug,
    Release,
}

impl BuildProfile {
    pub const fn current() -> Self {
        if cfg!(debug_assertions) {
            Self::Debug
        } else {
            Self::Release
        }
    }
}

#[derive(Clone, Debug)]
pub struct PathResolutionOptions {
    pub app_dir: PathBuf,
    pub workspace_root: Option<PathBuf>,
    pub configured_user_data_dir: Option<OsString>,
    pub local_app_data_dir: Option<PathBuf>,
    pub test_mode: bool,
    pub build_profile: BuildProfile,
    pub temp_root: PathBuf,
    pub current_dir: PathBuf,
}

impl PathResolutionOptions {
    #[allow(dead_code)]
    pub fn from_process(
        app_dir: impl Into<PathBuf>,
        workspace_root: Option<PathBuf>,
    ) -> Result<Self, AppPathError> {
        let current_dir = env::current_dir().map_err(|error| AppPathError::CurrentDirectory {
            message: error.to_string(),
        })?;

        Ok(Self {
            app_dir: app_dir.into(),
            workspace_root,
            configured_user_data_dir: env::var_os(USER_DATA_DIR_ENV),
            local_app_data_dir: env::var_os("LOCALAPPDATA").map(PathBuf::from),
            test_mode: env::var_os(TEST_MODE_ENV)
                .map(|value| value.to_string_lossy().trim() == "1")
                .unwrap_or(false),
            build_profile: BuildProfile::current(),
            temp_root: env::temp_dir(),
            current_dir,
        })
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct AppPaths {
    pub app_dir: PathBuf,
    pub user_data_dir: PathBuf,
    pub config_path: PathBuf,
    pub database_path: PathBuf,
    pub report_templates_dir: PathBuf,
    pub data_templates_dir: PathBuf,
    pub external_tools_dir: PathBuf,
    pub runtime_dir: PathBuf,
    pub test_mode: bool,
    pub build_profile: BuildProfile,
}

impl AppPaths {
    #[allow(dead_code)]
    pub fn from_process(
        app_dir: impl Into<PathBuf>,
        workspace_root: Option<PathBuf>,
    ) -> Result<Self, AppPathError> {
        let options = PathResolutionOptions::from_process(app_dir, workspace_root)?;
        resolve_app_paths(&options)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum AppPathError {
    CurrentDirectory {
        message: String,
    },
    InvalidAppDirectory {
        path: PathBuf,
    },
    MissingTestUserDataDirectory,
    MissingDebugUserDataDirectory,
    EmptyUserDataDirectory,
    MissingLocalAppDataDirectory,
    DebugUserDataDirectoryMustBeAbsolute {
        path: PathBuf,
    },
    DebugUserDataDirectoryMustBeTemporary {
        path: PathBuf,
        temp_root: PathBuf,
    },
    DebugUserDataDirectoryIsWorkspace {
        path: PathBuf,
        workspace_root: PathBuf,
    },
    DebugUserDataDirectoryUsesProtectedPath {
        path: PathBuf,
        component: &'static str,
    },
    TestUserDataDirectoryMustBeAbsolute {
        path: PathBuf,
    },
    TestUserDataDirectoryMustBeTemporary {
        path: PathBuf,
        temp_root: PathBuf,
    },
    TestUserDataDirectoryIsWorkspace {
        path: PathBuf,
        workspace_root: PathBuf,
    },
    TestUserDataDirectoryUsesProtectedPath {
        path: PathBuf,
        component: &'static str,
    },
}

impl AppPathError {
    pub const fn code(&self) -> &'static str {
        match self {
            Self::CurrentDirectory { .. } => "current_directory_unavailable",
            Self::InvalidAppDirectory { .. } => "invalid_app_directory",
            Self::MissingTestUserDataDirectory => "test_user_data_dir_required",
            Self::MissingDebugUserDataDirectory => "debug_user_data_dir_required",
            Self::EmptyUserDataDirectory => "user_data_dir_empty",
            Self::MissingLocalAppDataDirectory => "local_app_data_directory_unavailable",
            Self::DebugUserDataDirectoryMustBeAbsolute { .. } => {
                "debug_user_data_dir_must_be_absolute"
            }
            Self::DebugUserDataDirectoryMustBeTemporary { .. } => {
                "debug_user_data_dir_must_be_temporary"
            }
            Self::DebugUserDataDirectoryIsWorkspace { .. } => "debug_user_data_dir_is_workspace",
            Self::DebugUserDataDirectoryUsesProtectedPath { .. } => {
                "debug_user_data_dir_is_protected"
            }
            Self::TestUserDataDirectoryMustBeAbsolute { .. } => {
                "test_user_data_dir_must_be_absolute"
            }
            Self::TestUserDataDirectoryMustBeTemporary { .. } => {
                "test_user_data_dir_must_be_temporary"
            }
            Self::TestUserDataDirectoryIsWorkspace { .. } => "test_user_data_dir_is_workspace",
            Self::TestUserDataDirectoryUsesProtectedPath { .. } => {
                "test_user_data_dir_is_protected"
            }
        }
    }
}

impl fmt::Display for AppPathError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::CurrentDirectory { message } => {
                write!(formatter, "unable to resolve the current directory: {message}")
            }
            Self::InvalidAppDirectory { path } => {
                write!(formatter, "application directory is invalid: {}", path.display())
            }
            Self::MissingTestUserDataDirectory => write!(
                formatter,
                "KOI_TEST_MODE=1 requires an explicit KOI_USER_DATA_DIR"
            ),
            Self::MissingDebugUserDataDirectory => write!(
                formatter,
                "debug builds require an explicit KOI_USER_DATA_DIR pointing to an isolated test directory"
            ),
            Self::EmptyUserDataDirectory => {
                write!(formatter, "KOI_USER_DATA_DIR must not be empty")
            }
            Self::MissingLocalAppDataDirectory => write!(
                formatter,
                "installed release requires LOCALAPPDATA unless KOI_USER_DATA_DIR is configured"
            ),
            Self::DebugUserDataDirectoryMustBeAbsolute { path } => write!(
                formatter,
                "debug user data directory must be absolute: {}",
                path.display()
            ),
            Self::DebugUserDataDirectoryMustBeTemporary { path, temp_root } => write!(
                formatter,
                "debug user data directory must be a child of the system temporary directory {}: {}",
                temp_root.display(),
                path.display()
            ),
            Self::DebugUserDataDirectoryIsWorkspace {
                path,
                workspace_root,
            } => write!(
                formatter,
                "debug user data directory must not be inside workspace {}: {}",
                workspace_root.display(),
                path.display()
            ),
            Self::DebugUserDataDirectoryUsesProtectedPath { path, component } => write!(
                formatter,
                "debug user data directory contains protected path component {component}: {}",
                path.display()
            ),
            Self::TestUserDataDirectoryMustBeAbsolute { path } => write!(
                formatter,
                "test user data directory must be absolute: {}",
                path.display()
            ),
            Self::TestUserDataDirectoryMustBeTemporary { path, temp_root } => write!(
                formatter,
                "test user data directory must be a child of the system temporary directory {}: {}",
                temp_root.display(),
                path.display()
            ),
            Self::TestUserDataDirectoryIsWorkspace {
                path,
                workspace_root,
            } => write!(
                formatter,
                "test user data directory must not be inside workspace {}: {}",
                workspace_root.display(),
                path.display()
            ),
            Self::TestUserDataDirectoryUsesProtectedPath { path, component } => write!(
                formatter,
                "test user data directory contains protected path component {component}: {}",
                path.display()
            ),
        }
    }
}

impl std::error::Error for AppPathError {}

pub fn resolve_app_paths(options: &PathResolutionOptions) -> Result<AppPaths, AppPathError> {
    if options.app_dir.as_os_str().is_empty() {
        return Err(AppPathError::InvalidAppDirectory {
            path: options.app_dir.clone(),
        });
    }

    let app_dir = normalize_absolute(&options.app_dir, &options.current_dir);
    let workspace_root = options
        .workspace_root
        .as_deref()
        .map(|path| normalize_absolute(path, &options.current_dir));
    let configured_user_data_dir = configured_path(options.configured_user_data_dir.as_ref())?;

    if options.test_mode && configured_user_data_dir.is_none() {
        return Err(AppPathError::MissingTestUserDataDirectory);
    }
    if options.build_profile == BuildProfile::Debug && configured_user_data_dir.is_none() {
        return Err(AppPathError::MissingDebugUserDataDirectory);
    }

    let user_data_dir = match configured_user_data_dir {
        Some(path) => {
            if options.test_mode && !path.is_absolute() {
                return Err(AppPathError::TestUserDataDirectoryMustBeAbsolute { path });
            }
            if options.build_profile == BuildProfile::Debug && !path.is_absolute() {
                return Err(AppPathError::DebugUserDataDirectoryMustBeAbsolute { path });
            }
            normalize_absolute(&path, &options.current_dir)
        }
        None if portable_marker_is_valid(&app_dir) => app_dir
            .parent()
            .map(|parent| parent.join(PORTABLE_DATA_DIRECTORY))
            .unwrap_or_else(|| app_dir.join(PORTABLE_DATA_DIRECTORY)),
        None => options
            .local_app_data_dir
            .as_deref()
            .filter(|path| !path.as_os_str().is_empty())
            .map(|path| normalize_absolute(path, &options.current_dir))
            .map(|path| path.join(INSTALLED_DATA_DIRECTORY))
            .ok_or(AppPathError::MissingLocalAppDataDirectory)?,
    };

    if options.test_mode {
        validate_test_user_data_dir(
            &user_data_dir,
            &normalize_absolute(&options.temp_root, &options.current_dir),
            workspace_root.as_deref(),
        )?;
    }
    if options.build_profile == BuildProfile::Debug {
        validate_debug_user_data_dir(
            &user_data_dir,
            &normalize_absolute(&options.temp_root, &options.current_dir),
            workspace_root.as_deref(),
        )?;
    }

    Ok(AppPaths {
        app_dir: app_dir.clone(),
        config_path: user_data_dir.join("config.json"),
        database_path: user_data_dir.join("enterprise_classification.db"),
        report_templates_dir: user_data_dir.join("Report_Template"),
        data_templates_dir: user_data_dir.join("templates"),
        external_tools_dir: app_dir.join("retest_external_tools"),
        runtime_dir: user_data_dir.join(".koi-runtime"),
        user_data_dir,
        test_mode: options.test_mode,
        build_profile: options.build_profile,
    })
}

fn portable_marker_is_valid(app_dir: &Path) -> bool {
    let Some(parent) = app_dir.parent() else {
        return false;
    };
    let marker_path = parent.join(PORTABLE_MARKER_FILE);
    let Ok(metadata) = fs::symlink_metadata(&marker_path) else {
        return false;
    };
    if metadata.file_type().is_symlink() || !metadata.is_file() || metadata.len() > 64 * 1024 {
        return false;
    }
    let Ok(bytes) = fs::read(marker_path) else {
        return false;
    };
    let Ok(marker) = serde_json::from_slice::<Value>(&bytes) else {
        return false;
    };
    marker.get("format").and_then(Value::as_str) == Some(PORTABLE_MARKER_FORMAT)
        && marker.get("dataDirectory").and_then(Value::as_str) == Some(PORTABLE_DATA_DIRECTORY)
}

fn configured_path(value: Option<&OsString>) -> Result<Option<PathBuf>, AppPathError> {
    let Some(value) = value else {
        return Ok(None);
    };
    if value.to_string_lossy().trim().is_empty() {
        return Err(AppPathError::EmptyUserDataDirectory);
    }
    Ok(Some(PathBuf::from(value)))
}

fn validate_test_user_data_dir(
    user_data_dir: &Path,
    temp_root: &Path,
    workspace_root: Option<&Path>,
) -> Result<(), AppPathError> {
    if same_path(user_data_dir, temp_root) || !is_same_or_descendant(user_data_dir, temp_root) {
        return Err(AppPathError::TestUserDataDirectoryMustBeTemporary {
            path: user_data_dir.to_path_buf(),
            temp_root: temp_root.to_path_buf(),
        });
    }

    if let Some(workspace_root) = workspace_root {
        if is_same_or_descendant(user_data_dir, workspace_root) {
            return Err(AppPathError::TestUserDataDirectoryIsWorkspace {
                path: user_data_dir.to_path_buf(),
                workspace_root: workspace_root.to_path_buf(),
            });
        }
    }

    for protected in ["dist-tauri", "recovery-v4.0.0"] {
        if has_component(user_data_dir, protected) {
            return Err(AppPathError::TestUserDataDirectoryUsesProtectedPath {
                path: user_data_dir.to_path_buf(),
                component: protected,
            });
        }
    }

    Ok(())
}

fn validate_debug_user_data_dir(
    user_data_dir: &Path,
    temp_root: &Path,
    workspace_root: Option<&Path>,
) -> Result<(), AppPathError> {
    if same_path(user_data_dir, temp_root) || !is_same_or_descendant(user_data_dir, temp_root) {
        return Err(AppPathError::DebugUserDataDirectoryMustBeTemporary {
            path: user_data_dir.to_path_buf(),
            temp_root: temp_root.to_path_buf(),
        });
    }

    if let Some(workspace_root) = workspace_root {
        if is_same_or_descendant(user_data_dir, workspace_root) {
            return Err(AppPathError::DebugUserDataDirectoryIsWorkspace {
                path: user_data_dir.to_path_buf(),
                workspace_root: workspace_root.to_path_buf(),
            });
        }
    }

    for protected in ["dist-tauri", "recovery-v4.0.0"] {
        if has_component(user_data_dir, protected) {
            return Err(AppPathError::DebugUserDataDirectoryUsesProtectedPath {
                path: user_data_dir.to_path_buf(),
                component: protected,
            });
        }
    }

    Ok(())
}

fn normalize_absolute(path: &Path, current_dir: &Path) -> PathBuf {
    let absolute = if path.is_absolute() {
        path.to_path_buf()
    } else {
        current_dir.join(path)
    };
    let mut normalized = PathBuf::new();
    for component in absolute.components() {
        match component {
            Component::CurDir => {}
            Component::ParentDir => {
                normalized.pop();
            }
            _ => normalized.push(component.as_os_str()),
        }
    }
    normalized
}

fn comparable_components(path: &Path) -> Vec<String> {
    path.components()
        .map(|component| {
            let text = component.as_os_str().to_string_lossy();
            if cfg!(windows) {
                text.to_lowercase()
            } else {
                text.into_owned()
            }
        })
        .collect()
}

fn same_path(left: &Path, right: &Path) -> bool {
    comparable_components(left) == comparable_components(right)
}

fn is_same_or_descendant(path: &Path, root: &Path) -> bool {
    let path_components = comparable_components(path);
    let root_components = comparable_components(root);
    path_components.starts_with(&root_components)
}

fn has_component(path: &Path, expected: &str) -> bool {
    path.components().any(|component| {
        matches!(component, Component::Normal(value) if value.to_string_lossy().eq_ignore_ascii_case(expected))
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::{SystemTime, UNIX_EPOCH};

    fn unique_path(label: &str) -> PathBuf {
        let nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("clock is after unix epoch")
            .as_nanos();
        env::temp_dir().join(format!(
            "koi-path-test-{label}-{}-{nonce}",
            std::process::id()
        ))
    }

    fn options(profile: BuildProfile) -> PathResolutionOptions {
        let workspace = unique_path("workspace");
        PathResolutionOptions {
            app_dir: workspace.join("tauri-ui/src-tauri/target/debug"),
            workspace_root: Some(workspace.clone()),
            configured_user_data_dir: None,
            local_app_data_dir: Some(workspace.join("local-app-data")),
            test_mode: false,
            build_profile: profile,
            temp_root: env::temp_dir(),
            current_dir: workspace,
        }
    }

    #[test]
    fn configured_user_data_dir_wins_in_debug_and_release() {
        let configured = unique_path("configured");
        for profile in [BuildProfile::Debug, BuildProfile::Release] {
            let mut options = options(profile);
            options.configured_user_data_dir = Some(configured.clone().into_os_string());

            let paths = resolve_app_paths(&options).expect("configured path resolves");
            assert_eq!(paths.user_data_dir, configured);
            assert_eq!(paths.config_path, configured.join("config.json"));
        }
    }

    #[test]
    fn test_mode_requires_an_explicit_user_data_dir() {
        let mut options = options(BuildProfile::Debug);
        options.test_mode = true;

        assert!(matches!(
            resolve_app_paths(&options),
            Err(AppPathError::MissingTestUserDataDirectory)
        ));
    }

    #[test]
    fn debug_build_requires_an_explicit_user_data_dir() {
        let options = options(BuildProfile::Debug);

        assert!(matches!(
            resolve_app_paths(&options),
            Err(AppPathError::MissingDebugUserDataDirectory)
        ));
    }

    #[test]
    fn test_mode_accepts_a_dedicated_temp_child() {
        let configured = unique_path("data");
        let mut options = options(BuildProfile::Debug);
        options.test_mode = true;
        options.configured_user_data_dir = Some(configured.clone().into_os_string());

        let paths = resolve_app_paths(&options).expect("temporary path resolves");
        assert_eq!(paths.user_data_dir, configured);
        assert!(paths.test_mode);
    }

    #[test]
    fn test_mode_rejects_workspace_and_protected_release_paths() {
        let mut workspace_options = options(BuildProfile::Debug);
        workspace_options.test_mode = true;
        let workspace_data = workspace_options
            .workspace_root
            .as_ref()
            .expect("workspace")
            .join("test-data");
        workspace_options.configured_user_data_dir = Some(workspace_data.into_os_string());
        assert!(matches!(
            resolve_app_paths(&workspace_options),
            Err(AppPathError::TestUserDataDirectoryIsWorkspace { .. })
        ));

        for component in ["dist-tauri", "recovery-v4.0.0"] {
            let mut protected_options = options(BuildProfile::Debug);
            protected_options.test_mode = true;
            let protected = env::temp_dir().join(component).join("koi-data");
            protected_options.configured_user_data_dir = Some(protected.into_os_string());
            assert!(matches!(
                resolve_app_paths(&protected_options),
                Err(AppPathError::TestUserDataDirectoryUsesProtectedPath { .. })
            ));
        }
    }

    #[test]
    fn debug_build_rejects_workspace_data_even_when_configured() {
        let mut options = options(BuildProfile::Debug);
        let workspace_data = options
            .workspace_root
            .as_ref()
            .expect("workspace")
            .join("test-data");
        options.configured_user_data_dir = Some(workspace_data.into_os_string());

        assert!(matches!(
            resolve_app_paths(&options),
            Err(AppPathError::DebugUserDataDirectoryIsWorkspace { .. })
        ));
    }

    #[test]
    fn normal_mode_allows_the_recovery_data_snapshot() {
        let mut options = options(BuildProfile::Release);
        let recovery_data = options
            .workspace_root
            .as_ref()
            .expect("workspace")
            .join("dist-tauri/recovery-v4.0.0/koi-data");
        options.configured_user_data_dir = Some(recovery_data.clone().into_os_string());

        let paths = resolve_app_paths(&options).expect("normal recovery data is allowed");
        assert_eq!(paths.user_data_dir, recovery_data);
        assert!(!paths.test_mode);
    }

    #[test]
    fn installed_release_defaults_to_local_app_data() {
        let options = options(BuildProfile::Release);
        let expected = options
            .local_app_data_dir
            .as_ref()
            .expect("local app data")
            .join("Koi");

        let paths = resolve_app_paths(&options).expect("release defaults resolve");
        assert_eq!(paths.user_data_dir, expected);
    }

    #[test]
    fn portable_marker_uses_sibling_data_directory() {
        let options = options(BuildProfile::Release);
        fs::create_dir_all(&options.app_dir).expect("create portable app directory");
        let parent = options.app_dir.parent().expect("application parent");
        fs::write(
            parent.join(PORTABLE_MARKER_FILE),
            br#"{"format":"koi-portable-v1","version":"4.0.0","dataDirectory":"koi-data"}"#,
        )
        .expect("write portable marker");

        let paths = resolve_app_paths(&options).expect("portable paths resolve");
        assert_eq!(paths.user_data_dir, parent.join("koi-data"));
        let _ = fs::remove_dir_all(options.workspace_root.as_ref().expect("workspace root"));
    }

    #[test]
    fn invalid_portable_marker_does_not_redirect_installed_data() {
        let options = options(BuildProfile::Release);
        fs::create_dir_all(&options.app_dir).expect("create application directory");
        let parent = options.app_dir.parent().expect("application parent");
        fs::write(
            parent.join(PORTABLE_MARKER_FILE),
            br#"{"format":"koi-portable-v1","dataDirectory":"..\\shared"}"#,
        )
        .expect("write invalid portable marker");

        let paths = resolve_app_paths(&options).expect("installed paths resolve");
        assert_eq!(
            paths.user_data_dir,
            options
                .local_app_data_dir
                .as_ref()
                .expect("local app data")
                .join("Koi")
        );
        let _ = fs::remove_dir_all(options.workspace_root.as_ref().expect("workspace root"));
    }
}
