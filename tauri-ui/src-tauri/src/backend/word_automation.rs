use super::ConversionType;
use std::collections::HashSet;
use std::mem::size_of;
use std::mem::ManuallyDrop;
use std::path::Path;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::thread::{self, JoinHandle};
use std::time::Duration;
use windows::core::{BOOL, BSTR, GUID, PCWSTR};
use windows::Win32::Foundation::{CloseHandle, HWND, LPARAM, VARIANT_FALSE, VARIANT_TRUE, WPARAM};
use windows::Win32::Globalization::LOCALE_USER_DEFAULT;
use windows::Win32::System::Com::{
    CLSIDFromProgID, CoCreateInstance, CoDisableCallCancellation, CoEnableCallCancellation,
    CoInitializeEx, CoUninitialize, IDispatch, CLSCTX_LOCAL_SERVER, COINIT_APARTMENTTHREADED,
    DISPATCH_FLAGS, DISPATCH_METHOD, DISPATCH_PROPERTYGET, DISPATCH_PROPERTYPUT, DISPPARAMS,
    EXCEPINFO,
};
use windows::Win32::System::Diagnostics::ToolHelp::{
    CreateToolhelp32Snapshot, Process32FirstW, Process32NextW, PROCESSENTRY32W, TH32CS_SNAPPROCESS,
};
use windows::Win32::System::Ole::DISPID_PROPERTYPUT;
use windows::Win32::System::Variant::{
    VariantClear, VARENUM, VARIANT, VARIANT_0, VARIANT_0_0, VARIANT_0_0_0, VT_BOOL, VT_BSTR,
    VT_DISPATCH, VT_I4,
};
use windows::Win32::UI::WindowsAndMessaging::{
    EnumChildWindows, EnumWindows, GetClassNameW, GetDlgCtrlID, GetWindowTextLengthW,
    GetWindowTextW, GetWindowThreadProcessId, SendMessageTimeoutW, SMTO_ABORTIFHUNG,
    SMTO_ERRORONEXIT,
};

const WORD_PDF_FORMAT: i32 = 17;
const WORD_DOCX_FORMAT: i32 = 16;
const WORD_DO_NOT_SAVE: i32 = 0;

pub(super) fn convert(
    source: &Path,
    destination: &Path,
    kind: ConversionType,
) -> Result<(), String> {
    let _apartment = ComApartment::initialize()?;
    let existing_word_pids = word_process_ids()?;
    let mut word = WordSession::start()?;
    let conversion = (|| {
        word.open_read_only(source, kind, &existing_word_pids)?;
        match kind {
            ConversionType::WordToPdf => word.export_pdf(destination),
            ConversionType::WordToDocx => word.save_docx(destination),
            ConversionType::PdfToWord => word.save_docx(destination),
        }
    })();
    let cleanup = word.close();
    match (conversion, cleanup) {
        (Ok(()), Ok(())) => Ok(()),
        (Err(error), Ok(())) => Err(error),
        (Ok(()), Err(error)) => Err(format!("Word COM cleanup failed: {error}")),
        (Err(error), Err(cleanup)) => {
            Err(format!("{error}; Word COM cleanup also failed: {cleanup}"))
        }
    }
}

pub(super) struct NoticeRewriteFields<'a> {
    pub(super) company: &'a str,
    pub(super) vulnerability: &'a str,
    pub(super) current_date: &'a str,
    pub(super) deadline_date: &'a str,
    pub(super) copy_to: &'a str,
}

pub(super) fn rewrite_notice(
    source: &Path,
    template: &Path,
    destination: &Path,
    fields: NoticeRewriteFields<'_>,
) -> Result<(), String> {
    let _apartment = ComApartment::initialize()?;
    let application = DispatchObject::create("Word.Application")?;
    application.set_bool("Visible", false)?;
    application.set_i32("DisplayAlerts", 0)?;
    let documents = application.get_dispatch("Documents")?;
    let target = open_document(&documents, template, false)?;
    let source_document = match open_document(&documents, source, true) {
        Ok(document) => document,
        Err(error) => {
            let _ = close_document(&target);
            let _ =
                application.call_void("Quit", vec![AutomationVariant::from_i32(WORD_DO_NOT_SAVE)]);
            return Err(error);
        }
    };

    let operation = (|| {
        replace_notice_template_fields(&target, &fields)?;
        insert_notice_source_content(&source_document, &target)?;
        target.call_void(
            "SaveAs2",
            vec![
                AutomationVariant::from_path(destination),
                AutomationVariant::from_i32(WORD_DOCX_FORMAT),
            ],
        )
    })();

    let mut cleanup_errors = Vec::new();
    if let Err(error) = close_document(&source_document) {
        cleanup_errors.push(error);
    }
    if let Err(error) = close_document(&target) {
        cleanup_errors.push(error);
    }
    if let Err(error) =
        application.call_void("Quit", vec![AutomationVariant::from_i32(WORD_DO_NOT_SAVE)])
    {
        cleanup_errors.push(error);
    }
    match (operation, cleanup_errors.is_empty()) {
        (Ok(()), true) => Ok(()),
        (Ok(()), false) => Err(format!(
            "Word notice rewrite cleanup failed: {}",
            cleanup_errors.join("; ")
        )),
        (Err(error), true) => Err(error),
        (Err(error), false) => Err(format!(
            "{error}; Word notice rewrite cleanup also failed: {}",
            cleanup_errors.join("; ")
        )),
    }
}

