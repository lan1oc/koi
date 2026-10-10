//! Standalone, standard-library-only reproduction of an authored probe.
use serde_json::{json, Value};

pub(super) fn script(arguments: &Value) -> Option<String> {
    let source = arguments["script"].as_str()?;
    if source.len() > 256 * 1024 {
        return None;
    }
    let targets = arguments["targets"].as_array()?;
    let config = json!({"targets":targets,"context":arguments.get("context").cloned().unwrap_or(json!({})),"max_requests":arguments["max_requests"].as_u64().unwrap_or(100).clamp(1,100)});
    let literal = serde_json::to_string(&config.to_string()).ok()?;
    let compatibility = super::python_request_compatibility();
    Some(format!("{SUPPORT}\n{compatibility}\n_request_module=types.ModuleType('requests');_request_module.__dict__.update(vars(requests));sys.modules['requests']=_request_module\nfor _module_name,_facade in [('socket',socket),('ssl',ssl)]:\n    _module=types.ModuleType(_module_name);_module.__dict__.update(vars(_facade));sys.modules[_module_name]=_module\n_PROBE = json.loads({literal})\n_authorized_targets = _PROBE['targets']\n\n# ---- 本次模型编写的脚本 ----\n{source}\n\nif __name__ == '__main__':\n    result = run(_PROBE['targets'], _PROBE['context'])\n    print(json.dumps({{'result': result, 'findings': _findings, 'http_observations': _observations}}, ensure_ascii=False, indent=2, default=str))\n"))
}

const SUPPORT: &str = r#"# KOI 人工复测脚本。复制完整代码后使用 Python 3 运行，无需安装 requests。
# 保留本次目标范围、请求预算和 4 MiB 响应上限。不会自动执行其他目标。
import base64
import datetime
import http.cookiejar
import json
import re
import sys
import time
import types
import urllib.error
import urllib.parse
import urllib.request
import io,gzip,zlib,bz2,lzma,csv,decimal,statistics,ipaddress,uuid,secrets,functools,operator,mimetypes
import socket as _native_socket,ssl as _native_ssl
import http.cookies

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

_findings, _observations = [], []
_protocol_connections={}
_request_count = 0

def _origin(url):
    u = urllib.parse.urlsplit(url)
    if u.scheme not in ('http', 'https') or not u.hostname or u.username or u.password:
        raise ValueError('目标必须是 HTTP(S) 地址')
    return u.scheme, u.hostname.lower(), u.port or (443 if u.scheme == 'https' else 80)

def _check_target(url):
    if _origin(url) not in {_origin(target) for target in _PROBE['targets']}:
        raise ValueError('请求超出了本次复测目标范围: ' + url)

class _Redirect(urllib.request.HTTPRedirectHandler):
    def __init__(self, enabled): self.enabled = enabled
    def redirect_request(self, req, fp, code, msg, headers, url):
        global _request_count
        _check_target(url)
        if not self.enabled: return None
        if _request_count >= _PROBE['max_requests']: raise RuntimeError('本次请求预算已用完')
        _request_count += 1
        redirected = super().redirect_request(req, fp, code, msg, headers, url)
        if redirected and _origin(req.full_url) != _origin(url):
            for name in list(redirected.headers):
                normalized = name.lower().replace('-', '')
                if normalized in ('cookie', 'authorization', 'proxyauthorization') or any(part in normalized for part in ('token', 'apikey')):
                    redirected.remove_header(name)
        return redirected

class _Headers(dict):
    def __getitem__(self, key): return super().__getitem__(str(key).lower())
    def get(self, key, default=None): return super().get(str(key).lower(), default)
    def __contains__(self, key): return super().__contains__(str(key).lower())

class _Cookies(dict):
    def get_dict(self, **kwargs): return dict(self)
    def set(self, name, value, **kwargs): self[str(name)] = str(value)

