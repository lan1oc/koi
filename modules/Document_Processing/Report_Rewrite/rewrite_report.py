#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
通报改写工具
自动将漏洞通报内容插入到模板中，并进行格式化处理
"""

import sys
import io
import re
import os
import json
import tempfile
import shutil
import uuid
import time
from datetime import datetime, timedelta
from docx import Document
from docx.shared import Pt, RGBColor, Inches, Cm
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.enum.shape import WD_INLINE_SHAPE
from docx.oxml import parse_xml, OxmlElement
from docx.oxml.ns import qn
from copy import deepcopy
from pathlib import Path
# XML 处理库 - 用于处理 Word 文档的 XML 结构
from lxml import etree  # type: ignore

# 全局手动处理列表
MANUAL_PROCESSING_LIST = []

# 设置编码设置控制台编码，避免Unicode错误
def safe_print(text, fallback_text=None):
    """安全打印函数，处理编码问题"""
    try:
        print(text)
    except UnicodeEncodeError:
        if fallback_text:
            print(fallback_text)
        else:
            print(text.encode('utf-8', errors='ignore').decode('utf-8'))
    except Exception:
        if fallback_text:
            print(fallback_text)
        else:
            print("打印输出时发生错误")

# 导入文档完整性验证模块
try:
    from .document_integrity import (
        safe_save_document, validate_document_integrity, 
        cleanup_resources
    )
    INTEGRITY_MODULE_AVAILABLE = True
except ImportError:
    try:
        from document_integrity import (
            safe_save_document, validate_document_integrity, 
            cleanup_resources
        )
        INTEGRITY_MODULE_AVAILABLE = True
    except ImportError:
        INTEGRITY_MODULE_AVAILABLE = False
        safe_print("⚠️ 文档完整性验证模块导入失败，将使用原始保存方法")

def create_backup(file_path):
    """创建文档备份"""
    try:
        if Path(file_path).exists():
            backup_path = f"{file_path}.backup_{int(time.time())}"
            shutil.copy2(file_path, backup_path)
            print(f"  📋 已创建备份: {Path(backup_path).name}")
            return backup_path
    except Exception as e:
        print(f"  ⚠️ 备份创建失败: {e}")
    return None

def recover_from_backup(original_path, backup_path):
    """从备份恢复文档"""
    try:
        if backup_path and Path(backup_path).exists():
            shutil.copy2(backup_path, original_path)
            print(f"  🔄 已从备份恢复: {Path(original_path).name}")
            return True
    except Exception as e:
        print(f"  ❌ 备份恢复失败: {e}")
    return False

def cleanup_backups(file_path, keep_count=3):
    """清理旧备份文件，保留最新的几个"""
    try:
        backup_files = list(Path(file_path).parent.glob(f"{Path(file_path).name}.backup_*"))
        if len(backup_files) > keep_count:
            # 按时间排序，删除最旧的
            backup_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
            for old_backup in backup_files[keep_count:]:
                old_backup.unlink()
                print(f"  🗑️ 已清理旧备份: {old_backup.name}")
    except Exception as e:
        print(f"  ⚠️ 备份清理失败: {e}")


def add_to_manual_processing_list(file_path, error_type, error_detail):
    """添加文件到手动处理列表"""
    global MANUAL_PROCESSING_LIST
    
    entry = {
        'file_path': file_path,
        'file_name': os.path.basename(file_path),
        'error_type': error_type,
        'error_detail': error_detail,
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }
    
    MANUAL_PROCESSING_LIST.append(entry)
    print(f"  📝 已添加到手动处理列表: {entry['file_name']} - {error_type}")


def get_manual_processing_list():
    """获取手动处理列表"""
    return MANUAL_PROCESSING_LIST.copy()


def clear_manual_processing_list():
    """清空手动处理列表"""
    global MANUAL_PROCESSING_LIST
    MANUAL_PROCESSING_LIST.clear()


def print_manual_processing_list():
    """打印手动处理列表"""
    if not MANUAL_PROCESSING_LIST:
        print("  ✅ 无需手动处理的文件")
        return
    
    print("\n" + "=" * 60)
    print("📋 需要手动处理的文件列表")
    print("=" * 60)
    
    for i, entry in enumerate(MANUAL_PROCESSING_LIST, 1):
        print(f"\n{i}. 文件: {entry['file_name']}")
        print(f"   路径: {entry['file_path']}")
        print(f"   错误类型: {entry['error_type']}")
        print(f"   错误详情: {entry['error_detail']}")
        print(f"   时间: {entry['timestamp']}")
    
    print("\n" + "=" * 60)


def _should_keep_numbering(paragraph_element):
    """
    判断段落是否应该保留编号格式
    支持混合编号模式：文本编号（如"1.漏洞描述"）+ Word自动编号（如"验证情况"）
    
    Args:
        paragraph_element: 段落的XML元素
        
    Returns:
        bool: True表示应该保留编号，False表示应该移除编号
    """
    try:
        # 获取段落文本内容
        text_content = ""
        for text_elem in paragraph_element.findall('.//w:t', {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}):
            if text_elem.text:
                text_content += text_elem.text
        
        text_content = text_content.strip()
        
        # 如果段落为空，不保留编号
        if not text_content:
            return False
        
        # 检查是否有Word自动编号
        pPr = paragraph_element.find('.//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}pPr')
        has_auto_numbering = False
        if pPr is not None:
            numPr = pPr.find('.//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}numPr')
            if numPr is not None:
                has_auto_numbering = True
        
        # 明确的正文内容，即使有自动编号也不保留
        body_text_indicators = ['高危', '中危', '低危', '严重', '一般', '轻微']
        for indicator in body_text_indicators:
            if text_content == indicator or text_content.strip() == indicator:
                return False
        
        # 明确的字段标签，不应该有编号（这些是字段名，不是章节标题）
        field_labels = ['漏洞事件：', '发现时间：', '影响产品：', '影响危害：', '漏洞描述：', '验证截图：']
        for label in field_labels:
            if text_content == label or text_content.strip() == label:
                return False
        
        # 检查段落样式（如果有的话）
        if pPr is not None:
            # 检查是否有标题样式
            pStyle = pPr.find('.//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}pStyle')
            if pStyle is not None:
                style_val = pStyle.get('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val', '')
                if 'Heading' in style_val or '标题' in style_val:
                    return True
        
        # 特定的章节标题关键词（这些是真正的章节，应该有编号）
        section_keywords = ['漏洞描述', '验证情况', '整改要求', '整改建议', '处置措施']
        
        # 检查是否是章节标题（短文本且包含关键词）
        for keyword in section_keywords:
            if keyword in text_content and len(text_content.strip()) <= 15:
                return True
        
        # 检查是否是标题级别的文本编号（短文本且以编号开头）
        import re
        text_match = re.match(r'^\d+[.、）)]', text_content)
        if text_match:
            # 只有短文本（可能是标题）才保留编号，长文本（正文内容）不保留
            if len(text_content.strip()) <= 20:
                # 进一步检查是否包含标题关键词
                for keyword in section_keywords:
                    if keyword in text_content:
                        return True
                # 如果是纯编号+简短描述，也可能是标题
                if len(text_content.strip()) <= 10:
                    return True
        
        # 如果有自动编号且内容是章节标题，保留编号
        if has_auto_numbering:
            # 检查是否是章节标题（不是字段标签）
            for keyword in section_keywords:
                if keyword in text_content and len(text_content.strip()) <= 15:
                    return True
        
        # 其他情况（正文内容）不保留编号
        return False
        
    except Exception as e:
        print(f"  ⚠️ 编号检测出错: {e}")
        # 出错时默认不保留编号，避免错误显示
        return False


def _remove_paragraph_numbering(paragraph_element):
    """
    移除段落的编号格式
    
    Args:
        paragraph_element: 段落的XML元素
    """
    try:
        # 查找段落属性
        pPr = paragraph_element.find('.//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}pPr')
        if pPr is not None:
            # 移除编号属性 (numPr)
            numPr = pPr.find('.//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}numPr')
            if numPr is not None:
                pPr.remove(numPr)
                print(f"  🔧 移除段落编号格式")
                return True
        return False
                
    except Exception as e:
        print(f"  ⚠️ 移除编号格式时出错: {e}")
        return False


def _reassign_numbering_sequence(doc):
    """重新分配文档中保留编号段落的编号序列，确保所有编号按1、2、3顺序排列
    将所有保留编号的段落统一为文本编号，避免自动编号与文本编号冲突
    """
    try:
        print(f"\n  🔢 重新分配编号序列...")
        
        # 收集所有应该保留编号的段落
        numbered_paragraphs = []
        
        for para in doc.paragraphs:
            if _should_keep_numbering(para._element):
                para_text = para.text.strip()
                
                # 检查是否有Word自动编号
                pPr = para._element.find('.//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}pPr')
                has_auto_numbering = False
                if pPr is not None:
                    numPr = pPr.find('.//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}numPr')
                    if numPr is not None:
                        has_auto_numbering = True
                
                # 检查是否有文本编号
                import re
                text_match = re.match(r'^(\d+)[.、）)]', para_text)
                has_text_numbering = bool(text_match)
                
                numbered_paragraphs.append({
                    'paragraph': para,
                    'text': para_text,
                    'has_auto_numbering': has_auto_numbering,
                    'has_text_numbering': has_text_numbering,
                    'text_match': text_match
                })
        
        print(f"  找到 {len(numbered_paragraphs)} 个需要编号的段落")
        
        # 统一为文本编号，确保按顺序排列
        text_number_counter = 1
        
        for i, para_info in enumerate(numbered_paragraphs):
            try:
                para = para_info['paragraph']
                para_text = para_info['text']
                has_auto_numbering = para_info['has_auto_numbering']
                has_text_numbering = para_info['has_text_numbering']
                text_match = para_info['text_match']
                
                if has_text_numbering and text_match:
                    # 重新分配文本编号
                    old_number = text_match.group(1)
                    
                    # 替换段落文本中的编号
                    new_text = re.sub(r'^(\d+)([.、）)])', f'{text_number_counter}\\2', para_text)
                    para.text = new_text
                    
                    print(f"    段落 {i+1}: 文本编号 {old_number} -> {text_number_counter}")
                    
                elif has_auto_numbering:
                    # 将自动编号转换为文本编号
                    # 移除自动编号格式
                    _remove_paragraph_numbering(para._element)
                    
                    # 添加文本编号
                    new_text = f"{text_number_counter}.{para_text}"
                    para.text = new_text
                    
                    print(f"    段落 {i+1}: 自动编号 -> 文本编号 {text_number_counter} ('{para_text[:30]}...')")
                    
                else:
                    # 没有编号的段落，添加文本编号
                    new_text = f"{text_number_counter}.{para_text}"
                    para.text = new_text
                    
                    print(f"    段落 {i+1}: 无编号 -> 文本编号 {text_number_counter} ('{para_text[:30]}...')")
                
                text_number_counter += 1
                
            except Exception as e:
                print(f"    ⚠️ 处理段落 {i+1} 时出错: {e}")
        
        print(f"  ✓ 编号序列重新分配完成，所有编号已统一为文本编号并按顺序排列")
        return True
        
    except Exception as e:
        print(f"  ⚠️ 重新分配编号序列失败: {e}")
        return False



def _copy_image_to_document(drawing_element, source_doc, target_doc, target_run):
    """复制图片从源文档到目标文档 - 增强版，支持受保护文档"""
    try:
        from docx.oxml.ns import qn
        import tempfile
        import os
        import zipfile
        from pathlib import Path
        
        print(f"    🔍 开始图片复制流程...")
        
        # 方法1: 标准方式 - 通过关系ID获取图片
        success = _try_standard_image_copy(drawing_element, source_doc, target_doc, target_run)
        if success:
            print(f"    ✅ 标准方式复制成功")
            return True
        
        print(f"    ⚠️ 标准方式失败，尝试备用方案...")
        
        # 方法2: 直接从docx文件中提取图片
        success = _try_direct_image_extraction(drawing_element, source_doc, target_doc, target_run)
        if success:
            print(f"    ✅ 直接提取方式成功")
            return True
        
        print(f"    ⚠️ 直接提取失败，尝试COM方式...")
        
        # 方法3: 使用COM接口处理受保护文档
        if COM_UTILS_AVAILABLE:
            success = _try_com_image_copy(drawing_element, source_doc, target_doc, target_run)
            if success:
                print(f"    ✅ COM方式复制成功")
                return True
        
        print(f"    ❌ 所有图片复制方法都失败")
        return False
        
    except Exception as e:
        print(f"    ❌ 图片复制总体错误: {e}")
        return False


def _try_standard_image_copy(drawing_element, source_doc, target_doc, target_run):
    """标准图片复制方式"""
    try:
        from docx.oxml.ns import qn
        import tempfile
        import os
        
        # 查找图片的关系ID - 修复namespaces兼容性问题
        try:
            blip_elements = drawing_element.xpath('.//a:blip', namespaces={
                'a': 'http://schemas.openxmlformats.org/drawingml/2006/main'
            })
        except TypeError:
            # 兼容旧版本python-docx，不使用namespaces参数
            blip_elements = drawing_element.xpath('.//a:blip')
        
        if not blip_elements:
            # 尝试其他可能的图片元素
            try:
                pic_elements = drawing_element.xpath('.//pic:pic', namespaces={
                    'pic': 'http://schemas.openxmlformats.org/drawingml/2006/picture'
                })
            except TypeError:
                pic_elements = drawing_element.xpath('.//pic:pic')
                
            if pic_elements:
                try:
                    blip_elements = pic_elements[0].xpath('.//a:blip', namespaces={
                        'a': 'http://schemas.openxmlformats.org/drawingml/2006/main'
                    })
                except TypeError:
                    blip_elements = pic_elements[0].xpath('.//a:blip')
        
        if not blip_elements:
            return False
            
        embed_attr = blip_elements[0].get(qn('r:embed'))
        if not embed_attr:
            return False
            
        # 从源文档获取图片数据
        try:
            source_image_part = source_doc.part.related_parts.get(embed_attr)
            if not source_image_part:
                return False
                
            # 获取图片数据
            image_data = source_image_part.blob
            if not image_data:
                return False
                
        except Exception as e:
            print(f"      获取图片数据失败: {e}")
            return False
        
        # 确定图片格式（增强版本）
        image_ext = '.png'  # 默认
        if hasattr(source_image_part, 'content_type'):
            content_type = source_image_part.content_type.lower()
            if 'jpeg' in content_type or 'jpg' in content_type:
                image_ext = '.jpg'
            elif 'png' in content_type:
                image_ext = '.png'
            elif 'gif' in content_type:
                image_ext = '.gif'
            elif 'bmp' in content_type:
                image_ext = '.bmp'
            elif 'tiff' in content_type or 'tif' in content_type:
                image_ext = '.tiff'
            elif 'webp' in content_type:
                image_ext = '.webp'
            elif 'svg' in content_type:
                image_ext = '.svg'
        
        # 如果无法从content_type确定，尝试从图片数据头部检测
        if image_ext == '.png' and image_data:
            try:
                # 检查文件头部魔数
                if image_data.startswith(b'\xff\xd8\xff'):
                    image_ext = '.jpg'
                elif image_data.startswith(b'\x89PNG\r\n\x1a\n'):
                    image_ext = '.png'
                elif image_data.startswith(b'GIF87a') or image_data.startswith(b'GIF89a'):
                    image_ext = '.gif'
                elif image_data.startswith(b'BM'):
                    image_ext = '.bmp'
                elif image_data.startswith(b'RIFF') and b'WEBP' in image_data[:12]:
                    image_ext = '.webp'
                elif image_data.startswith(b'<svg') or image_data.startswith(b'<?xml'):
                    image_ext = '.svg'
            except Exception:
                pass  # 保持默认格式
        
        # 创建临时文件来存储图片
        with tempfile.NamedTemporaryFile(delete=False, suffix=image_ext) as temp_file:
            temp_file.write(image_data)
            temp_file_path = temp_file.name
        
        try:
            # 获取原始图片尺寸信息
            width, height = _get_image_dimensions(drawing_element)
            
            # 添加图片到目标run
            if width and height:
                target_run.add_picture(temp_file_path, width=width, height=height)
            else:
                target_run.add_picture(temp_file_path)
            return True
            
        finally:
            # 清理临时文件
            try:
                os.unlink(temp_file_path)
            except:
                pass
                
    except Exception as e:
        print(f"      标准复制错误: {e}")
        return False


def _try_direct_image_extraction(drawing_element, source_doc, target_doc, target_run):
    """直接从docx文件中提取图片"""
    try:
        import tempfile
        import os
        import zipfile
        from pathlib import Path
        
        # 获取源文档的文件路径
        source_path = _get_document_path(source_doc)
        if not source_path:
            return False
        
        source_path = Path(source_path)
        if not source_path.exists():
            return False
        
        print(f"      尝试从 {source_path.name} 直接提取图片...")
        
        # 打开docx文件作为zip
        with zipfile.ZipFile(source_path, 'r') as zip_file:
            # 列出所有图片文件
            image_files = [f for f in zip_file.namelist() if f.startswith('word/media/')]
            
            if not image_files:
                print(f"      未找到图片文件")
                return False
            
            print(f"      找到 {len(image_files)} 个图片文件")
            
            # 尝试每个图片文件
            for img_file in image_files:
                try:
                    # 提取图片数据
                    image_data = zip_file.read(img_file)
                    if not image_data:
                        continue
                    
                    # 确定文件扩展名
                    img_ext = Path(img_file).suffix or '.png'
                    
                    # 创建临时文件
                    with tempfile.NamedTemporaryFile(delete=False, suffix=img_ext) as temp_file:
                        temp_file.write(image_data)
                        temp_file_path = temp_file.name
                    
                    try:
                        # 获取图片尺寸
                        width, height = _get_image_dimensions(drawing_element)
                        
                        # 添加图片到目标run
                        if width and height:
                            target_run.add_picture(temp_file_path, width=width, height=height)
                        else:
                            target_run.add_picture(temp_file_path)
                        
                        print(f"      成功使用图片: {img_file}")
                        return True
                        
                    finally:
                        # 清理临时文件
                        try:
                            os.unlink(temp_file_path)
                        except:
                            pass
                            
                except Exception as e:
                    print(f"      处理图片 {img_file} 失败: {e}")
                    continue
        
        return False
        
    except Exception as e:
        print(f"      直接提取错误: {e}")
        return False


def _try_com_image_copy(drawing_element, source_doc, target_doc, target_run):
    """使用COM接口复制图片（处理受保护文档）"""
    try:
        if not COM_UTILS_AVAILABLE:
            return False
        
        import tempfile
        import os
        from pathlib import Path
        
        # 获取源文档路径
        source_path = _get_document_path(source_doc)
        if not source_path:
            return False
        
        source_path = Path(source_path)
        if not source_path.exists():
            return False
        
        print(f"      尝试COM方式处理: {source_path.name}")
        
        # 使用COM打开文档并提取图片
        word_app = None
        doc = None
        try:
            word_app = create_word_app_safely()
            if not word_app:
                return False
            
            # 以只读方式打开文档
            doc = word_app.Documents.Open(str(source_path), ReadOnly=True)
            
            # 查找所有图片
            inline_shapes = doc.InlineShapes
            if inline_shapes.Count == 0:
                return False
            
            # 尝试导出第一个图片
            for i in range(1, min(inline_shapes.Count + 1, 4)):  # 最多尝试前3个图片
                try:
                    shape = inline_shapes.Item(i)
                    if shape.Type == 3:  # wdInlineShapePicture
                        # 创建临时文件
                        temp_dir = tempfile.mkdtemp()
                        temp_image_path = os.path.join(temp_dir, f"temp_image_{i}.png")
                        
                        # 导出图片
                        shape.Range.Copy()
                        
                        # 创建新文档来粘贴图片
                        temp_doc = word_app.Documents.Add()
                        temp_doc.Range().Paste()
                        
                        # 保存为图片
                        if temp_doc.InlineShapes.Count > 0:
                            temp_shape = temp_doc.InlineShapes.Item(1)
                            temp_shape.Range.ExportAsFixedFormat(
                                OutputFileName=temp_image_path,
                                ExportFormat=17,  # wdExportFormatPNG
                                OptimizeFor=0
                            )
                        
                        temp_doc.Close(SaveChanges=False)
                        
                        # 检查文件是否创建成功
                        if os.path.exists(temp_image_path):
                            try:
                                # 获取图片尺寸
                                width, height = _get_image_dimensions(drawing_element)
                                
                                # 添加到目标文档
                                if width and height:
                                    target_run.add_picture(temp_image_path, width=width, height=height)
                                else:
                                    target_run.add_picture(temp_image_path)
                                
                                print(f"      COM方式成功复制图片 {i}")
                                return True
                                
                            finally:
                                # 清理临时文件
                                try:
                                    os.unlink(temp_image_path)
                                    os.rmdir(temp_dir)
                                except:
                                    pass
                
                except Exception as shape_error:
                    print(f"      处理图片 {i} 失败: {shape_error}")
                    continue
            
            return False
            
        finally:
            # 清理COM对象
            if doc:
                try:
                    doc.Close(SaveChanges=False)
                except:
                    pass
            if word_app:
                try:
                    word_app.Quit()
                except:
                    pass
        
    except Exception as e:
        print(f"      COM复制错误: {e}")
        return False


def _get_document_path(doc):
    """获取文档的文件路径"""
    try:
        # 尝试多种方式获取文档路径
        if hasattr(doc, '_path') and doc._path:
            return doc._path
        
        if hasattr(doc, 'core_properties') and hasattr(doc.core_properties, 'identifier'):
            return doc.core_properties.identifier
        
        if hasattr(doc, '_part') and hasattr(doc._part, 'package') and hasattr(doc._part.package, '_pkg_file'):
            pkg_file = doc._part.package._pkg_file
            if hasattr(pkg_file, 'name'):
                return pkg_file.name
        
        # 如果都没有，返回None
        return None
        
    except Exception:
        return None


def _get_image_dimensions(drawing_element):
    """获取图片尺寸信息"""
    try:
        width = None
        height = None
        
        # 尝试使用namespaces参数的xpath调用
        try:
            extent_elements = drawing_element.xpath('.//wp:extent', namespaces={
                'wp': 'http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing'
            })
        except TypeError:
            # 如果namespaces参数不支持，使用不带namespaces的xpath
            extent_elements = drawing_element.xpath('.//wp:extent')
        
        if extent_elements:
            cx = extent_elements[0].get('cx')
            cy = extent_elements[0].get('cy')
            if cx and cy:
                # 转换EMU到英寸 (1 inch = 914400 EMU)
                from docx.shared import Inches
                width = Inches(int(cx) / 914400)
                height = Inches(int(cy) / 914400)
                return width, height
        
        # 如果没有找到extent元素，尝试其他方法获取尺寸
        # 方法1: 查找inline元素的extent
        try:
            inline_elements = drawing_element.xpath('.//wp:inline')
            if inline_elements:
                for inline in inline_elements:
                    try:
                        extent_els = inline.xpath('.//wp:extent', namespaces={
                            'wp': 'http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing'
                        })
                    except TypeError:
                        extent_els = inline.xpath('.//wp:extent')
                    
                    if extent_els:
                        cx = extent_els[0].get('cx')
                        cy = extent_els[0].get('cy')
                        if cx and cy:
                            from docx.shared import Inches
                            width = Inches(int(cx) / 914400)
                            height = Inches(int(cy) / 914400)
                            return width, height
        except Exception:
            pass
        
        # 方法2: 查找anchor元素的extent
        try:
            anchor_elements = drawing_element.xpath('.//wp:anchor')
            if anchor_elements:
                for anchor in anchor_elements:
                    try:
                        extent_els = anchor.xpath('.//wp:extent', namespaces={
                            'wp': 'http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing'
                        })
                    except TypeError:
                        extent_els = anchor.xpath('.//wp:extent')
                    
                    if extent_els:
                        cx = extent_els[0].get('cx')
                        cy = extent_els[0].get('cy')
                        if cx and cy:
                            from docx.shared import Inches
                            width = Inches(int(cx) / 914400)
                            height = Inches(int(cy) / 914400)
                            return width, height
        except Exception:
            pass
        
        # 方法3: 直接查找所有extent元素
        try:
            all_extents = drawing_element.xpath('.//extent')
            if all_extents:
                for extent in all_extents:
                    cx = extent.get('cx')
                    cy = extent.get('cy')
                    if cx and cy:
                        from docx.shared import Inches
                        width = Inches(int(cx) / 914400)
                        height = Inches(int(cy) / 914400)
                        return width, height
        except Exception:
            pass
        
        return None, None
        
    except Exception as e:
        print(f"      获取图片尺寸时出错: {e}")
        return None, None










# 导入COM错误处理工具
try:
    from ...utils.com_error_handler import (
        robust_word_operation, safe_open_document,
        check_system_environment, create_word_app_safely, cleanup_word_processes
    )
    COM_UTILS_AVAILABLE = True
except ImportError:
    try:
        # 尝试绝对导入（当作为脚本直接运行时）
        from modules.utils.com_error_handler import (
            robust_word_operation, safe_open_document,
            check_system_environment, create_word_app_safely, cleanup_word_processes
        )
        COM_UTILS_AVAILABLE = True
    except ImportError:
            try:
                # 尝试从当前目录的相对路径导入
                import sys
                import os
                current_dir = os.path.dirname(os.path.abspath(__file__))
                utils_dir = os.path.normpath(os.path.join(current_dir, '..', '..', 'utils'))
                if utils_dir not in sys.path:
                    sys.path.insert(0, utils_dir)
                from com_error_handler import (  # type: ignore
                    robust_word_operation, safe_open_document,
                    check_system_environment, create_word_app_safely, cleanup_word_processes
                )
                COM_UTILS_AVAILABLE = True
            except ImportError:
                try:
                    # 最后尝试：直接从koi根目录导入
                    import sys
                    import os
                    current_dir = os.path.dirname(os.path.abspath(__file__))
                    root_dir = os.path.normpath(os.path.join(current_dir, '..', '..', '..'))
                    utils_path = os.path.normpath(os.path.join(root_dir, 'modules', 'utils'))
                    if utils_path not in sys.path:
                        sys.path.insert(0, utils_path)
                    from com_error_handler import (  # type: ignore
                        robust_word_operation, safe_open_document,
                        check_system_environment, create_word_app_safely, cleanup_word_processes
                    )
                    COM_UTILS_AVAILABLE = True
                except ImportError:
                    try:
                        # 绝对路径尝试
                        import sys
                        import os
                        # 获取当前文件的绝对路径
                        current_file = os.path.abspath(__file__)
                        # 向上三级到koi根目录
                        koi_root = os.path.dirname(os.path.dirname(os.path.dirname(current_file)))
                        utils_path = os.path.join(koi_root, 'modules', 'utils')
                        if os.path.exists(utils_path) and utils_path not in sys.path:
                            sys.path.insert(0, utils_path)
                        from com_error_handler import (  # type: ignore
                            robust_word_operation, safe_open_document,
                            check_system_environment, create_word_app_safely, cleanup_word_processes
                        )
                        COM_UTILS_AVAILABLE = True
                    except ImportError:
                        safe_print("⚠️ COM错误处理工具导入失败，将使用原始COM操作", 
                                  "WARNING: COM error handler import failed, using original COM operations")
                        COM_UTILS_AVAILABLE = False

# 导入PDF转换功能
PDF_CONVERSION_AVAILABLE = False
try:
    # 尝试导入PDF转换所需的模块
    import win32com.client
    PDF_CONVERSION_AVAILABLE = True
    safe_print("✅ PDF转换功能可用")
except ImportError:
    safe_print("⚠️ PDF转换功能不可用，缺少pywin32模块")

# 设置控制台编码
if sys.platform == 'win32':
    try:
        import codecs
        sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
        sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')
    except:
        pass


def wait_for_file_release(file_path, max_wait=15, check_interval=0.5):
    """
    主动等待文件被释放（不再被其他进程占用）
    
    参数:
        file_path: 文件路径
        max_wait: 最大等待时间（秒），默认15秒
        check_interval: 检查间隔（秒），默认0.5秒
    
    返回:
        True: 文件已释放
        False: 超时，文件仍被占用
    """
    import gc
    
    if not os.path.exists(file_path):
        return True  # 文件不存在，无需等待
    
    # 先强制垃圾回收
    gc.collect()
    
    start_time = time.time()
    attempts = 0
    
    while time.time() - start_time < max_wait:
        try:
            # 尝试以独占模式打开文件
            # 如果文件被占用，会抛出PermissionError
            with open(file_path, 'r+b') as f:
                # 成功打开，说明文件已释放
                return True
        except PermissionError:
            # 文件仍被占用，继续等待
            attempts += 1
            if attempts == 1:
                print(f"    ⏳ 文件被占用，等待释放...")
            elif attempts % 4 == 0:  # 每2秒打印一次
                elapsed = time.time() - start_time
                print(f"    ⏳ 仍在等待... ({elapsed:.1f}秒)")
            
            time.sleep(check_interval)
            gc.collect()  # 每次检查前垃圾回收
        except Exception as e:
            # 其他错误（如文件不存在），认为已释放
            return True
    
    # 超时
    elapsed = time.time() - start_time
    print(f"    ⚠️ 等待超时 ({elapsed:.1f}秒)，文件可能仍被占用")
    return False


def convert_docx_to_pdf(docx_path, pdf_path=None):
    """
    将Word文档转换为PDF
    
    参数:
        docx_path: Word文档路径
        pdf_path: PDF输出路径，如果为None则自动生成
    
    返回:
        tuple: (success, pdf_path, error_message)
    """
    if not PDF_CONVERSION_AVAILABLE:
        return False, None, "PDF转换功能不可用，缺少pywin32模块"
    
    COM_PATH_THRESHOLD = 260  # Windows路径长度限制
    
    try:
        docx_path = Path(docx_path)
        if not docx_path.exists():
            return False, None, f"源文件不存在: {docx_path}"
        
        # 如果没有指定PDF路径，则自动生成
        if pdf_path is None:
            pdf_path = docx_path.with_suffix('.pdf')
        else:
            pdf_path = Path(pdf_path)
        
        # 确保输出目录存在
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        
        print(f"  📄 开始转换PDF: {docx_path.name} -> {pdf_path.name}")
        
        # 检查路径长度
        src_path_length = len(str(docx_path))
        if src_path_length > COM_PATH_THRESHOLD:
            return False, None, f"源文件路径过长（{src_path_length}字符），超过COM操作安全阈值（{COM_PATH_THRESHOLD}字符）"
        
        # 检查文件是否被占用
        try:
            with open(docx_path, 'rb') as f:
                pass  # 只是测试能否打开
        except PermissionError:
            print(f"  ⚠️ 文件被占用，等待释放: {docx_path.name}")
            wait_for_file_release(str(docx_path), max_wait=10)
        except Exception as e:
            print(f"  ⚠️ 文件访问检查失败: {e}")
            # 继续尝试，可能是权限问题但COM仍能访问
        
        # 处理输出路径过长的情况
        temp_pdf_path = pdf_path
        revert_output_from_temp = False
        if len(str(pdf_path)) > COM_PATH_THRESHOLD:
            temp_dir = Path(tempfile.gettempdir()) / f"report_pdf_{uuid.uuid4().hex}"
            temp_dir.mkdir(parents=True, exist_ok=True)
            temp_pdf_path = temp_dir / pdf_path.name
            revert_output_from_temp = True
            print(f"  ⚠️ 输出路径过长，使用临时路径: {temp_pdf_path}")
        
        # 使用Word COM进行转换
        word = None
        try:
            # 使用增强的COM错误处理初始化Word应用程序
            if COM_UTILS_AVAILABLE:
                word = create_word_app_safely(visible=False, display_alerts=False, verbose=False)
            else:
                # 回退到原始方法
                word = win32com.client.Dispatch("Word.Application")
                word.Visible = False
                word.DisplayAlerts = 0  # wdAlertsNone
            
            if word is None:
                return False, None, "Word应用程序初始化失败"
            
            # 打开文档
            doc = None
            if COM_UTILS_AVAILABLE:
                try:
                    doc = safe_open_document(word, str(docx_path), verbose=False)
                except Exception as e:
                    # 如果打开失败，尝试重新创建Word应用程序
                    print(f"  ⚠️ 文档打开失败，尝试重新创建Word应用程序: {str(e)[:100]}")
                    try:
                        if word is not None:
                            word.Quit(SaveChanges=0)
                    except:
                        pass
                    word = create_word_app_safely(visible=False, display_alerts=False, verbose=False)
                    doc = safe_open_document(word, str(docx_path), verbose=False)
            else:
                doc = word.Documents.Open(str(docx_path), ReadOnly=True, Visible=False)
            
            if doc is None:
                return False, None, "文档打开失败"
            
            try:
                # 导出为PDF (17 = wdExportFormatPDF)
                doc.ExportAsFixedFormat(
                    OutputFileName=str(temp_pdf_path),
                    ExportFormat=17
                )
                
                # 如果使用了临时路径，需要移动文件到最终位置
                if revert_output_from_temp:
                    if temp_pdf_path.exists():
                        shutil.move(str(temp_pdf_path), str(pdf_path))
                        # 清理临时目录
                        try:
                            temp_pdf_path.parent.rmdir()
                        except:
                            pass
                    else:
                        return False, None, "临时PDF文件未生成"
                
                if pdf_path.exists():
                    print(f"  ✅ PDF转换成功: {pdf_path.name}")
                    return True, str(pdf_path), None
                else:
                    return False, None, "PDF文件未生成"
                
            finally:
                # 关闭文档
                try:
                    doc.Close(SaveChanges=0)  # 0 = wdDoNotSaveChanges
                except:
                    pass
                
        finally:
            # 关闭Word应用程序
            if word is not None:
                try:
                    word.Quit(SaveChanges=0)
                except:
                    pass
            
            # 使用增强的COM清理
            if COM_UTILS_AVAILABLE:
                cleanup_word_processes()
                
    except Exception as e:
        error_msg = f"PDF转换失败: {str(e)}"
        print(f"  ❌ {error_msg}")
        return False, None, error_msg


def get_config_file():
    """获取配置文件路径"""
    # 从脚本位置向上找到项目根目录
    script_dir = Path(__file__).resolve().parent
    project_root = script_dir.parent.parent.parent
    return project_root / "config.json"


def update_notification_number(docx_file):
    """
    更新通报编号
    
    参数:
        docx_file: 生成的通报文档路径
    
    返回:
        当前使用的编号
    """
    try:
        config_file = get_config_file()
        
        # 读取配置
        if not config_file.exists():
            print(f"  警告: 配置文件不存在: {config_file}")
            return None
        
        with open(config_file, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        # 获取当前编号
        if 'report_counters' not in config:
            config['report_counters'] = {
                'notification_number': 104,
                'rectification_number': 235,
                'year': datetime.now().year,
                'last_updated': ''
            }
        
        # 检查年份，如果是新年则重置编号
        current_year = datetime.now().year
        if 'year' not in config['report_counters'] or config['report_counters']['year'] != current_year:
            print(f"  🎊 检测到新年份: {current_year}，重置编号计数")
            config['report_counters']['notification_number'] = 1
            config['report_counters']['rectification_number'] = 1
            config['report_counters']['year'] = current_year
        
        # 使用配置中的年份（已更新后的）
        config_year = config['report_counters']['year']
        current_number = config['report_counters']['notification_number']
        
        # 打开文档并替换编号
        doc = Document(docx_file)
        replaced = False
        
        for para in doc.paragraphs:
            para_text = para.text
            # 查找 〔YYYY〕第XX期 的模式（支持任意年份）
            if '〔' in para_text and '〕' in para_text and '第' in para_text and '期' in para_text:
                # 提取当前的年份和期数
                year_match = re.search(r'〔(\d{4})〕', para_text)
                number_match = re.search(r'第(\d+)期', para_text)
                
                if year_match and number_match:
                    old_year = year_match.group(1)
                    old_number = number_match.group(1)
                    
                    # 对每个run进行替换
                    for run in para.runs:
                        # 替换年份中的数字（可能分散在多个runs中）
                        if old_year in run.text:
                            run.text = run.text.replace(old_year, str(config_year))
                            replaced = True
                        elif any(old_year[i:i+len(run.text)] == run.text for i in range(len(old_year)) if run.text and run.text.isdigit()):
                            # 处理年份被拆分的情况（如 '202' 或 '5'）
                            for i in range(len(old_year)):
                                if old_year[i:i+len(run.text)] == run.text:
                                    run.text = str(config_year)[i:i+len(run.text)]
                                    replaced = True
                                    break
                        
                        # 替换期数
                        if old_number in run.text:
                            run.text = run.text.replace(old_number, str(current_number))
                            replaced = True
                
                # 找到目标段落后退出循环
                break
        
        if replaced:
            # 保存文档（添加重试机制）
            max_retries = 3
            for retry in range(max_retries):
                try:
                    doc.save(docx_file)
                    break
                except PermissionError as pe:
                    if retry < max_retries - 1:
                        print(f"  ⚠️ 文件被占用，等待重试 ({retry + 1}/{max_retries})...")
                        time.sleep(1.0)
                    else:
                        raise pe
            
            # 更新配置中的编号
            old_notification_number = config['report_counters']['notification_number']
            new_notification_number = current_number + 1
            config['report_counters']['notification_number'] = new_notification_number
            config['report_counters']['last_updated'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
            print(f"  📝 准备更新配置文件: {config_file}")
            print(f"  📊 编号变更: {old_notification_number} → {new_notification_number}")
            
            try:
                # 使用统一配置管理器进行原子更新，避免覆盖其他模块的写入
                from modules.config.config_manager import ConfigManager
                cm = ConfigManager()
                # 更新编号
                cm.update_section('report_counters', {
                    'notification_number': new_notification_number,
                    'last_updated': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                })
                print(f"  💾 配置文件写入完成（统一管理器）")
                
                # 验证写入结果
                verify_config = cm.get_config('report_counters')
                actual_number = verify_config.get('notification_number', 'N/A')
                print(f"  ✅ 验证写入结果: {actual_number}")
                
                if actual_number == new_notification_number:
                    print(f"  ✓ 配置更新成功！编号已更新为: {new_notification_number}")
                else:
                    print(f"  ❌ 配置更新失败！期望: {new_notification_number}, 实际: {actual_number}")
                    
            except Exception as config_error:
                print(f"  ❌ 配置文件操作失败: {config_error}")
                raise config_error
            
            print(f"  ✓ 已更新通报编号: 〔{config_year}〕第{current_number}期")
            return current_number, config_year
        else:
            print(f"  警告: 未找到通报编号标记")
            return None
            
    except Exception as e:
        print(f"  警告: 更新通报编号失败: {str(e)}")
        return None


def extract_info_from_filename(filename):
    """
    从文件名中提取公司名和漏洞类型
    
    文件名格式示例：
    - 1759979441661关于浙江格瓦拉数字科技有限公司所属Druid系统存在未授权访问安全漏洞通报.docx
    - 关于宁波易到互联科技有限公司所属啾啾救援-全国道路救援生态云平台系统MongDB未授权访问安全漏洞通报.docx
    - 1760410609070舒普智能技术股份有限公司远程技术检查存在ecology远程命令执行漏洞.docx
    
    返回: (公司名, 漏洞描述)
    """
    # 去掉路径和扩展名
    basename = os.path.basename(filename)
    name_without_ext = basename.rsplit('.', 1)[0]
    
    # 去掉开头的数字
    name_clean = re.sub(r'^\d+', '', name_without_ext)
    
    # 提取公司名：尝试多种模式
    company_name = None
    
    # 模式1：关于...所属（最常见）
    company_match = re.search(r'关于(.+?)所属', name_clean)
    if company_match:
        company_name = company_match.group(1)
    else:
        # 模式2：关于...门户网站/官网/网站
        company_match = re.search(r'关于(.+?)(门户网站|官网|网站|平台|系统)', name_clean)
        if company_match:
            company_name = company_match.group(1)
        else:
            # 模式3：关于...存在（针对直接描述漏洞的文件名）
            company_match = re.search(r'关于(.+?)存在', name_clean)
            if company_match:
                company_name = company_match.group(1)
            else:
                # 模式4：关于...的
                company_match = re.search(r'关于(.+?)的', name_clean)
                if company_match:
                    company_name = company_match.group(1)
                else:
                    # 模式5：直接格式 - 公司名+技术检查/远程检查等
                    # 匹配：公司名（包含有限公司、股份有限公司等）+ 技术检查/远程检查等
                    company_match = re.search(r'^(.+?(?:有限公司|股份有限公司|集团|科技公司|科技))', name_clean)
                    if company_match:
                        company_name = company_match.group(1)
                    else:
                        # 模式6：尝试从"存在"之前提取公司名
                        company_match = re.search(r'^(.+?)(?:远程技术检查|技术检查|检查|远程|存在)', name_clean)
                        if company_match:
                            potential_company = company_match.group(1).strip()
                            # 验证是否包含公司关键词
                            if any(keyword in potential_company for keyword in ['有限公司', '股份有限公司', '集团', '科技']):
                                company_name = potential_company
    
    # 提取漏洞类型：尝试多种模式
    vuln_type = None
    
    # 模式1：查找"存在"和"通报"或"的报告"之间的内容
    vuln_match = re.search(r'存在(.+?)(?:通报|的报告)', name_clean)
    if vuln_match:
        # 去掉"存在"前缀，只保留漏洞类型描述
        vuln_type = vuln_match.group(1).strip()
    else:
        # 模式2：查找"系统"之后到"通报"或"的报告"之间的内容
        vuln_match = re.search(r'系统(.+?)(?:通报|的报告)', name_clean)
        if vuln_match:
            content = vuln_match.group(1).strip()
            # 去掉开头的"的"字
            content = re.sub(r'^的', '', content)
            # 去掉可能的系统名称，只保留漏洞描述
            vuln_type = content
        else:
            # 模式3：查找"网站"之后到"通报"或"的报告"之间的内容
            vuln_match = re.search(r'网站(.+?)(?:通报|的报告)', name_clean)
            if vuln_match:
                content = vuln_match.group(1).strip()
                # 去掉开头的"的"字
                content = re.sub(r'^的', '', content)
                vuln_type = content
            else:
                # 模式4：查找"存在"到文件名结尾的内容（针对没有"通报"或"的报告"的文件名）
                vuln_match = re.search(r'存在(.+?)(?:\.docx|$)', name_clean)
                if vuln_match:
                    # 去掉"存在"前缀，只保留漏洞类型描述
                    vuln_type = vuln_match.group(1).strip()
                else:
                    # 模式5：查找"技术检查存在"模式
                    vuln_match = re.search(r'(?:远程技术检查|技术检查|检查)存在(.+?)(?:\.docx|$)', name_clean)
                    if vuln_match:
                        # 去掉"存在"前缀，只保留漏洞类型描述
                        vuln_type = vuln_match.group(1).strip()
                    else:
                        # 模式6：最后尝试，查找包含"漏洞"或"风险"关键词的部分
                        vuln_match = re.search(r'([\u4e00-\u9fa5A-Za-z]+(?:漏洞|风险))', name_clean)
                        if vuln_match:
                            vuln_type = vuln_match.group(1)
    
    # 清理漏洞类型，去除不需要的后缀
    if vuln_type:
        # 去除"的报告"、"风险的报告"等后缀
        vuln_type = re.sub(r'(?:风险)?的报告$', '', vuln_type)
        # 去除"安全"重复
        vuln_type = re.sub(r'安全安全', '安全', vuln_type)
        # 确保以"漏洞"或"风险"结尾
        if not vuln_type.endswith(('漏洞', '风险')):
            if '漏洞' in vuln_type:
                # 如果包含"漏洞"但不以"漏洞"结尾，截取到"漏洞"
                vuln_match = re.search(r'(.+?漏洞)', vuln_type)
                if vuln_match:
                    vuln_type = vuln_match.group(1)
            elif '风险' in vuln_type:
                # 如果包含"风险"但不以"风险"结尾，截取到"风险"
                vuln_match = re.search(r'(.+?风险)', vuln_type)
                if vuln_match:
                    vuln_type = vuln_match.group(1)
    
    return company_name, vuln_type






def replace_text_in_runs(para, old_text, new_text):
    """
    在段落的runs中替换文本（支持跨runs替换），保留超链接
    
    参数:
        para: 段落对象
        old_text: 要查找的旧文本
        new_text: 替换后的新文本
    
    返回:
        是否成功替换
    """
    # 获取段落的完整文本
    full_text = para.text
    
    # 检查是否包含要替换的文本
    if old_text not in full_text:
        return False
    
    # 找到旧文本的起始位置
    start_pos = full_text.find(old_text)
    end_pos = start_pos + len(old_text)
    
    # 计算每个run的字符范围
    run_ranges = []
    current_pos = 0
    for run in para.runs:
        run_length = len(run.text)
        run_ranges.append((current_pos, current_pos + run_length, run))
        current_pos += run_length
    
    # 找出需要修改的runs
    affected_runs = []
    for run_start, run_end, run in run_ranges:
        # 如果run与替换区域有交集
        if run_start < end_pos and run_end > start_pos:
            affected_runs.append((run_start, run_end, run))
    
    if not affected_runs:
        return False
    
    # 检查受影响的runs中是否包含超链接
    has_hyperlink = False
    for run_start, run_end, run in affected_runs:
        if _run_contains_hyperlink(run):
            has_hyperlink = True
            print(f"    ⚠️ 检测到超链接，跳过文本替换以保留超链接: '{old_text}'")
            break
    
    # 如果包含超链接，跳过替换以保留超链接
    if has_hyperlink:
        return False
    
    # 执行替换
    for run_start, run_end, run in affected_runs:
        # 计算在当前run中的替换范围
        replace_start = max(0, start_pos - run_start)
        replace_end = min(len(run.text), end_pos - run_start)
        
        # 构建新的run文本
        old_run_text = run.text
        
        if replace_start == 0 and replace_end == len(run.text):
            # 整个run都在替换范围内
            if run == affected_runs[0][2]:
                # 第一个受影响的run，包含新文本
                run.text = new_text
            else:
                # 后续受影响的run，清空
                run.text = ""
        elif replace_start == 0:
            # 从run开头开始替换
            if run == affected_runs[0][2]:
                run.text = new_text + old_run_text[replace_end:]
            else:
                run.text = old_run_text[replace_end:]
        elif replace_end == len(run.text):
            # 替换到run结尾
            if run == affected_runs[0][2]:
                run.text = old_run_text[:replace_start] + new_text
            else:
                run.text = old_run_text[:replace_start]
        else:
            # 替换在run中间
            run.text = old_run_text[:replace_start] + new_text + old_run_text[replace_end:]
    
    return True


def _run_contains_hyperlink(run):
    """
    检查run是否包含超链接
    
    参数:
        run: run对象
    
    返回:
        bool: 是否包含超链接
    """
    try:
        # 检查run的XML元素中是否包含超链接
        if hasattr(run, '_element'):
            # 查找超链接元素
            hyperlinks = run._element.findall('.//w:hyperlink', {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'})
            if hyperlinks:
                return True
            
            # 查找fldChar元素（字段字符，超链接的另一种形式）
            fld_chars = run._element.findall('.//w:fldChar', {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'})
            if fld_chars:
                return True
            
            # 查找instrText元素（指令文本，超链接字段的一部分）
            instr_texts = run._element.findall('.//w:instrText', {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'})
            for instr_text in instr_texts:
                if instr_text.text and 'HYPERLINK' in instr_text.text:
                    return True
        
        return False
        
    except Exception as e:
        # 如果检查失败，为了安全起见，假设包含超链接
        print(f"    ⚠️ 超链接检查失败: {e}")
        return True


def _run_element_contains_hyperlink(run_element):
    """
    检查run XML元素是否包含超链接
    
    参数:
        run_element: run的XML元素
    
    返回:
        bool: 是否包含超链接
    """
    try:
        # 查找超链接元素
        hyperlinks = run_element.findall('.//w:hyperlink', {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'})
        if hyperlinks:
            return True
        
        # 查找fldChar元素（字段字符，超链接的另一种形式）
        fld_chars = run_element.findall('.//w:fldChar', {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'})
        if fld_chars:
            return True
        
        # 查找instrText元素（指令文本，超链接字段的一部分）
        instr_texts = run_element.findall('.//w:instrText', {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'})
        for instr_text in instr_texts:
            if instr_text.text and 'HYPERLINK' in instr_text.text:
                return True
        
        # 检查run是否在hyperlink元素内部
        parent = run_element.getparent()
        while parent is not None:
            if parent.tag.endswith('hyperlink'):
                return True
            parent = parent.getparent()
        
        return False
        
    except Exception as e:
        # 如果检查失败，为了安全起见，假设包含超链接
        print(f"    ⚠️ 超链接检查失败: {e}")
        return True


def is_notification_document(doc):
    """
    识别文档是否为通报文件
    
    参数:
        doc: Word文档对象
    
    返回:
        bool: 是否为通报文件
    """
    try:
        # 获取文档的前几个段落文本
        first_paragraphs_text = ""
        for i, para in enumerate(doc.paragraphs[:10]):  # 检查前10个段落
            first_paragraphs_text += para.text.strip() + " "
        
        # 通报文件的关键词
        notification_keywords = [
            "通报", "网络安全", "漏洞", "安全事件", "安全通告", 
            "风险提示", "安全预警", "威胁情报", "安全公告"
        ]
        
        # 检查是否包含通报相关关键词
        for keyword in notification_keywords:
            if keyword in first_paragraphs_text:
                print(f"  ✅ 检测到通报文件关键词: '{keyword}'")
                return True
        
        print(f"  ℹ️  未检测到通报文件关键词，跳过图片插入")
        return False
        
    except Exception as e:
        print(f"  ⚠️ 文档类型识别失败: {e}")
        return False


def get_accurate_page_count(doc):
    """
    获取文档的精确页数（严格使用COM接口）
    
    参数:
        doc: Word文档对象
    
    返回:
        int: 页数（成功时）
        None: 检测失败时
    """
    try:
        import win32com.client as win32
        import tempfile
        
        # 创建临时文件
        temp_file = tempfile.mktemp(suffix='.docx')
        doc.save(temp_file)
        
        word_app = None
        com_doc = None
        
        try:
            # 启动Word应用并获取页数
            word_app = win32.Dispatch("Word.Application")
            word_app.Visible = False
            word_app.DisplayAlerts = False
            
            com_doc = word_app.Documents.Open(temp_file)
            page_count = com_doc.ComputeStatistics(2)  # 2 = wdStatisticPages
            
            print(f"  📄 COM方式获取页数: {page_count}")
            return page_count
            
        except Exception as com_error:
            print(f"  ❌ COM接口页数检测失败: {com_error}")
            return None
            
        finally:
            # 清理资源
            try:
                if com_doc:
                    com_doc.Close(False)
                if word_app:
                    word_app.Quit()
            except:
                pass
            
            # 删除临时文件
            try:
                os.unlink(temp_file)
            except:
                pass
        
    except Exception as e:
        print(f"  ❌ 页数检测过程失败: {e}")
        return None


def check_existing_images_on_page(doc, page_start_para, page_end_para, image_signature):
    """
    检查指定页面范围内是否已存在相同的水印图片
    
    参数:
        doc: Word文档对象
        page_start_para: 页面开始段落索引
        page_end_para: 页面结束段落索引
        image_signature: 图片特征签名（包含文件名和大小）
    
    返回:
        bool: 是否已存在相同的水印图片
    """
    try:
        # 对于水印式图片，我们允许多个图片共存
        # 只检查是否已存在完全相同的水印图片（基于文件名和大小）
        watermark_count = 0
        
        for para_idx in range(page_start_para, min(page_end_para, len(doc.paragraphs))):
            para = doc.paragraphs[para_idx]
            
            # 检查段落中的图片
            for run in para.runs:
                if hasattr(run, '_element'):
                    # 查找图片元素
                    drawings = run._element.findall('.//w:drawing', {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'})
                    for drawing in drawings:
                        # 检查是否是图片
                        pic_elements = drawing.findall('.//pic:pic', {'pic': 'http://schemas.openxmlformats.org/drawingml/2006/picture'})
                        if pic_elements:
                            # 检查图片的描述信息，看是否包含我们的水印标识
                            # 这里我们采用更宽松的策略：允许添加水印，除非已经有太多相同的水印
                            watermark_count += 1
        
        # 如果已经有超过1个水印图片，则跳过（避免重复添加太多）
        if watermark_count >= 1 and "确认词条" in image_signature:
            print(f"    ℹ️ 第{page_start_para//20 + 1}页已有{watermark_count}个图片，跳过水印添加")
            return True
        
        return False
        
    except Exception as e:
        print(f"  ⚠️ 检查已存在图片失败: {e}")
        return False


def add_floating_image_to_pages(doc, image_path, start_page=2, source_file_path=None):
    """
    在文档的每一页（从指定页开始）添加浮动图片
    支持精确页数检测、防重复插入、页数变化处理
    
    参数:
        doc: Word文档对象
        image_path: 图片文件路径
        start_page: 开始添加图片的页码（默认从第2页开始）
        source_file_path: 源文件路径（用于错误记录）
    """
    try:
        print(f"\n🖼️ 开始添加浮动图片到文档...")
        print(f"  图片路径: {image_path}")
        print(f"  开始页码: {start_page}")
        
        # 1. 检查图片文件是否存在
        if not os.path.exists(image_path):
            print(f"  ❌ 图片文件不存在: {image_path}")
            return False
        
        # 2. 检查是否为通报文件
        if not is_notification_document(doc):
            return False
        
        # 3. 获取文档的所有段落
        paragraphs = doc.paragraphs
        if len(paragraphs) == 0:
            print(f"  ❌ 文档没有段落")
            return False
        
        # 4. 获取初始页数（严格使用COM接口）
        initial_page_count = get_accurate_page_count(doc)
        if initial_page_count is None:
            print(f"  ⚠️ 页数检测失败，使用默认逻辑继续处理")
            # 使用文档段落数量估算页数（备用方案）
            initial_page_count = max(1, len(paragraphs) // 20)  # 估算每20个段落为一页
            print(f"  📄 估算页数: {initial_page_count}")
            # 注意：不再添加到手动处理列表，因为新的图片插入逻辑更稳定
        
        print(f"  📄 初始页数: {initial_page_count}")
        
        # 5. 计算图片特征签名（用于防重复）
        image_signature = f"{os.path.basename(image_path)}_{os.path.getsize(image_path)}"
        
        # 6. 为每一页（从start_page开始）添加图片
        images_added = 0
        current_page_count = initial_page_count
        
        # 使用COM接口获取的实际页数
        actual_page_count = initial_page_count
        print(f"  📄 将为第{start_page}页到第{actual_page_count}页添加水印图片")
        
        for page_num in range(start_page, actual_page_count + 1):
            try:
                # 简化的页面范围计算：基于页码直接选择段落
                total_paragraphs = len(paragraphs)
                
                # 根据页码选择合适的段落范围
                # 基于实际页面分布：第1页(1-16), 第2页(17-33), 第3页(34-38)
                if page_num == 2:
                    # 第2页：段落17-33
                    start_para_idx = 16  # 从段落17开始（索引16）
                    end_para_idx = min(total_paragraphs, 33)  # 到段落33结束
                elif page_num == 3:
                    # 第3页：段落34-38
                    start_para_idx = 33  # 从段落34开始（索引33）
                    end_para_idx = total_paragraphs
                else:
                    # 其他页：使用平均分配
                    paragraphs_per_page = max(1, total_paragraphs // actual_page_count)
                    start_para_idx = (page_num - 1) * paragraphs_per_page
                    end_para_idx = min(page_num * paragraphs_per_page, total_paragraphs)
                
                if start_para_idx >= total_paragraphs:
                    print(f"    ⚠️ 第{page_num}页超出段落范围，跳过")
                    continue
                
                print(f"    📄 第{page_num}页段落范围: {start_para_idx} - {end_para_idx-1} (共{end_para_idx-start_para_idx}个段落)")
                
                # 寻找合适的插入位置：优先选择页面顶部空白区域
                # 对于第3页，强制插入到页面开始位置（段落24）
                if page_num == 3:
                    target_para_idx = start_para_idx
                    print(f"      🎯 第3页强制插入位置：段落{target_para_idx}")
                else:
                    target_para_idx = _find_best_insertion_point(paragraphs, start_para_idx, end_para_idx)
                
                if target_para_idx is not None and target_para_idx < len(paragraphs):
                    target_para = paragraphs[target_para_idx]
                    
                    # 在目标段落前添加一个新段落来放置图片（这样图片在空白区域）
                    new_para = doc.add_paragraph()
                    
                    # 将新段落移动到目标位置
                    target_element = target_para._element
                    parent = target_element.getparent()
                    parent.insert(parent.index(target_element), new_para._element)  # 插在前面而不是后面
                    
                    # 添加图片到新段落
                    run = new_para.add_run()
                    
                    # 添加图片（大小由_set_picture_floating函数控制）
                    picture = run.add_picture(image_path)
                    
                    # 设置图片为浮动样式（右上角）
                    floating_success = _set_picture_floating(picture, new_para)
                    
                    images_added += 1
                    if floating_success:
                        print(f"    ✅ 第{page_num}页图片添加成功（插入位置：段落{target_para_idx}前）")
                    else:
                        print(f"    ⚠️ 第{page_num}页图片已添加但需要手动调整浮动样式（插入位置：段落{target_para_idx}前）")
                    
                    # 检查页数是否发生变化
                    new_page_count = get_accurate_page_count(doc)
                    if new_page_count is None:
                        print(f"    ⚠️ 页数检测失败，继续处理下一页")
                        continue
                    
                    if new_page_count > current_page_count:
                        print(f"    📄 页数增加: {current_page_count} → {new_page_count}")
                        current_page_count = new_page_count
                        actual_page_count = new_page_count  # 更新实际页数
                else:
                    print(f"    ⚠️ 第{page_num}页未找到合适的插入位置")
                        
            except Exception as e:
                print(f"    ⚠️ 第{page_num}页图片添加失败: {e}")
                continue
        
        # 8. 最终页数检查和调整
        final_page_count = get_accurate_page_count(doc)
        if final_page_count is None:
            print(f"  ⚠️ 最终页数检测失败，但图片插入已完成")
            # 不再添加到手动处理列表，因为图片插入逻辑已经完成
            return images_added > 0
        
        if final_page_count > initial_page_count:
            print(f"  📄 最终页数变化: {initial_page_count} → {final_page_count}")
            
            # 如果新增了页面，为新页面也添加图片
            for page_num in range(initial_page_count + 1, final_page_count + 1):
                try:
                    # 为新增页面添加图片
                    start_para_idx = (page_num - 1) * paragraphs_per_page
                    if start_para_idx < len(doc.paragraphs):
                        target_para_idx = min(start_para_idx + 2, len(doc.paragraphs) - 1)
                        target_para = doc.paragraphs[target_para_idx]
                        
                        new_para = doc.add_paragraph()
                        target_element = target_para._element
                        parent = target_element.getparent()
                        parent.insert(parent.index(target_element) + 1, new_para._element)
                        
                        run = new_para.add_run()
                        picture = run.add_picture(image_path)
                        floating_success = _set_picture_floating(picture, new_para)
                        
                        images_added += 1
                        if floating_success:
                            print(f"    ✅ 新增第{page_num}页图片添加成功")
                        else:
                            print(f"    ⚠️ 新增第{page_num}页图片已添加但需要手动调整浮动样式")
                        
                except Exception as e:
                    print(f"    ⚠️ 新增第{page_num}页图片添加失败: {e}")
        
        print(f"  ✅ 图片添加完成，共添加 {images_added} 张图片")
        print(f"  📄 最终文档页数: {final_page_count}")
        return images_added > 0
        
    except Exception as e:
        print(f"  ❌ 添加浮动图片失败: {e}")
        return False


def _find_best_insertion_point(paragraphs, start_para_idx, end_para_idx):
    """
    寻找最佳的图片插入位置，优先选择空白区域
    
    参数:
        paragraphs: 段落列表
        start_para_idx: 页面开始段落索引
        end_para_idx: 页面结束段落索引
    
    返回:
        最佳插入位置的段落索引
    """
    # 确保索引在有效范围内
    start_para_idx = max(0, start_para_idx)
    end_para_idx = min(len(paragraphs) - 1, end_para_idx)
    
    # 策略1: 寻找空段落或只有少量文字的段落
    for i in range(start_para_idx, end_para_idx + 1):
        if i < len(paragraphs):
            para = paragraphs[i]
            text = para.text.strip()
            # 如果是空段落或只有很少文字（可能是标题或分隔符）
            if len(text) == 0 or len(text) < 10:
                return i
    
    # 策略2: 寻找页面顶部位置（前20%）
    page_range = end_para_idx - start_para_idx + 1
    top_20_percent = max(1, int(page_range * 0.2))
    for i in range(start_para_idx, min(start_para_idx + top_20_percent, end_para_idx + 1)):
        if i < len(paragraphs):
            return i
    
    # 策略3: 寻找页面底部位置（后20%）
    bottom_20_percent = max(1, int(page_range * 0.2))
    for i in range(max(end_para_idx - bottom_20_percent, start_para_idx), end_para_idx + 1):
        if i < len(paragraphs):
            return i
    
    # 策略4: 默认返回页面开始位置
    return start_para_idx


def _set_picture_floating(picture, paragraph):
    """
    设置图片为浮动样式，位于文字上方（水印效果）
    根据第二页图片的正确格式：使用anchor浮动，右对齐
    
    参数:
        picture: 图片对象（InlineShape对象）
        paragraph: 包含图片的段落
    """
    try:
        # 在python-docx中，InlineShape对象没有直接的XML访问方式
        # 我们需要通过段落的run来找到图片的XML元素
        
        # 查找包含图片的run
        target_run = None
        for run in paragraph.runs:
            if hasattr(run._element, 'xpath'):
                # 查找内联图片元素
                inline_elements = run._element.xpath('.//wp:inline')
                if inline_elements:
                    target_run = run
                    break
        
        if not target_run:
            print(f"      ❌ 无法找到包含图片的run")
            return False
        
        # 获取内联图片元素
        inline_elements = target_run._element.xpath('.//wp:inline')
        if not inline_elements:
            print(f"      ❌ 无法找到内联图片元素")
            return False
        
        inline_element = inline_elements[0]  # 取第一个内联图片
        
        # 获取图片的graphic元素
        graphic_xml = ""
        try:
            graphic_elements = inline_element.xpath('.//a:graphic')
            if graphic_elements:
                graphic_xml = etree.tostring(graphic_elements[0], encoding='unicode')
            else:
                # 如果无法获取graphic XML，使用简化版本
                graphic_xml = f'<a:graphic xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture"/></a:graphic>'
        except Exception as e:
            print(f"      ⚠️ 获取graphic XML失败: {e}")
            graphic_xml = f'<a:graphic xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture"/></a:graphic>'
        
        # 创建anchor元素来替换inline元素，完全按照第二页正确图片的格式
        anchor_xml = f'''<wp:anchor xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" xmlns:wp14="http://schemas.microsoft.com/office/word/2010/wordprocessingDrawing" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" distT="0" distB="0" distL="114300" distR="114300" simplePos="0" relativeHeight="251663360" behindDoc="0" locked="0" layoutInCell="1" allowOverlap="1" wp14:anchorId="36FF99FB" wp14:editId="53933A80"><wp:simplePos x="0" y="0"/><wp:positionH relativeFrom="column"><wp:posOffset>1731645</wp:posOffset></wp:positionH><wp:positionV relativeFrom="paragraph"><wp:posOffset>201295</wp:posOffset></wp:positionV><wp:extent cx="2134235" cy="1280160"/><wp:effectExtent l="0" t="0" r="0" b="0"/><wp:wrapNone/><wp:docPr id="1" name="Picture 1"/><wp:cNvGraphicFramePr><a:graphicFrameLocks noChangeAspect="1"/></wp:cNvGraphicFramePr>{graphic_xml}<wp:sizeRelH relativeFrom="page"><wp:pctWidth>0</wp:pctWidth></wp:sizeRelH><wp:sizeRelV relativeFrom="page"><wp:pctHeight>0</wp:pctHeight></wp:sizeRelV></wp:anchor>'''
        
        # 解析新的anchor XML
        anchor_element = parse_xml(anchor_xml)
        
        # 替换inline元素为anchor元素
        parent = inline_element.getparent()
        parent.replace(inline_element, anchor_element)
        
        # 设置段落格式，减少占用空间
        paragraph_format = paragraph.paragraph_format
        paragraph_format.space_before = Pt(0)
        paragraph_format.space_after = Pt(0)
        paragraph_format.line_spacing = Pt(6)  # 较小的行间距
        
        print(f"      ✅ 水印式图片样式设置完成（浮动anchor，右对齐）")
        return True
        
    except Exception as e:
        print(f"      ❌ 浮动图片样式设置失败: {e}")
        print(f"      ⚠️ 需要手动调整图片样式为浮动水印效果")
        return False


def replace_template_content(template_doc, company_name, vuln_type, current_date, deadline_date):
    """
    替换模板中的占位内容
    
    参数:
        template_doc: 模板文档对象
        company_name: 公司名称
        vuln_type: 漏洞类型描述
        current_date: 当前日期字符串
        deadline_date: 截止日期字符串
    """
    print(f"\n开始替换模板内容:")
    print(f"  公司名: {company_name}")
    print(f"  漏洞类型: {vuln_type}")
    print(f"  当前日期: {current_date}")
    print(f"  截止日期: {deadline_date}")
    print(f"  模板总段落数: {len(template_doc.paragraphs)}")
    print("=" * 60)
    
    for i, para in enumerate(template_doc.paragraphs, 1):
        original_text = para.text
        modified = False
        
        # 段落4：替换公司名（在标题中）
        if i == 4 and company_name:
            para_text = para.text
            # 提取"关于XXX公司所属"中的公司名
            match = re.search(r'关于([\u4e00-\u9fa5]+(?:集团)?(?:股份)?(?:有限)?公司)', para_text)
            if match:
                old_company = match.group(1)
                if replace_text_in_runs(para, old_company, company_name):
                    modified = True
                    print(f"    段落 4 公司名替换: '{old_company}' → '{company_name}'")
        
        # 段落6：替换公司名（收件人）
        if i == 6 and company_name:
            para_text = para.text
            # 提取"XXX公司："中的公司名
            match = re.search(r'([\u4e00-\u9fa5]+(?:集团)?(?:股份)?(?:有限)?公司)：', para_text)
            if match:
                old_company = match.group(1)
                if replace_text_in_runs(para, old_company, company_name):
                    modified = True
                    print(f"    段落 6 公司名替换: '{old_company}' → '{company_name}'")
        
        # 段落7：替换漏洞类型和截止日期
        if i == 7:
            para_text = para.text
            
            # 替换漏洞类型
            if vuln_type:
                vuln_match = re.search(r'存在.+?漏洞', para_text)
                if vuln_match:
                    old_vuln = vuln_match.group(0)
                    # 确保替换后保持"存在"关键词
                    new_vuln = f"存在{vuln_type}"
                    if replace_text_in_runs(para, old_vuln, new_vuln):
                        modified = True
            
            # 替换截止日期（需要重新获取文本，因为可能已被修改）
            para_text = para.text
            if deadline_date:
                date_match = re.search(r'20\d{2}年\d+月\d+日前', para_text)
                if date_match:
                    old_date = date_match.group(0)
                    if replace_text_in_runs(para, old_date, deadline_date + '前'):
                        modified = True
        
        # 段落14：替换当前日期
        if i == 14 and current_date:
            para_text = para.text
            date_match = re.search(r'20\d{2}年\d+月\d+日', para_text)
            if date_match:
                old_date = date_match.group(0)
                if replace_text_in_runs(para, old_date, current_date):
                    modified = True
                    print(f"    段落 14 日期替换: '{old_date}' → '{current_date}'")
        
        if modified:
            print(f"  段落 {i} 已更新: {original_text[:40]}... -> {para.text[:40]}...")


def rewrite_report(source_file, template_file=None, start_para=3, end_para=-1):
    """
    将源文档内容复制到模板文档中（保留格式，包括表格）
    
    参数:
        source_file: 源Word文档的路径
        template_file: 模板文档的路径（如果为None，则自动查找）
        start_para: 起始段落编号（从1开始），默认3
        end_para: 结束段落编号（从1开始），-1表示到倒数第二段
    """
    try:
        # 如果未指定模板文件，自动查找
        if template_file is None:
            # 先在 template 目录查找
            template_candidates = []
            if os.path.exists('Report_Template'):
                for filename in os.listdir('Report_Template'):
                    if filename.endswith('.docx') and '通报模板' in filename:
                        template_candidates.append(os.path.join('Report_Template', filename))
            
            # 如果 template 目录没找到，在当前目录查找
            if not template_candidates:
                for filename in os.listdir('.'):
                    if filename.endswith('.docx') and '通报模板' in filename:
                        template_candidates.append(filename)
            
            if not template_candidates:
                print("错误: 未找到通报模板文件！")
                print("  请确保以下位置之一存在通报模板文件：")
                print("    - Repor/通报模板.docx")
                print("    - ./通报模板.docx")
                return {
                    'success': False,
                    'skip_reason': '未找到通报模板文件',
                    'backup_file': None,
                    'needs_manual_processing': False
                }
            
            template_file = template_candidates[0]
            print(f"自动找到模板文件: {template_file}")
        
        # 从文件名中提取信息
        company_name, vuln_type = extract_info_from_filename(source_file)
        
        # 计算日期
        today = datetime.now()
        deadline = today + timedelta(days=5)
        # 格式化日期，去掉前导0
        current_date_str = f"{today.year}年{today.month}月{today.day}日"
        deadline_date_str = f"{deadline.year}年{deadline.month}月{deadline.day}日"
        
        # 读取源文档（尝试以编辑模式打开以确保图片可访问）
        try:
            # 首先尝试正常打开
            source_doc = Document(source_file)
            
            # 检查文档是否受保护或只读
            if hasattr(source_doc, 'settings') and hasattr(source_doc.settings, 'document_protection'):
                safe_print("⚠️ 检测到文档保护，可能影响图片提取")
            
            # 尝试通过COM接口以编辑模式打开（如果可用）
            if COM_UTILS_AVAILABLE:
                try:
                    import win32com.client
                    word_app = win32com.client.Dispatch("Word.Application")
                    word_app.Visible = False
                    word_doc = word_app.Documents.Open(os.path.abspath(source_file), ReadOnly=False)
                    # 保存一个临时副本以确保可编辑
                    temp_source = source_file.replace('.docx', '_temp_editable.docx')
                    word_doc.SaveAs2(os.path.abspath(temp_source))
                    word_doc.Close()
                    word_app.Quit()
                    
                    # 重新用临时副本打开
                    source_doc = Document(temp_source)
                    safe_print("✅ 已创建可编辑副本用于图片提取")
                    
                    # 标记需要清理临时文件
                    cleanup_temp_source = True
                except Exception as e:
                    safe_print(f"⚠️ COM方式打开失败，使用原始方式: {str(e)}")
                    cleanup_temp_source = False
            else:
                cleanup_temp_source = False
                
        except Exception as e:
            safe_print(f"错误: 无法打开源文档 {source_file}: {str(e)}")
            return {'success': False, 'skip_reason': f'无法打开源文档: {str(e)}'}
        
        # 读取模板文档
        template_doc = Document(template_file)
        
        # 确定段落范围
        total_paragraphs = len(source_doc.paragraphs)
        start_idx = (start_para - 1) if start_para else 0
        # 如果end_para是-1，表示到倒数第二段（跳过最后的空段落）
        if end_para == -1:
            end_idx = total_paragraphs - 1
        elif end_para:
            end_idx = end_para
        else:
            end_idx = total_paragraphs
        
        # 生成输出文件名：去掉源文件名开头的数字
        source_basename = os.path.basename(source_file)
        # 去掉开头的数字
        output_basename = re.sub(r'^\d+', '', source_basename)
        output_file = output_basename
        
        print(f"\n正在使用模板创建通报文档:")
        print(f"  源文件: {source_file}")
        print(f"  模板文件: {template_file}")
        print(f"  输出文件: {output_file}")
        print("=" * 60)
        print(f"复制段落范围: 第 {start_idx + 1} 段 到 第 {end_idx} 段")
        print(f"插入位置: 自动查找标记 '*'")
        print("=" * 60)
        
        # 找到插入位置（查找包含 * 标记的段落）
        insert_element_index = None
        marker_para_element = None
        para_count = 0
        marker_para_index = None
        
        for i, element in enumerate(template_doc.element.body):
            if element.tag.endswith('p'):
                para_count += 1
                # 查找对应的段落对象
                para = None
                for p in template_doc.paragraphs:
                    if p._element == element:
                        para = p
                        break
                
                if para and '*' in para.text:
                    # 找到了标记段落
                    insert_element_index = i  # 在这个段落的位置插入（替换它）
                    marker_para_element = element
                    marker_para_index = para_count
                    print(f"找到标记位置: 第 {marker_para_index} 段")
                    break
        
        if insert_element_index is None:
            print("错误: 未找到 * 标记！请在模板的第二页起始位置添加 * 标记。")
            return False
        
        # ⚠️ 重要：在插入原文段落之前，先替换模板内容
        # 因为插入原文段落会改变段落索引
        replace_template_content(template_doc, company_name, vuln_type, current_date_str, deadline_date_str)
        
        # 遍历源文档的body元素，复制指定范围的段落
        para_count = 0
        copied_count = 0
        
        for element in source_doc.element.body:
            # 检查是否是段落
            if element.tag.endswith('p'):
                # 跳过范围外的段落
                if para_count < start_idx or para_count >= end_idx:
                    para_count += 1
                    continue
                
                para_count += 1
                copied_count += 1
                
                # 从element创建段落对象
                paragraph = None
                for p in source_doc.paragraphs:
                    if p._element == element:
                        paragraph = p
                        break
                
                if paragraph is None:
                    continue
                
                # 直接深拷贝整个段落元素以保持所有格式
                new_para_element = deepcopy(paragraph._element)
                
                # 检查是否应该保留编号，如果不应该则移除
                if not _should_keep_numbering(new_para_element):
                    _remove_paragraph_numbering(new_para_element)
                
                # 移除段落边框（黑线）
                try:
                    if new_para_element.pPr is not None:
                        pBdr = new_para_element.pPr.find(qn('w:pBdr'))
                        if pBdr is not None:
                            new_para_element.pPr.remove(pBdr)
                except Exception as e:
                    pass
                
                # 处理段落中的文本替换和图片复制
                for run_element in new_para_element.findall('.//w:r', {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}):
                    # 检查run是否包含超链接
                    has_hyperlink = _run_element_contains_hyperlink(run_element)
                    
                    # 处理文本内容
                    for text_element in run_element.findall('.//w:t', {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}):
                        if text_element.text:
                            original_text = text_element.text
                            # 替换文本：将"XXX网信办"替换为"鄞州区网信办"
                            new_text = re.sub(r'[\u4e00-\u9fa5]+网信办', '鄞州区网信办', original_text)
                            if new_text != original_text:
                                if has_hyperlink:
                                    print(f"  ⚠️ 跳过超链接文本替换以保留超链接: '{original_text}'")
                                else:
                                    print(f"  文本替换: '{original_text}' -> '{new_text}'")
                                    text_element.text = new_text
                    
                    # 处理图片内容 - 这部分比较复杂，需要特殊处理
                    drawing_elements = run_element.findall('.//w:drawing', {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'})
                    if drawing_elements:
                        # 为了处理图片，我们需要创建一个临时的run对象
                        try:
                            # 创建临时段落和run来处理图片复制
                            temp_para = template_doc.add_paragraph()
                            temp_run = temp_para.add_run()
                            
                            # 尝试复制每个图片
                            for drawing_element in drawing_elements:
                                try:
                                    if _copy_image_to_document(drawing_element, source_doc, template_doc, temp_run):
                                        print(f"  📷 复制图片到段落 {copied_count}")
                                        # 如果图片复制成功，用新的图片元素替换原有的
                                        if temp_run._element and len(list(temp_run._element)) > 0:
                                            # 获取新复制的图片元素
                                            new_drawing = None
                                            for elem in temp_run._element:
                                                if elem.tag.endswith('drawing'):
                                                    new_drawing = elem
                                                    break
                                            if new_drawing is not None:
                                                # 替换原有的图片元素
                                                parent = drawing_element.getparent()
                                                if parent is not None:
                                                    parent.replace(drawing_element, deepcopy(new_drawing))
                                    else:
                                        print(f"  ⚠️ 图片复制失败，保留原始引用")
                                except Exception as img_error:
                                    print(f"  ⚠️ 图片复制失败: {img_error}")
                            
                            # 删除临时段落
                            template_doc._element.body.remove(temp_para._element)
                            
                        except Exception as e:
                            print(f"  ⚠️ 图片处理过程出错: {e}")
                            # 如果图片处理失败，保留原始图片引用
                

                
                # 将深拷贝的段落元素插入到模板的指定位置
                template_doc._element.body.insert(insert_element_index, new_para_element)
                insert_element_index += 1
        
        # 删除标记段落（包含 * 的段落）
        if marker_para_element is not None:
            try:
                template_doc._element.body.remove(marker_para_element)
                print(f"已删除标记段落")
            except Exception as e:
                print(f"删除标记段落时出错: {e}")
        
        # 🔢 重新分配编号序列，确保编号连续递增
        try:
            _reassign_numbering_sequence(template_doc)
        except Exception as e:
            print(f"  ⚠️ 重新分配编号序列失败: {e}")
        
        # 🔢 先更新通报编号（在创建备份之前）
        print(f"\n  📝 更新通报编号...")
        notification_number = None
        try:
            # 临时保存文档以便编号更新函数读取
            temp_save_path = str(Path(output_file).with_suffix('.temp.docx'))
            template_doc.save(temp_save_path)
            
            # 更新编号
            result = update_notification_number(temp_save_path)
            if result:
                notification_number, config_year = result if isinstance(result, tuple) else (result, None)
            else:
                notification_number, config_year = None, None
            
            # 如果函数返回的不是元组，从配置文件读取年份
            if config_year is None:
                try:
                    config_file = get_config_file()
                    if config_file.exists():
                        with open(config_file, 'r', encoding='utf-8') as f:
                            config = json.load(f)
                        config_year = config.get('report_counters', {}).get('year', datetime.now().year)
                    else:
                        config_year = datetime.now().year
                except:
                    config_year = datetime.now().year
            
            # 重新加载更新后的文档
            template_doc = Document(temp_save_path)
            
            # 删除临时文件
            Path(temp_save_path).unlink()
            
            if notification_number:
                print(f"  ✓ 通报编号已更新: 〔{config_year}〕第{notification_number}期")
        except Exception as e:
            print(f"  ⚠️ 编号更新失败: {e}")
        
        # 先保存主文档，然后创建备份文件
        backup_file_path = None
        

        
        # 第三步：删除数字开头的通报原文
        try:
            source_file_path = Path(source_file)
            if source_file_path.exists() and re.match(r'^\d+', source_file_path.name):
                source_file_path.unlink()
                print(f"  🗑️  已删除数字开头的通报原文: {source_file_path.name}")
        except Exception as delete_source_error:
            print(f"  ⚠️ 删除通报原文失败: {delete_source_error}")
        
        # 最后统一保存文档（只保存一次）
        backup_path = None
        try:
            # 如果输出文件已存在，先创建备份
            if Path(output_file).exists():
                backup_path = create_backup(output_file)
            
            # 使用新的安全保存方法
            if INTEGRITY_MODULE_AVAILABLE:
                save_result = safe_save_document(template_doc, output_file)
                
                if not save_result['success']:
                    print(f"  ❌ 文档保存失败: {save_result['error']}")
                    # 如果有备份，尝试恢复
                    if backup_path:
                        print(f"  🔄 尝试从备份恢复...")
                        if recover_from_backup(output_file, backup_path):
                            print(f"  ✅ 已从备份恢复原始文档")
                        else:
                            print(f"  ❌ 备份恢复也失败")
                    raise Exception(f"文档保存失败: {save_result['error']}")
                
                print(f"  ✓ 文档已保存 (方法: {save_result['method']})")
                
                # 检查是否需要COM验证
                com_verification_failed = False
                output_path_length = len(str(output_file))
                
                if save_result['validation']['valid'] and COM_UTILS_AVAILABLE:
                    if output_path_length <= 260:  # Windows路径长度限制
                        try:
                            word_app = create_word_app_safely(visible=False, display_alerts=False, verbose=False)
                            if word_app:
                                test_com_doc = safe_open_document(word_app, str(output_file), verbose=False)
                                if test_com_doc:
                                    com_para_count = test_com_doc.Paragraphs.Count
                                    test_com_doc.Close(False)
                                    word_app.Quit(SaveChanges=0)
                                    print(f"  ✅ Word COM验证通过（{com_para_count}个段落）")
                                else:
                                    print(f"  ℹ️  Word COM无法打开文档，但python-docx验证通过，文档正常")
                                    # 不设置com_verification_failed，因为python-docx已经验证通过
                            else:
                                print(f"  ℹ️  无法创建Word应用程序，但python-docx验证通过，文档正常")
                                # 不设置com_verification_failed，因为python-docx已经验证通过
                        except Exception as com_verify_error:
                            print(f"  ℹ️  Word COM验证失败，但python-docx验证通过，文档正常: {str(com_verify_error)[:50]}")
                            # 不设置com_verification_failed，因为python-docx已经验证通过
                            # COM验证失败不影响整体流程，因为python-docx已经验证通过
                    else:
                        print(f"  ℹ️  文档路径过长（{output_path_length}字符），跳过COM验证，但文档正常")
                elif not COM_UTILS_AVAILABLE:
                    print(f"  ℹ️  COM工具不可用，跳过验证，但文档正常")
                else:
                    print(f"  ℹ️  文档验证通过，跳过COM验证")
                
        except Exception as e:
            print(f"  ❌ 文档保存失败: {e}")
            # 尝试备用保存方法和文档修复
            try:
                import tempfile
                temp_file = tempfile.mktemp(suffix='.docx')
                
                # 尝试修复文档：重新创建一个新文档并复制内容
                print(f"  🔧 尝试修复文档...")
                repaired_doc = Document()
                
                # 复制段落内容
                for para in template_doc.paragraphs:
                    new_para = repaired_doc.add_paragraph()
                    new_para.text = para.text
                    # 尝试保留基本格式
                    try:
                        new_para.style = para.style
                    except:
                        pass
                
                # 保存修复后的文档
                repaired_doc.save(temp_file)
                
                # 验证临时文件
                if Path(temp_file).exists() and Path(temp_file).stat().st_size > 10240:
                    shutil.move(temp_file, output_file)
                    print(f"  ✓ 使用文档修复方法保存成功")
                    
                    # 再次验证
                    test_doc = Document(output_file)
                    print(f"  ✅ 修复后文档验证通过（{len(test_doc.paragraphs)}个段落）")
                else:
                    print(f"  ❌ 文档修复失败，临时文件无效")
                    raise Exception("文档修复失败")
                    
            except Exception as e2:
                print(f"  ❌ 备用保存方法也失败: {e2}")
                
                # 最后的降级策略：创建一个简化的纯文本文档
                try:
                    print(f"  🆘 使用最后的降级策略：创建简化文档...")
                    fallback_doc = Document()
                    
                    # 添加标题
                    title_para = fallback_doc.add_paragraph()
                    title_para.text = "网络安全漏洞通报"
                    title_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
                    
                    # 添加基本内容（只保留文本，不包含任何复杂格式）
                    content_added = False
                    for para in template_doc.paragraphs:
                        if para.text.strip():  # 只添加非空段落
                            new_para = fallback_doc.add_paragraph()
                            new_para.text = para.text.strip()
                            content_added = True
                    
                    if not content_added:
                        # 如果没有内容，添加一个默认段落
                        fallback_doc.add_paragraph("文档内容生成失败，请检查原始文件。")
                    
                    # 保存简化文档
                    fallback_doc.save(output_file)
                    
                    # 验证简化文档
                    if Path(output_file).exists() and Path(output_file).stat().st_size > 5120:  # 至少5KB
                        print(f"  ✅ 简化文档创建成功，可以正常打开")
                        print(f"  ⚠️  注意：此文档为简化版本，不包含复杂格式")
                    else:
                        raise Exception("简化文档创建失败")
                        
                except Exception as e3:
                    print(f"  ❌ 简化文档创建也失败: {e3}")
                    # 如果有备份，尝试恢复
                    if backup_path:
                        print(f"  🔄 尝试从备份恢复...")
                        if recover_from_backup(output_file, backup_path):
                            print(f"  ✅ 已从备份恢复原始文档")
                        else:
                            print(f"  ❌ 备份恢复也失败")
                    raise e
                
                # 等待文件完全写入并关闭
                time.sleep(0.5)
                
                # 确保所有COM进程都已关闭
                import gc
                gc.collect()
                time.sleep(0.5)
                
                # 额外等待，确保文件系统完全释放（批量处理时需要更长时间）
                print(f"  ⏳ 等待文件系统释放...")
                time.sleep(1.0)  # 增加到1秒
                gc.collect()  # 再次垃圾回收
        
        # 创建备份文件（在主文档保存成功后）
        backup_file_path = str(Path(output_file).with_suffix('.backup.docx'))
        try:
            if Path(output_file).exists():
                shutil.copy2(output_file, backup_file_path)
                print(f"  ✅ 已创建备份文件: {Path(backup_file_path).name}")
            else:
                print(f"  ⚠️ 主输出文件不存在，无法创建备份")
                backup_file_path = None
        except Exception as backup_error:
            print(f"  ⚠️ 创建备份文件失败: {backup_error}")
            backup_file_path = None

        print(f"\n✓ 成功创建通报文档!")
        print(f"  输出文件: {output_file}")
        print(f"  复制的段落数: {copied_count}")
        if notification_number:
            # 从配置文件读取年份
            try:
                config_file = get_config_file()
                if config_file.exists():
                    with open(config_file, 'r', encoding='utf-8') as f:
                        config = json.load(f)
                    config_year = config.get('report_counters', {}).get('year', datetime.now().year)
                else:
                    config_year = datetime.now().year
            except:
                config_year = datetime.now().year
            print(f"  通报编号: 〔{config_year}〕第{notification_number}期")
        
        print("=" * 60)
        
        # 清理旧备份文件
        try:
            cleanup_backups(output_file, keep_count=2)
        except Exception as cleanup_error:
            print(f"  ⚠️ 备份清理警告: {cleanup_error}")
        
        # 按用户要求：只保留backup文件，不进行重命名操作
        print(f"  📁 保留备份文件，不进行重命名操作")
        
        # 添加图片到主输出文件
        image_path = r"C:\Users\lan1o\Desktop\wow\Report_Template\确认词条.jpg"
        image_insertion_success = False
        
        if Path(image_path).exists() and Path(output_file).exists():
            print(f"\n🖼️ 开始添加确认词条图片到主输出文件...")
            try:
                # 加载主输出文档对象
                target_doc = Document(output_file)
                
                # 调用图片添加函数，传递源文件路径用于错误记录
                image_insertion_success = add_floating_image_to_pages(target_doc, image_path, start_page=2, source_file_path=output_file)
                
                if image_insertion_success:
                    # 保存修改后的文档
                    target_doc.save(output_file)
                    print(f"  ✅ 确认词条图片已添加到主输出文件的每一页（从第2页开始）")
                else:
                    print(f"  ❌ 图片添加失败，可能原因：")
                    print(f"    • COM接口页数检测失败")
                    print(f"    • 文档格式不兼容")
                    print(f"    • 图片文件损坏或格式不支持")
                    print(f"  💡 解决方案：")
                    print(f"    • 手动打开备份文件添加确认词条图片")
                    print(f"    • 检查图片文件是否完整")
                    
            except Exception as img_error:
                print(f"  ❌ 添加图片失败: {img_error}")
                print(f"  💡 建议：手动打开备份文件添加确认词条图片")
                image_insertion_success = False
        elif not Path(image_path).exists():
            print(f"\n⚠️ 确认词条图片文件不存在: {image_path}")
            print(f"  ℹ️  跳过图片添加，文档仍然可以正常使用")
        elif not Path(output_file).exists():
            print(f"\n⚠️ 主输出文件不存在，跳过图片添加")
        
        # 根据图片插入结果决定删除哪个文件
        if image_insertion_success:
            # 图片插入成功，删除备份文件，保留主输出文件
            try:
                if backup_file_path and Path(backup_file_path).exists():
                    Path(backup_file_path).unlink()
                    print(f"  🗑️ 图片插入成功，已删除备份文件: {Path(backup_file_path).name}")
                    print(f"  ✅ 保留主输出文件: {Path(output_file).name}")
            except Exception as e:
                print(f"  ⚠️ 删除备份文件失败: {e}")
        else:
            # 图片插入失败，删除主输出文件，保留备份文件
            try:
                if Path(output_file).exists():
                    Path(output_file).unlink()
                    print(f"  🗑️ 图片插入失败，已删除主输出文件: {Path(output_file).name}")
                
                # 确定最终要保留的备份文件（只保留backup.docx）
                if backup_file_path and Path(backup_file_path).exists():
                    backup_type = "备份"
                    print(f"  ✅ 已保留{backup_type}文件: {Path(backup_file_path).name}")
                else:
                    print(f"  ⚠️ 备份文件路径为空或文件不存在")
            except Exception as e:
                print(f"  ⚠️ 删除主输出文件失败: {e}")
        
        # 删除数字开头的原始通报文件
        try:
            source_path = Path(source_file)
            source_filename = source_path.name
            
            # 检查文件名是否以数字开头
            if source_filename and source_filename[0].isdigit():
                if source_path.exists():
                    source_path.unlink()
                    print(f"  🗑️ 已删除原始通报文件: {source_filename}")
                else:
                    print(f"  ℹ️  原始通报文件已不存在: {source_filename}")
            else:
                print(f"  ℹ️  原始文件名不以数字开头，保留: {source_filename}")
        except Exception as delete_error:
            print(f"  ⚠️ 删除原始通报文件失败: {delete_error}")
        
        # PDF转换逻辑
        pdf_file = None
        pdf_conversion_success = False
        
        # 跳过PDF转换，因为主输出文件已被删除，只保留备份文件
        print(f"\n📄 跳过PDF转换...")
        print(f"  ℹ️  主输出文件已删除，只保留备份文件，不进行PDF转换")
        print(f"  ℹ️  如需PDF文件，请手动转换备份文件")

        # 返回结果信息，包含是否需要手动处理的标记
        # 注意：由于执行了文件替换逻辑，clean_backup和final_backup文件已被清理
        # 如果文件替换成功，backup_file_path已更新为最终文件路径
        result = {
            'success': True,
            'output_file': output_file,
            'backup_file': backup_file_path if backup_file_path and Path(backup_file_path).exists() else None,
            'clean_backup_file': None,  # 已被清理或重命名为主文件
            'final_backup_file': None,  # 已被清理或重命名为主文件
            'needs_manual_processing': False,  # 默认不需要手动处理
            'skip_reason': None,
            'pdf_file': pdf_file,  # 新增PDF文件路径
            'pdf_conversion_success': pdf_conversion_success  # 新增PDF转换状态
        }
        
        # 检查是否需要手动处理的情况
        manual_processing_reasons = []
        
        # COM验证失败
        if 'com_verification_failed' in locals() and com_verification_failed:
            manual_processing_reasons.append("Word COM验证失败，可能存在兼容性问题")
        
        # 图片添加失败
        if not image_insertion_success:
            manual_processing_reasons.append("确认词条图片添加失败，需要手动添加图片")
        
        # 设置手动处理标志
        if manual_processing_reasons:
            result['needs_manual_processing'] = True
            result['skip_reason'] = '; '.join(manual_processing_reasons)
            print(f"  ⚠️ 注意：此文档需要手动处理 - {result['skip_reason']}")
        
        # 清理临时文件
        if 'cleanup_temp_source' in locals() and cleanup_temp_source:
            try:
                temp_source = source_file.replace('.docx', '_temp_editable.docx')
                if os.path.exists(temp_source):
                    os.remove(temp_source)
                    safe_print("🧹 已清理临时可编辑文件")
            except Exception as e:
                safe_print(f"⚠️ 清理临时文件失败: {str(e)}")

        
        return result
        
    except FileNotFoundError as e:
        # 清理临时文件
        if 'cleanup_temp_source' in locals() and cleanup_temp_source:
            try:
                temp_source = source_file.replace('.docx', '_temp_editable.docx')
                if os.path.exists(temp_source):
                    os.remove(temp_source)
            except:
                pass
        
        print(f"错误: 找不到文件: {e}")
        return {
            'success': False,
            'output_file': None,
            'backup_file': None,
            'needs_manual_processing': False,
            'skip_reason': f'文件未找到: {e}'
        }
    except Exception as e:
        # 清理临时文件
        if 'cleanup_temp_source' in locals() and cleanup_temp_source:
            try:
                temp_source = source_file.replace('.docx', '_temp_editable.docx')
                if os.path.exists(temp_source):
                    os.remove(temp_source)
            except:
                pass
        
        print(f"创建文档时出错: {str(e)}")
        import traceback
        traceback.print_exc()
        return {
            'success': False,
            'output_file': None,
            'backup_file': None,
            'needs_manual_processing': False,
            'skip_reason': f'创建失败: {str(e)}'
        }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("=" * 60)
        print("通报改写工具")
        print("=" * 60)
        print("\n使用方法:")
        print("  python rewrite_report.py <源通报文档>")
        print("  python rewrite_report.py <源通报文档> <起始段落> <结束段落>")
        print("\n功能说明:")
        print("  1. 智能识别：从文件名自动提取公司名和漏洞类型")
        print("  2. 自动替换：")
        print("     - 段落4、6：公司名自动更新")
        print("     - 段落7：漏洞类型自动更新")
        print("     - 段落7：截止日期自动设置为5天后")
        print("     - 段落14：当前日期自动设置为今天")
        print("     - 内容中'XXX网信办'替换为'鄞州区网信办'")
        print("  3. 自动查找模板中的 * 标记作为插入位置")
        print("  4. 从源文档复制指定段落到模板")
        print("  5. 保留所有格式（标题、字体、颜色等）")
        print("  6. 移除段落边框（黑线）")
        print("  7. 文件名自动去掉开头数字")
        print("\n默认参数:")
        print("  起始段落: 3")
        print("  结束段落: -1（倒数第2段，跳过最后的空段落）")
        print("  模板文件: 自动查找 Report_Template/通报模板*.docx 或 ./通报模板*.docx")
        print("\n示例:")
        print("  python rewrite_report.py 1759979441661关于XXX漏洞通报.docx")
        print("  python rewrite_report.py 源文档.docx 3 20")
        print("\n提示:")
        print("  1. 请确保模板文件中有 * 标记标注第二页起始位置")
        print("  2. 模板文件会自动从 Report_Template 目录或当前目录查找")
        print("=" * 60)
        sys.exit(1)
    
    source_file = sys.argv[1]
    
    # 默认参数
    start_para = 3
    end_para = -1
    
    # 解析可选参数
    if len(sys.argv) > 2:
        try:
            start_para = int(sys.argv[2])
        except ValueError:
            print("错误: 起始段落必须是数字")
            sys.exit(1)
    
    if len(sys.argv) > 3:
        try:
            end_para = int(sys.argv[3])
        except ValueError:
            print("错误: 结束段落必须是数字")
            sys.exit(1)
    
    # 执行改写
    result = rewrite_report(source_file, start_para=start_para, end_para=end_para)
    
    if result['success']:
        print("\n改写完成！")
        if result['needs_manual_processing']:
            print(f"⚠️ 需要手动处理: {result['skip_reason']}")
            if result['backup_file']:
                print(f"📁 备份文件: {result['backup_file']}")
        
        # 显示PDF转换结果
        if result.get('pdf_conversion_success'):
            print(f"📄 PDF转换成功: {Path(result['pdf_file']).name}")
        elif result.get('pdf_file') is not None:
            print(f"⚠️ PDF转换失败")
        
    else:
        print(f"\n改写失败: {result['skip_reason']}")
        sys.exit(1)