fn open_document(
    documents: &DispatchObject,
    path: &Path,
    read_only: bool,
) -> Result<DispatchObject, String> {
    documents.call_dispatch(
        "Open",
        vec![
            AutomationVariant::from_path(path),
            AutomationVariant::from_bool(false),
            AutomationVariant::from_bool(read_only),
            AutomationVariant::from_bool(false),
        ],
    )
}

fn close_document(document: &DispatchObject) -> Result<(), String> {
    document.call_void("Close", vec![AutomationVariant::from_i32(WORD_DO_NOT_SAVE)])
}

fn paragraph_text(paragraph: &DispatchObject) -> Result<String, String> {
    let range = paragraph.get_dispatch("Range")?;
    Ok(range
        .get_string("Text")?
        .trim_end_matches(['\r', '\u{7}'])
        .to_string())
}

fn set_paragraph_text(paragraph: &DispatchObject, value: &str) -> Result<(), String> {
    paragraph
        .get_dispatch("Range")?
        .set_string("Text", &format!("{value}\r"))
}

fn replace_notice_template_fields(
    document: &DispatchObject,
    fields: &NoticeRewriteFields<'_>,
) -> Result<(), String> {
    let paragraphs = document.get_dispatch("Paragraphs")?;
    let count = paragraphs.get_i32("Count")?.max(0);
    for index in 1..=count {
        let paragraph =
            paragraphs.call_dispatch("Item", vec![AutomationVariant::from_i32(index)])?;
        let original = paragraph_text(&paragraph)?;
        let mut value = original.clone();
        if index == 4 {
            value = replace_between(&value, "关于", &["所属", "存在"], fields.company);
        }
        if index == 6 {
            if let Some(colon) = value.find(['：', ':']) {
                value.replace_range(..colon, fields.company);
            }
        }
        if index == 7 {
            value = replace_notice_issue(&value, fields.vulnerability);
            value = replace_chinese_date(&value, fields.deadline_date, true);
        }
        if index == 14 {
            value = replace_chinese_date(&value, fields.current_date, false);
        }
        let trimmed = value.trim();
        if is_copy_to_placeholder(trimmed) {
            value = format!("抄送：{}", fields.copy_to);
        }
        if value != original {
            set_paragraph_text(&paragraph, &value)?;
        }
    }
    Ok(())
}

fn replace_between(value: &str, prefix: &str, suffixes: &[&str], replacement: &str) -> String {
    let Some(start) = value.find(prefix).map(|index| index + prefix.len()) else {
        return value.to_string();
    };
    let Some(end) = suffixes
        .iter()
        .filter_map(|suffix| value[start..].find(suffix).map(|index| start + index))
        .min()
    else {
        return value.to_string();
    };
    if end <= start {
        return value.to_string();
    }
    let mut output = value.to_string();
    output.replace_range(start..end, replacement);
    output
}

fn replace_notice_issue(value: &str, vulnerability: &str) -> String {
    let Some(start) = value.find("存在").map(|index| index + "存在".len()) else {
        return value.to_string();
    };
    let end = ["。请", "，请", ".请"]
        .iter()
        .filter_map(|marker| value[start..].find(marker).map(|index| start + index))
        .min();
    let Some(end) = end else {
        return value.to_string();
    };
    let mut output = value.to_string();
    output.replace_range(start..end, vulnerability.trim_start_matches("存在"));
    output
}

fn replace_chinese_date(value: &str, replacement: &str, keep_before: bool) -> String {
    let bytes = value.as_bytes();
    for start in 0..bytes.len().saturating_sub(3) {
        if bytes[start] != b'2' || bytes.get(start + 1) != Some(&b'0') {
            continue;
        }
        let rest = &value[start..];
        let Some(year) = rest.find('年') else {
            continue;
        };
        let Some(month) = rest[year + '年'.len_utf8()..].find('月') else {
            continue;
        };
        let month_end = year + '年'.len_utf8() + month;
        let Some(day) = rest[month_end + '月'.len_utf8()..].find('日') else {
            continue;
        };
        let end = start + month_end + '月'.len_utf8() + day + '日'.len_utf8();
        let mut output = value.to_string();
        output.replace_range(start..end, replacement);
        if !keep_before && output[start + replacement.len()..].starts_with('前') {
            output.remove(start + replacement.len());
        }
        return output;
    }
    value.to_string()
}

