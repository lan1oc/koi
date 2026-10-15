use super::probe_sandbox::{self, ProbeHttpBrokerLaunch, ProbeLaunchRequest, ProbeSandboxLimits};
use super::probe_wheels;
#[path = "probe_replay.rs"]
mod replay;
pub(crate) fn replay_script(arguments: &Value) -> Option<String> {
    replay::script(arguments)
}
use serde::Deserialize;
use serde_json::{json, Value};
use std::fs::{self, File, OpenOptions};
use std::io::{Read, Write};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::{SystemTime, UNIX_EPOCH};

const MAX_SCRIPT_BYTES: usize = 256 * 1024;
const MAX_CONTEXT_BYTES: usize = 512 * 1024;
const MAX_OUTPUT_BYTES: u64 = 4 * 1024 * 1024;
const MAX_TARGETS: usize = 20;
static NEXT_RUN_ID: AtomicU64 = AtomicU64::new(1);

const PROBE_BOOTSTRAP: &str = r#"import ast
import base64
import builtins
import json
import os
import re
import struct
import sys
import traceback
import types
import urllib.parse
import time
import hashlib
import hmac
import binascii
import codecs
import itertools
import collections
import datetime
import random
import string
import math
import difflib
import textwrap
import html
import xml.etree.ElementTree
import http.cookies
import contextlib
import io
import gzip
import zlib
import bz2
import lzma
import csv
import decimal
import statistics
import ipaddress
import uuid
import secrets
import functools
import operator
import mimetypes
import zipfile
import tarfile
import pathlib
import typing
import dataclasses
import enum
import html.parser

# Keep bootstrap capabilities explicit. User scripts receive scoped wrappers
# below instead of these process-level handles.
_BOOTSTRAP_OPEN = builtins.open
_BOOTSTRAP_COMPILE = builtins.compile
_BOOTSTRAP_GETATTR = builtins.getattr
_BOOTSTRAP_HASATTR = builtins.hasattr
_BOOTSTRAP_SETATTR = builtins.setattr
_BOOTSTRAP_IMPORT = builtins.__import__
_BOOTSTRAP_SYSTEM_EXIT = builtins.SystemExit
_BOOTSTRAP_BASE_EXCEPTION = builtins.BaseException
_BOOTSTRAP_TRACEBACK_FORMAT_EXC = traceback.format_exc

PROTOCOL = int(os.environ.get("KOI_PROBE_PROTOCOL", "0"))
PIPE_NAME = os.environ.get("KOI_PROBE_PIPE", "")
TOKEN = os.environ.get("KOI_PROBE_TOKEN", "")
_pipe = None
_request_sequence = 0
_http_observations = []
_findings = []

def _read_exact(stream, length):
    chunks = []
    remaining = length
    while remaining:
        chunk = stream.read(remaining)
        if not chunk:
            raise RuntimeError("probe broker pipe closed early")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)

def _broker_call(method, url, headers=None, body=b"", follow_redirects=True, timeout=30, transport="http", response_limit=None, verify=True, connection_id=None):
    global _pipe, _request_sequence
    if not PIPE_NAME or not TOKEN or PROTOCOL != 1:
        raise RuntimeError("probe HTTP broker is unavailable")
    if _pipe is None:
        _pipe = _BOOTSTRAP_OPEN(PIPE_NAME, "r+b", buffering=0)
    _request_sequence += 1
    request = {
        "version": PROTOCOL,
        "token": TOKEN,
        "request_id": "probe-%d" % _request_sequence,
        "method": str(method or "GET").upper(),
        "url": str(url or ""),
        "headers": {str(k): str(v) for k, v in dict(headers or {}).items()},
        "body_base64": base64.b64encode(body).decode("ascii") if body else "",
        "follow_redirects": bool(follow_redirects),
        "timeout_ms": int(max(0.001, min(90.0, float(timeout))) * 1000),
        "transport": transport,
        "response_limit": response_limit,
        "verify_tls": bool(verify),
        "connection_id": connection_id,
    }
    payload = json.dumps(request, separators=(",", ":")).encode("utf-8")
    _pipe.write(struct.pack("<I", len(payload)))
    _pipe.write(payload)
    length = struct.unpack("<I", _read_exact(_pipe, 4))[0]
    if length <= 0 or length > 86 * 1024 * 1024:
        raise RuntimeError("probe broker returned an invalid frame length")
    reply = json.loads(_read_exact(_pipe, length).decode("utf-8"))
    observation = {"request_id": request["request_id"], "method": request["method"], "url": request["url"], "transport": transport, "ok": bool(reply.get("ok"))}
    if reply.get("ok"):
        data = reply.get("data") or {}
        observation.update({"status_code": data.get("status_code"), "elapsed_ms": data.get("elapsed_ms"), "body_excerpt": str(data.get("body_text") or "")[:4000], "body_truncated": bool(data.get("body_truncated")), "body_bytes": data.get("body_bytes"), "binary": bool(data.get("binary")), "content_length": data.get("content_length")})
        if data.get("binary"):
            observation["body_prefix_hex"] = base64.b64decode(data.get("body_base64") or "")[:64].hex()
    else:
        observation["error"] = reply.get("error") or {}
    _http_observations.append(observation)
    if not reply.get("ok"):
        error = reply.get("error") or {}
        raise RuntimeError("%s: %s" % (error.get("code", "broker_error"), error.get("message", "request denied")))
    return reply.get("data") or {}

class CookieJar(dict):
    def get_dict(self, domain=None, path=None):
        return dict(self)
    def set(self, name, value, **kwargs):
        self[str(name)] = str(value)

class ResponseHeaders(dict):
    def __getitem__(self, key): return super().__getitem__(str(key).lower())
    def get(self, key, default=None): return super().get(str(key).lower(), default)
    def __contains__(self, key): return super().__contains__(str(key).lower())

class Response:
    def __init__(self, data):
        self.status_code = int(data.get("status_code") or 0)
        self.headers = ResponseHeaders({str(k).lower(): v for k, v in (data.get("headers") or {}).items()})
        self.url = str(data.get("final_url") or "")
        self.elapsed_ms = int(data.get("elapsed_ms") or 0)
        self.elapsed = datetime.timedelta(milliseconds=self.elapsed_ms)
        self.truncated = bool(data.get("body_truncated"))
        self.content_length = data.get("content_length")
        self.content = base64.b64decode(data.get("body_base64") or "")
        self.encoding = "utf-8"
        parsed_cookies = http.cookies.SimpleCookie()
        parsed_cookies.load(self.headers.get("set-cookie", ""))
        self.cookies = CookieJar({name: item.value for name, item in parsed_cookies.items()})
    @property
    def text(self): return self.content.decode(self.encoding or "utf-8", errors="replace")
    @property
    def is_redirect(self): return self.status_code in (301,302,303,307,308) and "location" in self.headers
    def close(self): pass
    def __enter__(self): return self
    def __exit__(self, *args): self.close()
    def iter_lines(self, decode_unicode=False, **kwargs):
        for line in self.content.splitlines(): yield line.decode(self.encoding, errors="replace") if decode_unicode else line
    @property
    def ok(self):
        return 200 <= self.status_code < 400
    def json(self):
        if self.truncated:
            raise ValueError("response was truncated at 4 MiB; use a smaller page size or an explicit Range request before parsing JSON")
        return json.loads(self.text)
    def iter_content(self, chunk_size=8192, decode_unicode=False):
        for offset in range(0, len(self.content), max(1, int(chunk_size))):
            chunk=self.content[offset:offset+max(1, int(chunk_size))]
            yield chunk.decode(self.encoding, errors="replace") if decode_unicode else chunk
    def raise_for_status(self):
        if not self.ok:
            raise RuntimeError("HTTP %d" % self.status_code)