class _Response:
    def __init__(self, response, started):
        self.status_code = response.code
        self.url = response.geturl()
        self.headers = _Headers({key.lower(): value for key, value in response.headers.items()})
        self.content_length = self.headers.get('content-length')
        data = response.read(4 * 1024 * 1024 + 1)
        self.truncated = len(data) > 4 * 1024 * 1024
        self.content = data[:4 * 1024 * 1024]
        self.text = self.content.decode('utf-8', errors='replace')
        self.elapsed_ms = int((time.monotonic() - started) * 1000)
        self.elapsed = datetime.timedelta(milliseconds=self.elapsed_ms)
        self.cookies = _Cookies()
        jar = __import__('http.cookies', fromlist=['SimpleCookie']).SimpleCookie()
        jar.load(self.headers.get('set-cookie', ''))
        self.cookies.update({key: item.value for key, item in jar.items()})
    @property
    def ok(self): return 200 <= self.status_code < 400
    def raise_for_status(self):
        if not self.ok: raise RuntimeError('HTTP %d' % self.status_code)
    def json(self):
        if self.truncated: raise ValueError('响应超过4MiB，请分页后解析JSON')
        return json.loads(self.text)
    def iter_content(self, chunk_size=8192):
        for offset in range(0, len(self.content), max(1, int(chunk_size))):
            yield self.content[offset:offset+max(1, int(chunk_size))]

def http_request(method, url, headers=None, data=None, json_data=None, json=None,
                 allow_redirects=True, timeout=30, params=None, cookies=None, **kwargs):
    global _request_count
    _check_target(url)
    if _request_count >= _PROBE['max_requests']: raise RuntimeError('本次请求预算已用完')
    _request_count += 1
    method = str(method).upper()
    if params:
        u = urllib.parse.urlsplit(url)
        pairs = urllib.parse.parse_qsl(u.query, keep_blank_values=True)
        pairs.extend(params.items() if isinstance(params, dict) else params)
        url = urllib.parse.urlunsplit((u.scheme, u.netloc, u.path, urllib.parse.urlencode(pairs, doseq=True), u.fragment))
    headers = dict(headers or {})
    if cookies: headers.setdefault('cookie', '; '.join(str(k)+'='+str(v) for k,v in cookies.items()))
    payload = json_data if json_data is not None else json
    if payload is not None:
        data = globals()['json'].dumps(payload, separators=(',', ':')).encode()
        headers.setdefault('content-type', 'application/json')
    elif isinstance(data, dict):
        data = urllib.parse.urlencode(data, doseq=True).encode()
        headers.setdefault('content-type', 'application/x-www-form-urlencoded')
    elif isinstance(data, str): data = data.encode()
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    started = time.monotonic()
    opener = urllib.request.build_opener(_Redirect(allow_redirects))
    try:
        try: response = opener.open(request, timeout=min(90, max(0.001, float(timeout or 30))))
        except urllib.error.HTTPError as error: response = error
        with response: result = _Response(response, started)
    except (OSError, urllib.error.URLError) as error:
        raise RuntimeError(str(error)) from error
    _observations.append({'method': method, 'url': url, 'status_code': result.status_code,
                          'body_bytes': len(result.content), 'body_truncated': result.truncated})
    return result

class Session:
    def __init__(self): self.headers, self.cookies = {}, _Cookies()
    def __enter__(self): return self
    def __exit__(self, *args): self.close()
    def close(self): pass
    def request(self, method, url, **kwargs):
        headers = dict(self.headers); headers.update(kwargs.pop('headers', {}) or {})
        cookies = dict(self.cookies); cookies.update(kwargs.pop('cookies', {}) or {})
        result = http_request(method, url, headers=headers, cookies=cookies, **kwargs)
        self.cookies.update(result.cookies)
        return result

requests = types.ModuleType('requests')
requests.request, requests.Session = http_request, Session
for _method in ('get', 'head', 'options', 'post', 'put', 'patch', 'delete'):
    setattr(requests, _method, lambda url, _m=_method, **kw: http_request(_m.upper(), url, **kw))
    setattr(Session, _method, lambda self, url, _m=_method, **kw: self.request(_m.upper(), url, **kw))
requests.exceptions = types.SimpleNamespace(RequestException=RuntimeError, HTTPError=RuntimeError,
                                            Timeout=RuntimeError, ConnectionError=RuntimeError,
                                            JSONDecodeError=json.JSONDecodeError)