fn is_copy_to_placeholder(value: &str) -> bool {
    let compact = value.replace([' ', '\u{3000}'], "");
    compact == "抄送：*" || compact == "抄送:*"
}

fn is_source_body_anchor(value: &str) -> bool {
    let trimmed = value.trim();
    let mut chars = trimmed.chars();
    chars.next() == Some('1')
        && chars
            .next()
            .is_some_and(|character| matches!(character, '.' | '．' | '、' | ')' | '）'))
        && chars.any(|character| !character.is_whitespace())
}

fn insert_notice_source_content(
    source: &DispatchObject,
    target: &DispatchObject,
) -> Result<(), String> {
    let source_paragraphs = source.get_dispatch("Paragraphs")?;
    let source_count = source_paragraphs.get_i32("Count")?.max(0);
    let mut first_nonempty = None;
    let mut body_start = None;
    let mut last_nonempty = None;
    for index in 1..=source_count {
        let paragraph =
            source_paragraphs.call_dispatch("Item", vec![AutomationVariant::from_i32(index)])?;
        let text = paragraph_text(&paragraph)?;
        if text.trim().is_empty() {
            continue;
        }
        first_nonempty.get_or_insert(index);
        if body_start.is_none() && is_source_body_anchor(&text) {
            body_start = Some(index);
        }
        last_nonempty = Some(index);
    }
    let start_index = body_start
        .or(first_nonempty)
        .ok_or_else(|| "notice source contains no non-empty paragraph to insert".to_string())?;
    let end_index = last_nonempty.unwrap_or(start_index);
    let source_start = source_paragraphs
        .call_dispatch("Item", vec![AutomationVariant::from_i32(start_index)])?
        .get_dispatch("Range")?
        .get_i32("Start")?;
    let source_end = source_paragraphs
        .call_dispatch("Item", vec![AutomationVariant::from_i32(end_index)])?
        .get_dispatch("Range")?
        .get_i32("End")?;
    let source_range = source.call_dispatch(
        "Range",
        vec![
            AutomationVariant::from_i32(source_start),
            AutomationVariant::from_i32(source_end),
        ],
    )?;

    let target_paragraphs = target.get_dispatch("Paragraphs")?;
    let target_count = target_paragraphs.get_i32("Count")?.max(0);
    let anchors = [
        "1.漏洞描述",
        "1．漏洞描述",
        "一、漏洞描述",
        "漏洞事件：",
        "漏洞事件:",
    ];
    let mut insertion_start = None;
    let mut truncate_tail = false;
    let mut marker_end = None;
    for index in 1..=target_count {
        let paragraph =
            target_paragraphs.call_dispatch("Item", vec![AutomationVariant::from_i32(index)])?;
        let text = paragraph_text(&paragraph)?;
        let range = paragraph.get_dispatch("Range")?;
        if text.contains('*') && !is_copy_to_placeholder(text.trim()) {
            insertion_start = Some(range.get_i32("Start")?);
            marker_end = Some(range.get_i32("End")?);
            break;
        }
        if anchors.iter().any(|anchor| text.trim().starts_with(anchor)) {
            insertion_start = Some(range.get_i32("Start")?);
            truncate_tail = true;
            break;
        }
    }
    let content = target.get_dispatch("Content")?;
    let content_end = content.get_i32("End")?.saturating_sub(1);
    let insertion_start = insertion_start.unwrap_or(content_end);
    let delete_end = if truncate_tail {
        content_end
    } else {
        marker_end.unwrap_or(insertion_start)
    };
    if delete_end > insertion_start {
        target
            .call_dispatch(
                "Range",
                vec![
                    AutomationVariant::from_i32(insertion_start),
                    AutomationVariant::from_i32(delete_end),
                ],
            )?
            .call_void("Delete", Vec::new())?;
    }
    source_range.call_void("Copy", Vec::new())?;
    target
        .call_dispatch(
            "Range",
            vec![
                AutomationVariant::from_i32(insertion_start),
                AutomationVariant::from_i32(insertion_start),
            ],
        )?
        .call_void("PasteAndFormat", vec![AutomationVariant::from_i32(16)])
}

struct ComApartment {
    cancellation_enabled: bool,
}

impl ComApartment {
    fn initialize() -> Result<Self, String> {
        unsafe { CoInitializeEx(None, COINIT_APARTMENTTHREADED) }
            .ok()
            .map_err(|error| format!("cannot initialize the Word COM STA: {error}"))?;
        if let Err(error) = unsafe { CoEnableCallCancellation(None) } {
            unsafe { CoUninitialize() };
            return Err(format!(
                "cannot enable cancellation for the Word COM STA: {error}"
            ));
        }
        Ok(Self {
            cancellation_enabled: true,
        })
    }
}

impl Drop for ComApartment {
    fn drop(&mut self) {
        if self.cancellation_enabled {
            let _ = unsafe { CoDisableCallCancellation(None) };
        }
        unsafe { CoUninitialize() };
    }
}