def http_request(method, url, headers=None, data=None, json_data=None, json=None,
                 allow_redirects=True, timeout=30, params=None, cookies=None, files=None, auth=None, verify=True, **kwargs):
    timeout = max(timeout) if isinstance(timeout, (tuple, list)) else timeout
    timeout = 30 if timeout is None else float(timeout)
    if kwargs.get("json_body") is not None and json is None: json = kwargs["json_body"]
    if kwargs.get("body") is not None and data is None: data = kwargs["body"]
    if not urllib.parse.urlsplit(url).scheme and _authorized_targets: url = urllib.parse.urljoin(_authorized_targets[0], url)
    body = b""
    final_headers = dict(headers or {})
    if params:
        split = urllib.parse.urlsplit(url)
        query = urllib.parse.parse_qsl(split.query, keep_blank_values=True)
        query.extend(params.items() if isinstance(params, dict) else params)
        url = urllib.parse.urlunsplit((split.scheme, split.netloc, split.path, urllib.parse.urlencode(query, doseq=True), split.fragment))
    if auth is not None:
        if isinstance(auth, (tuple, list)) and len(auth) == 2:
            final_headers.setdefault("authorization", "Basic " + base64.b64encode((str(auth[0])+":"+str(auth[1])).encode()).decode())
        elif callable(auth): raise TypeError("use an explicit Authorization header or username/password tuple")
    if cookies:
        final_headers.setdefault("cookie", "; ".join(str(key)+"="+str(value) for key, value in cookies.items()))
    payload = json_data if json_data is not None else json
    if files:
        boundary = "koi-" + uuid.uuid4().hex
        chunks = []
        def field_name(value):
            value = str(value)
            if any(c in value for c in '\r\n"'): raise ValueError("multipart field name contains a delimiter")
            return value
        for name, value in (data.items() if isinstance(data, dict) else data or []):
            for item in (value if isinstance(value, (list, tuple)) else [value]):
                chunks.append(("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n" % (boundary, field_name(name), item)).encode())
        for name, item in (files.items() if isinstance(files, dict) else files):
            filename, content, content_type = (item[0], item[1], item[2] if len(item)>2 else None) if isinstance(item, tuple) else (name, item, None)
            if hasattr(content, "read"): content = content.read()
            content = content.encode() if isinstance(content, str) else bytes(content)
            content_type = content_type or mimetypes.guess_type(str(filename))[0] or "application/octet-stream"
            chunks.append(("--%s\r\nContent-Disposition: form-data; name=\"%s\"; filename=\"%s\"\r\nContent-Type: %s\r\n\r\n" % (boundary, field_name(name), field_name(filename), content_type)).encode()+content+b"\r\n")
        chunks.append(("--%s--\r\n" % boundary).encode())
        body = b"".join(chunks)
        final_headers.setdefault("content-type", "multipart/form-data; boundary="+boundary)
    elif payload is not None:
        body = globals()["json"].dumps(payload, separators=(",", ":")).encode("utf-8")
        final_headers.setdefault("content-type", "application/json")
    elif data is not None:
        if isinstance(data, bytes):
            body = data
        elif isinstance(data, str):
            body = data.encode("utf-8")
        elif isinstance(data, (dict, list, tuple)):
            body = urllib.parse.urlencode(data, doseq=True).encode("utf-8")
            final_headers.setdefault("content-type", "application/x-www-form-urlencoded")
        else:
            raise TypeError("unsupported request body")
    return Response(_broker_call(method, url, final_headers, body, allow_redirects, timeout=timeout, verify=verify))

_authorized_targets = []
def tcp_exchange(url, data=b"", timeout=30, response_limit=262144, tls=False, verify=True):
    if not urllib.parse.urlsplit(url).scheme and _authorized_targets: url=urllib.parse.urljoin(_authorized_targets[0],url)
    payload=data.encode() if isinstance(data,str) else bytes(data)
    return Response(_broker_call("GET",url,body=payload,follow_redirects=False,timeout=timeout,
        transport="tls" if tls else "tcp",response_limit=int(response_limit),verify=verify))

def udp_exchange(url, data=b"", timeout=30, response_limit=65507):
    payload=data.encode() if isinstance(data,str) else bytes(data)
    return Response(_broker_call("GET",url,body=payload,follow_redirects=False,timeout=timeout,transport="udp",response_limit=int(response_limit)))

def tls_exchange(url, data=b"", timeout=30, response_limit=262144, verify=True):
    return tcp_exchange(url,data,timeout,response_limit,tls=True,verify=verify)

class _ScopedSocket:
    def __init__(self, family=2, type=1, proto=0, fileno=None):
        if type != 1 or fileno is not None: raise ValueError("protocol probes use stream sockets created for the reported service")
        self.timeout=30;self.url=None;self.connection_id=None;self.tls=False;self.verify=True
    def settimeout(self,value): self.timeout=30 if value is None else float(value)
    def gettimeout(self): return self.timeout
    def setblocking(self,flag): self.settimeout(None if flag else .001)
    def setsockopt(self,*args): pass
    def connect(self,address):
        host,port=address[0],int(address[1])
        for target in _authorized_targets:
            parsed=urllib.parse.urlsplit(target)
            if parsed.hostname==host and (parsed.port or (443 if parsed.scheme=='https' else 80))==port:
                self.url=target;return
        raise ValueError("socket address is outside the reported target host and port")
    def _open(self):
        if self.url is None: raise RuntimeError("socket.connect is required before protocol I/O")
        if self.connection_id is None:
            data=_broker_call('GET',self.url,timeout=self.timeout,transport='tls_open' if self.tls else 'tcp_open',verify=self.verify)
            self.connection_id=data['headers']['koi-connection-id']
    def sendall(self,data,flags=0):
        self._open();_broker_call('GET',self.url,body=bytes(data),timeout=self.timeout,transport='socket_send',connection_id=self.connection_id)
    def send(self,data,flags=0): self.sendall(data,flags);return len(data)
    def recv(self,size,flags=0):
        self._open();data=_broker_call('GET',self.url,timeout=self.timeout,transport='socket_recv',response_limit=int(size),connection_id=self.connection_id)
        return base64.b64decode(data.get('body_base64') or '')
    def recv_into(self,buffer,nbytes=0,flags=0):
        data=self.recv(nbytes or len(buffer),flags);buffer[:len(data)]=data;return len(data)
    def close(self):
        if self.connection_id:
            try: _broker_call('GET',self.url,timeout=self.timeout,transport='socket_close',connection_id=self.connection_id)
            finally:self.connection_id=None
    def shutdown(self,how=2): self.close()
    def __enter__(self): return self
    def __exit__(self,*args): self.close()
    def makefile(self,mode='r',buffering=None,encoding='utf8',errors=None,newline=None):return _SocketFile(self,mode,encoding)
class _SocketFile:
    def __init__(self,socket,mode,encoding):self.socket=socket;self.mode=mode;self.encoding=encoding;self.buffer=b''
    def read(self,size=-1):
        data=self.socket.recv(262144 if size<0 else size);return data if 'b' in self.mode else data.decode(self.encoding)
    def readline(self,size=-1):
        while b'\n' not in self.buffer and (size<0 or len(self.buffer)<size):
            part=self.socket.recv(8192)
            if not part:break
            self.buffer+=part
        end=self.buffer.find(b'\n')+1 if b'\n' in self.buffer else len(self.buffer)
        if size>=0:end=min(end,size)
        data,self.buffer=self.buffer[:end],self.buffer[end:]
        return data if 'b' in self.mode else data.decode(self.encoding)
    def write(self,data):self.socket.sendall(data.encode(self.encoding) if isinstance(data,str) else data);return len(data)
    def flush(self):pass
    def close(self):pass
    def __enter__(self):return self
    def __exit__(self,*args):self.close()
def _create_connection(address,timeout=30,source_address=None,all_errors=False):
    sock=_ScopedSocket();sock.settimeout(timeout);sock.connect(address);return sock
class _ScopedSSLContext:
    check_hostname=True;verify_mode=2
    def wrap_socket(self,sock,server_hostname=None,**kwargs):
        if sock.connection_id is not None:raise RuntimeError("wrap TLS before reading or sending protocol data")
        if server_hostname and urllib.parse.urlsplit(sock.url).hostname!=server_hostname:raise ValueError("TLS server name differs from reported host")
        sock.tls=True;sock.verify=self.verify_mode!=0;return sock
socket=types.SimpleNamespace(socket=_ScopedSocket,create_connection=_create_connection,AF_INET=2,AF_INET6=23,SOCK_STREAM=1,SOL_SOCKET=65535,SO_REUSEADDR=4,IPPROTO_TCP=6,TCP_NODELAY=1,SHUT_RD=0,SHUT_WR=1,SHUT_RDWR=2,timeout=TimeoutError,error=OSError)
ssl=types.SimpleNamespace(create_default_context=lambda *args,**kwargs:_ScopedSSLContext(),SSLContext=lambda *args,**kwargs:_ScopedSSLContext(),PROTOCOL_TLS_CLIENT=16,CERT_REQUIRED=2,CERT_NONE=0,SSLError=OSError)