sys.modules['requests'] = requests

def _broker_call(method, url, headers=None, body=b"", follow_redirects=True, timeout=30, transport="http", response_limit=None, verify=True,connection_id=None):
    global _request_count
    _check_target(url)
    if _request_count >= _PROBE['max_requests']: raise RuntimeError('本次请求预算已用完')
    _request_count += 1
    started=time.monotonic()
    if transport in ('tcp_open','tls_open'):
        parsed=urllib.parse.urlsplit(url);connection=_native_socket.create_connection((parsed.hostname,parsed.port or (443 if parsed.scheme=='https' else 80)),timeout=min(90,float(timeout)))
        if transport=='tls_open':
            context=_native_ssl.create_default_context() if verify else _native_ssl._create_unverified_context()
            connection=context.wrap_socket(connection,server_hostname=parsed.hostname)
        key='connection-'+uuid.uuid4().hex;_protocol_connections[key]=(url,connection)
        content=b'';status,final_url,response_headers=0,url,{'koi-connection-id':key}
    elif transport in ('socket_send','socket_recv','socket_close'):
        saved_url,connection=_protocol_connections[connection_id]
        if _origin(saved_url)!=_origin(url):raise ValueError('protocol target mismatch')
        connection.settimeout(min(90,float(timeout)));content=b''
        if transport=='socket_send':connection.sendall(body)
        elif transport=='socket_recv':content=connection.recv(min(4*1024*1024,int(response_limit or 8192)))
        else:connection.close();del _protocol_connections[connection_id]
        status,final_url,response_headers=0,url,{'koi-connection-id':connection_id}
    elif transport=='udp':
        parsed=urllib.parse.urlsplit(url);address=_native_socket.getaddrinfo(parsed.hostname,parsed.port or (443 if parsed.scheme=='https' else 80),type=_native_socket.SOCK_DGRAM)[0]
        with _native_socket.socket(address[0],_native_socket.SOCK_DGRAM) as connection:
            connection.settimeout(min(90,float(timeout)));connection.connect(address[4]);connection.send(body);content=connection.recv(65508)
            status,final_url,response_headers=0,url,{}
    elif transport in ('tcp','tls'):
        parsed=urllib.parse.urlsplit(url)
        connection=_native_socket.create_connection((parsed.hostname,parsed.port or (443 if parsed.scheme=='https' else 80)),timeout=min(90,float(timeout)))
        if transport=='tls':connection=_native_ssl.create_default_context().wrap_socket(connection,server_hostname=parsed.hostname)
        with connection:
            if body:connection.sendall(body)
            content=connection.recv(min(4*1024*1024,int(response_limit or 262144))+1)
            status, final_url, response_headers = 0,url,{}
    else:
        request=urllib.request.Request(url,data=body if body else None,headers=headers or {},method=method)
        context=_native_ssl.create_default_context() if verify else _native_ssl._create_unverified_context()
        opener=urllib.request.build_opener(_Redirect(follow_redirects),urllib.request.HTTPSHandler(context=context))
        try:response=opener.open(request,timeout=min(90,max(.001,float(timeout))))
        except urllib.error.HTTPError as error:response=error
        with response:
            content=response.read(4*1024*1024+1);status=response.code;final_url=response.geturl();response_headers=dict(response.headers)
    truncated=len(content)>4*1024*1024;content=content[:4*1024*1024]
    _observations.append({'method':method,'url':url,'transport':transport,'status_code':status,'body_bytes':len(content),'body_truncated':truncated})
    return {'status_code':status,'headers':response_headers,'body_base64':base64.b64encode(content).decode(),'body_truncated':truncated,'body_bytes':len(content),'body_text':content.decode('utf8',errors='replace'),'binary':transport!='http','final_url':final_url,'elapsed_ms':int((time.monotonic()-started)*1000)}

def record(title, severity='info', detail='', evidence='', relation='reported_vulnerability', verdict_support='inconclusive'):
    _findings.append(dict(title=title, severity=severity, detail=detail, evidence=evidence,
                         relation=relation, verdict_support=verdict_support))