#[derive(Clone)]
struct DispatchObject(IDispatch);

impl DispatchObject {
    fn create(prog_id: &str) -> Result<Self, String> {
        let prog_id = WideName::new(prog_id);
        let class_id = unsafe { CLSIDFromProgID(prog_id.as_pcwstr()) }
            .map_err(|error| format!("Word.Application is not registered: {error}"))?;
        let dispatch: IDispatch = unsafe { CoCreateInstance(&class_id, None, CLSCTX_LOCAL_SERVER) }
            .map_err(|error| format!("cannot start Word.Application: {error}"))?;
        Ok(Self(dispatch))
    }

    fn set_bool(&self, name: &str, value: bool) -> Result<(), String> {
        self.invoke(
            name,
            DISPATCH_PROPERTYPUT,
            vec![AutomationVariant::from_bool(value)],
            true,
        )
        .map(|_| ())
    }

    fn set_i32(&self, name: &str, value: i32) -> Result<(), String> {
        self.invoke(
            name,
            DISPATCH_PROPERTYPUT,
            vec![AutomationVariant::from_i32(value)],
            true,
        )
        .map(|_| ())
    }

    fn set_string(&self, name: &str, value: &str) -> Result<(), String> {
        self.invoke(
            name,
            DISPATCH_PROPERTYPUT,
            vec![AutomationVariant::from_string(value)],
            true,
        )
        .map(|_| ())
    }

    fn get_i32(&self, name: &str) -> Result<i32, String> {
        self.invoke(name, DISPATCH_PROPERTYGET, Vec::new(), false)?
            .to_i32(name)
    }

    fn get_string(&self, name: &str) -> Result<String, String> {
        self.invoke(name, DISPATCH_PROPERTYGET, Vec::new(), false)?
            .to_string_value(name)
    }

    fn get_dispatch(&self, name: &str) -> Result<Self, String> {
        self.invoke(name, DISPATCH_PROPERTYGET, Vec::new(), false)?
            .to_dispatch(name)
    }

    fn call_dispatch(&self, name: &str, arguments: Vec<AutomationVariant>) -> Result<Self, String> {
        self.invoke(name, DISPATCH_METHOD, arguments, false)?
            .to_dispatch(name)
    }

    fn call_void(&self, name: &str, arguments: Vec<AutomationVariant>) -> Result<(), String> {
        self.invoke(name, DISPATCH_METHOD, arguments, false)
            .map(|_| ())
    }

    fn invoke(
        &self,
        name: &str,
        flags: DISPATCH_FLAGS,
        arguments: Vec<AutomationVariant>,
        property_put: bool,
    ) -> Result<AutomationVariant, String> {
        let member = self.member_id(name)?;
        // Automation stores positional arguments right-to-left in DISPPARAMS.
        let mut arguments = reverse_for_dispatch(arguments);
        let mut property_put_id = DISPID_PROPERTYPUT;
        let parameters = DISPPARAMS {
            rgvarg: if arguments.is_empty() {
                std::ptr::null_mut()
            } else {
                arguments.as_mut_ptr().cast::<VARIANT>()
            },
            rgdispidNamedArgs: if property_put {
                &mut property_put_id
            } else {
                std::ptr::null_mut()
            },
            cArgs: arguments.len() as u32,
            cNamedArgs: u32::from(property_put),
        };
        let mut result = AutomationVariant::empty();
        let mut exception = ExceptionInfo::default();
        let mut argument_error = u32::MAX;
        let iid_null = GUID::from_u128(0);
        let invoked = unsafe {
            self.0.Invoke(
                member,
                &iid_null,
                LOCALE_USER_DEFAULT,
                flags,
                &parameters,
                Some(result.as_mut_ptr()),
                Some(exception.as_mut_ptr()),
                Some(&mut argument_error),
            )
        };
        if let Err(error) = invoked {
            let detail = exception.describe();
            let argument = if argument_error == u32::MAX {
                String::new()
            } else {
                format!(" (argument index {argument_error})")
            };
            return Err(if detail.is_empty() {
                format!("Word COM {name} failed{argument}: {error}")
            } else {
                format!("Word COM {name} failed{argument}: {error}; {detail}")
            });
        }
        Ok(result)
    }

    fn member_id(&self, name: &str) -> Result<i32, String> {
        let member_name = name;
        let name = WideName::new(name);
        let pointer = name.as_pcwstr();
        let mut member = 0i32;
        let iid_null = GUID::from_u128(0);
        unsafe {
            self.0
                .GetIDsOfNames(&iid_null, &pointer, 1, LOCALE_USER_DEFAULT, &mut member)
        }
        .map_err(|error| format!("Word COM member lookup failed for {member_name}: {error}"))?;
        Ok(member)
    }
}

struct WordSession {
    application: Option<DispatchObject>,
    document: Option<DispatchObject>,
}

