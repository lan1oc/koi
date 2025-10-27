#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
响应文件美化工具
用于美化企业查询脚本生成的响应文件，提高可读性
"""

import os
import json
import re
from datetime import datetime
from pathlib import Path
import argparse

class ResponseBeautifier:
    def __init__(self, output_dir):
        self.output_dir = Path(output_dir)
        self.beautified_count = 0
        self.error_count = 0
        
    def beautify_json_file(self, file_path):
        """美化JSON文件"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # 添加更多信息和美化格式
            if 'url' in data:
                # 解析URL信息
                url_info = self._parse_url_info(data['url'])
                data['url_info'] = url_info
            
            # 添加请求分析
            if 'headers' in data:
                data['analysis'] = self._analyze_headers(data['headers'])
            
            # 美化时间戳
            if 'timestamp' in data:
                data['formatted_time'] = self._format_timestamp(data['timestamp'])
            
            # 重新写入文件，使用美化的格式
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2, separators=(',', ': '))
            
            self.beautified_count += 1
            return True
            
        except Exception as e:
            print(f"❌ 美化JSON文件失败 {file_path}: {e}")
            self.error_count += 1
            return False
    
    def beautify_content_file(self, file_path):
        """美化内容文件"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # 尝试解析为JSON并美化
            try:
                json_data = json.loads(content)
                beautified_content = json.dumps(json_data, ensure_ascii=False, indent=2, separators=(',', ': '))
                
                # 添加文件头部信息
                header = self._create_content_header(file_path, "JSON")
                final_content = header + "\n" + beautified_content
                
            except json.JSONDecodeError:
                # 如果不是JSON，则添加HTML美化或其他格式处理
                if '<html' in content.lower() or '<!doctype' in content.lower():
                    final_content = self._beautify_html_content(content, file_path)
                else:
                    # 普通文本，添加头部信息
                    header = self._create_content_header(file_path, "TEXT")
                    final_content = header + "\n" + content
            
            # 写回文件
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(final_content)
            
            self.beautified_count += 1
            return True
            
        except Exception as e:
            print(f"❌ 美化内容文件失败 {file_path}: {e}")
            self.error_count += 1
            return False
    
    def _parse_url_info(self, url):
        """解析URL信息"""
        info = {
            "domain": "",
            "path": "",
            "query_params": {},
            "api_type": "unknown"
        }
        
        try:
            from urllib.parse import urlparse, parse_qs
            parsed = urlparse(url)
            info["domain"] = parsed.netloc
            info["path"] = parsed.path
            info["query_params"] = {k: v[0] if len(v) == 1 else v for k, v in parse_qs(parsed.query).items()}
            
            # 判断API类型
            if "tianyancha.com" in parsed.netloc:
                if "/nsearch" in parsed.path:
                    info["api_type"] = "企业搜索"
                elif "/icpRecordList" in parsed.path:
                    info["api_type"] = "ICP备案查询"
                elif "/appbkinfo" in parsed.path:
                    info["api_type"] = "APP备案信息"
                elif "/list" in parsed.path:
                    info["api_type"] = "列表查询"
                else:
                    info["api_type"] = "天眼查API"
            elif "aiqicha.baidu.com" in parsed.netloc:
                info["api_type"] = "爱企查API"
            
        except Exception:
            pass
        
        return info
    
    def _analyze_headers(self, headers):
        """分析响应头"""
        analysis = {
            "content_type": headers.get("Content-Type", "unknown"),
            "encoding": "unknown",
            "cache_policy": "unknown",
            "server_info": headers.get("Server", "unknown"),
            "security_headers": []
        }
        
        # 分析内容类型和编码
        content_type = headers.get("Content-Type", "")
        if "charset=" in content_type:
            analysis["encoding"] = content_type.split("charset=")[1].split(";")[0]
        
        # 分析缓存策略
        cache_control = headers.get("cache-control", headers.get("Cache-Control", ""))
        if cache_control:
            analysis["cache_policy"] = cache_control
        
        # 检查安全头
        security_headers = ["Access-Control-Allow-Origin", "X-Frame-Options", "X-Content-Type-Options"]
        for header in security_headers:
            if header in headers:
                analysis["security_headers"].append({
                    "name": header,
                    "value": headers[header]
                })
        
        return analysis
    
    def _format_timestamp(self, timestamp):
        """格式化时间戳"""
        try:
            # 假设时间戳格式为 YYYYMMDD_HHMMSS
            dt = datetime.strptime(timestamp, "%Y%m%d_%H%M%S")
            return {
                "readable": dt.strftime("%Y年%m月%d日 %H:%M:%S"),
                "iso": dt.isoformat(),
                "weekday": dt.strftime("%A"),
                "weekday_cn": ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][dt.weekday()]
            }
        except Exception:
            return {"readable": timestamp, "iso": timestamp}
    
    def _create_content_header(self, file_path, content_type):
        """创建内容文件头部"""
        file_name = Path(file_path).name
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        header = f"""/*
 * 文件名: {file_name}
 * 内容类型: {content_type}
 * 美化时间: {timestamp}
 * 美化工具: ResponseBeautifier v1.0
 * ================================================
 */"""
        return header
    
    def _beautify_html_content(self, content, file_path):
        """美化HTML内容"""
        try:
            # 简单的HTML美化
            import re
            
            # 添加缩进
            content = re.sub(r'><', '>\n<', content)
            
            # 添加文件头
            header = self._create_content_header(file_path, "HTML")
            return header + "\n" + content
            
        except Exception:
            header = self._create_content_header(file_path, "HTML")
            return header + "\n" + content
    
    def beautify_directory(self):
        """美化整个目录"""
        print(f"🎨 开始美化目录: {self.output_dir}")
        print("="*60)
        
        # 处理所有JSON文件
        json_files = list(self.output_dir.glob("*_headers.json"))
        for json_file in json_files:
            print(f"📄 美化JSON文件: {json_file.name}")
            self.beautify_json_file(json_file)
        
        # 处理所有内容文件
        content_files = list(self.output_dir.glob("*_content.txt"))
        for content_file in content_files:
            print(f"📄 美化内容文件: {content_file.name}")
            self.beautify_content_file(content_file)
        
        # 创建汇总报告
        self.create_summary_report()
        
        print("="*60)
        print(f"✅ 美化完成！")
        print(f"📊 成功处理: {self.beautified_count} 个文件")
        if self.error_count > 0:
            print(f"❌ 处理失败: {self.error_count} 个文件")
    
    def create_summary_report(self):
        """创建汇总报告"""
        try:
            report_path = self.output_dir / "美化报告.md"
            
            # 收集文件信息
            json_files = list(self.output_dir.glob("*_headers.json"))
            content_files = list(self.output_dir.glob("*_content.txt"))
            
            report_content = f"""# 响应文件美化报告