"#;

#[cfg(test)]
mod tests {
    use super::*;
    use std::{
        fs,
        io::{Read, Write},
        net::TcpListener,
        process::Command,
        time::{Duration, Instant, SystemTime, UNIX_EPOCH},
    };

    #[test]
    #[cfg(windows)]
    fn copied_probe_runs_standalone_with_targets_cookies_and_request_helpers() {
        let listener = TcpListener::bind(("127.0.0.1", 0)).unwrap();
        listener.set_nonblocking(true).unwrap();
        let target = format!("http://{}/", listener.local_addr().unwrap());
        let server = std::thread::spawn(move || {
            let mut requests = Vec::new();
            let deadline = Instant::now() + Duration::from_secs(15);
            for body in [
                "{\"seed\":true}".to_string(),
                json!({"data":"a".repeat(80000)}).to_string(),
            ] {
                let mut socket = loop {
                    if let Ok((s, _)) = listener.accept() {
                        break s;
                    }
                    assert!(
                        Instant::now() < deadline,
                        "copied script did not request fixture"
                    );
                    std::thread::sleep(Duration::from_millis(20));
                };
                socket
                    .set_read_timeout(Some(Duration::from_secs(4)))
                    .unwrap();
                let mut request = Vec::new();
                loop {
                    let mut buf = [0u8; 1024];
                    let n = socket.read(&mut buf).unwrap();
                    request.extend_from_slice(&buf[..n]);
                    if n == 0 || request.windows(4).any(|s| s == b"\r\n\r\n") {
                        break;
                    }
                }
                requests.push(String::from_utf8_lossy(&request).to_string());
                write!(socket,"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nSet-Cookie: replay=ok; Path=/\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",body.len()).unwrap();
            }
            requests
        });
        let source = r#"import requests
def run(targets, context):
    with requests.Session() as s:
        first = s.get(targets[0]+'seed', params={'label':context['label']})
        assert first.json()['seed'] and s.cookies.get_dict()['replay']=='ok'
        second = s.get(targets[0]+'data')
        assert second.headers['Content-Type']=='application/json'
        assert not second.truncated
        record('copied script proof', detail=str(len(second.json()['data'])))
        try:
            s.get('http://other.invalid/')
            raise AssertionError('scope check missing')
        except ValueError:
            pass
        return {'size':len(second.json()['data']), 'label':context['label']}
"#;
        let replay=script(&json!({"script":source,"targets":[target],"context":{"label":"人工核验\nquoted \"text\""}})).unwrap();
        assert!(replay.contains(source));
        let fixture_dir =
            std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../output/playwright");
        fs::create_dir_all(&fixture_dir).unwrap();
        fs::write(
            fixture_dir.join("probe-replay-fixture.json"),
            serde_json::to_vec_pretty(&json!({"script":source,"replay":replay})).unwrap(),
        )
        .unwrap();
        let root = std::env::temp_dir().join(format!(
            "koi-replay-{}",
            SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        fs::create_dir(&root).unwrap();
        let path = root.join("copied.py");
        fs::write(&path, replay).unwrap();
        let runtime = super::super::probe_sandbox::discover_verified_runtime(
            &super::super::runtime_application_dir().unwrap(),
        )
        .unwrap();
        let output = Command::new(runtime.executable())
            .args(["-I", "-S", "-B"])
            .arg(&path)
            .output()
            .unwrap();
        assert!(
            output.status.success(),
            "{}",
            String::from_utf8_lossy(&output.stderr)
        );
        let result: Value = serde_json::from_slice(&output.stdout).unwrap();
        assert_eq!(result["result"]["size"], 80000);
        assert_eq!(result["result"]["label"], "人工核验\nquoted \"text\"");
        let requests = server.join().unwrap();
        assert!(requests[1].to_lowercase().contains("cookie: replay=ok"));
        assert_eq!(result["http_observations"].as_array().unwrap().len(), 2);
        fs::remove_dir_all(root).unwrap();
    }
}