impl WordSession {
    fn start() -> Result<Self, String> {
        let application = DispatchObject::create("Word.Application")?;
        let mut session = Self {
            application: Some(application),
            document: None,
        };
        let configured = (|| {
            session.application()?.set_bool("Visible", false)?;
            session.application()?.set_i32("DisplayAlerts", 0)?;
            // Word's PDF reflow prompt is controlled by this per-instance
            // option; unlike the UI checkbox it does not persist globally.
            if let Ok(options) = session.application()?.get_dispatch("Options") {
                let _ = options.set_bool("ConfirmConversions", false);
            }
            Ok(())
        })();
        if let Err(error) = configured {
            let _ = session.close();
            return Err(error);
        }
        Ok(session)
    }

    fn open_read_only(
        &mut self,
        source: &Path,
        kind: ConversionType,
        existing_word_pids: &HashSet<u32>,
    ) -> Result<(), String> {
        let prompt = if kind == ConversionType::PdfToWord {
            let process_id = wait_for_new_word_process(existing_word_pids)?;
            Some(PdfConversionPrompt::start(process_id)?)
        } else {
            None
        };
        let documents = self.application()?.get_dispatch("Documents")?;
        let opened = documents.call_dispatch(
            "Open",
            vec![
                AutomationVariant::from_path(source),
                AutomationVariant::from_bool(false),
                AutomationVariant::from_bool(true),
                AutomationVariant::from_bool(false),
            ],
        );
        let prompt_result = prompt.map(PdfConversionPrompt::finish).unwrap_or(Ok(()));
        let document = match (opened, prompt_result) {
            (Ok(document), Ok(())) => document,
            (Err(error), Ok(())) => return Err(error),
            (Ok(_), Err(error)) => return Err(error),
            (Err(open_error), Err(prompt_error)) => {
                return Err(format!(
                    "{open_error}; Word PDF confirmation watcher also failed: {prompt_error}"
                ));
            }
        };
        self.document = Some(document);
        Ok(())
    }

    fn export_pdf(&self, destination: &Path) -> Result<(), String> {
        self.document()?.call_void(
            "ExportAsFixedFormat",
            vec![
                AutomationVariant::from_path(destination),
                AutomationVariant::from_i32(WORD_PDF_FORMAT),
            ],
        )
    }

    fn save_docx(&self, destination: &Path) -> Result<(), String> {
        self.document()?.call_void(
            "SaveAs2",
            vec![
                AutomationVariant::from_path(destination),
                AutomationVariant::from_i32(WORD_DOCX_FORMAT),
            ],
        )
    }

    fn application(&self) -> Result<&DispatchObject, String> {
        self.application
            .as_ref()
            .ok_or_else(|| "Word COM application has already closed".to_string())
    }

    fn document(&self) -> Result<&DispatchObject, String> {
        self.document
            .as_ref()
            .ok_or_else(|| "Word COM document is not open".to_string())
    }

    fn close(&mut self) -> Result<(), String> {
        let mut errors = Vec::new();
        if let Some(document) = self.document.take() {
            if let Err(error) =
                document.call_void("Close", vec![AutomationVariant::from_i32(WORD_DO_NOT_SAVE)])
            {
                errors.push(error);
            }
        }
        if let Some(application) = self.application.take() {
            if let Err(error) =
                application.call_void("Quit", vec![AutomationVariant::from_i32(WORD_DO_NOT_SAVE)])
            {
                errors.push(error);
            }
        }
        if errors.is_empty() {
            Ok(())
        } else {
            Err(errors.join("; "))
        }
    }
}

impl Drop for WordSession {
    fn drop(&mut self) {
        let _ = self.close();
    }
}

#[repr(transparent)]
struct AutomationVariant(VARIANT);

impl AutomationVariant {
    fn empty() -> Self {
        Self(VARIANT::default())
    }

    fn from_i32(value: i32) -> Self {
        Self::from_parts(VT_I4, VARIANT_0_0_0 { lVal: value })
    }

    fn from_bool(value: bool) -> Self {
        Self::from_parts(
            VT_BOOL,
            VARIANT_0_0_0 {
                boolVal: if value { VARIANT_TRUE } else { VARIANT_FALSE },
            },
        )
    }

    fn from_path(path: &Path) -> Self {
        let path = office_path_wide(path);
        Self::from_parts(
            VT_BSTR,
            VARIANT_0_0_0 {
                bstrVal: ManuallyDrop::new(BSTR::from_wide(&path)),
            },
        )
    }

    fn from_string(value: &str) -> Self {
        Self::from_parts(
            VT_BSTR,
            VARIANT_0_0_0 {
                bstrVal: ManuallyDrop::new(BSTR::from(value)),
            },
        )
    }

    fn from_parts(kind: VARENUM, value: VARIANT_0_0_0) -> Self {
        Self(VARIANT {
            Anonymous: VARIANT_0 {
                Anonymous: ManuallyDrop::new(VARIANT_0_0 {
                    vt: kind,
                    wReserved1: 0,
                    wReserved2: 0,
                    wReserved3: 0,
                    Anonymous: value,
                }),
            },
        })
    }

