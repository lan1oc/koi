import argparse
import sys
import json
from pathlib import Path
from typing import List, Tuple, Dict


def parse_page_ranges(ranges_str: str, total_pages: int) -> List[int]:
    """
    Parse a string like "2-6,9,11-12" into a sorted unique list of 1-based page numbers.
    Validates against total_pages and raises ValueError on invalid input.
    """
    if not ranges_str:
        raise ValueError("请输入页码范围，例如: 2-6 或 2-6,9,11-12")

    pages_set = set()
    parts = [p.strip() for p in ranges_str.split(',') if p.strip()]
    if not parts:
        raise ValueError("页码范围格式不正确")

    def add_page(page_num: int) -> None:
        if page_num < 1 or page_num > total_pages:
            raise ValueError(f"页码超出范围: {page_num}，总页数: {total_pages}")
        pages_set.add(page_num)

    for part in parts:
        if '-' in part:
            start_str, end_str = [s.strip() for s in part.split('-', 1)]
            if not start_str.isdigit() or not end_str.isdigit():
                raise ValueError(f"范围格式错误: {part}")
            start = int(start_str)
            end = int(end_str)
            if start > end:
                raise ValueError(f"范围起止顺序错误: {part}")
            for p in range(start, end + 1):
                add_page(p)
        else:
            if not part.isdigit():
                raise ValueError(f"页码格式错误: {part}")
            add_page(int(part))

    return sorted(pages_set)


def extract_pages(input_pdf: Path, output_pdf: Path, page_numbers_1_based: List[int]) -> Tuple[int, int]:
    """
    Extract specified 1-based pages from input_pdf and write to output_pdf.
    Returns (extracted_count, total_pages)
    """
    try:
        from pypdf import PdfReader, PdfWriter  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("未安装 pypdf，请先安装：pip install pypdf") from exc

    print(f"[DEBUG] 开始读取PDF: {input_pdf}")
    reader = PdfReader(str(input_pdf))
    total_pages = len(reader.pages)
    print(f"[DEBUG] PDF共 {total_pages} 页")

    writer = PdfWriter()
    for page_num in page_numbers_1_based:
        print(f"[DEBUG] 添加第 {page_num} 页")
        # convert to 0-based index
        writer.add_page(reader.pages[page_num - 1])

    print(f"[DEBUG] 准备写入: {output_pdf}")
    output_pdf.parent.mkdir(parents=True, exist_ok=True)
    with output_pdf.open("wb") as f:
        writer.write(f)
    
    # 检查输出文件大小
    if output_pdf.exists():
        file_size = output_pdf.stat().st_size
        print(f"[DEBUG] 输出文件大小: {file_size} bytes")
    else:
        print(f"[DEBUG] 警告: 输出文件不存在!")

    return len(page_numbers_1_based), total_pages


def merge_pages_from_multiple_pdfs(page_selections: List[Dict], output_pdf: Path) -> Tuple[int, int]:
    """
    从多个PDF文件中按选择顺序合并页面
    
    排序规则：
    - 如果选择的页面都来自同一个文件，按照文件中页面的顺序排列
    - 如果来自不同文件，按照用户选择的顺序排列
    
    Args:
        page_selections: 页面选择列表，每个元素包含:
            {
                'file_path': str,  # PDF文件路径
                'page_num': int,   # 页码（1基）
                'order': int       # 选择顺序（用于排序）
            }
        output_pdf: 输出PDF文件路径
    
    Returns:
        (合并的页面数, 总文件数)
    """
    try:
        from pypdf import PdfReader, PdfWriter  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("未安装 pypdf，请先安装：pip install pypdf") from exc
    
    if not page_selections:
        raise ValueError("没有选择任何页面")
    
    # 检查是否所有页面来自同一个文件
    unique_files = set(sel['file_path'] for sel in page_selections)
    
    if len(unique_files) == 1:
        # 所有页面来自同一文件，按文件内页码排序
        sorted_selections = sorted(page_selections, key=lambda x: x['page_num'])
    else:
        # 来自不同文件，按用户选择的顺序排序
        sorted_selections = sorted(page_selections, key=lambda x: x['order'])
    
    # 合并页面
    writer = PdfWriter()
    processed_files: Dict[str, PdfReader] = {}
    
    try:
        for selection in sorted_selections:
            file_path = selection['file_path']
            page_num = selection['page_num']
            
            # 打开PDF文件（如果还没打开）
            if file_path not in processed_files:
                reader = PdfReader(str(file_path))
                processed_files[file_path] = reader
            
            reader = processed_files[file_path]
            
            # 验证页码
            if page_num < 1 or page_num > len(reader.pages):
                raise ValueError(f"文件 {Path(file_path).name} 的页码 {page_num} 超出范围（总页数: {len(reader.pages)}）")
            
            # 添加页面（转换为0基索引）
            writer.add_page(reader.pages[page_num - 1])
        
        # 写入输出文件
        output_pdf.parent.mkdir(parents=True, exist_ok=True)
        with output_pdf.open("wb") as f:
            writer.write(f)
        
        return len(sorted_selections), len(processed_files)
    
    finally:
        # 关闭所有打开的PDF文件
        for reader in processed_files.values():
            try:
                reader.stream.close()
            except Exception:
                pass


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="从PDF中按页码范围提取页面并生成新PDF")
    parser.add_argument("input", help="输入PDF文件路径")
    parser.add_argument("ranges", help="页码范围（1基），例如: 2-6 或 2-6,9,11-12")
    parser.add_argument(
        "-o",
        "--output",
        dest="output",
        default=None,
        help="输出PDF文件路径（默认：在源文件名后添加 _extract_范围）",
    )
    return parser.parse_args(argv)


