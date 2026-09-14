//! Hash-locked PDFium runtime used for page rendering and raster compression.
//!
//! The DLL is never resolved from PATH. Its adjacent public lock must match the
//! lock embedded at compile time, every runtime file is hashed, and the DLL is
//! loaded by absolute path with a restricted Windows dependency search policy.

use image::codecs::jpeg::JpegEncoder;
use image::codecs::png::PngEncoder;
use image::{ColorType, ImageEncoder};
use lopdf::{dictionary, Dictionary, Document, Object, Stream};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::collections::BTreeSet;
use std::fs::{self, File};
use std::io::Read;
use std::path::{Component, Path, PathBuf};
use std::sync::Mutex;

pub const LOCK_FILE_NAME: &str = "pdfium-runtime.lock.json";
pub const RUNTIME_DIR_NAME: &str = "pdfium-runtime";
const EMBEDDED_LOCK: &str = include_str!(concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/../../pdfium-runtime.lock.json"
));
const EXPECTED_FORMAT: &str = "koi-pdfium-runtime-v1";
const EXPECTED_PLATFORM: &str = "windows-x64";
const EXPECTED_ARCHITECTURE: &str = "x86_64";
const DLL_FILE_NAME: &str = "pdfium.dll";
const MAX_RUNTIME_FILE_BYTES: u64 = 64 * 1024 * 1024;
const MAX_PDF_BYTES: usize = 256 * 1024 * 1024;
const MAX_RENDER_PAGES: usize = 2_000;
const MAX_RENDER_PIXELS: u64 = 16_000_000;
const THUMBNAIL_WIDTH: u32 = 180;
const STRONG_MAX_DIMENSION: u32 = 1_600;
const STRONG_JPEG_QUALITY: u8 = 68;

