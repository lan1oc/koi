#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Hunter语法文档模块
提供Hunter鹰图平台查询语法的详细说明和示例
"""

def get_hunter_syntax_doc():
    """获取Hunter语法文档内容"""
    return """
    <div style='font-family: Consolas, Monaco, monospace; line-height: 1.6;'>
    <h2 style='color: #007bff; border-bottom: 2px solid #007bff; padding-bottom: 10px;'>Hunter 鹰图平台查询语法文档</h2>
    
    <h3 style='color: #28a745; margin-top: 20px;'>逻辑连接符</h3>
    <table style='border-collapse: collapse; width: 100%; margin: 10px 0;'>
    <tr style='background-color: #f8f9fa;'>
        <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>连接符</th>
        <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>查询含义</th>
    </tr>
    <tr>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>=</td>
        <td style='border: 1px solid #dee2e6; padding: 8px;'>模糊查询，表示查询包含关键词的资产</td>
    </tr>
    <tr>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>==</td>
        <td style='border: 1px solid #dee2e6; padding: 8px;'>精确查询，表示查询有且仅有关键词的资产</td>
    </tr>
    <tr>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>!=</td>
        <td style='border: 1px solid #dee2e6; padding: 8px;'>模糊剔除，表示剔除包含关键词的资产。使用!=""时，可查询值不为空的情况</td>
    </tr>
    <tr>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>&&、||</td>
        <td style='border: 1px solid #dee2e6; padding: 8px;'>多种条件组合查询，&&同and，表示和；||同or，表示或</td>
    </tr>
    <tr>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>()</td>
        <td style='border: 1px solid #dee2e6; padding: 8px;'>括号内表示查询优先级最高</td>
    </tr>
    </table>
    
    <h3 style='color: #28a745; margin-top: 20px;'>IP相关语法</h3>
    <table style='border-collapse: collapse; width: 100%; margin: 10px 0;'>
    <tr style='background-color: #f8f9fa;'>
        <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>语法</th>
        <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>示例</th>
        <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>说明</th>
    </tr>
    <tr>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>ip</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>ip="1.1.1.1"</td>
        <td style='border: 1px solid #dee2e6; padding: 8px;'>搜索IP为"1.1.1.1"的资产</td>
    </tr>
    <tr>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>ip.port</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>ip.port="80"</td>
        <td style='border: 1px solid #dee2e6; padding: 8px;'>搜索开放端口为"80"的资产</td>
    </tr>
    <tr>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>ip.country</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>ip.country="中国"</td>
        <td style='border: 1px solid #dee2e6; padding: 8px;'>搜索IP对应主机所在国为"中国"的资产</td>
    </tr>
    <tr>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>ip.province</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>ip.province="江苏"</td>
        <td style='border: 1px solid #dee2e6; padding: 8px;'>搜索IP对应主机在江苏省的资产</td>
    </tr>
    <tr>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>ip.city</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>ip.city="北京"</td>
        <td style='border: 1px solid #dee2e6; padding: 8px;'>搜索IP对应主机所在城市为"北京"市的资产</td>
    </tr>
    <tr>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>ip.isp</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>ip.isp="电信"</td>
        <td style='border: 1px solid #dee2e6; padding: 8px;'>搜索运营商为"中国电信"的资产</td>
    </tr>
    <tr>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>ip.os</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>ip.os="Windows"</td>
        <td style='border: 1px solid #dee2e6; padding: 8px;'>搜索操作系统标记为"Windows"的资产</td>
    </tr>
    <tr>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>ip.port_count</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>ip.port_count>"2"</td>
        <td style='border: 1px solid #dee2e6; padding: 8px;'>搜索开放端口大于2的IP（支持等于、大于、小于）</td>
    </tr>
    <tr>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>ip.ports</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>ip.ports="80" && ip.ports="443"</td>
        <td style='border: 1px solid #dee2e6; padding: 8px;'>查询开放了80和443端口号的资产</td>
    </tr>
    <tr>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>ip.tag</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>ip.tag="CDN"</td>
        <td style='border: 1px solid #dee2e6; padding: 8px;'>查询包含IP标签"CDN"的资产</td>
    </tr>
    </table>
    
    <h3 style='color: #28a745; margin-top: 20px;'>域名相关语法</h3>
    <table style='border-collapse: collapse; width: 100%; margin: 10px 0;'>
    <tr style='background-color: #f8f9fa;'>
        <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>语法</th>
        <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>示例</th>
        <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>说明</th>
    </tr>
    <tr>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>is_domain</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>is_domain=true</td>
        <td style='border: 1px solid #dee2e6; padding: 8px;'>搜索域名标记不为空的资产</td>
    </tr>
    <tr>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>domain</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>domain="qianxin"</td>
        <td style='border: 1px solid #dee2e6; padding: 8px;'>搜索域名包含"qianxin"的网站</td>
    </tr>
    <tr>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>domain.suffix</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>domain.suffix="qianxin.com"</td>
        <td style='border: 1px solid #dee2e6; padding: 8px;'>搜索主域为"qianxin.com"的网站</td>
    </tr>
    <tr>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>domain.status</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>domain.status="clientDeleteProhibited"</td>
        <td style='border: 1px solid #dee2e6; padding: 8px;'>搜索域名状态为"client Delete Prohibited"的网站</td>
    </tr>
    </table>
    
    <h3 style='color: #28a745; margin-top: 20px;'>Web相关语法</h3>
    <table style='border-collapse: collapse; width: 100%; margin: 10px 0;'>
    <tr style='background-color: #f8f9fa;'>
        <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>语法</th>
        <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>示例</th>
        <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>说明</th>
    </tr>
    <tr>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>is_web</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>is_web=true</td>
        <td style='border: 1px solid #dee2e6; padding: 8px;'>搜索web资产</td>
    </tr>
    <tr>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>web.title</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>web.title="北京"</td>
        <td style='border: 1px solid #dee2e6; padding: 8px;'>从网站标题中搜索"北京"</td>
    </tr>
    <tr>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>web.body</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>web.body="网络空间测绘"</td>
        <td style='border: 1px solid #dee2e6; padding: 8px;'>搜索网站正文包含"网络空间测绘"的资产</td>
    </tr>
    <tr>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>web.similar</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>web.similar="baidu.com:443"</td>
        <td style='border: 1px solid #dee2e6; padding: 8px;'>查询与baidu.com:443网站的特征相似的资产</td>
    </tr>
    <tr>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>web.similar_icon</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>web.similar_icon=="17262739310191283300"</td>
        <td style='border: 1px solid #dee2e6; padding: 8px;'>查询网站icon与该icon相似的资产</td>
    </tr>
    <tr>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>web.similar_id</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>web.similar_id="3322dfb483ea6fd250b29de488969b35"</td>
        <td style='border: 1px solid #dee2e6; padding: 8px;'>查询与该网页相似的资产</td>
    </tr>
    <tr>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>web.icon</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>web.icon="22eeab765346f14faf564a4709f98548"</td>
        <td style='border: 1px solid #dee2e6; padding: 8px;'>查询网站icon与该icon相同的资产</td>
    </tr>
    <tr>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>web.tag</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>web.tag="登录页面"</td>
        <td style='border: 1px solid #dee2e6; padding: 8px;'>查询包含资产标签"登录页面"的资产</td>
    </tr>
    </table>
    
    <h3 style='color: #28a745; margin-top: 20px;'>Header响应头语法</h3>
    <table style='border-collapse: collapse; width: 100%; margin: 10px 0;'>
    <tr style='background-color: #f8f9fa;'>
        <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>语法</th>
        <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>示例</th>
        <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>说明</th>
    </tr>
    <tr>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>header.server</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>header.server=="Microsoft-IIS/10"</td>
        <td style='border: 1px solid #dee2e6; padding: 8px;'>搜索server全名为"Microsoft-IIS/10"的服务器</td>
    </tr>
    <tr>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>header.content_length</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>header.content_length="691"</td>
        <td style='border: 1px solid #dee2e6; padding: 8px;'>搜索HTTP消息主体的大小为691的网站</td>
    </tr>
    <tr>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>header.status_code</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>header.status_code="402"</td>
        <td style='border: 1px solid #dee2e6; padding: 8px;'>搜索HTTP请求返回状态码为"402"的资产</td>
    </tr>
    <tr>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>header</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>header="elastic"</td>
        <td style='border: 1px solid #dee2e6; padding: 8px;'>搜索HTTP响应头中含有"elastic"的资产</td>
    </tr>
    </table>
    
    <h3 style='color: #28a745; margin-top: 20px;'>ICP备案语法</h3>
    <table style='border-collapse: collapse; width: 100%; margin: 10px 0;'>
    <tr style='background-color: #f8f9fa;'>
        <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>语法</th>
        <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>示例</th>
        <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>说明</th>
    </tr>
    <tr>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>icp.province</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>icp.province="江苏"</td>
        <td style='border: 1px solid #dee2e6; padding: 8px;'>搜索icp备案企业注册地址在江苏省的资产</td>
    </tr>
    <tr>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>icp.city</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>icp.city="上海"</td>
        <td style='border: 1px solid #dee2e6; padding: 8px;'>搜索icp备案企业注册地址在"上海"这个城市的资产</td>
    </tr>
    <tr>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>icp.district</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>icp.district="杨浦"</td>
        <td style='border: 1px solid #dee2e6; padding: 8px;'>搜索icp备案企业注册地址在"杨浦"这个区县的资产</td>
    </tr>
    <tr>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>icp.is_exception</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>icp.is_exception=true</td>
        <td style='border: 1px solid #dee2e6; padding: 8px;'>搜索含有ICP备案异常的资产</td>
    </tr>
    <tr>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>icp.name</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>icp.name!=""</td>
        <td style='border: 1px solid #dee2e6; padding: 8px;'>查询备案企业不为空的资产</td>
    </tr>
    </table>
    
    <h3 style='color: #28a745; margin-top: 20px;'>证书相关语法</h3>
    <table style='border-collapse: collapse; width: 100%; margin: 10px 0;'>
    <tr style='background-color: #f8f9fa;'>
        <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>语法</th>
        <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>示例</th>
        <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>说明</th>
    </tr>
    <tr>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>cert.is_trust</td>
        <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>cert.is_trust=true</td>
        <td style='border: 1px solid #dee2e6; padding: 8px;'>搜索证书可信的资产</td>
    </tr>
    </table>
    
    <h3 style='color: #28a745; margin-top: 20px;'>示例查询</h3>
    <div style='background-color: #e9ecef; padding: 15px; border-radius: 8px; margin: 10px 0;'>
    <p><strong>🔍 基础查询：</strong></p>
    <p><code>ip="1.1.1.1"</code> - 查询指定IP</p>
    <p><code>ip.port="80"</code> - 查询开放80端口的资产</p>
    <p><code>domain="baidu.com"</code> - 查询指定域名</p>
    <p><code>web.title="管理后台"</code> - 查询标题包含"管理后台"的网站</p>
    
    <p><strong>🎯 组合查询：</strong></p>
    <p><code>app="Apache httpd" && ip.country="中国"</code> - 搜索中国的Apache服务器</p>
    <p><code>web.title="登录" && ip.port="8080"</code> - 搜索8080端口的登录页面</p>
    <p><code>is_web=true && ip.province="北京"</code> - 搜索北京的Web资产</p>
    <p><code>(ip.port="80" || ip.port="443") && ip.country="中国"</code> - 搜索中国开放80或443端口的资产</p>
    
    <p><strong>⚡ 高级查询：</strong></p>
    <p><code>web.body="<ListBucketResult>"</code> - 查询暴露的OSS存储桶</p>
    <p><code>ip.port_count>"10"</code> - 搜索开放端口数大于10的IP</p>
    <p><code>domain.suffix="edu.cn"</code> - 搜索教育网域名</p>
    <p><code>icp.name!="" && icp.province="江苏"</code> - 搜索江苏备案的网站</p>
    <p><code>web.similar="baidu.com:443"</code> - 搜索与baidu.com相似的网站</p>
    <p><code>header.status_code="200" && web.body="admin"</code> - 搜索包含admin的正常响应页面</p>
    </div>
    </div>
    """

def get_hunter_common_fields():
    """获取Hunter常用字段列表"""
    return [
        "ip", "port", "domain", "web.title", "web.body", "web.server", 
        "ip.country", "ip.province", "ip.city", "ip.isp", "ip.os", "header.server"
    ]

def get_hunter_syntax_examples():
    """获取Hunter语法示例"""
    return {
        "基础查询": [
            'ip="1.1.1.1"',
            'ip.port="80"',
            'domain="example.com"',
            'web.title="管理"'
        ],
        "组合查询": [
            'app="Apache" && ip.country="CN"',
            'web.title="登录" && ip.port="8080"',
            'is_web=true && ip.port_count>"5"'
        ],
        "高级查询": [
            'web.similar="baidu.com:443"',
            'web.icon="22eeab765346f14faf564a4709f98548"',
            'cert.is_trust=true'
        ]
    }

if __name__ == "__main__":
    print("Hunter语法文档模块加载成功")
    print("常用字段:", get_hunter_common_fields())
    examples = get_hunter_syntax_examples()
    for category, queries in examples.items():
        print(f"\n{category}:")
        for query in queries:
            print(f"  {query}")