class Session:
    def __init__(self):
        self.headers = {}
        self.cookies = CookieJar()
        self.auth = None
        self.verify = True
    def __enter__(self): return self
    def __exit__(self, *args): self.close()
    def close(self): pass
    def request(self, method, url, **kwargs):
        headers = dict(self.headers)
        headers.update(kwargs.pop("headers", {}) or {})
        cookies = dict(self.cookies)
        cookies.update(kwargs.pop("cookies", {}) or {})
        kwargs.setdefault("auth", self.auth)
        kwargs.setdefault("verify", self.verify)
        response = http_request(method, url, headers=headers, cookies=cookies, **kwargs)
        self.cookies.update(response.cookies)
        return response
    def get(self, url, **kwargs): return self.request("GET", url, **kwargs)
    def head(self, url, **kwargs): return self.request("HEAD", url, **kwargs)
    def options(self, url, **kwargs): return self.request("OPTIONS", url, **kwargs)
    def post(self, url, **kwargs): return self.request("POST", url, **kwargs)
    def put(self, url, **kwargs): return self.request("PUT", url, **kwargs)
    def patch(self, url, **kwargs): return self.request("PATCH", url, **kwargs)
    def delete(self, url, **kwargs): return self.request("DELETE", url, **kwargs)

requests = types.SimpleNamespace(
    request=http_request,
    get=lambda url, **kwargs: http_request("GET", url, **kwargs),
    head=lambda url, **kwargs: http_request("HEAD", url, **kwargs),
    options=lambda url, **kwargs: http_request("OPTIONS", url, **kwargs),
    post=lambda url, **kwargs: http_request("POST", url, **kwargs),
    put=lambda url, **kwargs: http_request("PUT", url, **kwargs),
    patch=lambda url, **kwargs: http_request("PATCH", url, **kwargs),
    delete=lambda url, **kwargs: http_request("DELETE", url, **kwargs),
    Session=Session,
    exceptions=types.SimpleNamespace(RequestException=RuntimeError, HTTPError=RuntimeError, Timeout=RuntimeError, ConnectionError=RuntimeError, JSONDecodeError=json.JSONDecodeError),
)

SAFE_MODULES = {
    "socket":socket,"ssl":ssl,
    "base64": base64,
    "json": json,
    "re": re,
    "traceback": types.SimpleNamespace(format_exc=_BOOTSTRAP_TRACEBACK_FORMAT_EXC),
    "urllib.parse": urllib.parse,
    "requests": requests,
    "requests.exceptions": requests.exceptions,
    "time": time, "hashlib": hashlib, "hmac": hmac, "struct": struct,
    "binascii": binascii, "codecs": codecs, "itertools": itertools,
    "collections": collections, "datetime": datetime, "random": random,
    "string": string, "math": math, "difflib": difflib, "textwrap": textwrap,
    "html": html, "xml.etree.ElementTree": xml.etree.ElementTree,
    "io":io,"gzip":gzip,"zlib":zlib,"bz2":bz2,"lzma":lzma,"csv":csv,"decimal":decimal,"statistics":statistics,"ipaddress":ipaddress,"uuid":uuid,"secrets":secrets,"functools":functools,"operator":operator,"mimetypes":mimetypes,"http.cookies":http.cookies,"zipfile":zipfile,"tarfile":tarfile,"pathlib":pathlib,"typing":typing,"dataclasses":dataclasses,"enum":enum,"html.parser":html.parser,
}

def record(title, severity="info", detail="", evidence="", relation="reported_vulnerability", verdict_support="inconclusive"):
    if len(_findings) < 40:
        _findings.append({"title": str(title)[:200], "severity": str(severity)[:20], "detail": str(detail)[:2000],
                         "evidence": str(evidence)[:4000], "relation": str(relation)[:50], "verdict_support": str(verdict_support)[:40]})
_LOCKED_IMPORT_ROOTS = set()
def safe_import(name, globals=None, locals=None, fromlist=(), level=0):
    del level
    if name in SAFE_MODULES:
        if "." in name and not fromlist:
            return _BOOTSTRAP_IMPORT(name, globals, locals, fromlist, 0)
        return SAFE_MODULES[name]
    root = str(name).split(".", 1)[0]
    if root in _LOCKED_IMPORT_ROOTS:
        return _BOOTSTRAP_IMPORT(name, globals, locals, fromlist, 0)
    if root in ("os","sys","subprocess","ctypes","winreg"): raise ImportError("host process module is unavailable in this isolated probe: "+name)
    error=ModuleNotFoundError("Missing probe module: %s; request its PyPI distribution via packages, then retry this script" % name)
    error.name=name
    raise error

SAFE_NAMES = [
    "abs", "all", "any", "bool", "bytes", "bytearray", "chr", "dict", "enumerate",
    "BaseException", "Exception", "SystemExit", "compile", "filter", "float", "format",
    "getattr", "hasattr", "hex", "int",
    "isinstance", "issubclass", "iter", "len", "list", "map", "max", "min", "next",
    "object", "ord", "pow", "print", "range", "repr", "memoryview", "complex", "divmod", "frozenset", "super", "staticmethod", "classmethod", "property", "reversed", "round", "set", "setattr",
    "slice", "sorted", "str", "sum", "tuple", "type", "ValueError", "RuntimeError",
    "TypeError", "ModuleNotFoundError", "KeyError", "IndexError", "AttributeError", "ImportError", "NameError", "StopIteration", "ZeroDivisionError", "UnicodeDecodeError", "OSError", "TimeoutError", "ConnectionError", "AssertionError", "isinstance", "callable", "open", "zip",
]
safe_builtins = {name: getattr(builtins, name) for name in SAFE_NAMES}
safe_builtins["__import__"] = safe_import
safe_builtins["__build_class__"] = builtins.__build_class__

# Function and module objects have reflective attributes which can recover
# the bootstrap's unrestricted handles (for example
# `http_request.__globals__["_BOOTSTRAP_OPEN"]`).  The operating-system
# sandbox remains the outer boundary, but reject these accesses before user
# code executes so the Python layer cannot bypass its scoped wrappers.
_ALLOWED_DUNDER_ATTRIBUTES = {"__name__"}
def _reject_dunder_name(name):
    if not isinstance(name, str):
        raise TypeError("attribute name must be a string")
    if name.startswith("__") and name not in _ALLOWED_DUNDER_ATTRIBUTES:
        raise AttributeError("dunder introspection is unavailable in the KOI probe")
    return name

def _safe_getattr(obj, name, *default):
    name = _reject_dunder_name(name)
    if name in ("format", "format_map") and isinstance(obj, str):
        return lambda *args, **kwargs: _safe_format(obj, name, *args, **kwargs)
    return _BOOTSTRAP_GETATTR(obj, name, *default)

def _safe_hasattr(obj, name):
    name = _reject_dunder_name(name)
    return _BOOTSTRAP_HASATTR(obj, name)

def _safe_setattr(obj, name, value):
    return _BOOTSTRAP_SETATTR(obj, _reject_dunder_name(name), value)

safe_builtins["getattr"] = _safe_getattr
safe_builtins["hasattr"] = _safe_hasattr
safe_builtins["setattr"] = _safe_setattr

def _safe_format(template, method, *args, **kwargs):
    for _, field, spec, _ in string.Formatter().parse(str(template)):
        if field is not None and ("__" in field or "__" in spec): raise AttributeError("format-based attribute expansion is unavailable for reflective fields")
    return str(template).format_map(args[0]) if method == "format_map" else str(template).format(*args, **kwargs)

class _FormatCalls(ast.NodeTransformer):
    def visit_Call(self, node):
        node = self.generic_visit(node)
        if isinstance(node.func, ast.Attribute) and node.func.attr in ("format", "format_map"):
            return ast.copy_location(ast.Call(func=ast.Name(id="_koi_safe_format", ctx=ast.Load()),
                args=[node.func.value, ast.Constant(node.func.attr)] + node.args, keywords=node.keywords), node)
        return node

def _validate_script(source):
    tree = ast.fix_missing_locations(_FormatCalls().visit(ast.parse(source, "<koi-dynamic-probe>", "exec")))
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr in ("format", "format_map")):
            raise RuntimeError("format-based attribute expansion is unavailable in the KOI probe")
        if isinstance(node, ast.Attribute):
            if node.attr.startswith("__") and node.attr not in _ALLOWED_DUNDER_ATTRIBUTES:
                raise RuntimeError("dunder introspection is unavailable in the KOI probe")
            if node.attr in ("format", "format_map"):
                raise RuntimeError("format-based attribute expansion is unavailable in the KOI probe")
        elif isinstance(node, ast.Name):
            if node.id.startswith("__") and node.id not in _ALLOWED_DUNDER_ATTRIBUTES:
                raise RuntimeError("dunder introspection is unavailable in the KOI probe")
        elif isinstance(node, ast.alias):
            if ((node.name and node.name.startswith("__"))
                    or (node.asname and node.asname.startswith("__"))):
                raise RuntimeError("dunder imports are unavailable in the KOI probe")
    return tree