## 📊 统计信息
- **美化时间**: {datetime.now().strftime("%Y年%m月%d日 %H:%M:%S")}
- **处理目录**: {self.output_dir}
- **JSON文件数量**: {len(json_files)}
- **内容文件数量**: {len(content_files)}
- **成功处理**: {self.beautified_count} 个文件
- **处理失败**: {self.error_count} 个文件

## 📁 文件列表

### JSON响应头文件
"""
            
            for json_file in sorted(json_files):
                try:
                    with open(json_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    
                    url_info = data.get('url_info', {})
                    api_type = url_info.get('api_type', '未知')
                    status_code = data.get('status_code', '未知')
                    
                    report_content += f"- **{json_file.name}**\n"
                    report_content += f"  - API类型: {api_type}\n"
                    report_content += f"  - 状态码: {status_code}\n"
                    report_content += f"  - URL: {data.get('url', '未知')}\n\n"
                except Exception:
                    report_content += f"- **{json_file.name}** (解析失败)\n\n"
            
            report_content += "\n### 内容响应文件\n"
            
            for content_file in sorted(content_files):
                file_size = content_file.stat().st_size
                size_str = f"{file_size:,} 字节"
                if file_size > 1024:
                    size_str += f" ({file_size/1024:.1f} KB)"
                
                report_content += f"- **{content_file.name}**\n"
                report_content += f"  - 文件大小: {size_str}\n\n"
            
            report_content += f"""
## 🎨 美化说明

### JSON文件美化内容
1. **URL信息解析**: 自动解析域名、路径、查询参数
2. **API类型识别**: 根据URL自动识别API类型
3. **响应头分析**: 分析内容类型、编码、缓存策略等
4. **时间格式化**: 将时间戳转换为可读格式
5. **JSON格式化**: 使用2空格缩进，中文不转义

### 内容文件美化内容
1. **JSON自动格式化**: 检测JSON内容并自动格式化
2. **HTML简单美化**: 为HTML内容添加换行
3. **文件头信息**: 为所有文件添加美化信息头
4. **编码统一**: 统一使用UTF-8编码

---
*报告生成时间: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}*
*美化工具: ResponseBeautifier v1.0*
"""
            
            with open(report_path, 'w', encoding='utf-8') as f:
                f.write(report_content)
            
            print(f"📋 汇总报告已生成: {report_path}")
            
        except Exception as e:
            print(f"❌ 生成汇总报告失败: {e}")

def main():
    parser = argparse.ArgumentParser(description="响应文件美化工具")
    parser.add_argument("directory", help="要美化的目录路径")
    
    args = parser.parse_args()
    
    if not os.path.exists(args.directory):
        print(f"❌ 目录不存在: {args.directory}")
        return
    
    beautifier = ResponseBeautifier(args.directory)
    beautifier.beautify_directory()

if __name__ == "__main__":
    main()