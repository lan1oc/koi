#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Quake语法文档模块
提供Quake 360网络空间测绘查询语法的详细说明和示例
"""

def get_quake_syntax_doc():
    """获取Quake语法文档内容"""
    return """
    <div style='font-family: Consolas, Monaco, monospace; line-height: 1.6;'>
    <h2 style='color: #007bff; border-bottom: 2px solid #007bff; padding-bottom: 10px;'>Quake 360网络空间测绘查询语法文档</h2>
    
    <h3 style='color: #28a745; margin-top: 20px;'>基础语法</h3>
    <table style='border-collapse: collapse; width: 100%; margin: 10px 0;'>
    <tr style='background-color: #f8f9fa;'>
        <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>语法</th>
        <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>示例</th>
        <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>说明</th>
    </tr>
    <tr>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>ip</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>ip:"1.1.1.1"</td>
        <td style='border: 1px solid #dee2e6; padding: 8px;'>搜索指定IP地址的资产</td>
    </tr>
    <tr>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>port</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>port:80</td>
        <td style='border: 1px solid #dee2e6; padding: 8px;'>搜索开放指定端口的资产</td>
    </tr>
    <tr>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>hostname</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>hostname:"example.com"</td>
        <td style='border: 1px solid #dee2e6; padding: 8px;'>搜索指定主机名的资产</td>
    </tr>
    <tr>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>domain</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>domain:"example.com"</td>
        <td style='border: 1px solid #dee2e6; padding: 8px;'>搜索指定域名的资产</td>
    </tr>
    <tr>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>service</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>service:"http"</td>
        <td style='border: 1px solid #dee2e6; padding: 8px;'>搜索指定服务类型的资产</td>
    </tr>
    <tr>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>app</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>app:"nginx"</td>
        <td style='border: 1px solid #dee2e6; padding: 8px;'>搜索指定应用的资产</td>
    </tr>
    <tr>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>components</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>components:"openssl"</td>
        <td style='border: 1px solid #dee2e6; padding: 8px;'>搜索包含指定组件的资产</td>
    </tr>
    <tr>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>vulns</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>vulns:"CVE-2021-44228"</td>
        <td style='border: 1px solid #dee2e6; padding: 8px;'>搜索包含指定漏洞的资产</td>
    </tr>
    <tr>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>title</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>title:"管理后台"</td>
        <td style='border: 1px solid #dee2e6; padding: 8px;'>搜索网站标题包含指定内容的资产</td>
    </tr>
    <tr>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>body</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>body:"login"</td>
        <td style='border: 1px solid #dee2e6; padding: 8px;'>搜索网页内容包含指定文本的资产</td>
    </tr>
    <tr>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>os</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>os:"Windows"</td>
        <td style='border: 1px solid #dee2e6; padding: 8px;'>搜索指定操作系统的资产</td>
    </tr>
    <tr>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>server</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>server:"Apache"</td>
        <td style='border: 1px solid #dee2e6; padding: 8px;'>搜索指定Web服务器的资产</td>
    </tr>
    <tr>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>cert</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>cert:"example.com"</td>
        <td style='border: 1px solid #dee2e6; padding: 8px;'>搜索SSL证书包含指定内容的资产</td>
    </tr>
    <tr>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>jarm</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>jarm:"2ad2ad0002ad2ad00042d42d00000ad9fb3bc51631e1c39ac59a7e"</td>
        <td style='border: 1px solid #dee2e6; padding: 8px;'>搜索指定JARM指纹的资产</td>
    </tr>
    <tr>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>asn</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>asn:4134</td>
        <td style='border: 1px solid #dee2e6; padding: 8px;'>搜索指定ASN的资产</td>
    </tr>
    <tr>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>org</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>org:"China Telecom"</td>
        <td style='border: 1px solid #dee2e6; padding: 8px;'>搜索指定组织的资产</td>
    </tr>
    <tr>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>isp</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>isp:"China Telecom"</td>
        <td style='border: 1px solid #dee2e6; padding: 8px;'>搜索指定ISP的资产</td>
    </tr>
    </table>
    
    <h3 style='color: #28a745; margin-top: 20px;'>地理位置语法</h3>
    <table style='border-collapse: collapse; width: 100%; margin: 10px 0;'>
    <tr style='background-color: #f8f9fa;'>
        <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>语法</th>
        <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>示例</th>
        <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>说明</th>
    </tr>
    <tr>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>country</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>country:"China"</td>
        <td style='border: 1px solid #dee2e6; padding: 8px;'>搜索指定国家的资产</td>
    </tr>
    <tr>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>province</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>province:"Beijing"</td>
        <td style='border: 1px solid #dee2e6; padding: 8px;'>搜索指定省份的资产</td>
    </tr>
    <tr>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>city</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>city:"Shanghai"</td>
        <td style='border: 1px solid #dee2e6; padding: 8px;'>搜索指定城市的资产</td>
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
        <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>AND / &&</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>port:80 AND country:"China"</td>
        <td style='border: 1px solid #dee2e6; padding: 8px;'>逻辑与，同时满足多个条件</td>
    </tr>
    <tr>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>OR / ||</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>port:80 OR port:443</td>
        <td style='border: 1px solid #dee2e6; padding: 8px;'>逻辑或，满足任一条件</td>
    </tr>
    <tr>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>NOT / -</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>port:80 NOT country:"China"</td>
        <td style='border: 1px solid #dee2e6; padding: 8px;'>逻辑非，排除指定条件</td>
    </tr>
    <tr>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>()</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>(port:80 OR port:443) AND country:"China"</td>
        <td style='border: 1px solid #dee2e6; padding: 8px;'>括号用于控制查询优先级</td>
    </tr>
    </table>
    
    <h3 style='color: #28a745; margin-top: 20px;'>范围查询</h3>
    <table style='border-collapse: collapse; width: 100%; margin: 10px 0;'>
    <tr style='background-color: #f8f9fa;'>
        <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>语法</th>
        <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>示例</th>
        <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>说明</th>
    </tr>
    <tr>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>[x TO y]</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>port:[80 TO 90]</td>
        <td style='border: 1px solid #dee2e6; padding: 8px;'>搜索端口在80到90之间的资产</td>
    </tr>
    <tr>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>>=</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>port:>=80</td>
        <td style='border: 1px solid #dee2e6; padding: 8px;'>搜索端口大于等于80的资产</td>
    </tr>
    <tr>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'><=</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>port:<=1024</td>
        <td style='border: 1px solid #dee2e6; padding: 8px;'>搜索端口小于等于1024的资产</td>
    </tr>
    </table>
    
    <h3 style='color: #28a745; margin-top: 20px;'>通配符查询</h3>
    <table style='border-collapse: collapse; width: 100%; margin: 10px 0;'>
    <tr style='background-color: #f8f9fa;'>
        <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>通配符</th>
        <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>示例</th>
        <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>说明</th>
    </tr>
    <tr>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>*</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>hostname:"*.example.com"</td>
        <td style='border: 1px solid #dee2e6; padding: 8px;'>匹配任意字符序列</td>
    </tr>
    <tr>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>?</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>hostname:"test?.example.com"</td>
        <td style='border: 1px solid #dee2e6; padding: 8px;'>匹配单个字符</td>
    </tr>
    </table>
    
    <h3 style='color: #28a745; margin-top: 20px;'>常用字段速览</h3>
    <div style='background-color: #f8f9fa; padding: 12px 16px; border-radius: 8px; margin: 10px 0;'>
    <code>ip, port, hostname, domain, title, country, province, city, service, app, components, vulns</code>
    </div>
    
    <h3 style='color: #28a745; margin-top: 20px;'>示例查询</h3>
    <div style='background-color: #e9ecef; padding: 15px; border-radius: 8px; margin: 10px 0;'>
    <p><strong>🔍 基础查询：</strong></p>
    <p><code>ip:"1.1.1.1"</code> - 查询指定IP</p>
    <p><code>port:80</code> - 查询开放80端口的资产</p>
    <p><code>domain:"baidu.com"</code> - 查询指定域名</p>
    <p><code>title:"管理后台"</code> - 查询标题包含"管理后台"的网站</p>
    
    <p><strong>🎯 组合查询：</strong></p>
    <p><code>app:"nginx" AND country:"China"</code> - 搜索中国的nginx服务器</p>
    <p><code>service:"http" AND NOT port:8080</code> - 搜索HTTP服务但排除8080端口</p>
    <p><code>port:80 AND country:"China"</code> - 搜索中国的80端口资产</p>
    <p><code>(port:80 OR port:443) AND country:"China"</code> - 搜索中国开放80或443端口的资产</p>
    
    <p><strong>⚡ 高级查询：</strong></p>
    <p><code>response:"<ListBucketResult>"</code> - 查询暴露的OSS存储桶</p>
    <p><code>hostname:"*.baidu.com"</code> - 搜索百度的子域名</p>
    <p><code>title:/.*管理.*/</code> - 使用正则表达式搜索标题</p>
    <p><code>cert:"example.com"</code> - 搜索证书包含example.com的资产</p>
    <p><code>port:[80 TO 90]</code> - 搜索端口在80到90之间的资产</p>
    <p><code>asn:4134 AND province:"Beijing"</code> - 搜索中国电信北京的资产</p>
    </div>
    </div>
    """

def get_quake_common_fields():
    """获取Quake常用字段列表"""
    return [
        "ip", "port", "hostname", "domain", "service", "app", "title", "body", 
        "os", "server", "cert", "jarm", "asn", "org", "isp", "country", "province", "city"
    ]

def get_quake_syntax_examples():
    """获取Quake语法示例"""
    return {
        "基础查询": [
            'ip:"1.1.1.1"',
            'port:80',
            'hostname:"example.com"',
            'title:"管理后台"'
        ],
        "组合查询": [
            'app:"nginx" AND country:"China"',
            'service:"http" AND NOT port:8080',
            'port:80 AND country:"China"'
        ],
        "高级查询": [
            'hostname:"*.baidu.com"',
            'port:[80 TO 90]',
            'jarm:"2ad2ad0002ad2ad00042d42d00000ad9fb3bc51631e1c39ac59a7e"'
        ]
    }

if __name__ == "__main__":
    print("Quake语法文档模块加载成功")
    print("常用字段:", get_quake_common_fields())
    examples = get_quake_syntax_examples()
    for category, queries in examples.items():
        print(f"\n{category}:")
        for query in queries:
            print(f"  {query}")