static PDFIUM_CALL_LOCK: Mutex<()> = Mutex::new(());

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
struct RuntimeLock {
    format: String,
    version: String,
    chromium_branch: String,
    platform: String,
    architecture: String,
    source: RuntimeSource,
    licenses: RuntimeLicenses,
    files: Vec<RuntimeFile>,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
struct RuntimeSource {
    project: String,
    upstream_url: String,
    binary_distributor: String,
    release_url: String,
    archive_url: String,
    archive_size: u64,
    archive_sha256: String,
    target_commitish: String,
    immutable_release: bool,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
struct RuntimeLicenses {
    binary_distribution_spdx: String,
    pdfium_spdx: String,
    notice_directory: String,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
struct RuntimeFile {
    path: String,
    size: u64,
    sha256: String,
    role: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct RuntimeReport {
    pub version: String,
    pub chromium_branch: String,
    pub platform: String,
    pub runtime_dir: PathBuf,
    pub files_verified: usize,
    pub rendered_width: u32,
    pub rendered_height: u32,
}

#[derive(Debug, Clone)]
struct VerifiedRuntime {
    runtime_dir: PathBuf,
    dll_path: PathBuf,
    lock: RuntimeLock,
}

#[derive(Debug)]
struct RenderedPage {
    page_width: f32,
    page_height: f32,
    pixel_width: u32,
    pixel_height: u32,
    rgb: Vec<u8>,
}

#[derive(Debug, Clone, Copy)]
enum RenderPurpose {
    Thumbnail,
    StrongCompression,
}

fn sha256_file(path: &Path, max_bytes: u64) -> Result<(u64, String), String> {
    let metadata = fs::metadata(path)
        .map_err(|error| format!("unable to read PDFium runtime metadata: {error}"))?;
    if !metadata.is_file() {
        return Err(format!(
            "PDFium runtime entry is not a file: {}",
            path.display()
        ));
    }
    if metadata.len() > max_bytes {
        return Err(format!(
            "PDFium runtime entry is too large: {}",
            path.display()
        ));
    }
    let mut file = File::open(path)
        .map_err(|error| format!("unable to open PDFium runtime entry: {error}"))?;
    let mut hasher = Sha256::new();
    let mut buffer = [0_u8; 64 * 1024];
    let mut total = 0_u64;
    loop {
        let count = file
            .read(&mut buffer)
            .map_err(|error| format!("unable to hash PDFium runtime entry: {error}"))?;
        if count == 0 {
            break;
        }
        total = total
            .checked_add(count as u64)
            .ok_or_else(|| "PDFium runtime entry size overflow".to_string())?;
        if total > max_bytes {
            return Err(format!(
                "PDFium runtime entry is too large: {}",
                path.display()
            ));
        }
        hasher.update(&buffer[..count]);
    }
    Ok((total, format!("{:x}", hasher.finalize())))
}

fn is_lower_hex_sha256(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
}

fn validate_relative_file_path(value: &str) -> Result<PathBuf, String> {
    if value.is_empty() || value.contains('\\') {
        return Err(format!("invalid PDFium runtime lock path: {value}"));
    }
    let path = Path::new(value);
    if path.is_absolute()
        || path.components().any(|component| {
            matches!(
                component,
                Component::Prefix(_) | Component::RootDir | Component::ParentDir
            )
        })
    {
        return Err(format!("unsafe PDFium runtime lock path: {value}"));
    }
    Ok(path.to_path_buf())
}

fn parse_embedded_lock() -> Result<RuntimeLock, String> {
    let lock: RuntimeLock = serde_json::from_str(EMBEDDED_LOCK)
        .map_err(|error| format!("embedded PDFium runtime lock is invalid: {error}"))?;
    if lock.format != EXPECTED_FORMAT
        || lock.platform != EXPECTED_PLATFORM
        || lock.architecture != EXPECTED_ARCHITECTURE
    {
        return Err("embedded PDFium runtime lock targets an unsupported build".to_string());
    }
    if lock.version.trim().is_empty()
        || lock.chromium_branch.trim().is_empty()
        || lock.source.project != "PDFium"
        || lock.source.binary_distributor != "bblanchon/pdfium-binaries"
        || !lock.source.immutable_release
        || lock.source.archive_size == 0
        || !is_lower_hex_sha256(&lock.source.archive_sha256)
        || lock.source.target_commitish.len() != 40
        || !lock
            .source
            .target_commitish
            .bytes()
            .all(|byte| byte.is_ascii_hexdigit())
        || !lock.source.upstream_url.starts_with("https://")
        || !lock.source.release_url.starts_with("https://")
        || !lock.source.archive_url.starts_with("https://")
    {
        return Err("embedded PDFium runtime source provenance is incomplete".to_string());
    }
    if lock.licenses.binary_distribution_spdx != "MIT"
        || lock.licenses.pdfium_spdx != "BSD-3-Clause"
        || lock.licenses.notice_directory != "licenses"
    {
        return Err("embedded PDFium runtime license metadata is invalid".to_string());
    }
    let mut paths = BTreeSet::new();
    let mut runtime_dlls = 0_usize;
    let mut upstream_licenses = 0_usize;
    for entry in &lock.files {
        validate_relative_file_path(&entry.path)?;
        if entry.size == 0
            || entry.size > MAX_RUNTIME_FILE_BYTES
            || !is_lower_hex_sha256(&entry.sha256)
        {
            return Err(format!("invalid PDFium runtime lock entry: {}", entry.path));
        }
        if !paths.insert(entry.path.clone()) {
            return Err(format!(
                "duplicate PDFium runtime lock entry: {}",
                entry.path
            ));
        }
        if entry.path == DLL_FILE_NAME && entry.role == "runtime" {
            runtime_dlls += 1;
        }
        if entry.path == "licenses/pdfium.txt" && entry.role == "upstream-license" {
            upstream_licenses += 1;
        }
    }
    if runtime_dlls != 1 || upstream_licenses != 1 || !paths.contains("LICENSE") {
        return Err("PDFium runtime lock is missing its DLL or required licenses".to_string());
    }
    Ok(lock)
}

fn runtime_inventory(root: &Path) -> Result<BTreeSet<String>, String> {
    let mut pending = vec![root.to_path_buf()];
    let mut files = BTreeSet::new();
    while let Some(directory) = pending.pop() {
        for entry in fs::read_dir(&directory)
            .map_err(|error| format!("unable to enumerate PDFium runtime: {error}"))?
        {
            let entry =
                entry.map_err(|error| format!("unable to enumerate PDFium runtime: {error}"))?;
            let file_type = entry
                .file_type()
                .map_err(|error| format!("unable to inspect PDFium runtime entry: {error}"))?;
            if file_type.is_symlink() {
                return Err(format!(
                    "PDFium runtime must not contain symbolic links: {}",
                    entry.path().display()
                ));
            }
            if file_type.is_dir() {
                pending.push(entry.path());
            } else if file_type.is_file() {
                let relative = entry
                    .path()
                    .strip_prefix(root)
                    .map_err(|_| "PDFium runtime path escaped its root".to_string())?
                    .to_string_lossy()
                    .replace('\\', "/");
                files.insert(relative);
            } else {
                return Err(format!(
                    "unsupported PDFium runtime entry: {}",
                    entry.path().display()
                ));
            }
        }
    }
    Ok(files)
}

fn verify_pe_x64(path: &Path) -> Result<(), String> {
    let bytes = fs::read(path).map_err(|error| format!("unable to read PDFium DLL: {error}"))?;
    if bytes.len() < 0x40 || &bytes[..2] != b"MZ" {
        return Err("PDFium runtime DLL is not a PE image".to_string());
    }
    let pe_offset = u32::from_le_bytes(bytes[0x3c..0x40].try_into().unwrap()) as usize;
    if pe_offset.checked_add(6).is_none_or(|end| end > bytes.len())
        || &bytes[pe_offset..pe_offset + 4] != b"PE\0\0"
    {
        return Err("PDFium runtime DLL has an invalid PE header".to_string());
    }
    let machine = u16::from_le_bytes(bytes[pe_offset + 4..pe_offset + 6].try_into().unwrap());
    if machine != 0x8664 {
        return Err(format!(
            "PDFium runtime DLL is not Windows x64 (machine 0x{machine:04x})"
        ));
    }
    Ok(())
}

fn verify_runtime_at(base: &Path) -> Result<VerifiedRuntime, String> {
    let public_lock = base.join(LOCK_FILE_NAME);
    let lock_bytes = fs::read(&public_lock).map_err(|error| {
        format!(
            "unable to read PDFium runtime lock {}: {error}",
            public_lock.display()
        )
    })?;
    if lock_bytes != EMBEDDED_LOCK.as_bytes() {
        return Err(
            "public PDFium runtime lock does not match the lock embedded in koi.exe".to_string(),
        );
    }
    let lock = parse_embedded_lock()?;
    let runtime_dir = base.join(RUNTIME_DIR_NAME);
    let canonical_root = fs::canonicalize(&runtime_dir).map_err(|error| {
        format!(
            "unable to resolve PDFium runtime directory {}: {error}",
            runtime_dir.display()
        )
    })?;
    if !canonical_root.is_dir() {
        return Err("PDFium runtime path is not a directory".to_string());
    }
    let expected = lock
        .files
        .iter()
        .map(|entry| entry.path.clone())
        .collect::<BTreeSet<_>>();
    let actual = runtime_inventory(&canonical_root)?;
    if actual != expected {
        let missing = expected.difference(&actual).cloned().collect::<Vec<_>>();
        let extra = actual.difference(&expected).cloned().collect::<Vec<_>>();
        return Err(format!(
            "PDFium runtime inventory mismatch (missing: {}; extra: {})",
            missing.join(", "),
            extra.join(", ")
        ));
    }
    for entry in &lock.files {
        let relative = validate_relative_file_path(&entry.path)?;
        let path = canonical_root.join(relative);
        let canonical = fs::canonicalize(&path)
            .map_err(|error| format!("unable to resolve PDFium runtime entry: {error}"))?;
        if !canonical.starts_with(&canonical_root) {
            return Err(format!(
                "PDFium runtime entry escaped its root: {}",
                entry.path
            ));
        }
        let (size, digest) = sha256_file(&canonical, MAX_RUNTIME_FILE_BYTES)?;
        if size != entry.size || digest != entry.sha256 {
            return Err(format!("PDFium runtime hash mismatch: {}", entry.path));
        }
    }
    let dll_path = canonical_root.join(DLL_FILE_NAME);
    verify_pe_x64(&dll_path)?;
    Ok(VerifiedRuntime {
        runtime_dir: canonical_root,
        dll_path,
        lock,
    })
}

fn runtime_base_candidates_for(
    debug_build: bool,
    debug_override: Option<PathBuf>,
    executable_dir: Option<PathBuf>,
    source_root: PathBuf,
) -> Vec<PathBuf> {
    let mut candidates = Vec::new();
    if debug_build {
        if let Some(path) = debug_override {
            candidates.push(path);
        }
    }
    if let Some(parent) = executable_dir {
        candidates.push(parent);
    }
    if debug_build {
        candidates.push(source_root);
    }
    let mut unique = BTreeSet::new();
    candidates
        .into_iter()
        .filter(|path| unique.insert(path.clone()))
        .collect()
}

fn runtime_base_candidates() -> Vec<PathBuf> {
    // Test harnesses run from `target/<profile>/deps`, where bundled runtime
    // files are not copied.  Permit the checked-in source runtime only for
    // tests; release application binaries remain source-tree independent.
    let allow_test_source = cfg!(debug_assertions) || cfg!(test);
    let debug_override = allow_test_source
        .then(|| std::env::var_os("KOI_PDFIUM_RUNTIME_BASE").map(PathBuf::from))
        .flatten();
    let executable_dir = std::env::current_exe()
        .ok()
        .and_then(|path| path.parent().map(Path::to_path_buf));
    let source_root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("..")
        .join("..");
    runtime_base_candidates_for(
        allow_test_source,
        debug_override,
        executable_dir,
        source_root,
    )
}

fn discover_verified_runtime() -> Result<VerifiedRuntime, String> {
    let candidates = runtime_base_candidates();
    let mut errors = Vec::new();
    for base in &candidates {
        match verify_runtime_at(base) {
            Ok(runtime) => return Ok(runtime),
            Err(error) => errors.push(format!("{}: {error}", base.display())),
        }
    }
    Err(format!(
        "no verified PDFium runtime is available; {}",
        errors.join(" | ")
    ))
}

#[cfg(windows)]
mod native {
    use super::*;
    use libloading::os::windows::{
        Library, LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR, LOAD_LIBRARY_SEARCH_SYSTEM32,
    };
    use std::ffi::{c_char, c_int, c_uint, c_void};
    use std::ptr;
    use std::slice;