    fn as_mut_ptr(&mut self) -> *mut VARIANT {
        &mut self.0
    }

    fn kind(&self) -> VARENUM {
        unsafe { self.0.Anonymous.Anonymous.vt }
    }

    fn to_dispatch(&self, context: &str) -> Result<DispatchObject, String> {
        if self.kind() != VT_DISPATCH {
            return Err(format!(
                "Word COM {context} returned VARIANT type {} instead of IDispatch",
                self.kind().0
            ));
        }
        let dispatch = unsafe { &*self.0.Anonymous.Anonymous.Anonymous.pdispVal };
        dispatch
            .clone()
            .map(DispatchObject)
            .ok_or_else(|| format!("Word COM {context} returned a null IDispatch"))
    }

    fn to_i32(&self, context: &str) -> Result<i32, String> {
        if self.kind() != VT_I4 {
            return Err(format!(
                "Word COM {context} returned VARIANT type {} instead of i32",
                self.kind().0
            ));
        }
        Ok(unsafe { self.0.Anonymous.Anonymous.Anonymous.lVal })
    }

    fn to_string_value(&self, context: &str) -> Result<String, String> {
        if self.kind() != VT_BSTR {
            return Err(format!(
                "Word COM {context} returned VARIANT type {} instead of BSTR",
                self.kind().0
            ));
        }
        let value = unsafe { &self.0.Anonymous.Anonymous.Anonymous.bstrVal };
        Ok(value.to_string())
    }

    #[cfg(test)]
    fn as_i32(&self) -> Option<i32> {
        (self.kind() == VT_I4).then(|| unsafe { self.0.Anonymous.Anonymous.Anonymous.lVal })
    }
}

struct PdfConversionPrompt {
    stop: Arc<AtomicBool>,
    join: Option<JoinHandle<Result<(), String>>>,
}

impl PdfConversionPrompt {
    fn start(process_id: u32) -> Result<Self, String> {
        let stop = Arc::new(AtomicBool::new(false));
        let worker_stop = Arc::clone(&stop);
        let join = thread::Builder::new()
            .name("koi-word-pdf-confirmation".to_string())
            .spawn(move || {
                for _ in 0..1_200 {
                    if worker_stop.load(Ordering::Acquire) {
                        return Ok(());
                    }
                    if dismiss_pdf_conversion_prompt(process_id)? {
                        return Ok(());
                    }
                    thread::sleep(Duration::from_millis(50));
                }
                Ok(())
            })
            .map_err(|error| format!("cannot start Word PDF confirmation watcher: {error}"))?;
        Ok(Self {
            stop,
            join: Some(join),
        })
    }

    fn finish(mut self) -> Result<(), String> {
        self.stop.store(true, Ordering::Release);
        match self.join.take() {
            Some(join) => join
                .join()
                .map_err(|_| "Word PDF confirmation watcher panicked".to_string())?,
            None => Ok(()),
        }
    }
}

impl Drop for PdfConversionPrompt {
    fn drop(&mut self) {
        self.stop.store(true, Ordering::Release);
        if let Some(join) = self.join.take() {
            let _ = join.join();
        }
    }
}

struct PromptSearch {
    process_id: u32,
    dismissed: bool,
    error: Option<String>,
}

struct WindowText {
    value: String,
    ok_button: Option<HWND>,
}

fn dismiss_pdf_conversion_prompt(process_id: u32) -> Result<bool, String> {
    let mut search = PromptSearch {
        process_id,
        dismissed: false,
        error: None,
    };
    unsafe {
        EnumWindows(
            Some(find_pdf_conversion_prompt),
            LPARAM((&mut search as *mut PromptSearch) as isize),
        )
    }
    .map_err(|error| format!("cannot enumerate Word confirmation windows: {error}"))?;
    match search.error {
        Some(error) => Err(error),
        None => Ok(search.dismissed),
    }
}

unsafe extern "system" fn find_pdf_conversion_prompt(hwnd: HWND, state: LPARAM) -> BOOL {
    let search = unsafe { &mut *(state.0 as *mut PromptSearch) };
    if window_process_id(hwnd) != Some(search.process_id) {
        return BOOL(1);
    }
    let mut text = WindowText {
        value: window_text(hwnd),
        ok_button: None,
    };
    unsafe {
        let _ = EnumChildWindows(
            Some(hwnd),
            Some(collect_window_text),
            LPARAM((&mut text as *mut WindowText) as isize),
        );
    };
    if !is_pdf_conversion_prompt(&text.value) {
        return BOOL(1);
    }
    let Some(ok_button) = text.ok_button else {
        return BOOL(1);
    };
    const BM_CLICK: u32 = 0x00F5;
    let delivered = unsafe {
        SendMessageTimeoutW(
            ok_button,
            BM_CLICK,
            WPARAM(0),
            LPARAM(0),
            SMTO_ABORTIFHUNG | SMTO_ERRORONEXIT,
            1_000,
            None,
        )
    };
    if delivered.0 != 0 {
        search.dismissed = true;
        BOOL(0)
    } else {
        search.error =
            Some("Word PDF confirmation accepted no input before the safety timeout".to_string());
        BOOL(0)
    }
}

