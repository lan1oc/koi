"""
Cookie管理器 - 用于在Chrome用户数据目录中设置cookie
"""
import json
import os
import sqlite3
import tempfile
import shutil
import builtins
import sys
from pathlib import Path
from typing import List, Dict, Any, Optional
import time


def print(*args, **kwargs):
    """Windows GBK consoles cannot encode emoji; keep diagnostics from breaking control flow."""
    try:
        builtins.print(*args, **kwargs)
    except UnicodeEncodeError:
        encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
        safe_args = [
            str(arg).encode(encoding, errors="replace").decode(encoding, errors="replace")
            for arg in args
        ]
        builtins.print(*safe_args, **kwargs)


class ChromeCookieManager:
    """Chrome Cookie管理器"""
    
    def __init__(self, config_path: Optional[str] = None):
        if config_path:
            self.config_path = config_path
        else:
            try:
                from modules.config.config_manager import ConfigManager
                self.config_path = ConfigManager().config_file
            except Exception:
                env_data_dir = os.environ.get("KOI_USER_DATA_DIR")
                self.config_path = os.path.join(env_data_dir, "config.json") if env_data_dir else "config.json"
    
    def load_cookies_from_config(self) -> List[Dict[str, Any]]:
        """从配置文件加载cookie"""
        try:
            if not os.path.exists(self.config_path):
                print(f"❌ 配置文件不存在: {self.config_path}")
                return []
            
            with open(self.config_path, 'r', encoding='utf-8-sig') as f:
                config = json.load(f)
            
            # 从tyc.cookie字段读取cookie字符串
            cookie_string = config.get('tyc', {}).get('cookie', '')
            
            if not cookie_string:
                print(f"⚠️ 配置文件中没有找到tyc.cookie字段")
                return []
            
            # 解析cookie字符串为cookie列表
            cookies = self._parse_cookie_string(cookie_string)
            print(f"✅ 从配置文件读取到 {len(cookies)} 个cookie")
            return cookies
        except Exception as e:
            print(f"❌ 读取配置文件失败: {e}")
            return []
    
    def _parse_cookie_string(self, cookie_string: str) -> List[Dict[str, Any]]:
        """解析cookie字符串为cookie字典列表 - 去重并保留最新的cookie值"""
        cookies = []
        cookie_dict = {}  # 用于去重，保留最新的cookie值
        
        # 按分号分割cookie
        cookie_pairs = cookie_string.split(';')
        
        # 需要使用www.tianyancha.com域名的cookie
        www_domain_cookies = {'HWWAFSESID', 'HWWAFSESTIME', 'csrfToken'}
        
        # 关键登录cookie，需要特别关注
        critical_cookies = {
            'auth_token', 'tyc-user-info', 'tyc-user-phone', 
            'tyc-user-info-save-time', 'CUID', 'TYCID'
        }
        
        for pair in cookie_pairs:
            pair = pair.strip()
            if not pair:
                continue
                
            # 分割name和value
            if '=' in pair:
                name, value = pair.split('=', 1)
                name = name.strip()
                value = value.strip()
                
                if name and value:
                    # 根据cookie名称选择正确的域名
                    if name in www_domain_cookies:
                        domain = 'www.tianyancha.com'
                    else:
                        domain = '.tianyancha.com'
                    
                    # 去重：同名cookie保留最后出现的值（通常是最新的）
                    cookie_dict[name] = {
                        'name': name,
                        'value': value,  # 使用原始cookie值，不进行任何编码处理
                        'domain': domain,
                        'path': '/',
                        'secure': False,
                        'httpOnly': False,
                        'is_critical': name in critical_cookies
                    }
        
        # 转换为列表，优先放置关键cookie
        critical_cookies_list = []
        normal_cookies_list = []
        
        for cookie in cookie_dict.values():
            if cookie['is_critical']:
                critical_cookies_list.append(cookie)
            else:
                normal_cookies_list.append(cookie)
        
        # 关键cookie放在前面
        cookies = critical_cookies_list + normal_cookies_list
        
        # 移除is_critical字段，因为Chrome不需要这个字段
        for cookie in cookies:
            cookie.pop('is_critical', None)
        
        print(f"📊 解析cookie: 原始{len(cookie_pairs)}个 -> 去重后{len(cookies)}个")
        print(f"🔑 关键cookie: {len(critical_cookies_list)}个")
        print(f"🌐 域名分配: www.tianyancha.com({len([c for c in cookies if c['domain'] == 'www.tianyancha.com'])}) + .tianyancha.com({len([c for c in cookies if c['domain'] == '.tianyancha.com'])})")
        
        # 显示关键cookie信息
        if critical_cookies_list:
            print("🔑 关键cookie详情:")
            for cookie in critical_cookies_list:
                value_preview = cookie['value'][:50] + "..." if len(cookie['value']) > 50 else cookie['value']
                print(f"   - {cookie['name']}: {value_preview}")
        
        return cookies

    def load_aiqicha_cookies_from_config(self) -> List[Dict[str, Any]]:
        """从 config.json 的 aiqicha.cookie 解析为 Chrome Cookies 表结构列表（域 .baidu.com）。"""
        try:
            if not os.path.exists(self.config_path):
                return []
            with open(self.config_path, "r", encoding="utf-8-sig") as f:
                config = json.load(f)
            cookie_string = (config.get("aiqicha") or {}).get("cookie", "")
            if not cookie_string or not str(cookie_string).strip():
                return []
            return self._parse_aiqicha_cookie_string(str(cookie_string))
        except Exception as e:
            print(f"❌ 读取爱企查 Cookie 失败: {e}")
            return []

    def _parse_aiqicha_cookie_string(self, cookie_string: str) -> List[Dict[str, Any]]:
        """爱企查/百度系站点 Cookie 写入 Chrome 时使用 .baidu.com 域。"""
        out: List[Dict[str, Any]] = []
        seen: Dict[str, Dict[str, Any]] = {}
        for pair in cookie_string.split(";"):
            pair = pair.strip()
            if not pair or "=" not in pair:
                continue
            name, value = pair.split("=", 1)
            name = name.strip()
            value = value.strip()
            if not name or not value:
                continue
            # 与百度系子域（aiqicha、passport、xunkebao 等）共享
            seen[name] = {
                "name": name,
                "value": value,
                "domain": ".baidu.com",
                "path": "/",
                "secure": False,
                "httpOnly": False,
            }
        out = list(seen.values())
        if out:
            print(f"✅ 解析爱企查 Cookie: 共 {len(out)} 条（域 .baidu.com）")
        return out

    def create_user_data_dir(self, with_cookies: bool = True) -> str:
        """创建用户数据目录"""
        if with_cookies:
            # 带cookie的目录
            data_dir = os.path.join(tempfile.gettempdir(), "tianyancha_with_cookies")
        else:
            # 不带cookie的目录
            data_dir = os.path.join(tempfile.gettempdir(), "tianyancha_no_cookies")
        
        # 确保目录存在
        os.makedirs(data_dir, exist_ok=True)
        print(f"📁 创建用户数据目录: {data_dir}")
        return data_dir
    
    def setup_cookies_in_chrome_profile(self, user_data_dir: str, cookies: List[Dict[str, Any]]) -> bool:
        """在Chrome用户数据目录中设置cookie"""
        try:
            # Chrome的默认配置文件路径
            default_profile_dir = os.path.join(user_data_dir, "Default")
            os.makedirs(default_profile_dir, exist_ok=True)
            
            # 创建Network目录（Chrome新版本的cookie存储位置）
            network_dir = os.path.join(default_profile_dir, "Network")
            os.makedirs(network_dir, exist_ok=True)
            
            # Cookie数据库路径（新版Chrome存储在Network目录下）
            cookies_db_path = os.path.join(network_dir, "Cookies")
            
            # 创建Cookie数据库
            self._create_cookies_database(cookies_db_path, cookies)
            
            print(f"✅ 成功在Chrome配置文件中设置 {len(cookies)} 个cookie")
            print(f"📁 Cookie数据库路径: {cookies_db_path}")
            return True
            
        except Exception as e:
            print(f"❌ 设置Chrome配置文件cookie失败: {e}")
            return False
    
    def _create_cookies_database(self, db_path: str, cookies: List[Dict[str, Any]]):
        """创建Chrome Cookie数据库 - 基于真实Chrome数据库结构"""
        # 如果数据库已存在，先删除
        if os.path.exists(db_path):
            os.remove(db_path)
        
        # 创建数据库连接
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # 创建cookies表（基于真实Chrome数据库结构）
        cursor.execute('''
            CREATE TABLE cookies (
                creation_utc INTEGER NOT NULL,
                host_key TEXT NOT NULL,
                top_frame_site_key TEXT NOT NULL,
                name TEXT NOT NULL,
                value TEXT NOT NULL,
                encrypted_value BLOB DEFAULT '',
                path TEXT NOT NULL,
                expires_utc INTEGER NOT NULL,
                is_secure INTEGER NOT NULL,
                is_httponly INTEGER NOT NULL,
                last_access_utc INTEGER NOT NULL,
                has_expires INTEGER NOT NULL,
                is_persistent INTEGER NOT NULL,
                priority INTEGER NOT NULL,
                samesite INTEGER NOT NULL,
                source_scheme INTEGER NOT NULL,
                source_port INTEGER NOT NULL,
                is_same_party INTEGER NOT NULL
            )
        ''')
        
        # 创建索引（提高查询性能）
        cursor.execute('CREATE INDEX domain_idx ON cookies(host_key)')
        cursor.execute('CREATE INDEX name_idx ON cookies(name)')
        
        # 当前时间戳（Chrome使用的是Windows epoch时间，微秒级）
        current_time = int((time.time() + 11644473600) * 1000000)  # 转换为Chrome时间格式
        
        # 统计插入成功的cookie数量
        success_count = 0
        failed_count = 0
        
        # 插入cookie数据
        for cookie in cookies:
            try:
                # 解析cookie的域名
                domain = cookie.get('domain', '.tianyancha.com')
                cookie_name = cookie.get('name', '')
                
                # 根据真实Chrome数据库的域名格式设置host_key
                if domain == 'www.tianyancha.com':
                    host_key = 'www.tianyancha.com'  # 不添加点号
                elif domain.startswith('.'):
                    host_key = domain  # 已经有点号，保持原样
                else:
                    host_key = '.' + domain  # 其他情况添加点号
                
                # 设置过期时间（设置为2年后，与真实cookie类似）
                expires_utc = current_time + (2 * 365 * 24 * 60 * 60 * 1000000)  # 2年后
                
                # 根据cookie名称和域名设置安全属性（基于真实数据分析）
                is_secure = 0  # 真实数据显示所有cookie都不是secure
                is_httponly = 0  # 真实数据显示所有cookie都不是httponly
                
                # 设置SameSite属性（基于真实数据）
                samesite = -1  # Unspecified，与真实数据一致
                
                # 设置source_scheme和source_port（基于真实数据）
                source_scheme = 2  # Secure (HTTPS)
                source_port = 443  # HTTPS端口
                
                # 设置top_frame_site_key（基于真实数据格式）
                if host_key.startswith('.'):
                    top_frame_site_key = f"https://{host_key[1:]}"  # 去掉前导点
                else:
                    top_frame_site_key = f"https://{host_key}"
                
                cursor.execute('''
                    INSERT INTO cookies (
                        creation_utc, host_key, top_frame_site_key, name, value,
                        encrypted_value, path, expires_utc, is_secure, is_httponly,
                        last_access_utc, has_expires, is_persistent, priority,
                        samesite, source_scheme, source_port, is_same_party
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    current_time,  # creation_utc
                    host_key,  # host_key - 使用正确的域名格式
                    top_frame_site_key,  # top_frame_site_key
                    cookie_name,  # name
                    cookie.get('value', ''),  # value
                    b'',  # encrypted_value
                    cookie.get('path', '/'),  # path
                    expires_utc,  # expires_utc
                    is_secure,  # is_secure
                    is_httponly,  # is_httponly
                    current_time,  # last_access_utc
                    1,  # has_expires
                    1,  # is_persistent
                    1,  # priority (Medium)
                    samesite,  # samesite
                    source_scheme,  # source_scheme
                    source_port,  # source_port
                    0   # is_same_party
                ))
                
                success_count += 1
                
            except Exception as e:
                print(f"⚠️ 插入cookie失败 {cookie.get('name', 'unknown')}: {e}")
                failed_count += 1
                continue
        
        # 提交并关闭连接
        conn.commit()
        conn.close()
        
        print(f"✅ Cookie数据库创建完成: {db_path}")
        print(f"📊 插入结果: 成功{success_count}个, 失败{failed_count}个")
        
        # 如果有失败的cookie，给出提示
        if failed_count > 0:
            print(f"⚠️ 有{failed_count}个cookie插入失败，请检查cookie格式")
    
    def prepare_browser_profile(self) -> str:
        """准备浏览器配置文件"""
        # 创建用户数据目录
        user_data_dir = self.create_user_data_dir()
        
        # 加载并设置cookie
        cookies = self.load_cookies_from_config()
        if cookies:
            success = self.setup_cookies_in_chrome_profile(user_data_dir, cookies)
            if success:
                print(f"🍪 成功准备带cookie的浏览器配置文件")
            else:
                print(f"⚠️ cookie设置失败，但仍使用该配置文件")
        else:
            print(f"⚠️ 没有找到cookie，使用空的配置文件")
        
        return user_data_dir


def test_cookie_manager():
    """测试cookie管理器"""
    manager = ChromeCookieManager()
    
    # 测试带cookie的配置文件
    print("=== 测试浏览器配置文件 ===")
    profile_dir = manager.prepare_browser_profile()
    print(f"配置文件路径: {profile_dir}")


if __name__ == "__main__":
    test_cookie_manager()
