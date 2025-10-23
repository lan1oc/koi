import argparse
import sys
from pathlib import Path
from typing import List, Tuple


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

    reader = PdfReader(str(input_pdf))
    total_pages = len(reader.pages)

    writer = PdfWriter()
    for page_num in page_numbers_1_based:
        # convert to 0-based index
        writer.add_page(reader.pages[page_num - 1])

    output_pdf.parent.mkdir(parents=True, exist_ok=True)
    with output_pdf.open("wb") as f:
        writer.write(f)

    return len(page_numbers_1_based), total_pages


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


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))


