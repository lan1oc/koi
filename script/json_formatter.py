#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
JSON格式化工具
用于提取并格式化天眼查响应文件中的压缩JSON数据
"""

import json
import re
import os

def format_tianyancha_json():
    """提取并格式化天眼查响应文件中的JSON数据"""
    
    # 输入文件路径
    input_file = 'c:/Users/lan1o/Desktop/wow/script/output/tianyancha/001_20251027_121205_get_nsearch-key_杭州安恒_content.txt'
    
    # 输出文件路径
    output_file = 'c:/Users/lan1o/Desktop/wow/script/output/tianyancha/formatted_next_data.json'
    
    try:
        # 读取原始文件
        print(f"正在读取文件: {input_file}")
        with open(input_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # 查找script标签中的JSON数据
        print("正在搜索__NEXT_DATA__脚本标签...")
        pattern = r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>'
        match = re.search(pattern, content, re.DOTALL)
        
        if match:
            json_str = match.group(1)
            print(f"找到JSON数据，原始大小: {len(json_str)} 字符")
            
            try:
                # 解析JSON
                print("正在解析JSON数据...")
                json_data = json.loads(json_str)
                
                # 格式化JSON
                print("正在格式化JSON数据...")
                formatted_json = json.dumps(json_data, indent=2, ensure_ascii=False)
                
                # 确保输出目录存在
                os.makedirs(os.path.dirname(output_file), exist_ok=True)
                
                # 保存格式化后的JSON
                with open(output_file, 'w', encoding='utf-8') as f:
                    f.write(formatted_json)
                
                print(f"✅ 成功提取并格式化JSON数据!")
                print(f"📁 保存位置: {output_file}")
                print(f"📊 格式化后大小: {len(formatted_json)} 字符")
                print(f"📊 原始压缩大小: {len(json_str)} 字符")
                print(f"📈 可读性提升: {len(formatted_json) / len(json_str):.2f}x")
                
                # 显示JSON结构概览
                print("\n📋 JSON数据结构概览:")
                if isinstance(json_data, dict):
                    for key in list(json_data.keys())[:5]:  # 显示前5个键
                        print(f"  - {key}: {type(json_data[key]).__name__}")
                    if len(json_data) > 5:
                        print(f"  ... 还有 {len(json_data) - 5} 个键")
                
                return True
                
            except json.JSONDecodeError as e:
                print(f"❌ JSON解析错误: {e}")
                return False
                
        else:
            print("❌ 未找到__NEXT_DATA__脚本标签")
            return False
            
    except FileNotFoundError:
        print(f"❌ 文件未找到: {input_file}")
        return False
    except Exception as e:
        print(f"❌ 处理过程中发生错误: {e}")
        return False

if __name__ == "__main__":
    print("🚀 开始格式化天眼查JSON数据...")
    success = format_tianyancha_json()
    
    if success:
        print("\n🎉 格式化完成!")
    else:
        print("\n💥 格式化失败!")