    type DocumentHandle = *mut c_void;
    type PageHandle = *mut c_void;
    type BitmapHandle = *mut c_void;
    type InitLibrary = unsafe extern "system" fn();
    type DestroyLibrary = unsafe extern "system" fn();
    type LoadMemDocument64 =
        unsafe extern "system" fn(*const c_void, usize, *const c_char) -> DocumentHandle;
    type CloseDocument = unsafe extern "system" fn(DocumentHandle);
    type GetPageCount = unsafe extern "system" fn(DocumentHandle) -> c_int;
    type LoadPage = unsafe extern "system" fn(DocumentHandle, c_int) -> PageHandle;
    type ClosePage = unsafe extern "system" fn(PageHandle);
    type GetPageWidth = unsafe extern "system" fn(PageHandle) -> f32;
    type GetPageHeight = unsafe extern "system" fn(PageHandle) -> f32;
    type BitmapCreate = unsafe extern "system" fn(c_int, c_int, c_int) -> BitmapHandle;
    type BitmapDestroy = unsafe extern "system" fn(BitmapHandle);
    type BitmapFillRect =
        unsafe extern "system" fn(BitmapHandle, c_int, c_int, c_int, c_int, c_uint);
    type RenderPageBitmap = unsafe extern "system" fn(
        BitmapHandle,
        PageHandle,
        c_int,
        c_int,
        c_int,
        c_int,
        c_int,
        c_int,
    );
    type BitmapGetBuffer = unsafe extern "system" fn(BitmapHandle) -> *mut c_void;
    type BitmapGetStride = unsafe extern "system" fn(BitmapHandle) -> c_int;
    type GetLastError = unsafe extern "system" fn() -> c_uint;

