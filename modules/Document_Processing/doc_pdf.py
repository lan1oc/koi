import argparse
import sys
import shutil
import tempfile
import uuid
import subprocess
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

# 添加项目根目录到Python路径
current_dir = Path(__file__).resolve().parent
project_root = current_dir.parent.parent  # 回到项目根目录
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

def list_document_files(root_dir: Path, recursive: bool, file_type: str = "word", skip_keywords: Optional[List[str]] = None) -> List[Path]:
    """
    Return a list of document files under root_dir.
    Excludes temporary files that start with '~$'.
    file_type: "word" for Word files, "pdf" for PDF files
    """
    if file_type == "word":
        patterns = ["*.doc", "*.docx"]
    elif file_type == "pdf":
        patterns = ["*.pdf"]
    else:
        raise ValueError(f"Unsupported file type: {file_type}")
    files: List[Path] = []
    def should_include(path: Path) -> bool:
        if path.name.startswith("~$"):
            return False
        # Skip files whose filename contains any of the skip keywords
        if skip_keywords:
            name = path.name
            for kw in skip_keywords:
                if kw and kw in name:
                    return False
        return True

    if recursive:
        for pattern in patterns:
            files.extend(p for p in root_dir.rglob(pattern) if should_include(p))
    else:
        for pattern in patterns:
            files.extend(p for p in root_dir.glob(pattern) if should_include(p))
    # Deduplicate and sort for stable order
    unique_sorted = sorted({p.resolve() for p in files})
    return unique_sorted


def compute_output_path(input_file: Path, input_root: Path, output_root: Optional[Path], conversion_type: str = "word_to_pdf") -> Path:
    """
    Compute the output file path for conversion.
    If output_root is provided, preserve the relative structure under it.
    Otherwise, place the output file next to the source file.
    conversion_type: "word_to_pdf" or "pdf_to_word"
    """
    if conversion_type == "word_to_pdf":
        output_name = input_file.with_suffix(".pdf").name
        default_output = input_file.with_suffix(".pdf")
    elif conversion_type == "pdf_to_word":
        output_name = input_file.with_suffix(".docx").name
        default_output = input_file.with_suffix(".docx")
    else:
        raise ValueError(f"Unsupported conversion type: {conversion_type}")
    
    if output_root is None:
        return default_output
    rel = input_file.parent.relative_to(input_root)
    return (output_root / rel / output_name)


def ensure_parent_dir(path: Path) -> None:
    """Create parent directory for path if missing."""
    path.parent.mkdir(parents=True, exist_ok=True)


def _find_soffice_executable() -> Optional[str]:
    """Find LibreOffice executable across platforms."""
    for candidate in ("soffice", "libreoffice"):
        found = shutil.which(candidate)
        if found:
            return found

    mac_default = Path("/Applications/LibreOffice.app/Contents/MacOS/soffice")
    if mac_default.exists():
        return str(mac_default)

    return None


def convert_with_libreoffice(
    files: List[Tuple[Path, Path]],
    overwrite: bool,
) -> Tuple[int, int, List[Tuple[Path, str]]]:
    """
    Convert Word files to PDF using LibreOffice CLI.
    Returns: (num_converted, num_skipped, failures)
    """
    soffice = _find_soffice_executable()
    if not soffice:
        raise RuntimeError(
            "未找到 LibreOffice/soffice。请安装 LibreOffice 并确保 soffice 在 PATH 中。"
        )

    num_converted = 0
    num_skipped = 0
    failures: List[Tuple[Path, str]] = []

    for src_path, dst_path in files:
        try:
            if dst_path.exists() and not overwrite:
                num_skipped += 1
                continue

            ensure_parent_dir(dst_path)
            tmp_out_dir = Path(tempfile.gettempdir()) / f"soffice_pdf_{uuid.uuid4().hex}"
            tmp_out_dir.mkdir(parents=True, exist_ok=True)

            try:
                cmd = [
                    soffice,
                    "--headless",
                    "--convert-to",
                    "pdf",
                    "--outdir",
                    str(tmp_out_dir),
                    str(src_path),
                ]
                proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
                converted_tmp = tmp_out_dir / f"{src_path.stem}.pdf"
                if proc.returncode != 0 or not converted_tmp.exists():
                    stderr = (proc.stderr or "").strip()[:200]
                    stdout = (proc.stdout or "").strip()[:200]
                    detail = stderr or stdout or f"退出码 {proc.returncode}"
                    failures.append((src_path, f"LibreOffice 转换失败: {detail}"))
                    continue

                shutil.copy2(converted_tmp, dst_path)
                num_converted += 1
            finally:
                shutil.rmtree(tmp_out_dir, ignore_errors=True)
        except Exception as e:
            failures.append((src_path, str(e)))

    return num_converted, num_skipped, failures


