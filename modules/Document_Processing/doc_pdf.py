import argparse
import sys
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

# 添加项目根目录到Python路径
current_dir = Path(__file__).resolve().parent
project_root = current_dir.parent.parent  # 回到项目根目录
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# COM路径长度阈值（Windows路径长度限制）
COM_PATH_THRESHOLD = 260

def wait_for_file_release(file_path, max_wait=10):
    """等待文件被释放"""
    import time
    for i in range(max_wait):
        try:
            with open(file_path, 'rb') as f:
                pass
            return True
        except (PermissionError, OSError):
            if i < max_wait - 1:
                time.sleep(1)
            else:
                return False
    return False

# 导入COM错误处理工具
try:
    from modules.utils.com_error_handler import (
        robust_word_operation,
        safe_open_document,
        create_word_app_safely,
        cleanup_word_processes,
        check_word_app_connection,
    )
    COM_UTILS_AVAILABLE = True
except ImportError:
    try:
        # 尝试相对导入
        from ..utils.com_error_handler import (
            robust_word_operation,
            safe_open_document,
            create_word_app_safely,
            cleanup_word_processes,
            check_word_app_connection,
        )
        COM_UTILS_AVAILABLE = True
    except ImportError:
        try:
            # 尝试从当前目录的绝对路径导入
            import os
            current_dir = os.path.dirname(os.path.abspath(__file__))
            utils_dir = os.path.normpath(os.path.join(current_dir, '..', 'utils'))
            if utils_dir not in sys.path:
                sys.path.insert(0, utils_dir)
            # 使用绝对导入路径
            from modules.utils.com_error_handler import (
                robust_word_operation,
                safe_open_document,
                create_word_app_safely,
                cleanup_word_processes,
                check_word_app_connection,
            )
            COM_UTILS_AVAILABLE = True
        except ImportError:
            print("警告: COM错误处理工具导入失败，将使用原始COM操作")
            COM_UTILS_AVAILABLE = False


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


