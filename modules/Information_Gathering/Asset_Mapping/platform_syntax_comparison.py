#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
平台语法对比文档模块
提供FOFA、Hunter、Quake三大平台的语法对比
"""

def get_platform_comparison_doc():
    """获取平台语法对比文档内容"""
    return """
    <div style='font-family: Consolas, Monaco, monospace; line-height: 1.6;'>
    <h2 style='color: #007bff; border-bottom: 2px solid #007bff; padding-bottom: 10px;'>三大平台语法对比</h2>
    
    <h3 style='color: #28a745; margin-top: 20px;'>基础查询对比</h3>
    <table style='border-collapse: collapse; width: 100%; margin: 10px 0;'>
    <tr style='background-color: #f8f9fa;'>
        <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>查询类型</th>
        <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>FOFA</th>
        <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>Hunter</th>
        <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>Quake</th>
    </tr>
    <tr>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold;'>IP地址</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>ip="1.1.1.1"</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>ip="1.1.1.1"</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>ip:"1.1.1.1"</td>
    </tr>
    <tr>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold;'>端口</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>port="80"</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>ip.port="80"</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>port:80</td>
    </tr>
    <tr>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold;'>域名</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>domain="example.com"</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>domain="example.com"</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>hostname:"example.com"</td>
    </tr>
    <tr>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold;'>网页标题</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>title="管理"</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>web.title="管理"</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>title:"管理"</td>
    </tr>
    <tr>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold;'>网页内容</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>body="login"</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>web.body="login"</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>body:"login"</td>
    </tr>
    <tr>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold;'>应用识别</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>app="nginx"</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>web.framework="nginx"</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>app:"nginx"</td>
    </tr>
    <tr>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold;'>服务器</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>server="Apache"</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>header.server="Apache"</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>server:"Apache"</td>
    </tr>
    <tr>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold;'>国家</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>country="CN"</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>ip.country="中国"</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>country:"China"</td>
    </tr>
    </table>
    
    <h3 style='color: #28a745; margin-top: 20px;'>逻辑运算符对比</h3>
    <table style='border-collapse: collapse; width: 100%; margin: 10px 0;'>
    <tr style='background-color: #f8f9fa;'>
        <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>运算符</th>
        <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>FOFA</th>
        <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>Hunter</th>
        <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>Quake</th>
    </tr>
    <tr>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold;'>逻辑与</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>&&</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>&&</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>AND 或 &&</td>
    </tr>
    <tr>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold;'>逻辑或</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>||</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>||</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>OR 或 ||</td>
    </tr>
    <tr>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold;'>逻辑非</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>!=</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>!=</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>NOT 或 -</td>
    </tr>
    <tr>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold;'>精确匹配</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>="value"</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>=="value"</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>:"value"</td>
    </tr>
    </table>
    
    <h3 style='color: #28a745; margin-top: 20px;'>特色功能对比</h3>
    <table style='border-collapse: collapse; width: 100%; margin: 10px 0;'>
    <tr style='background-color: #f8f9fa;'>
        <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>功能</th>
        <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>FOFA</th>
        <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>Hunter</th>
        <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>Quake</th>
    </tr>
    <tr>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold;'>网站相似性</td>
        <td style='border: 1px solid #dee2e6; padding: 8px;'>❌ 不支持</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>web.similar="site:443"</td>
        <td style='border: 1px solid #dee2e6; padding: 8px;'>❌ 不支持</td>
    </tr>
    <tr>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold;'>图标哈希</td>
        <td style='border: 1px solid #dee2e6; padding: 8px;'>❌ 不支持</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>web.icon="hash"</td>
        <td style='border: 1px solid #dee2e6; padding: 8px;'>❌ 不支持</td>
    </tr>
    <tr>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold;'>JARM指纹</td>
        <td style='border: 1px solid #dee2e6; padding: 8px;'>❌ 不支持</td>
        <td style='border: 1px solid #dee2e6; padding: 8px;'>❌ 不支持</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>jarm:"fingerprint"</td>
    </tr>
    <tr>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold;'>端口数量</td>
        <td style='border: 1px solid #dee2e6; padding: 8px;'>❌ 不支持</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>ip.port_count>"5"</td>
        <td style='border: 1px solid #dee2e6; padding: 8px;'>❌ 不支持</td>
    </tr>
    <tr>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold;'>ICP备案</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>icp="备案号"</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>icp.name!=""</td>
        <td style='border: 1px solid #dee2e6; padding: 8px;'>❌ 不支持</td>
    </tr>
    <tr>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold;'>范围查询</td>
        <td style='border: 1px solid #dee2e6; padding: 8px;'>❌ 不支持</td>
        <td style='border: 1px solid #dee2e6; padding: 8px;'>❌ 不支持</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>port:[80 TO 90]</td>
    </tr>
    <tr>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold;'>通配符</td>
        <td style='border: 1px solid #dee2e6; padding: 8px;'>❌ 不支持</td>
        <td style='border: 1px solid #dee2e6; padding: 8px;'>❌ 不支持</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>hostname:"*.com"</td>
    </tr>
    </table>
    
    <h3 style='color: #28a745; margin-top: 20px;'>平台特点总结</h3>
    <div style='background-color: #e9ecef; padding: 15px; border-radius: 8px; margin: 10px 0;'>
    <h4 style='color: #007bff; margin-top: 0;'>FOFA</h4>
    <ul>
        <li>✅ 语法简洁，易于上手</li>
        <li>✅ 支持丰富的基础字段</li>
        <li>✅ 数据更新及时</li>
        <li>❌ 缺少高级查询功能</li>
    </ul>
    
    <h4 style='color: #007bff;'>Hunter</h4>
    <ul>
        <li>✅ 支持网站相似性查询</li>
        <li>✅ 支持图标哈希匹配</li>
        <li>✅ 支持端口数量统计</li>
        <li>✅ 详细的ICP备案信息</li>
        <li>❌ 语法相对复杂</li>
    </ul>
    
    <h4 style='color: #007bff;'>Quake</h4>
    <ul>
        <li>✅ 支持JARM指纹识别</li>
        <li>✅ 支持范围查询</li>
        <li>✅ 支持通配符查询</li>
        <li>✅ 支持正则表达式</li>
        <li>❌ 部分功能需要高级权限</li>
    </ul>
    </div>
    
    <h3 style='color: #28a745; margin-top: 20px;'>查询建议</h3>
    <div style='background-color: #d4edda; padding: 15px; border-radius: 8px; margin: 10px 0; border-left: 4px solid #28a745;'>
    <h4 style='color: #155724; margin-top: 0;'>💡 使用建议</h4>
    <ul style='color: #155724;'>
        <li><strong>新手用户：</strong>建议从FOFA开始，语法简单易懂</li>
        <li><strong>高级用户：</strong>根据需求选择平台特色功能</li>
        <li><strong>批量查询：</strong>建议使用统一查询功能，自动转换语法</li>
        <li><strong>精确查询：</strong>Hunter的精确匹配功能更强大</li>
        <li><strong>研究分析：</strong>Quake的高级查询功能更适合深度分析</li>
    </ul>
    </div>
    </div>
    """

def get_syntax_conversion_rules():
    """获取语法转换规则"""
    return {
        "ip": {
            "fofa": 'ip="{value}"',
            "hunter": 'ip="{value}"',
            "quake": 'ip:"{value}"'
        },
        "port": {
            "fofa": 'port="{value}"',
            "hunter": 'ip.port="{value}"',
            "quake": 'port:{value}'
        },
        "domain": {
            "fofa": 'domain="{value}"',
            "hunter": 'domain="{value}"',
            "quake": 'hostname:"{value}"'
        },
        "title": {
            "fofa": 'title="{value}"',
            "hunter": 'web.title="{value}"',
            "quake": 'title:"{value}"'
        },
        "body": {
            "fofa": 'body="{value}"',
            "hunter": 'web.body="{value}"',
            "quake": 'body:"{value}"'
        },
        "server": {
            "fofa": 'server="{value}"',
            "hunter": 'header.server="{value}"',
            "quake": 'server:"{value}"'
        },
        "app": {
            "fofa": 'app="{value}"',
            "hunter": 'web.framework="{value}"',
            "quake": 'app:"{value}"'
        },
        "country": {
            "fofa": 'country="{value}"',
            "hunter": 'ip.country="{value}"',
            "quake": 'country:"{value}"'
        }
    }

def convert_query_between_platforms(query: str, from_platform: str, to_platform: str) -> str:
    """在平台间转换查询语句"""
    conversion_rules = get_syntax_conversion_rules()
    
    # 这里可以实现更复杂的转换逻辑
    # 目前返回基础转换示例
    return query

if __name__ == "__main__":
    print("平台语法对比文档模块加载成功")
    rules = get_syntax_conversion_rules()
    print("\n支持的字段转换:")
    for field in rules.keys():
        print(f"  {field}")