    struct Api {
        _library: Library,
        destroy_library: DestroyLibrary,
        load_mem_document: LoadMemDocument64,
        close_document: CloseDocument,
        get_page_count: GetPageCount,
        load_page: LoadPage,
        close_page: ClosePage,
        get_page_width: GetPageWidth,
        get_page_height: GetPageHeight,
        bitmap_create: BitmapCreate,
        bitmap_destroy: BitmapDestroy,
        bitmap_fill_rect: BitmapFillRect,
        render_page_bitmap: RenderPageBitmap,
        bitmap_get_buffer: BitmapGetBuffer,
        bitmap_get_stride: BitmapGetStride,
        get_last_error: GetLastError,
    }

    unsafe fn load_symbol<T: Copy>(library: &Library, name: &[u8]) -> Result<T, String> {
        library
            .get::<T>(name)
            .map(|symbol| *symbol)
            .map_err(|error| {
                format!(
                    "PDFium runtime is missing {}: {error}",
                    String::from_utf8_lossy(name).trim_end_matches('\0')
                )
            })
    }

    impl Api {
        fn load(runtime: &VerifiedRuntime) -> Result<Self, String> {
            let flags = LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR | LOAD_LIBRARY_SEARCH_SYSTEM32;
            let library = unsafe { Library::load_with_flags(&runtime.dll_path, flags) }
                .map_err(|error| format!("unable to load verified PDFium runtime: {error}"))?;
            let init_library: InitLibrary =
                unsafe { load_symbol(&library, b"FPDF_InitLibrary\0")? };
            let api = Self {
                destroy_library: unsafe { load_symbol(&library, b"FPDF_DestroyLibrary\0")? },
                load_mem_document: unsafe { load_symbol(&library, b"FPDF_LoadMemDocument64\0")? },
                close_document: unsafe { load_symbol(&library, b"FPDF_CloseDocument\0")? },
                get_page_count: unsafe { load_symbol(&library, b"FPDF_GetPageCount\0")? },
                load_page: unsafe { load_symbol(&library, b"FPDF_LoadPage\0")? },
                close_page: unsafe { load_symbol(&library, b"FPDF_ClosePage\0")? },
                get_page_width: unsafe { load_symbol(&library, b"FPDF_GetPageWidthF\0")? },
                get_page_height: unsafe { load_symbol(&library, b"FPDF_GetPageHeightF\0")? },
                bitmap_create: unsafe { load_symbol(&library, b"FPDFBitmap_Create\0")? },
                bitmap_destroy: unsafe { load_symbol(&library, b"FPDFBitmap_Destroy\0")? },
                bitmap_fill_rect: unsafe { load_symbol(&library, b"FPDFBitmap_FillRect\0")? },
                render_page_bitmap: unsafe { load_symbol(&library, b"FPDF_RenderPageBitmap\0")? },
                bitmap_get_buffer: unsafe { load_symbol(&library, b"FPDFBitmap_GetBuffer\0")? },
                bitmap_get_stride: unsafe { load_symbol(&library, b"FPDFBitmap_GetStride\0")? },
                get_last_error: unsafe { load_symbol(&library, b"FPDF_GetLastError\0")? },
                _library: library,
            };
            unsafe { init_library() };
            Ok(api)
        }