def _scoped_open(work_root, file, mode="r", buffering=-1, encoding=None, errors=None,
                 newline=None, closefd=True, opener=None):
    # The dynamic script may inspect only its one-time work directory. The
    # AppContainer remains the outer boundary, while this check prevents an
    # accidental absolute path or a pre-existing reparse link from widening
    # the script's file capability.
    candidate = os.path.realpath(os.path.join(work_root, os.fspath(file)) if not os.path.isabs(os.fspath(file)) else os.fspath(file))
    root = os.path.realpath(work_root)
    try:
        inside = os.path.normcase(os.path.commonpath([candidate, root])) == os.path.normcase(root)
    except ValueError:
        inside = False
    if not inside:
        raise PermissionError("probe open is restricted to the working directory")
    if opener is not None:
        raise PermissionError("custom openers are not available in the probe sandbox")
    return _BOOTSTRAP_OPEN(
        candidate,
        mode,
        buffering=buffering,
        encoding=encoding,
        errors=errors,
        newline=newline,
        closefd=closefd,
    )

def _script_builtins(work_root):
    scoped = dict(safe_builtins)
    scoped["open"] = lambda file, mode="r", buffering=-1, encoding=None, errors=None, newline=None, closefd=True, opener=None: _scoped_open(
        work_root, file, mode, buffering, encoding, errors, newline, closefd, opener
    )
    return scoped

def _json_evidence(value, depth=0, budget=None):
    if budget is None:
        budget = [256 * 1024]
    if depth > 12 or budget[0] <= 0:
        return {"truncated": True, "reason": "probe return value exceeded evidence budget"}
    if isinstance(value, (bytes, bytearray)):
        budget[0] -= 512
        return {"binary": True, "byte_length": len(value), "sha256": hashlib.sha256(value).hexdigest(), "prefix_hex": bytes(value[:64]).hex()}
    if isinstance(value, str):
        size = len(value.encode('utf-8'))
        limit = min(budget[0], 64 * 1024)
        budget[0] -= min(size, limit)
        if size > limit:
            return {"text": value.encode('utf-8')[:limit].decode('utf-8', errors='ignore'), "total_bytes": size, "truncated": True}
        return value
    if isinstance(value, dict):
        result = {str(k): _json_evidence(v, depth+1, budget) for k, v in list(value.items())[:100]}
        if len(value) > 100:
            result['_omitted_items'] = len(value) - 100
        return result
    if isinstance(value, (list, tuple, set)):
        items = [_json_evidence(v, depth+1, budget) for v in list(value)[:100]]
        return {"items": items, "total_items": len(value), "truncated": True} if len(value) > 100 else items
    budget[0] -= 16
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return _json_evidence(str(value), depth+1, budget)

class _CapturedOutput:
    encoding = 'utf-8'
    def __init__(self): self.parts, self.size, self.truncated = [], 0, False
    def write(self, text):
        text = str(text)
        remaining = max(0, 65536 - self.size)
        kept = text[:remaining]
        if kept: self.parts.append(kept)
        self.size += len(kept)
        self.truncated = self.truncated or len(text) > remaining
        return len(text)
    def flush(self): pass
    def getvalue(self): return ''.join(self.parts)

def main():
    global _authorized_targets
    request_path, output_path = sys.argv[1], sys.argv[2]
    with _BOOTSTRAP_OPEN(request_path, "r", encoding="utf-8") as stream:
        request = json.load(stream)
    _authorized_targets = list(request.get("targets") or [])
    package_root = str(request.get("site_packages") or "").strip()
    if package_root:
        # The directory is granted read-only by the Rust launcher.  It is
        # inserted before user code runs, while imports remain allow-listed by
        # the lock's explicit import roots.
        sys.path.insert(0, package_root)
        _LOCKED_IMPORT_ROOTS.update(
            str(item).split(".", 1)[0]
            for item in list(request.get("allowed_imports") or [])
        )
    scope = {
        "__builtins__": _script_builtins(os.path.dirname(os.path.realpath(request_path))),
        "__name__": "koi_dynamic_probe",
        "http_request": http_request,
        "tcp_exchange": tcp_exchange,
        "tls_exchange": tls_exchange, "udp_exchange": udp_exchange,
        "_koi_safe_format": _safe_format,
        "requests": requests,
        "json": json,
        "re": re,
        "traceback": SAFE_MODULES["traceback"],
        "record": record,
    }
    report = {"ok": False}
    stdout, stderr = _CapturedOutput(), _CapturedOutput()
    try:
        source = request.get("script") or ""
        tree = _validate_script(source)
        code = _BOOTSTRAP_COMPILE(tree, "<koi-dynamic-probe>", "exec")
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            exec(code, scope, scope)
            run = scope.get("run")
            if not callable(run):
                raise RuntimeError("probe script must define run(targets, context)")
            result = run(list(request.get("targets") or []), dict(request.get("context") or {}))
        report = {"ok": True, "result": _json_evidence(result)}
    except _BOOTSTRAP_BASE_EXCEPTION as error:
        report = {
            "ok": False,
            "error_type": type(error).__name__,
            "error": str(error)[:4000],
            "traceback": _BOOTSTRAP_TRACEBACK_FORMAT_EXC(limit=12)[-12000:],
        }
    report["http_observations"] = _http_observations
    report["findings"] = _findings
    report["request_count"] = _request_sequence
    report["stdout"], report["stderr"] = stdout.getvalue(), stderr.getvalue()
    report["output_truncated"] = stdout.truncated or stderr.truncated
    with _BOOTSTRAP_OPEN(output_path, "w", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, separators=(",", ":"))
    return 0 if report.get("ok") else 1

raise _BOOTSTRAP_SYSTEM_EXIT(main())
"#;

pub(super) fn python_request_compatibility() -> &'static str {
    let start = PROBE_BOOTSTRAP
        .find("class CookieJar")
        .expect("probe compatibility start");
    let end = PROBE_BOOTSTRAP
        .find("SAFE_MODULES =")
        .expect("probe compatibility end");
    &PROBE_BOOTSTRAP[start..end]
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct DynamicProbeRequest {
    script: String,
    targets: Vec<String>,
    #[serde(default)]
    context: Value,
    /// Optional distribution names from the reviewed recursive wheel lock.
    /// Unknown or source-only distributions fail before the sandbox launches.
    #[serde(default)]
    packages: Vec<String>,
    #[serde(default = "default_request_limit")]
    max_requests: u32,
}

fn default_request_limit() -> u32 {
    100
}

#[allow(dead_code)] // Used by the standalone probe audit example.
pub fn execute(data_dir: &Path, arguments: &Value) -> Result<Value, String> {
    execute_cancellable(data_dir, arguments, &|| false)
}

pub(crate) fn execute_cancellable(
    data_dir: &Path,
    arguments: &Value,
    is_cancelled: &dyn Fn() -> bool,
) -> Result<Value, String> {
    let request: DynamicProbeRequest = serde_json::from_value(arguments.clone())
        .map_err(|error| format!("invalid run_python_probe arguments: {error}"))?;
    validate_request(&request)?;
    let application_dir = runtime_application_dir()?;
    let runtime = probe_sandbox::discover_verified_runtime(&application_dir)
        .map_err(|error| error.to_string())?;
    let downloaded = if request.packages.is_empty() {
        Vec::new()
    } else {
        let cache = data_dir.join(".koi-runtime").join("probe-wheel-cache");
        probe_wheels::download_probe_packages(&application_dir, &cache, &request.packages)
            .map_err(|error| error.to_string())?
    };
    let root = data_dir.join(".koi-runtime").join("dynamic-probes");
    fs::create_dir_all(&root)
        .map_err(|error| format!("create dynamic probe directory failed: {error}"))?;
    let work_dir = root.join(unique_id());
    fs::create_dir(&work_dir)
        .map_err(|error| format!("create one-time dynamic probe directory failed: {error}"))?;
    // Keep installed wheels outside the writable work directory.  The
    // launcher grants this sibling directory read/execute access only, so a
    // probe cannot modify its own imported code during execution.
    let package_dir = if downloaded.is_empty() {
        None
    } else {
        let path = root.join(unique_id());
        fs::create_dir(&path)
            .map_err(|error| format!("create one-time wheel directory failed: {error}"))?;
        if let Err(error) = probe_wheels::install_offline(&downloaded, &path) {
            let _ = fs::remove_dir_all(&path);
            let _ = fs::remove_dir_all(&work_dir);
            return Err(error.to_string());
        }
        Some(path)
    };
    let result = execute_in_directory(
        &runtime,
        &request,
        &downloaded,
        package_dir.as_deref(),
        &work_dir,
        is_cancelled,
    );
    let cleanup = fs::remove_dir_all(&work_dir);
    let package_cleanup = package_dir
        .as_ref()
        .map(fs::remove_dir_all)
        .unwrap_or(Ok(()));
    match (result, cleanup, package_cleanup) {
        (Ok(value), Ok(()), Ok(())) => Ok(value),
        (Err(error), Ok(()), Ok(())) => Err(error),
        (Ok(_), Err(error), Ok(())) | (Ok(_), Ok(()), Err(error)) => {
            Err(format!("dynamic probe cleanup failed: {error}"))
        }
        (Err(error), Err(cleanup), Ok(())) | (Err(error), Ok(()), Err(cleanup)) => Err(format!(
            "{error}; dynamic probe cleanup also failed: {cleanup}"
        )),
        (Ok(_), Err(work), Err(package)) => Err(format!(
            "dynamic probe cleanup failed: {work}; package cleanup also failed: {package}"
        )),
        (Err(error), Err(work), Err(package)) => Err(format!(
            "{error}; dynamic probe cleanup failed: {work}; package cleanup also failed: {package}"
        )),
    }
}