def convert_with_word_com(
    files: List[Tuple[Path, Path]],
    overwrite: bool,
) -> Tuple[int, int, List[Tuple[Path, str]]]:
    """
    Convert Word files to PDF using Microsoft Word COM automation.
    """
    try:
        import pythoncom  # type: ignore
        import win32com.client as win32  # type: ignore
    except Exception as exc:
        raise RuntimeError("未安装 pywin32（win32com），无法使用 Word COM 转换") from exc

    num_converted = 0
    num_skipped = 0
    failures: List[Tuple[Path, str]] = []
    com_initialized = False

    try:
        pythoncom.CoInitialize()
        com_initialized = True
    except Exception as exc:
        failures.extend((src_path, f"Word COM 初始化失败: {exc}") for src_path, _ in files)
        return num_converted, num_skipped, failures

    try:
        for src_path, dst_path in files:
            word = None
            doc = None
            try:
                if dst_path.exists() and not overwrite:
                    num_skipped += 1
                    continue

                ensure_parent_dir(dst_path)

                word = win32.Dispatch("Word.Application")
                word.Visible = False
                word.DisplayAlerts = 0

                doc = word.Documents.Open(
                    str(src_path),
                    ReadOnly=True,
                    Visible=False,
                    ConfirmConversions=False,
                    AddToRecentFiles=False,
                )
                # 17 = wdExportFormatPDF
                doc.ExportAsFixedFormat(OutputFileName=str(dst_path), ExportFormat=17)
                num_converted += 1
            except Exception as e:
                failures.append((src_path, str(e)))
            finally:
                try:
                    if doc is not None:
                        doc.Close(SaveChanges=0)
                except Exception:
                    pass
                try:
                    if word is not None:
                        word.Quit(SaveChanges=0)
                except Exception:
                    pass
    finally:
        if com_initialized:
            try:
                pythoncom.CoUninitialize()
            except Exception:
                pass

    return num_converted, num_skipped, failures