        fn last_error(&self, action: &str) -> String {
            let code = unsafe { (self.get_last_error)() };
            let description = match code {
                0 => "unknown",
                1 => "file",
                2 => "format",
                3 => "password",
                4 => "security",
                5 => "page",
                _ => "unrecognized",
            };
            format!("PDFium {action} failed ({description}, error {code})")
        }
    }

    impl Drop for Api {
        fn drop(&mut self) {
            unsafe { (self.destroy_library)() };
        }
    }

    struct PdfDocument<'a> {
        api: &'a Api,
        handle: DocumentHandle,
    }

    impl Drop for PdfDocument<'_> {
        fn drop(&mut self) {
            unsafe { (self.api.close_document)(self.handle) };
        }
    }

    struct PdfPage<'a> {
        api: &'a Api,
        handle: PageHandle,
    }

    impl Drop for PdfPage<'_> {
        fn drop(&mut self) {
            unsafe { (self.api.close_page)(self.handle) };
        }
    }

    struct PdfBitmap<'a> {
        api: &'a Api,
        handle: BitmapHandle,
    }

    impl Drop for PdfBitmap<'_> {
        fn drop(&mut self) {
            unsafe { (self.api.bitmap_destroy)(self.handle) };
        }
    }

    fn pixel_dimensions(
        width: f32,
        height: f32,
        purpose: RenderPurpose,
    ) -> Result<(u32, u32), String> {
        if !width.is_finite() || !height.is_finite() || width <= 0.0 || height <= 0.0 {
            return Err("PDFium returned invalid page dimensions".to_string());
        }
        let scale = match purpose {
            RenderPurpose::Thumbnail => (THUMBNAIL_WIDTH as f32 / width).clamp(0.12, 0.45),
            RenderPurpose::StrongCompression => {
                (STRONG_MAX_DIMENSION as f32 / width.max(height)).clamp(0.3, 2.0)
            }
        };
        let mut pixel_width = (width * scale).round().max(1.0) as u32;
        let mut pixel_height = (height * scale).round().max(1.0) as u32;
        let pixels = u64::from(pixel_width) * u64::from(pixel_height);
        if pixels > MAX_RENDER_PIXELS {
            let reduction = (MAX_RENDER_PIXELS as f64 / pixels as f64).sqrt() as f32;
            pixel_width = (pixel_width as f32 * reduction).floor().max(1.0) as u32;
            pixel_height = (pixel_height as f32 * reduction).floor().max(1.0) as u32;
        }
        Ok((pixel_width, pixel_height))
    }

    fn render_with_api(
        api: &Api,
        bytes: &[u8],
        purpose: RenderPurpose,
        limit: usize,
    ) -> Result<Vec<RenderedPage>, String> {
        let document_handle =
            unsafe { (api.load_mem_document)(bytes.as_ptr().cast(), bytes.len(), ptr::null()) };
        if document_handle.is_null() {
            return Err(api.last_error("document load"));
        }
        let document = PdfDocument {
            api,
            handle: document_handle,
        };
        let page_count = unsafe { (api.get_page_count)(document.handle) };
        if page_count <= 0 {
            return Err("PDFium found no renderable pages".to_string());
        }
        let page_count =
            usize::try_from(page_count).map_err(|_| "invalid page count".to_string())?;
        if page_count > MAX_RENDER_PAGES && matches!(purpose, RenderPurpose::StrongCompression) {
            return Err(format!(
                "PDF has {page_count} pages, exceeding the strong-compression limit of {MAX_RENDER_PAGES}"
            ));
        }
        let render_count = page_count.min(limit);
        let mut rendered = Vec::with_capacity(render_count);
        for page_index in 0..render_count {
            let page_handle = unsafe { (api.load_page)(document.handle, page_index as c_int) };
            if page_handle.is_null() {
                return Err(api.last_error(&format!("page {} load", page_index + 1)));
            }
            let page = PdfPage {
                api,
                handle: page_handle,
            };
            let page_width = unsafe { (api.get_page_width)(page.handle) };
            let page_height = unsafe { (api.get_page_height)(page.handle) };
            let (pixel_width, pixel_height) = pixel_dimensions(page_width, page_height, purpose)?;
            let bitmap_handle =
                unsafe { (api.bitmap_create)(pixel_width as c_int, pixel_height as c_int, 0) };
            if bitmap_handle.is_null() {
                return Err(api.last_error(&format!("page {} bitmap creation", page_index + 1)));
            }
            let bitmap = PdfBitmap {
                api,
                handle: bitmap_handle,
            };
            unsafe {
                (api.bitmap_fill_rect)(
                    bitmap.handle,
                    0,
                    0,
                    pixel_width as c_int,
                    pixel_height as c_int,
                    0xffff_ffff,
                );
                (api.render_page_bitmap)(
                    bitmap.handle,
                    page.handle,
                    0,
                    0,
                    pixel_width as c_int,
                    pixel_height as c_int,
                    0,
                    0x01 | 0x02,
                );
            }
            let stride = unsafe { (api.bitmap_get_stride)(bitmap.handle) };
            if stride < 0 || (stride as u32) < pixel_width.saturating_mul(4) {
                return Err("PDFium returned an invalid bitmap stride".to_string());
            }
            let buffer = unsafe { (api.bitmap_get_buffer)(bitmap.handle) };
            if buffer.is_null() {
                return Err("PDFium returned a null bitmap buffer".to_string());
            }
            let buffer_len = usize::try_from(stride)
                .ok()
                .and_then(|stride| stride.checked_mul(pixel_height as usize))
                .ok_or_else(|| "PDFium bitmap size overflow".to_string())?;
            let bgra = unsafe { slice::from_raw_parts(buffer.cast::<u8>(), buffer_len) };
            let rgb_len = usize::try_from(pixel_width)
                .ok()
                .and_then(|width| width.checked_mul(pixel_height as usize))
                .and_then(|pixels| pixels.checked_mul(3))
                .ok_or_else(|| "PDFium RGB buffer size overflow".to_string())?;
            let mut rgb = Vec::with_capacity(rgb_len);
            for row in 0..pixel_height as usize {
                let row_start = row * stride as usize;
                for column in 0..pixel_width as usize {
                    let offset = row_start + column * 4;
                    rgb.extend_from_slice(&[bgra[offset + 2], bgra[offset + 1], bgra[offset]]);
                }
            }
            rendered.push(RenderedPage {
                page_width,
                page_height,
                pixel_width,
                pixel_height,
                rgb,
            });
        }
        Ok(rendered)
    }

    pub(super) fn render(
        bytes: &[u8],
        purpose: RenderPurpose,
        limit: usize,
    ) -> Result<(VerifiedRuntime, Vec<RenderedPage>), String> {
        let _guard = PDFIUM_CALL_LOCK
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        let runtime = discover_verified_runtime()?;
        let api = Api::load(&runtime)?;
        let pages = render_with_api(&api, bytes, purpose, limit)?;
        Ok((runtime, pages))
    }
}