fn execute_in_directory(
    runtime: &probe_sandbox::VerifiedProbeRuntime,
    request: &DynamicProbeRequest,
    wheels: &[probe_wheels::DownloadedWheel],
    site_packages: Option<&Path>,
    work_dir: &Path,
    is_cancelled: &dyn Fn() -> bool,
) -> Result<Value, String> {
    let runner = work_dir.join("koi_probe_runner.py");
    let input = work_dir.join("request.json");
    let output = work_dir.join("result.json");
    let allowed_imports = wheels
        .iter()
        .flat_map(|wheel| wheel.package.imports.iter().cloned())
        .collect::<Vec<_>>();
    write_new_file(&runner, PROBE_BOOTSTRAP.as_bytes())?;
    let input_bytes = serde_json::to_vec(&json!({
        "script": request.script,
        "targets": request.targets,
        "context": request.context,
        "site_packages": site_packages.map(|path| path.to_string_lossy().to_string()),
        "allowed_imports": allowed_imports,
    }))
    .map_err(|error| format!("serialize dynamic probe request failed: {error}"))?;
    write_new_file(&input, &input_bytes)?;
    let exit = probe_sandbox::run_verified_probe_cancellable(
        runtime,
        &ProbeLaunchRequest {
            arguments: vec![
                "-I".to_string(),
                "-S".to_string(),
                "-B".to_string(),
                runner.to_string_lossy().to_string(),
                input.to_string_lossy().to_string(),
                output.to_string_lossy().to_string(),
            ],
            working_directory: work_dir.to_path_buf(),
            read_only_directories: site_packages.into_iter().map(Path::to_path_buf).collect(),
            limits: ProbeSandboxLimits::default(),
            http_broker: Some(ProbeHttpBrokerLaunch {
                authorized_targets: request.targets.clone(),
                request_limit: request.max_requests,
            }),
        },
        is_cancelled,
    )
    .map_err(|error| error.to_string())?;
    if exit.timed_out {
        return Err("dynamic probe exceeded its 300 second wall limit".to_string());
    }
    let report = read_limited_json(&output)?;
    Ok(json!({
        "success": report["ok"],
        "dependencies":wheels.iter().map(|wheel|json!({"name":wheel.package.name,"version":wheel.package.version,"sha256":wheel.package.artifact.sha256})).collect::<Vec<_>>(),
        "python_probe": true,
        "sandbox": "windows_appcontainer",
        "network": "rust_named_pipe_broker",
        "exit_code": exit.exit_code,
        "result": report.get("result").cloned().unwrap_or(Value::Null),
        "http_observations": report["http_observations"],
        "findings": report["findings"],
        "request_count": report["request_count"],
        "error": report.get("error"),
        "error_type": report.get("error_type"),
        "traceback": report.get("traceback"),
        "stdout": report.get("stdout"),
        "stderr": report.get("stderr"),
        "output_truncated": report.get("output_truncated"),
    }))
}

fn validate_request(request: &DynamicProbeRequest) -> Result<(), String> {
    if request.max_requests == 0 || request.max_requests > 100 {
        return Err("probe max_requests must be 1..=100".into());
    }
    let script_bytes = request.script.len();
    if script_bytes == 0 || script_bytes > MAX_SCRIPT_BYTES {
        return Err(format!(
            "dynamic probe script must contain 1..={MAX_SCRIPT_BYTES} UTF-8 bytes"
        ));
    }
    if request.targets.is_empty() || request.targets.len() > MAX_TARGETS {
        return Err(format!(
            "dynamic probe requires 1..={MAX_TARGETS} authorized targets"
        ));
    }
    if request.packages.len() > 32 {
        return Err("dynamic probe package list cannot exceed 32 entries".to_string());
    }
    for target in &request.targets {
        let parsed = reqwest::Url::parse(target)
            .map_err(|_| format!("dynamic probe target URL is invalid: {target}"))?;
        if !matches!(parsed.scheme(), "http" | "https") || parsed.host_str().is_none() {
            return Err(format!("dynamic probe target is not HTTP(S): {target}"));
        }
    }
    let context = serde_json::to_vec(&request.context)
        .map_err(|error| format!("dynamic probe context is invalid: {error}"))?;
    if context.len() > MAX_CONTEXT_BYTES {
        return Err(format!(
            "dynamic probe context exceeds {MAX_CONTEXT_BYTES} bytes"
        ));
    }
    Ok(())
}

fn runtime_application_dir() -> Result<PathBuf, String> {
    if let Some(directory) = std::env::current_exe()
        .ok()
        .and_then(|path| path.parent().map(Path::to_path_buf))
        .filter(|path| path.join(probe_sandbox::LOCK_FILE_NAME).is_file())
    {
        return Ok(directory);
    }
    // Test harnesses run below `target/<profile>/deps` and need to exercise
    // the checked-in locked runtime.  A production release still requires
    // the runtime beside the executable and never falls back to the source
    // tree.
    if cfg!(debug_assertions) || cfg!(test) {
        return Ok(PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("..")
            .join(".."));
    }
    Err("locked probe runtime is missing beside the application".to_string())
}

fn write_new_file(path: &Path, bytes: &[u8]) -> Result<(), String> {
    let mut file = OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(path)
        .map_err(|error| format!("create {} failed: {error}", path.display()))?;
    file.write_all(bytes)
        .and_then(|_| file.sync_all())
        .map_err(|error| format!("write {} failed: {error}", path.display()))
}

fn read_limited_json(path: &Path) -> Result<Value, String> {
    let metadata = fs::metadata(path)
        .map_err(|error| format!("dynamic probe did not produce a result: {error}"))?;
    if !metadata.is_file() || metadata.len() > MAX_OUTPUT_BYTES {
        return Err("dynamic probe result exceeds the 4 MiB limit".to_string());
    }
    let mut bytes = Vec::with_capacity(metadata.len() as usize);
    File::open(path)
        .and_then(|file| file.take(MAX_OUTPUT_BYTES + 1).read_to_end(&mut bytes))
        .map_err(|error| format!("read dynamic probe result failed: {error}"))?;
    if bytes.len() as u64 > MAX_OUTPUT_BYTES {
        return Err("dynamic probe result exceeds the 4 MiB limit".to_string());
    }
    serde_json::from_slice(&bytes)
        .map_err(|error| format!("dynamic probe result is invalid JSON: {error}"))
}