def convert_pdf_to_word(
    files: List[Tuple[Path, Path]],
    overwrite: bool,
) -> Tuple[int, int, List[Tuple[Path, str]]]:
    """
    Convert PDF files to Word using pdf2docx library.

    Returns: (num_converted, num_skipped, failures)
    failures is a list of (input_file, reason)
    """
    try:
        from pdf2docx import Converter
    except ImportError as exc:
        raise RuntimeError(
            "未安装 pdf2docx。请先安装：pip install pdf2docx"
        ) from exc

    num_converted = 0
    num_skipped = 0
    failures: List[Tuple[Path, str]] = []

    for src_path, dst_path in files:
        try:
            if dst_path.exists() and not overwrite:
                print(f"跳过已存在文件: {dst_path}")
                num_skipped += 1
                continue

            ensure_parent_dir(dst_path)

            print(f"正在转换: {src_path.name} -> {dst_path.name}")
            
            # 执行PDF转Word
            cv = Converter(str(src_path))
            cv.convert(str(dst_path))
            cv.close()
            
            print(f"转换完成: {src_path.name}")
            num_converted += 1
            
        except Exception as e:
            failures.append((src_path, str(e)))
            print(f"转换失败 {src_path.name}: {str(e)}")

    return num_converted, num_skipped, failures


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "文档格式转换工具：支持 Word ↔ PDF 双向转换。"
        )
    )
    parser.add_argument(
        "--mode",
        choices=["word_to_pdf", "pdf_to_word"],
        default="word_to_pdf",
        help="转换模式（默认：word_to_pdf）",
    )
    parser.add_argument(
        "input_path",
        nargs="?",
        default=str(Path.cwd()),
        help="输入目录或单个文件路径（默认：当前目录）",
    )
    parser.add_argument(
        "--output-dir",
        dest="output_dir",
        default=None,
        help="输出根目录（默认：与源文件同目录）。会保留目录结构。",
    )
    parser.add_argument(
        "--no-recursive",
        dest="recursive",
        action="store_false",
        help="不递归子目录（默认：递归）",
    )
    parser.add_argument(
        "--no-overwrite",
        dest="overwrite",
        action="store_false",
        default=True,
        help="若目标 PDF 已存在则跳过（默认：覆盖）",
    )
    parser.add_argument(
        "--quiet",
        dest="verbose",
        action="store_false",
        default=True,
        help="不显示详细转换日志（默认：显示）",
    )
    parser.add_argument(
        "--no-skip-template",
        dest="no_skip_template",
        action="store_true",
        help="不跳过包含'漏洞隐患处置文件模板'的文件（默认：跳过）",
    )
    parser.add_argument(
        "--skip-keyword",
        dest="skip_keywords",
        action="append",
        default=None,
        help="额外需要跳过的文件名关键字，可重复使用该参数",
    )
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    input_path = Path(args.input_path).resolve()
    output_root = Path(args.output_dir).resolve() if args.output_dir else None
    conversion_mode = args.mode

    if not input_path.exists():
        print(f"输入路径不存在: {input_path}")
        return 2

    # Build skip keyword list
    default_keywords: List[str] = [] if args.no_skip_template else ["漏洞隐患处置文件模板", "app整改模板", "处置文件模板"]
    if args.skip_keywords:
        default_keywords.extend(args.skip_keywords)

    # Determine file type and expected extensions based on conversion mode
    if conversion_mode == "word_to_pdf":
        file_type = "word"
        expected_extensions = ['.doc', '.docx']
        file_description = "Word文档"
    elif conversion_mode == "pdf_to_word":
        file_type = "pdf"
        expected_extensions = ['.pdf']
        file_description = "PDF文件"
    else:
        print(f"不支持的转换模式: {conversion_mode}")
        return 2

    # Check if input is a single file or directory
    if input_path.is_file():
        # Single file mode
        if input_path.suffix.lower() not in expected_extensions:
            print(f"输入文件不是{file_description}: {input_path}")
            return 2
        
        # Check if file should be skipped
        should_skip = False
        if default_keywords:
            for kw in default_keywords:
                if kw and kw in input_path.name:
                    should_skip = True
                    break
        
        if should_skip:
            print(f"文件被跳过（包含关键字）: {input_path}")
            return 0
        
        input_files = [input_path]
        input_root = input_path.parent
    else:
        # Directory mode
        if not input_path.is_dir():
            print(f"输入路径既不是文件也不是目录: {input_path}")
            return 2
        
        input_root = input_path
        input_files = list_document_files(input_root, recursive=args.recursive, file_type=file_type, skip_keywords=default_keywords)
        if not input_files:
            extensions_str = "/".join(expected_extensions)
            print(f"未找到任何 {extensions_str} 文件。")
            return 0

    file_map: List[Tuple[Path, Path]] = []
    for src in input_files:
        dst = compute_output_path(src, input_root, output_root, conversion_mode)
        file_map.append((src, dst))

    if args.verbose:
        print(f"待转换文件数: {len(file_map)}")
        if output_root:
            print(f"输出根目录: {output_root}")

    try:
        if conversion_mode == "word_to_pdf":
            converted, skipped, failures = convert_with_word_com(file_map, overwrite=args.overwrite)
        elif conversion_mode == "pdf_to_word":
            converted, skipped, failures = convert_pdf_to_word(file_map, overwrite=args.overwrite)
        else:
            print(f"不支持的转换模式: {conversion_mode}")
            return 2
    except RuntimeError as e:
        print(str(e))
        return 3

    if args.verbose:
        for src, reason in failures:
            print(f"失败: {src} -> {reason}")

    print(
        f"转换完成：成功 {converted}，跳过 {skipped}，失败 {len(failures)}"
    )
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())