#[cfg(not(windows))]
mod native {
    use super::*;

    pub(super) fn render(
        _bytes: &[u8],
        _purpose: RenderPurpose,
        _limit: usize,
    ) -> Result<(VerifiedRuntime, Vec<RenderedPage>), String> {
        Err("the locked PDFium runtime is only available on Windows x64".to_string())
    }
}

fn validate_pdf_input(bytes: &[u8]) -> Result<(), String> {
    if bytes.len() > MAX_PDF_BYTES {
        return Err("PDF exceeds the 256 MiB rendering limit".to_string());
    }
    if !bytes.starts_with(b"%PDF-") {
        return Err("input is not a PDF document".to_string());
    }
    Ok(())
}

pub(crate) fn render_thumbnails(bytes: &[u8], limit: usize) -> Result<Vec<Vec<u8>>, String> {
    validate_pdf_input(bytes)?;
    if limit == 0 {
        return Ok(Vec::new());
    }
    let (_, pages) = native::render(bytes, RenderPurpose::Thumbnail, limit.min(MAX_RENDER_PAGES))?;
    pages
        .into_iter()
        .map(|page| {
            let mut png = Vec::new();
            PngEncoder::new(&mut png)
                .write_image(
                    &page.rgb,
                    page.pixel_width,
                    page.pixel_height,
                    ColorType::Rgb8,
                )
                .map_err(|error| format!("unable to encode PDF thumbnail PNG: {error}"))?;
            Ok(png)
        })
        .collect()
}