unsafe extern "system" fn collect_window_text(hwnd: HWND, state: LPARAM) -> BOOL {
    let text = unsafe { &mut *(state.0 as *mut WindowText) };
    let value = window_text(hwnd);
    if !value.is_empty() {
        text.value.push('\n');
        text.value.push_str(&value);
    }
    if is_prompt_accept_button(&value, unsafe { GetDlgCtrlID(hwnd) }, &window_class(hwnd)) {
        text.ok_button = Some(hwnd);
    }
    BOOL(1)
}

fn is_pdf_conversion_prompt(value: &str) -> bool {
    let lower = value.to_lowercase();
    let identifies_word_pdf = lower.contains("word") && lower.contains("pdf");
    let english_reflow =
        lower.contains("convert") && lower.contains("editable") && lower.contains("document");
    let chinese_reflow =
        value.contains("转换") && value.contains("可编辑") && value.contains("文档");
    identifies_word_pdf && (english_reflow || chinese_reflow)
}

fn is_prompt_accept_button(value: &str, control_id: i32, class_name: &str) -> bool {
    let lower = value.trim().to_lowercase();
    matches!(lower.as_str(), "ok" | "确定" | "确定(&o)" | "确认")
        || (control_id == 1 && class_name.eq_ignore_ascii_case("button"))
}

fn window_process_id(hwnd: HWND) -> Option<u32> {
    let mut process_id = 0_u32;
    let thread_id = unsafe { GetWindowThreadProcessId(hwnd, Some(&mut process_id)) };
    (thread_id != 0 && process_id != 0).then_some(process_id)
}

fn window_class(hwnd: HWND) -> String {
    let mut buffer = vec![0_u16; 256];
    let copied = unsafe { GetClassNameW(hwnd, &mut buffer) };
    if copied <= 0 {
        String::new()
    } else {
        String::from_utf16_lossy(&buffer[..copied as usize])
    }
}

fn word_process_ids() -> Result<HashSet<u32>, String> {
    let snapshot = unsafe { CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0) }
        .map_err(|error| format!("cannot enumerate Word processes: {error}"))?;
    let mut entry = PROCESSENTRY32W {
        dwSize: size_of::<PROCESSENTRY32W>() as u32,
        ..Default::default()
    };
    let mut result = HashSet::new();
    (|| {
        let first = unsafe { Process32FirstW(snapshot, &mut entry) };
        if first.is_err() {
            return;
        }
        loop {
            let length = entry
                .szExeFile
                .iter()
                .position(|value| *value == 0)
                .unwrap_or(entry.szExeFile.len());
            let name = String::from_utf16_lossy(&entry.szExeFile[..length]);
            if name.eq_ignore_ascii_case("WINWORD.EXE") {
                result.insert(entry.th32ProcessID);
            }
            if unsafe { Process32NextW(snapshot, &mut entry) }.is_err() {
                break;
            }
        }
    })();
    unsafe { CloseHandle(snapshot) }
        .map_err(|error| format!("cannot close Word process snapshot: {error}"))?;
    Ok(result)
}

fn wait_for_new_word_process(existing: &HashSet<u32>) -> Result<u32, String> {
    for _ in 0..200 {
        let current = word_process_ids()?;
        let mut new = current.difference(existing).copied();
        if let Some(pid) = new.next() {
            if new.next().is_none() {
                return Ok(pid);
            }
            return Err(
                "multiple new Word processes appeared; refusing to guess the confirmation owner"
                    .to_string(),
            );
        }
        thread::sleep(Duration::from_millis(25));
    }
    Err("no new Word process appeared for the COM conversion".to_string())
}

fn window_text(hwnd: HWND) -> String {
    let length = unsafe { GetWindowTextLengthW(hwnd) };
    if length <= 0 {
        return String::new();
    }
    let mut buffer = vec![0_u16; length as usize + 1];
    let copied = unsafe { GetWindowTextW(hwnd, &mut buffer) };
    if copied <= 0 {
        String::new()
    } else {
        String::from_utf16_lossy(&buffer[..copied as usize])
    }
}

impl Drop for AutomationVariant {
    fn drop(&mut self) {
        let _ = unsafe { VariantClear(&mut self.0) };
    }
}

#[derive(Default)]
struct ExceptionInfo(EXCEPINFO);

impl ExceptionInfo {
    fn as_mut_ptr(&mut self) -> *mut EXCEPINFO {
        &mut self.0
    }