def build_default_output_path(input_path: Path, ranges_str: str) -> Path:
    safe_ranges = ranges_str.replace(" ", "").replace(",", "_")
    return input_path.with_name(f"{input_path.stem}_extract_{safe_ranges}{input_path.suffix}")


def main(argv: List[str]) -> int:
    args = parse_args(argv)
    input_path = Path(args.input).resolve()
    if not input_path.exists() or input_path.suffix.lower() != ".pdf":
        print(f"输入文件无效或不是PDF: {input_path}")
        return 2

    try:
        from pypdf import PdfReader  # type: ignore
    except Exception:
        print("未安装 pypdf，请先执行: pip install pypdf")
        return 3

    # Get total pages for validation
    total_pages = len(PdfReader(str(input_path)).pages)
    try:
        pages = parse_page_ranges(args.ranges, total_pages)
    except ValueError as e:
        print(str(e))
        return 4

    output_path = Path(args.output).resolve() if args.output else build_default_output_path(input_path, args.ranges)

    try:
        extracted, total = extract_pages(input_path, output_path, pages)
        print(f"已从 {input_path.name} 提取 {extracted}/{total} 页 -> {output_path}")
        return 0
    except RuntimeError as e:
        print(str(e))
        return 3
    except Exception as e:
        print(f"提取失败: {e}")
        return 1


def merge_main(argv: List[str]) -> int:
    """
    多PDF合并模式的主函数
    接受JSON格式的页面选择列表
    """
    parser = argparse.ArgumentParser(description="从多个PDF中按选择顺序合并页面")
    parser.add_argument("--selections", required=True, help="JSON格式的页面选择列表")
    parser.add_argument("-o", "--output", required=True, help="输出PDF文件路径")
    
    args = parser.parse_args(argv)
    
    try:
        from pypdf import PdfReader  # type: ignore
    except Exception:
        print("未安装 pypdf，请先执行: pip install pypdf")
        return 3
    
    # 解析页面选择
    try:
        page_selections = json.loads(args.selections)
    except json.JSONDecodeError as e:
        print(f"JSON解析失败: {e}")
        return 4
    
    if not isinstance(page_selections, list) or not page_selections:
        print("页面选择列表格式错误")
        return 4
    
    # 验证文件存在
    for selection in page_selections:
        file_path = Path(selection.get('file_path', ''))
        if not file_path.exists() or file_path.suffix.lower() != '.pdf':
            print(f"文件不存在或不是PDF: {file_path}")
            return 2
    
    output_path = Path(args.output).resolve()
    
    try:
        merged_count, file_count = merge_pages_from_multiple_pdfs(page_selections, output_path)
        print(f"已合并 {merged_count} 页（来自 {file_count} 个文件）-> {output_path}")
        return 0
    except RuntimeError as e:
        print(str(e))
        return 3
    except Exception as e:
        print(f"合并失败: {e}")
        return 1


if __name__ == "__main__":
    # 检查是否为合并模式
    if "--merge" in sys.argv:
        sys.argv.remove("--merge")
        sys.exit(merge_main(sys.argv[1:]))
    else:
        sys.exit(main(sys.argv[1:]))