def convert_with_word_com(
    files: List[Tuple[Path, Path]],
    overwrite: bool,
) -> Tuple[int, int, List[Tuple[Path, str]]]:
    """
    Convert Word files to PDF using Microsoft Word COM automation.

    Returns: (num_converted, num_skipped, failures)
    failures is a list of (input_file, reason)
    """
    try:
        import win32com.client  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(
            "未安装 pywin32（win32com）。请先安装：pip install pywin32"
        ) from exc

    word = None
    num_converted = 0
    num_skipped = 0
    failures: List[Tuple[Path, str]] = []

    try:
        # Clear the corrupted cache first
        try:
            import shutil
            import win32com.client.gencache  # type: ignore
            
            # Clear the corrupted cache
            cache_dir = win32com.client.gencache.GetGeneratePath()  # type: ignore[attr-defined]
            if cache_dir and Path(cache_dir).exists():
                print(f"清理损坏的 COM 缓存: {cache_dir}")
                shutil.rmtree(cache_dir, ignore_errors=True)
        except Exception as e:
            print(f"清理缓存时出现错误（可忽略）: {e}")
        
        # 使用增强的COM错误处理初始化Word应用程序
        if COM_UTILS_AVAILABLE:
            try:
                word = create_word_app_safely(visible=False, display_alerts=False, verbose=True)
            except Exception as e:
                raise Exception(f"无法初始化Word应用程序: {str(e)}")
        else:
            # 回退到原始方法
            word_init_retries = 3
            word = None
            for init_attempt in range(word_init_retries):
                try:
                    word = win32com.client.dynamic.Dispatch("Word.Application")  # type: ignore[attr-defined]
                    word.Visible = False
                    # 0 = wdAlertsNone
                    word.DisplayAlerts = 0
                    break
                except Exception as init_err:
                    if init_attempt == word_init_retries - 1:
                        raise Exception(f"无法初始化Word应用程序（尝试{word_init_retries}次后失败）: {str(init_err)}")
                    print(f"  警告: Word初始化失败（尝试 {init_attempt + 1}/{word_init_retries}）: {str(init_err)[:100]}")
                    
                    # 清理可能的残留进程
                    try:
                        import subprocess
                        subprocess.run(['taskkill', '/f', '/im', 'winword.exe'], 
                                     capture_output=True, check=False)
                        import time
                        time.sleep(2)
                    except Exception:
                        pass

        # Prefer ExportAsFixedFormat for fidelity, fallback to SaveAs2 if needed
        for src_path, dst_path in files:
            try:
                if dst_path.exists() and not overwrite:
                    num_skipped += 1
                    continue

                # 在每个文件转换前检查Word应用程序连接状态
                if COM_UTILS_AVAILABLE:
                    if not check_word_app_connection(word, verbose=False):
                        print(f"  重新连接: Word连接失效，重新创建应用程序...")
                        try:
                            if word is not None:
                                word.Quit(SaveChanges=0)
                        except:
                            pass
                        cleanup_word_processes()
                        word = create_word_app_safely(visible=False, display_alerts=False, verbose=True)

                ensure_parent_dir(dst_path)

                temp_cleanup = None
                temp_src_path = str(src_path)
                temp_dst_path = str(dst_path)
                revert_output_from_temp = False
                
                # 检查源文件路径长度，如果过长则跳过COM操作
                src_path_length = len(str(src_path))
                if src_path_length > COM_PATH_THRESHOLD:
                    print(f"  警告: 源文件路径过长（{src_path_length}字符），跳过转换: {Path(src_path).name}")
                    failures.append((src_path, f"文件路径过长（{src_path_length}字符），超过COM操作安全阈值（{COM_PATH_THRESHOLD}字符）"))
                    continue
                
                # 直接使用源文件路径
                temp_src_path = str(src_path)
                temp_cleanup = None
                
                # 额外的文件名安全检查
                if not Path(temp_src_path).exists():
                    raise FileNotFoundError(f"源文件不存在: {temp_src_path}")
                
                # 检查文件是否被占用
                try:
                    with open(temp_src_path, 'rb') as f:
                        pass  # 只是测试能否打开
                except PermissionError:
                    print(f"  警告: 文件被占用，等待释放: {Path(temp_src_path).name}")
                    wait_for_file_release(temp_src_path, max_wait=10)
                except Exception as e:
                    print(f"  警告: 文件访问检查失败: {e}")
                    # 继续尝试，可能是权限问题但COM仍能访问

                if len(temp_dst_path) > COM_PATH_THRESHOLD:
                    temp_dir = Path(tempfile.gettempdir()) / f"report_pdf_{uuid.uuid4().hex}"
                    temp_dir.mkdir(parents=True, exist_ok=True)
                    temp_dst_path = str(temp_dir / Path(temp_dst_path).name)
                    revert_output_from_temp = True
                    print(f"PDF转换: 输出路径过长（{len(str(dst_path))}字符），改用临时路径 {temp_dst_path}")

                # 确保 word 应用程序已初始化
                if word is None:
                    raise Exception("Word应用程序未正确初始化")
                
                # 使用增强的COM错误处理打开文档
                doc = None
                if COM_UTILS_AVAILABLE:
                    try:
                        doc = safe_open_document(word, temp_src_path, verbose=True)
                    except Exception as e:
                        # 如果打开失败，尝试重新创建Word应用程序
                        print(f"  警告: 文档打开失败，尝试重新创建Word应用程序: {str(e)[:100]}")
                        try:
                            if word is not None:
                                word.Quit(SaveChanges=0)
                        except:
                            pass
                        cleanup_word_processes()
                        word = create_word_app_safely(visible=False, display_alerts=False, verbose=True)
                        
                        # 重新尝试打开文档
                        try:
                            doc = safe_open_document(word, temp_src_path, verbose=True)
                        except Exception as retry_e:
                            raise Exception(f"重新创建Word后仍无法打开文档: {str(retry_e)}")
                else:
                    # 回退到原始方法
                    max_retries = 3
                    for attempt in range(max_retries):
                        try:
                            # 尝试不同的打开参数组合
                            if attempt == 0:
                                # 第一次尝试：标准参数
                                doc = word.Documents.Open(temp_src_path, ReadOnly=True, Visible=False)  # type: ignore
                            elif attempt == 1:
                                # 第二次尝试：添加更多参数
                                doc = word.Documents.Open(temp_src_path, ReadOnly=True, Visible=False,  # type: ignore
                                                        ConfirmConversions=False, AddToRecentFiles=False)
                            else:
                                # 第三次尝试：最小参数
                                doc = word.Documents.Open(temp_src_path)  # type: ignore
                            break
                        except Exception as e:
                            if attempt == max_retries - 1:
                                raise Exception(f"无法打开文档（尝试{max_retries}次后失败）: {str(e)}")
                            print(f"  警告: 打开文档失败（尝试 {attempt + 1}/{max_retries}）: {str(e)[:100]}")
                            
                            # 在重试前清理可能的COM缓存问题
                            try:
                                import gc
                                gc.collect()
                                import time
                                time.sleep(1 + attempt)  # 递增等待时间
                            except Exception:
                                pass
                
                try:
                    # 17 = wdExportFormatPDF
                    try:
                        # 添加超时机制防止卡住
                        import threading
                        import time
                        
                        export_success = False
                        export_error = None
                        
                        def export_task():
                            nonlocal export_success, export_error
                            try:
                                doc.ExportAsFixedFormat(  # type: ignore
                                    OutputFileName=temp_dst_path,
                                    ExportFormat=17,
                                )
                                export_success = True
                            except Exception as e:
                                export_error = e
                        
                        # 启动导出任务
                        export_thread = threading.Thread(target=export_task)
                        export_thread.daemon = True
                        export_thread.start()
                        
                        # 等待最多60秒
                        export_thread.join(timeout=60)
                        
                        if export_thread.is_alive():
                            # 超时，尝试强制终止
                            print(f"  警告: PDF导出超时，尝试SaveAs2方法")
                            try:
                                doc.SaveAs2(temp_dst_path, FileFormat=17)  # type: ignore
                            except Exception as saveas_err:
                                raise Exception(f"PDF导出超时且SaveAs2也失败: {str(saveas_err)}")
                        elif not export_success and export_error:
                            # ExportAsFixedFormat失败，尝试SaveAs2
                            print(f"  警告: ExportAsFixedFormat失败，尝试SaveAs2: {str(export_error)[:100]}")
                            doc.SaveAs2(temp_dst_path, FileFormat=17)  # type: ignore
                        elif not export_success:
                            raise Exception("PDF导出失败，原因未知")
                            
                    except Exception as export_err:
                        # Fallback: SaveAs2 with PDF format
                        # 17 = wdFormatPDF
                        print(f"  警告: ExportAsFixedFormat失败，尝试SaveAs2: {str(export_err)[:100]}")
                        doc.SaveAs2(temp_dst_path, FileFormat=17)  # type: ignore
                finally:
                    if doc is not None:
                        # 0 = do not save changes
                        doc.Close(SaveChanges=0)  # type: ignore

                # temp_cleanup已移除，无需清理

                if revert_output_from_temp:
                    try:
                        wait_for_file_release(temp_dst_path, max_wait=15)
                        ensure_parent_dir(dst_path)
                        shutil.copy2(temp_dst_path, dst_path)
                    finally:
                        try:
                            wait_for_file_release(temp_dst_path, max_wait=5)
                        except Exception:
                            pass
                        try:
                            Path(temp_dst_path).unlink(missing_ok=True)
                        except Exception:
                            pass
                        try:
                            temp_dir.rmdir()
                        except Exception:
                            shutil.rmtree(temp_dir, ignore_errors=True)

                num_converted += 1
            except Exception as e:
                failures.append((src_path, str(e)))
    finally:
        # 使用增强的COM清理
        if COM_UTILS_AVAILABLE:
            try:
                if word is not None:
                    word.Quit(SaveChanges=0)
            except:
                pass
            cleanup_word_processes()
        else:
            # 回退到原始清理方法
            if word is not None:
                # 0 = do not save normal template
                word.Quit(SaveChanges=0)

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



