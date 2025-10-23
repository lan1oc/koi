#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FOFA语法文档模块
提供FOFA查询语法的详细说明和示例
"""

def get_fofa_syntax_doc():
    """获取FOFA语法文档内容"""
    return """
    <div style='font-family: Consolas, Monaco, monospace; line-height: 1.6;'>
    <h2 style='color: #007bff; border-bottom: 2px solid #007bff; padding-bottom: 10px;'>FOFA 网络空间测绘查询语法文档</h2>
    
    <h3 style='color: #28a745; margin-top: 20px;'>基础语法</h3>
    <table style='border-collapse: collapse; width: 100%; margin: 10px 0;'>
    <tr style='background-color: #f8f9fa;'>
        <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>语法</th>
        <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>示例</th>
        <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>用途说明</th>
    </tr>
    <tr>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>ip</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>ip="1.1.1.1"</td>
        <td style='border: 1px solid #dee2e6; padding: 8px;'>通过IP地址进行查询</td>
    </tr>
    <tr>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>port</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>port="80"</td>
        <td style='border: 1px solid #dee2e6; padding: 8px;'>通过端口进行查询</td>
    </tr>
    <tr>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>domain</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>domain="baidu.com"</td>
        <td style='border: 1px solid #dee2e6; padding: 8px;'>通过域名进行查询</td>
    </tr>
    <tr>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>host</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>host="www.baidu.com"</td>
        <td style='border: 1px solid #dee2e6; padding: 8px;'>通过主机名进行查询</td>
    </tr>
    <tr>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>title</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>title="百度"</td>
        <td style='border: 1px solid #dee2e6; padding: 8px;'>通过网站标题进行查询</td>
    </tr>
    <tr>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>body</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>body="管理"</td>
        <td style='border: 1px solid #dee2e6; padding: 8px;'>通过网页内容进行查询</td>
    </tr>
    <tr>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>app</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>app="Apache"</td>
        <td style='border: 1px solid #dee2e6; padding: 8px;'>通过应用类型进行查询</td>
    </tr>
    <tr>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>protocol</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>protocol="https"</td>
        <td style='border: 1px solid #dee2e6; padding: 8px;'>通过协议类型进行查询</td>
    </tr>
    <tr>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>server</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>server="nginx"</td>
        <td style='border: 1px solid #dee2e6; padding: 8px;'>通过Web服务器进行查询</td>
    </tr>
    <tr>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>header</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>header="nginx"</td>
        <td style='border: 1px solid #dee2e6; padding: 8px;'>通过HTTP响应头进行查询</td>
    </tr>
    <tr>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>banner</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>banner="SSH-2.0"</td>
        <td style='border: 1px solid #dee2e6; padding: 8px;'>通过协议banner进行查询</td>
    </tr>
    </table>
    
    <h3 style='color: #28a745; margin-top: 20px;'>地理位置类</h3>
    <table style='border-collapse: collapse; width: 100%; margin: 10px 0;'>
    <tr style='background-color: #f8f9fa;'>
        <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>语法</th>
        <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>示例</th>
        <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>用途说明</th>
    </tr>
    <tr>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>country</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>country="CN"</td>
        <td style='border: 1px solid #dee2e6; padding: 8px;'>通过国家代码进行查询</td>
    </tr>
    <tr>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>region</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>region="Beijing"</td>
        <td style='border: 1px solid #dee2e6; padding: 8px;'>通过省份/地区进行查询</td>
    </tr>
    <tr>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>city</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>city="Beijing"</td>
        <td style='border: 1px solid #dee2e6; padding: 8px;'>通过城市进行查询</td>
    </tr>
    </table>
    
    <h3 style='color: #28a745; margin-top: 20px;'>系统与组织类</h3>
    <table style='border-collapse: collapse; width: 100%; margin: 10px 0;'>
    <tr style='background-color: #f8f9fa;'>
        <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>语法</th>
        <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>示例</th>
        <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>用途说明</th>
    </tr>
    <tr>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>os</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>os="Windows"</td>
        <td style='border: 1px solid #dee2e6; padding: 8px;'>通过操作系统进行查询</td>
    </tr>
    <tr>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>org</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>org="China Telecom"</td>
        <td style='border: 1px solid #dee2e6; padding: 8px;'>通过所属组织/ISP进行查询</td>
    </tr>
    <tr>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>asn</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>asn="4134"</td>
        <td style='border: 1px solid #dee2e6; padding: 8px;'>通过自治系统号进行查询</td>
    </tr>
    </table>
    
    <h3 style='color: #28a745; margin-top: 20px;'>证书与备案类</h3>
    <table style='border-collapse: collapse; width: 100%; margin: 10px 0;'>
    <tr style='background-color: #f8f9fa;'>
        <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>语法</th>
        <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>示例</th>
        <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>用途说明</th>
    </tr>
    <tr>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>cert</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>cert="baidu.com"</td>
        <td style='border: 1px solid #dee2e6; padding: 8px;'>通过证书内容进行查询</td>
    </tr>
    <tr>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>icp</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>icp="京ICP备"</td>
        <td style='border: 1px solid #dee2e6; padding: 8px;'>通过ICP备案号进行查询</td>
    </tr>
    </table>
    
    <h3 style='color: #28a745; margin-top: 20px;'>逻辑运算符</h3>
    <table style='border-collapse: collapse; width: 100%; margin: 10px 0;'>
    <tr style='background-color: #f8f9fa;'>
        <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>运算符</th>
        <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>示例</th>
        <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>说明</th>
    </tr>
    <tr>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>=</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>title="管理"</td>
        <td style='border: 1px solid #dee2e6; padding: 8px;'>模糊匹配</td>
    </tr>
    <tr>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>==</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>title=="管理后台"</td>
        <td style='border: 1px solid #dee2e6; padding: 8px;'>完全匹配</td>
    </tr>
    <tr>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>!=</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>country!="CN"</td>
        <td style='border: 1px solid #dee2e6; padding: 8px;'>不匹配</td>
    </tr>
    <tr>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>&&</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>port="80" && country="CN"</td>
        <td style='border: 1px solid #dee2e6; padding: 8px;'>逻辑与（AND）</td>
    </tr>
    <tr>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>||</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>port="80" || port="443"</td>
        <td style='border: 1px solid #dee2e6; padding: 8px;'>逻辑或（OR）</td>
    </tr>
    <tr>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>()</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>(port="80" || port="443") && country="CN"</td>
        <td style='border: 1px solid #dee2e6; padding: 8px;'>括号优先级</td>
    </tr>
    </table>
    
    <h3 style='color: #28a745; margin-top: 20px;'>示例查询</h3>
    <div style='background-color: #e9ecef; padding: 15px; border-radius: 8px; margin: 10px 0;'>
    <p><strong>🔍 基础查询：</strong></p>
    <p><code>ip="1.1.1.1"</code> - 查询指定IP</p>
    <p><code>port="80"</code> - 查询开放80端口的资产</p>
    <p><code>domain="baidu.com"</code> - 查询指定域名</p>
    <p><code>title="管理后台"</code> - 查询标题包含"管理后台"的网站</p>
    
    <p><strong>🎯 组合查询：</strong></p>
    <p><code>app="Apache httpd" && country="CN"</code> - 搜索中国的Apache服务器</p>
    <p><code>title="登录" && port="8080"</code> - 搜索8080端口的登录页面</p>
    <p><code>body="管理" && header="nginx"</code> - 搜索包含管理的nginx网站</p>
    <p><code>(port="80" || port="443") && country="CN"</code> - 搜索中国开放80或443端口的资产</p>
    
    <p><strong>⚡ 高级查询：</strong></p>
    <p><code>cert="baidu.com"</code> - 查询证书包含baidu.com的资产</p>
    <p><code>body="<ListBucketResult>"</code> - 查询暴露的OSS存储桶</p>
    <p><code>ip="1.1.1.0/24" && port="22"</code> - 搜索C段内开放SSH的主机</p>
    <p><code>icp="京ICP备" && city="Beijing"</code> - 搜索北京备案的网站</p>
    <p><code>banner="SSH-2.0-OpenSSH" && os="Linux"</code> - 搜索Linux系统的SSH服务</p>
    </div>
    </div>
    """

def get_fofa_common_fields():
    """获取FOFA常用字段列表"""
    return [
        "host", "ip", "port", "title", "country", "city", "server", 
        "protocol", "banner", "cert", "domain", "icp", "fid", "structinfo"
    ]

def get_fofa_syntax_examples():
    """获取FOFA语法示例"""
    return {
        "基础查询": [
            'ip="1.1.1.1"',
            'port="80"',
            'domain="baidu.com"',
            'title="管理"'
        ],
        "组合查询": [
            'app="Apache" && country="CN"',
            'title="登录" && port="8080"',
            'body="管理" && header="nginx"'
        ],
        "高级查询": [
            'domain="edu.cn"',
            'ip="1.1.1.0/24" && port="22"',
            'cert="example.com"'
        ]
    }

if __name__ == "__main__":
    print("FOFA语法文档模块加载成功")
    print("常用字段:", get_fofa_common_fields())
    examples = get_fofa_syntax_examples()
    for category, queries in examples.items():
        print(f"\n{category}:")
        for query in queries:
            print(f"  {query}")