fn unique_id() -> String {
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_nanos())
        .unwrap_or_default();
    format!(
        "probe-{}-{}-{nonce}",
        std::process::id(),
        NEXT_RUN_ID.fetch_add(1, Ordering::Relaxed)
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::process::Command;

    fn temp_dir(label: &str) -> PathBuf {
        let path = std::env::temp_dir().join(format!(
            "koi-probe-runner-{label}-{}-{}",
            std::process::id(),
            NEXT_RUN_ID.fetch_add(1, Ordering::Relaxed)
        ));
        fs::create_dir_all(&path).expect("create probe test directory");
        path
    }

    #[test]
    fn rejects_empty_targets_and_oversized_scripts() {
        let empty = DynamicProbeRequest {
            max_requests: 20,
            script: "def run(targets, context): return []".to_string(),
            targets: Vec::new(),
            context: json!({}),
            packages: Vec::new(),
        };
        assert!(validate_request(&empty).is_err());
        let oversized = DynamicProbeRequest {
            max_requests: 20,
            script: "x".repeat(MAX_SCRIPT_BYTES + 1),
            targets: vec!["https://example.test/".to_string()],
            context: json!({}),
            packages: Vec::new(),
        };
        assert!(validate_request(&oversized).is_err());
        let too_many_packages = DynamicProbeRequest {
            max_requests: 20,
            script: "def run(targets, context): return []".to_string(),
            targets: vec!["https://example.test/".to_string()],
            context: json!({}),
            packages: (0..33).map(|index| format!("package-{index}")).collect(),
        };
        assert!(validate_request(&too_many_packages).is_err());
    }

    #[test]
    #[cfg(all(windows, target_arch = "x86_64"))]
    #[ignore = "requires real AppContainer and actual slow HTTP/TCP fixtures"]
    fn expanded_probe_runs_multipart_auth_modules_format_and_tcp_with_real_timeout() {
        use std::net::TcpListener;
        let http = TcpListener::bind(("127.0.0.1", 0)).unwrap();
        let tcp = TcpListener::bind(("127.0.0.1", 0)).unwrap();
        let http_target = format!("http://{}/", http.local_addr().unwrap());
        let tcp_target = format!("http://{}/", tcp.local_addr().unwrap());
        let http_server = std::thread::spawn(move || {
            let (mut stream, _) = http.accept().unwrap();
            stream
                .set_read_timeout(Some(std::time::Duration::from_secs(5)))
                .unwrap();
            let mut bytes = Vec::new();
            loop {
                let mut chunk = [0u8; 4096];
                let count = stream.read(&mut chunk).unwrap();
                bytes.extend_from_slice(&chunk[..count]);
                if let Some(end) = bytes.windows(4).position(|w| w == b"\r\n\r\n") {
                    let headers = String::from_utf8_lossy(&bytes[..end]).to_lowercase();
                    let size = headers
                        .lines()
                        .find_map(|line| {
                            line.strip_prefix("content-length:")
                                .and_then(|value| value.trim().parse::<usize>().ok())
                        })
                        .unwrap_or(0);
                    if bytes.len() >= end + 4 + size {
                        break;
                    }
                }
            }
            let request = String::from_utf8_lossy(&bytes);
            assert!(request.contains("id=one&id=two"), "{request}");
            assert!(
                request.contains("Authorization: Basic")
                    || request.contains("authorization: Basic"),
                "{request}"
            );
            assert!(request.contains("filename=\"proof.txt\""), "{request}");
            assert!(request.contains("payload-nonce"), "{request}");
            std::thread::sleep(std::time::Duration::from_secs(13));
            stream
                .write_all(
                    b"HTTP/1.1 200 OK\r\nContent-Length: 7\r\nConnection: close\r\n\r\nsuccess",
                )
                .unwrap();
        });
        let tcp_server = std::thread::spawn(move || {
            let (mut stream, _) = tcp.accept().unwrap();
            let mut bytes = [0u8; 16];
            let count = stream.read(&mut bytes).unwrap();
            assert_eq!(&bytes[..count], b"PING\r\n");
            stream.write_all(b"+PONG\r\n").unwrap();
        });
        let data = temp_dir("expanded-probe-capabilities");
        let result=execute(&data,&json!({"targets":[http_target,tcp_target],"max_requests":100,"script":r#"
import requests,io,gzip,zlib,bz2,lzma,hashlib,ipaddress,uuid,csv
class Proof:
    def value(self): return 'payload-{}'.format('nonce')
def run(targets,context):
    payload=Proof().value()
    assert gzip.decompress(gzip.compress(payload.encode())).decode()==payload
    assert bz2.decompress(bz2.compress(payload.encode())).decode()==payload
    assert lzma.decompress(lzma.compress(payload.encode())).decode()==payload
    with requests.Session() as session:
        session.auth=('fixture','password')
        with session.post(targets[0]+'upload',params={'id':['one','two']},files={'file':('proof.txt',io.BytesIO(payload.encode()),'text/plain')},timeout=20) as response:
            assert response.status_code==200 and response.text=='success'
            assert list(response.iter_lines(decode_unicode=True))==['success']
    protocol=tcp_exchange(targets[1],b'PING\r\n',timeout=20)
    assert protocol.content==b'+PONG\r\n'
    record('custom protocol proof',detail=protocol.text)
    return {'multipart':True,'tcp':protocol.text,'http_seconds':response.elapsed.total_seconds()}
"#})).unwrap();
        assert_eq!(result["success"], true, "{result}");
        assert_eq!(result["request_count"], 2);
        assert!(result["result"]["http_seconds"].as_f64().unwrap() > 12.0);
        http_server.join().unwrap();
        tcp_server.join().unwrap();
        std::fs::remove_dir_all(data).unwrap();
    }

    #[test]
    #[cfg(all(windows, target_arch = "x86_64"))]
    #[ignore = "requires real AppContainer and a local UDP fixture"]
    fn tool_audit_python_can_retest_udp_protocol_and_preserve_binary_evidence() {
        let socket = std::net::UdpSocket::bind("127.0.0.1:0").unwrap();
        socket
            .set_read_timeout(Some(std::time::Duration::from_secs(10)))
            .unwrap();
        let address = socket.local_addr().unwrap();
        let server = std::thread::spawn(move || {
            let mut buf = [0u8; 64];
            let (count, peer) = socket.recv_from(&mut buf).unwrap();
            assert_eq!(&buf[..count], b"\x01PING");
            socket.send_to(b"\x02PONG", peer).unwrap();
        });
        let data = temp_dir("tool-audit-udp");
        let result=execute(&data,&json!({"targets":[format!("http://{address}/")],"script":"def run(targets,context):\n    response=udp_exchange(targets[0],b'\x01PING',timeout=5)\n    assert response.content==b'\x02PONG'\n    return {'protocol':'udp','proof':response.content.hex()}"})).unwrap();
        assert_eq!(result["success"], true, "{result}");
        assert_eq!(result["http_observations"][0]["transport"], "udp");
        assert_eq!(result["request_count"], 1);
        server.join().unwrap();
        fs::remove_dir_all(data).unwrap();
    }

    #[test]
    #[cfg(all(windows, target_arch = "x86_64"))]
    #[ignore = "requires actual PyPI download and AppContainer"]
    fn online_probe_installs_missing_pypi_library_and_runs_its_script() {
        let data = temp_dir("online-missing-library");
        let result=execute(&data,&json!({"targets":["http://127.0.0.1:9/"],"packages":["beautifulsoup4>=4.12,<5"],"script":r#"
from bs4 import BeautifulSoup
def run(targets,context):
    soup=BeautifulSoup('<form action="/login"><input name="nonce" value="fixture"></form>','html.parser')
    return {'action':soup.form['action'],'nonce':soup.input['value']}
"#})).unwrap();
        assert_eq!(result["success"], true, "{result}");
        assert_eq!(result["result"]["action"], "/login");
        assert_eq!(result["result"]["nonce"], "fixture");
        assert!(result["dependencies"]
            .as_array()
            .unwrap()
            .iter()
            .any(|item| item["name"] == "beautifulsoup4"));
        std::fs::remove_dir_all(data).unwrap();
    }

    #[test]
    #[cfg(all(windows, target_arch = "x86_64"))]
    #[ignore = "requires real AppContainer and persistent TCP fixture"]
    fn python_socket_maintains_a_multistep_protocol_connection() {
        use std::net::TcpListener;
        let listener = TcpListener::bind(("127.0.0.1", 0)).unwrap();
        let address = listener.local_addr().unwrap();
        let server = std::thread::spawn(move || {
            let (mut stream, _) = listener.accept().unwrap();
            stream
                .set_read_timeout(Some(std::time::Duration::from_secs(5)))
                .unwrap();
            stream.write_all(b"READY\r\n").unwrap();
            let mut bytes = [0u8; 64];
            let count = stream.read(&mut bytes).unwrap();
            assert_eq!(&bytes[..count], b"HELLO\r\n");
            stream.write_all(b"OK\r\n").unwrap();
            let count = stream.read(&mut bytes).unwrap();
            assert_eq!(&bytes[..count], b"PING\r\n");
            stream.write_all(b"PONG\r\n").unwrap();
        });
        let data = temp_dir("persistent-protocol");
        let result = execute(
            &data,
            &json!({"targets":[format!("http://{address}/")],"script":r#"
import socket,urllib.parse
def run(targets,context):
    target=urllib.parse.urlsplit(targets[0])
    with socket.create_connection((target.hostname,target.port),timeout=20) as connection:
        greeting=connection.recv(64)
        connection.sendall(b'HELLO\r\n')
        first=connection.recv(64)
        connection.sendall(b'PING\r\n')
        second=connection.recv(64)
    record('multi-step protocol proof',detail=second.decode())
    return {'greeting':greeting.decode(),'first':first.decode(),'second':second.decode()}
"#}),
        )
        .unwrap();
        assert_eq!(result["success"], true, "{result}");
        assert_eq!(result["result"]["second"], "PONG\r\n");
        server.join().unwrap();
        std::fs::remove_dir_all(data).unwrap();
    }

    #[test]
    #[cfg(all(windows, target_arch = "x86_64"))]
    #[ignore = "requires real AppContainer and loopback broker"]
    fn agent_probe_reads_large_json_and_binary_and_preserves_script_errors() {
        use std::net::TcpListener;
        let listener = TcpListener::bind(("127.0.0.1", 0)).unwrap();
        listener.set_nonblocking(true).unwrap();
        let target = format!("http://{}/", listener.local_addr().unwrap());
        let server = std::thread::spawn(move || {
            let deadline = std::time::Instant::now() + std::time::Duration::from_secs(20);
            for (kind,body) in [("application/json",serde_json::to_vec(&json!({"items":(0..4000).map(|n|json!({"id":n,"value":"fixture"})).collect::<Vec<_>>()})).unwrap()), ("application/octet-stream",vec![0u8;128*1024])] {
                let mut socket=loop {
                    if let Ok((socket,_))=listener.accept() {break socket;}
                    assert!(std::time::Instant::now()<deadline,"probe failed to send the expected request");
                    std::thread::sleep(std::time::Duration::from_millis(20));
                };
                socket.set_nonblocking(false).unwrap();
                socket.set_read_timeout(Some(std::time::Duration::from_secs(5))).unwrap();
                socket.set_write_timeout(Some(std::time::Duration::from_secs(5))).unwrap();
                let mut request=Vec::new();
                while !request.windows(4).any(|bytes| bytes==b"\r\n\r\n") {
                    let mut bytes=[0u8;4096];
                    let count=socket.read(&mut bytes).unwrap();
                    if count==0 {break;}
                    request.extend_from_slice(&bytes[..count]);
                }
                write!(socket,"HTTP/1.1 200 OK\r\nContent-Type: {kind}\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",body.len()).unwrap();
                socket.write_all(&body).unwrap();
            }
        });
        let root = temp_dir("large-response");
        let result = execute(
            &root,
            &json!({"targets":[target],"script":r#"
import requests
def run(targets, context):
    with requests.Session() as s:
        r=s.get(targets[0]+'data')
        assert r.headers['Content-Type']=='application/json'
        assert len(r.json()['items'])==4000
        print('JSON items:', len(r.json()['items']))
        b=s.get(targets[0]+'file')
        assert len(b.content)==131072 and not b.truncated
        assert sum(len(chunk) for chunk in b.iter_content(1024))==131072
        return {'count':len(r.json()['items']), 'file_bytes':len(b.content), 'sample':b.content}
"#}),
        )
        .unwrap();
        assert_eq!(result["success"], true, "{result}");
        assert_eq!(result["result"]["count"], 4000);
        assert_eq!(result["stdout"], "JSON items: 4000\n");
        assert_eq!(result["result"]["sample"]["binary"], true);
        assert_eq!(result["result"]["sample"]["byte_length"], 131072);
        assert_eq!(result["http_observations"][1]["body_excerpt"], "");
        assert_eq!(result["http_observations"][1]["binary"], true);
        server.join().unwrap();
        let failure=execute(&root,&json!({"targets":[target],"script":"def run(targets, context):\n    raise ValueError('fixture failure')"})).unwrap();
        assert_eq!(failure["success"], false);
        assert_eq!(failure["error_type"], "ValueError");
        assert!(failure["traceback"].as_str().unwrap().contains("line 2"));
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    #[cfg(all(windows, target_arch = "x86_64"))]
    #[ignore = "requires real AppContainer and loopback broker"]
    fn agent_probe_preserves_session_cookie_query_parameters_and_http_audit() {
        use std::net::TcpListener;
        use std::thread;
        let listener = TcpListener::bind(("127.0.0.1", 0)).unwrap();
        let target = format!("http://{}/seed", listener.local_addr().unwrap());
        let server = thread::spawn(move || {
            let mut requests = Vec::new();
            for _ in 0..2 {
                let (mut stream, _) = listener.accept().unwrap();
                stream
                    .set_read_timeout(Some(std::time::Duration::from_secs(5)))
                    .unwrap();
                let mut request = Vec::new();
                while !request.windows(4).any(|part| part == b"\r\n\r\n") {
                    let mut bytes = [0u8; 4096];
                    let size = stream.read(&mut bytes).unwrap();
                    if size == 0 {
                        break;
                    }
                    request.extend_from_slice(&bytes[..size]);
                }
                stream.write_all(b"HTTP/1.1 200 OK\r\nSet-Cookie: test_session=bounded; Path=/\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok").unwrap();
                requests.push(String::from_utf8_lossy(&request).into_owned());
            }
            requests
        });
        let root = temp_dir("agent-session");
        let result = execute(&root,&json!({"targets":[target],"max_requests":2,"script":
            "def run(targets, context):\n    import urllib.parse\n    with requests.Session() as s:\n        first = s.get(targets[0], params={'proof': 'audit'})\n        assert first.cookies.get_dict()['test_session'] == 'bounded'\n        assert s.cookies.get_dict()['test_session'] == 'bounded'\n        second = s.get(urllib.parse.urljoin(targets[0], '/confirm'))\n        record('session proof', detail=second.text)\n        return {'status':second.status_code}\n"
        })).unwrap();
        assert_eq!(result["success"], true, "{result}");
        assert_eq!(result["request_count"], 2);
        assert_eq!(result["http_observations"].as_array().unwrap().len(), 2);
        let requests = server.join().unwrap();
        assert!(requests[0].contains("/seed?proof=audit"));
        assert!(requests[1]
            .to_lowercase()
            .contains("cookie: test_session=bounded"));
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    #[cfg(all(windows, target_arch = "x86_64"))]
    #[ignore = "requires real AppContainer cancellation"]
    fn cancelled_agent_probe_terminates_job_before_wall_timeout() {
        let root = temp_dir("agent-cancel");
        let start = std::time::Instant::now();
        let error = execute_cancellable(
            &root,
            &json!({
                "targets":["http://127.0.0.1:9/"],
                "script":"def run(targets, context):\n    while True:\n        pass\n"
            }),
            &|| start.elapsed() > std::time::Duration::from_millis(400),
        )
        .unwrap_err();
        assert!(error.contains("cancelled"), "{error}");
        assert!(start.elapsed() < std::time::Duration::from_secs(15));
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn packaged_wheel_lock_allows_only_reviewed_packages() {
        let application_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("..")
            .join("..");
        let lock = probe_wheels::load_lock(&application_dir).expect("bundled wheel lock");
        assert_eq!(lock.roots, vec!["idna"]);
        assert_eq!(lock.packages.len(), 2);
        assert!(lock
            .packages
            .iter()
            .any(|package| package.name == "flit-core"));
        assert_eq!(
            probe_wheels::resolve_packages(&lock, &["idna".into()])
                .expect("reviewed package")
                .len(),
            1
        );
        let error = probe_wheels::resolve_packages(&lock, &["not-reviewed".into()])
            .expect_err("unreviewed package must be refused");
        assert_eq!(error.stage, "resolve");
    }

    #[test]
    fn bootstrap_exposes_broker_only_and_denies_socket_import() {
        assert!(PROBE_BOOTSTRAP.contains("KOI_PROBE_PIPE"));
        assert!(PROBE_BOOTSTRAP.contains("Missing probe module"));
        assert!(!PROBE_BOOTSTRAP.contains("subprocess."));
        for forbidden in ["subprocess", "ctypes", "winreg", "os"] {
            assert!(
                !PROBE_BOOTSTRAP.contains(&format!("\"{forbidden}\":")),
                "forbidden module exposed in SAFE_MODULES: {forbidden}"
            );
        }
        assert!(!PROBE_BOOTSTRAP.contains("eval("));
        assert!(!PROBE_BOOTSTRAP.contains("os.system"));
    }

    #[test]
    fn bootstrap_declares_minimum_runtime_builtins_and_restricted_traceback() {
        for required in ["BaseException", "SystemExit", "compile", "open"] {
            assert!(
                PROBE_BOOTSTRAP.contains(&format!("\"{required}\"")),
                "bootstrap did not explicitly provide {required}"
            );
        }
        assert!(PROBE_BOOTSTRAP.contains("\"traceback\": types.SimpleNamespace"));
        assert!(PROBE_BOOTSTRAP.contains("_script_builtins"));
        assert!(PROBE_BOOTSTRAP.contains("_validate_script"));
        assert!(PROBE_BOOTSTRAP.contains("_safe_getattr"));
        assert!(PROBE_BOOTSTRAP.contains("dunder introspection is unavailable"));
        assert!(PROBE_BOOTSTRAP.contains("format-based attribute expansion is unavailable"));
        assert!(PROBE_BOOTSTRAP.contains("probe open is restricted to the working directory"));
        assert!(PROBE_BOOTSTRAP.contains("custom openers are not available"));
    }

    #[cfg(windows)]
    #[test]
    fn bundled_bootstrap_runs_scripts_and_rejects_forbidden_imports() {
        let application_dir = runtime_application_dir().expect("probe application directory");
        let runtime = probe_sandbox::discover_verified_runtime(&application_dir)
            .expect("bundled probe runtime");
        let root = temp_dir("bootstrap-script");
        let runner = root.join("runner.py");
        let request = root.join("request.json");
        let output = root.join("result.json");
        fs::write(&runner, PROBE_BOOTSTRAP.as_bytes()).expect("write bootstrap");
        fs::write(
            &request,
            serde_json::to_vec(&json!({
                "script": r#"
def run(targets, context):
    import traceback
    forbidden_errors = {}
    try:
        import socket
        forbidden_errors["socket"] = "unexpected_import_success"
    except BaseException as error:
        forbidden_errors["socket"] = type(error).__name__
    try:
        import subprocess
        forbidden_errors["subprocess"] = "unexpected_import_success"
    except BaseException as error:
        forbidden_errors["subprocess"] = type(error).__name__
    try:
        import os
        forbidden_errors["os"] = "unexpected_import_success"
    except BaseException as error:
        forbidden_errors["os"] = type(error).__name__
    try:
        import ctypes
        forbidden_errors["ctypes"] = "unexpected_import_success"
    except BaseException as error:
        forbidden_errors["ctypes"] = type(error).__name__
    try:
        import winreg
        forbidden_errors["winreg"] = "unexpected_import_success"
    except BaseException as error:
        forbidden_errors["winreg"] = type(error).__name__
    try:
        open("../outside.txt", "r")
        open_error = "unexpected_open_success"
    except BaseException as error:
        open_error = type(error).__name__
    with open("inside.txt", "w", encoding="utf-8") as stream:
        stream.write("ok")
    code = compile("1 + 1", "<probe-test>", "eval")
    return {
        "forbidden_errors": forbidden_errors,
        "open_error": open_error,
        "traceback_available": traceback.format_exc() is not None,
        "system_exit_is_exception": issubclass(SystemExit, BaseException),
        "compile_type": type(code).__name__,
    }
"#,
                "targets": ["https://example.test/"],
                "context": {},
            }))
            .expect("serialize bootstrap request"),
        )
        .expect("write bootstrap request");
        let status = Command::new(runtime.executable())
            .args([
                "-I",
                "-S",
                "-B",
                runner.to_string_lossy().as_ref(),
                request.to_string_lossy().as_ref(),
                output.to_string_lossy().as_ref(),
            ])
            .current_dir(&root)
            .env_remove("KOI_PROBE_PIPE")
            .env_remove("KOI_PROBE_TOKEN")
            .status()
            .expect("run bundled bootstrap");
        assert!(status.success(), "bootstrap process failed: {status}");
        let report: Value =
            serde_json::from_slice(&fs::read(&output).expect("read bootstrap result"))
                .expect("parse bootstrap result");
        assert_eq!(report["ok"], true);
        for forbidden in ["subprocess", "os", "ctypes", "winreg"] {
            assert_eq!(
                report["result"]["forbidden_errors"][forbidden],
                "ImportError"
            );
        }
        assert_eq!(
            report["result"]["forbidden_errors"]["socket"],
            "unexpected_import_success"
        );
        assert_eq!(report["result"]["open_error"], "PermissionError");
        assert_eq!(report["result"]["traceback_available"], true);
        assert_eq!(report["result"]["system_exit_is_exception"], true);
        assert_eq!(report["result"]["compile_type"], "code");
        assert_eq!(
            fs::read(root.join("inside.txt")).expect("read allowed file"),
            b"ok"
        );
        assert!(!root.parent().unwrap().join("outside.txt").exists());
        let _ = fs::remove_dir_all(root);
    }

    #[cfg(windows)]
    #[test]
    fn bundled_bootstrap_rejects_direct_and_dynamic_dunder_introspection() {
        let application_dir = runtime_application_dir().expect("probe application directory");
        let runtime = probe_sandbox::discover_verified_runtime(&application_dir)
            .expect("bundled probe runtime");
        let root = temp_dir("bootstrap-introspection");
        let runner = root.join("runner.py");
        let request = root.join("request.json");
        let output = root.join("result.json");
        fs::write(&runner, PROBE_BOOTSTRAP.as_bytes()).expect("write bootstrap");

        let run = |script: &str| -> (std::process::ExitStatus, Value) {
            fs::write(
                &request,
                serde_json::to_vec(&json!({
                    "script": script,
                    "targets": ["https://example.test/"],
                    "context": {}
                }))
                .expect("serialize introspection request"),
            )
            .expect("write introspection request");
            let status = Command::new(runtime.executable())
                .args([
                    "-I",
                    "-S",
                    "-B",
                    runner.to_string_lossy().as_ref(),
                    request.to_string_lossy().as_ref(),
                    output.to_string_lossy().as_ref(),
                ])
                .current_dir(&root)
                .env_remove("KOI_PROBE_PIPE")
                .env_remove("KOI_PROBE_TOKEN")
                .status()
                .expect("run introspection bootstrap");
            let report: Value =
                serde_json::from_slice(&fs::read(&output).expect("read introspection result"))
                    .expect("parse introspection result");
            (status, report)
        };

        let (direct_status, direct_report) = run(r#"
def run(targets, context):
    return http_request.__globals__["_BOOTSTRAP_OPEN"]
"#);
        assert!(!direct_status.success());
        assert_eq!(direct_report["ok"], false);
        assert!(direct_report["error"]
            .as_str()
            .unwrap_or_default()
            .contains("dunder introspection"));

        let (dynamic_status, dynamic_report) = run(r#"
def run(targets, context):
    try:
        getattr(http_request, "__globals__")
    except BaseException as error:
        return {"error_type": type(error).__name__}
    return {"error_type": "unexpected_success"}
"#);
        assert!(dynamic_status.success());
        assert_eq!(dynamic_report["ok"], true);
        assert_eq!(dynamic_report["result"]["error_type"], "AttributeError");

        let (format_status, format_report) = run(r#"
def run(targets, context):
    return "{0.__globals__}".format(http_request)
"#);
        assert!(!format_status.success());
        assert_eq!(format_report["ok"], false);
        assert!(format_report["error"]
            .as_str()
            .unwrap_or_default()
            .contains("format-based attribute expansion"));

        let (import_status, import_report) = run(r#"
from json import __dict__
def run(targets, context):
    return __dict__
"#);
        assert!(!import_status.success());
        assert_eq!(import_report["ok"], false);
        assert!(import_report["error"]
            .as_str()
            .unwrap_or_default()
            .contains("dunder"));

        let (dynamic_format_status, dynamic_format_report) = run(r#"
def run(targets, context):
    result=getattr("value={0}", "format")("fixture")
    try:
        getattr("{0.__globals__}", "format")(http_request)
    except BaseException as error:
        return {"result":result,"reflection_error":type(error).__name__}
    return {"reflection_error":"unexpected_success"}
"#);
        assert!(dynamic_format_status.success());
        assert_eq!(dynamic_format_report["ok"], true);
        assert_eq!(dynamic_format_report["result"]["result"], "value=fixture");
        assert_eq!(
            dynamic_format_report["result"]["reflection_error"],
            "AttributeError"
        );
        let _ = fs::remove_dir_all(root);
    }

    #[cfg(all(windows, target_arch = "x86_64"))]
    #[test]
    #[ignore = "requires an interactive Windows user profile that can create AppContainers"]
    fn executes_in_the_real_locked_appcontainer_without_host_python() {
        let data_dir = temp_dir("appcontainer");
        let result = execute(
            &data_dir,
            &json!({
                "script": "def run(targets, context):\n    return {'target_count': len(targets), 'marker': context.get('marker')}\n",
                "targets": ["http://127.0.0.1:9/"],
                "context": {"marker": "appcontainer-ok"}
            }),
        )
        .expect("run locked AppContainer probe");
        assert_eq!(result["success"], true);
        assert_eq!(result["sandbox"], "windows_appcontainer");
        assert_eq!(result["result"]["target_count"], 1);
        assert_eq!(result["result"]["marker"], "appcontainer-ok");
        assert!(!data_dir
            .join(".koi-runtime/dynamic-probes")
            .read_dir()
            .is_ok_and(|mut entries| entries.next().is_some()));
        let _ = fs::remove_dir_all(data_dir);
    }
}