fn build_raster_pdf(pages: Vec<RenderedPage>) -> Result<Vec<u8>, String> {
    if pages.is_empty() {
        return Err("PDFium produced no pages for strong compression".to_string());
    }
    let page_count = pages.len();
    let mut document = Document::with_version("1.5");
    let pages_id = document.new_object_id();
    let mut kids = Vec::with_capacity(pages.len());
    for page in pages {
        let mut jpeg = Vec::new();
        JpegEncoder::new_with_quality(&mut jpeg, STRONG_JPEG_QUALITY)
            .encode(
                &page.rgb,
                page.pixel_width,
                page.pixel_height,
                ColorType::Rgb8,
            )
            .map_err(|error| format!("unable to encode strong-compression JPEG: {error}"))?;
        let image_id = document.add_object(Stream::new(
            dictionary! {
                "Type" => "XObject",
                "Subtype" => "Image",
                "Width" => i64::from(page.pixel_width),
                "Height" => i64::from(page.pixel_height),
                "ColorSpace" => "DeviceRGB",
                "BitsPerComponent" => 8,
                "Filter" => "DCTDecode",
            },
            jpeg,
        ));
        let resources_id = document.add_object(dictionary! {
            "XObject" => dictionary! { "Im0" => image_id },
        });
        let content = format!(
            "q\n{} 0 0 {} 0 0 cm\n/Im0 Do\nQ\n",
            page.page_width, page.page_height
        );
        let content_id = document.add_object(Stream::new(Dictionary::new(), content.into_bytes()));
        let page_id = document.add_object(dictionary! {
            "Type" => "Page",
            "Parent" => pages_id,
            "MediaBox" => vec![
                Object::Integer(0),
                Object::Integer(0),
                Object::Real(page.page_width),
                Object::Real(page.page_height),
            ],
            "Resources" => resources_id,
            "Contents" => content_id,
        });
        kids.push(Object::Reference(page_id));
    }
    document.set_object(
        pages_id,
        dictionary! {
            "Type" => "Pages",
            "Kids" => kids,
            "Count" => i64::try_from(page_count).map_err(|_| "too many PDF pages")?,
        },
    );
    let catalog_id = document.add_object(dictionary! {
        "Type" => "Catalog",
        "Pages" => pages_id,
    });
    document.trailer.set("Root", catalog_id);
    document.renumber_objects();
    let mut bytes = Vec::new();
    document
        .save_to(&mut bytes)
        .map_err(|error| format!("unable to serialize strong-compression PDF: {error}"))?;
    let verified = Document::load_mem(&bytes)
        .map_err(|error| format!("strong-compression PDF validation failed: {error}"))?;
    if verified.get_pages().len() != page_count {
        return Err("strong-compression PDF page-count validation failed".to_string());
    }
    Ok(bytes)
}