    fn describe(&mut self) -> String {
        if let Some(fill) = self.0.pfnDeferredFillIn {
            let _ = unsafe { fill(&mut self.0) };
            self.0.pfnDeferredFillIn = None;
        }
        let source = self.0.bstrSource.to_string();
        let description = self.0.bstrDescription.to_string();
        match (source.is_empty(), description.is_empty()) {
            (true, true) => String::new(),
            (true, false) => description,
            (false, true) => source,
            (false, false) => format!("{source}: {description}"),
        }
    }
}

impl Drop for ExceptionInfo {
    fn drop(&mut self) {
        unsafe {
            ManuallyDrop::drop(&mut self.0.bstrSource);
            ManuallyDrop::drop(&mut self.0.bstrDescription);
            ManuallyDrop::drop(&mut self.0.bstrHelpFile);
        }
    }
}

struct WideName(Vec<u16>);

impl WideName {
    fn new(value: &str) -> Self {
        Self(value.encode_utf16().chain(Some(0)).collect())
    }

    fn as_pcwstr(&self) -> PCWSTR {
        PCWSTR(self.0.as_ptr())
    }
}

fn office_path_wide(path: &Path) -> Vec<u16> {
    use std::os::windows::ffi::OsStrExt;

    const DEVICE_PREFIX: &[u16] = &[b'\\' as u16, b'\\' as u16, b'?' as u16, b'\\' as u16];
    const UNC_PREFIX: &[u16] = &[
        b'\\' as u16,
        b'\\' as u16,
        b'?' as u16,
        b'\\' as u16,
        b'U' as u16,
        b'N' as u16,
        b'C' as u16,
        b'\\' as u16,
    ];
    let wide: Vec<u16> = path.as_os_str().encode_wide().collect();
    if wide.starts_with(UNC_PREFIX) {
        let mut normalized = vec![b'\\' as u16, b'\\' as u16];
        normalized.extend_from_slice(&wide[UNC_PREFIX.len()..]);
        normalized
    } else if wide.starts_with(DEVICE_PREFIX) {
        wide[DEVICE_PREFIX.len()..].to_vec()
    } else {
        wide
    }
}

fn reverse_for_dispatch<T>(mut arguments: Vec<T>) -> Vec<T> {
    arguments.reverse();
    arguments
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn dispatch_arguments_are_reversed_for_automation() {
        let values = reverse_for_dispatch(vec![
            AutomationVariant::from_i32(1),
            AutomationVariant::from_i32(2),
            AutomationVariant::from_i32(3),
        ]);
        assert_eq!(
            values
                .iter()
                .map(AutomationVariant::as_i32)
                .collect::<Vec<_>>(),
            vec![Some(3), Some(2), Some(1)]
        );
    }

    #[test]
    fn office_paths_drop_only_windows_device_prefixes() {
        use std::os::windows::ffi::OsStringExt;
        use std::path::PathBuf;

        let local = PathBuf::from(r"\\?\C:\input\report.docx");
        let unc = PathBuf::from(r"\\?\UNC\server\share\report.docx");
        assert_eq!(
            String::from_utf16(&office_path_wide(&local)).unwrap(),
            r"C:\input\report.docx"
        );
        assert_eq!(
            String::from_utf16(&office_path_wide(&unc)).unwrap(),
            r"\\server\share\report.docx"
        );

        let invalid = PathBuf::from(std::ffi::OsString::from_wide(&[
            b'C' as u16,
            b':' as u16,
            b'\\' as u16,
            0xD800,
        ]));
        assert_eq!(office_path_wide(&invalid).last(), Some(&0xD800));
    }

    #[test]
    fn pdf_conversion_prompt_requires_word_pdf_and_reflow_language() {
        let english =
            "Microsoft Word\nWord will now convert your PDF to an editable Word document.\nOK";
        let chinese = "Microsoft Word\nWord 现在将把 PDF 转换为可编辑的 Word 文档。\n确定";
        assert!(is_pdf_conversion_prompt(english));
        assert!(is_pdf_conversion_prompt(chinese));

        assert!(!is_pdf_conversion_prompt(
            "Microsoft Word\nSave this document as a PDF?\nOK"
        ));
        assert!(!is_pdf_conversion_prompt(
            "PDF conversion produced an editable document\nOK"
        ));
        assert!(!is_pdf_conversion_prompt(
            "Microsoft Word\nThis document is editable\nOK"
        ));
    }

    #[test]
    fn prompt_accept_button_rejects_unrelated_controls() {
        assert!(is_prompt_accept_button("OK", 0, "NetUIHWND"));
        assert!(is_prompt_accept_button("确定", 0, "NetUIHWND"));
        assert!(is_prompt_accept_button("确定(&O)", 0, "NetUIHWND"));
        assert!(is_prompt_accept_button("", 1, "Button"));

        assert!(!is_prompt_accept_button("Cancel", 2, "Button"));
        assert!(!is_prompt_accept_button("Don't show again", 1, "NetUIHWND"));
        assert!(!is_prompt_accept_button("", 1, "Static"));
    }
}