pub(crate) fn strong_compress_pdf(bytes: &[u8]) -> Result<Vec<u8>, String> {
    validate_pdf_input(bytes)?;
    let (_, pages) = native::render(bytes, RenderPurpose::StrongCompression, MAX_RENDER_PAGES)?;
    build_raster_pdf(pages)
}

fn self_test_pdf() -> Result<Vec<u8>, String> {
    let mut document = Document::with_version("1.5");
    let pages_id = document.new_object_id();
    let content_id = document.add_object(Stream::new(Dictionary::new(), Vec::new()));
    let page_id = document.add_object(dictionary! {
        "Type" => "Page",
        "Parent" => pages_id,
        "MediaBox" => vec![0.into(), 0.into(), 72.into(), 72.into()],
        "Resources" => Dictionary::new(),
        "Contents" => content_id,
    });
    document.set_object(
        pages_id,
        dictionary! {
            "Type" => "Pages",
            "Kids" => vec![Object::Reference(page_id)],
            "Count" => 1,
        },
    );
    let catalog_id = document.add_object(dictionary! {
        "Type" => "Catalog",
        "Pages" => pages_id,
    });
    document.trailer.set("Root", catalog_id);
    let mut bytes = Vec::new();
    document
        .save_to(&mut bytes)
        .map_err(|error| format!("unable to build PDFium self-test document: {error}"))?;
    Ok(bytes)
}

pub fn run_self_test() -> Result<RuntimeReport, String> {
    let bytes = self_test_pdf()?;
    let (runtime, mut pages) = native::render(&bytes, RenderPurpose::Thumbnail, 1)?;
    let page = pages
        .pop()
        .ok_or_else(|| "PDFium self-test rendered no page".to_string())?;
    if page.rgb.len() != page.pixel_width as usize * page.pixel_height as usize * 3 {
        return Err("PDFium self-test returned an invalid RGB buffer".to_string());
    }
    Ok(RuntimeReport {
        version: runtime.lock.version,
        chromium_branch: runtime.lock.chromium_branch,
        platform: runtime.lock.platform,
        runtime_dir: runtime.runtime_dir,
        files_verified: runtime.lock.files.len(),
        rendered_width: page.pixel_width,
        rendered_height: page.pixel_height,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn bundled_runtime_matches_embedded_lock_and_renders() {
        let report = run_self_test().expect("verify and render with bundled PDFium runtime");
        assert_eq!(report.version, "153.0.8009.0");
        assert_eq!(report.platform, EXPECTED_PLATFORM);
        assert_eq!(report.files_verified, 18);
        assert!(report.rendered_width > 0 && report.rendered_height > 0);
    }

    #[test]
    fn lock_rejects_unlisted_runtime_files() {
        let base = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("..")
            .join("..");
        let verified = verify_runtime_at(&base).expect("verify source runtime");
        assert_eq!(
            verified.lock.source.archive_sha256,
            "c78a8cd51b48abafcb266d868e401afefda1d189aa01ebbe743dc1d144e06031"
        );
        assert!(verified.dll_path.ends_with(DLL_FILE_NAME));
    }

    #[test]
    fn release_candidates_never_include_the_source_tree() {
        let executable = PathBuf::from(r"C:\Program Files\Koi");
        let source = PathBuf::from(r"C:\build\workspace");
        let candidates = runtime_base_candidates_for(
            false,
            Some(PathBuf::from(r"C:\attacker-controlled")),
            Some(executable.clone()),
            source,
        );
        assert_eq!(candidates, vec![executable]);
    }
}
