//! Typed, fail-closed HTTP broker policy for the dynamic Python probe.
//!
//! The AppContainer has no network capability. Probe HTTP is represented by
//! this protocol and executed by Rust after origin, DNS, and resource checks.

use base64::engine::general_purpose::STANDARD as BASE64;
use base64::Engine;
use reqwest::blocking::{Client, Response};
use reqwest::header::{
    HeaderMap, HeaderName, HeaderValue, AUTHORIZATION, CONTENT_LENGTH, COOKIE, LOCATION,
    PROXY_AUTHORIZATION,
};
use reqwest::{Method, StatusCode};
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, BTreeSet, HashMap};
use std::io::Read;
use std::net::{IpAddr, SocketAddr, ToSocketAddrs};
use std::str::FromStr;
use std::time::{Duration, Instant};
use url::{Host, Url};

pub const PROBE_BROKER_PROTOCOL_VERSION: u32 = 1;
pub const MAX_PROBE_REQUESTS: u32 = 20;
pub const PROBE_REQUEST_TIMEOUT: Duration = Duration::from_secs(12);
pub const MAX_PROBE_RESPONSE_BYTES: usize = 4 * 1024 * 1024;
pub const MAX_PROBE_UPLOAD_BYTES: usize = 64 * 1024 * 1024;
pub const MAX_PROBE_REDIRECTS: usize = 10;
pub const MAX_BROKER_FRAME_BYTES: usize = 86 * 1024 * 1024;

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "UPPERCASE")]
pub enum ProbeHttpMethod {
    Get,
    Head,
    Post,
    Put,
    Patch,
    Delete,
    Options,
    Trace,
}

impl ProbeHttpMethod {
    fn as_reqwest(&self) -> Method {
        match self {
            Self::Get => Method::GET,
            Self::Head => Method::HEAD,
            Self::Post => Method::POST,
            Self::Put => Method::PUT,
            Self::Patch => Method::PATCH,
            Self::Delete => Method::DELETE,
            Self::Options => Method::OPTIONS,
            Self::Trace => Method::TRACE,
        }
    }
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct ProbeBrokerRequest {
    pub version: u32,
    pub token: String,
    pub request_id: String,
    pub method: ProbeHttpMethod,
    pub url: String,
    #[serde(default)]
    pub headers: BTreeMap<String, String>,
    #[serde(default)]
    pub body_base64: String,
    #[serde(default)]
    pub follow_redirects: bool,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct ProbeBrokerResponseData {
    pub status_code: u16,
    pub headers: BTreeMap<String, String>,
    pub body_base64: String,
    pub body_text: String,
    #[serde(default)]
    pub body_truncated: bool,
    #[serde(default)]
    pub body_bytes: usize,
    #[serde(default)]
    pub content_length: Option<u64>,
    #[serde(default)]
    pub binary: bool,
    pub final_url: String,
    pub elapsed_ms: u64,
    pub redirects_followed: usize,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct ProbeBrokerErrorBody {
    pub code: String,
    pub message: String,
    pub retryable: bool,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct ProbeBrokerReply {
    pub version: u32,
    pub request_id: String,
    pub ok: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub data: Option<ProbeBrokerResponseData>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<ProbeBrokerErrorBody>,
}

impl ProbeBrokerReply {
    fn success(request_id: String, data: ProbeBrokerResponseData) -> Self {
        Self {
            version: PROBE_BROKER_PROTOCOL_VERSION,
            request_id,
            ok: true,
            data: Some(data),
            error: None,
        }
    }

    fn failure(request_id: String, error: ProbeBrokerError) -> Self {
        Self {
            version: PROBE_BROKER_PROTOCOL_VERSION,
            request_id,
            ok: false,
            data: None,
            error: Some(error.into_body()),
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ProbeBrokerError {
    code: &'static str,
    message: String,
    retryable: bool,
}

impl ProbeBrokerError {
    fn policy(code: &'static str, message: impl Into<String>) -> Self {
        Self {
            code,
            message: message.into(),
            retryable: false,
        }
    }

    fn transport(message: impl Into<String>) -> Self {
        Self {
            code: "transport_error",
            message: message.into(),
            retryable: true,
        }
    }

    fn into_body(self) -> ProbeBrokerErrorBody {
        ProbeBrokerErrorBody {
            code: self.code.to_string(),
            message: self.message,
            retryable: self.retryable,
        }
    }
}

impl std::fmt::Display for ProbeBrokerError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(formatter, "probe broker {}: {}", self.code, self.message)
    }
}

impl std::error::Error for ProbeBrokerError {}

#[derive(Clone, Debug, Hash, PartialEq, Eq)]
struct ProbeOrigin {
    scheme: String,
    host: String,
    port: u16,
}

impl ProbeOrigin {
    fn parse(url: &Url) -> Result<Self, ProbeBrokerError> {
        if !matches!(url.scheme(), "http" | "https") {
            return Err(ProbeBrokerError::policy(
                "unsupported_scheme",
                "only HTTP and HTTPS probe targets are allowed",
            ));
        }
        if !url.username().is_empty() || url.password().is_some() {
            return Err(ProbeBrokerError::policy(
                "url_credentials_forbidden",
                "credentials embedded in a probe URL are forbidden",
            ));
        }
        let host = url
            .host_str()
            .ok_or_else(|| ProbeBrokerError::policy("invalid_url", "probe URL has no host"))?
            .trim_end_matches('.')
            .to_ascii_lowercase();
        let port = url.port_or_known_default().ok_or_else(|| {
            ProbeBrokerError::policy("invalid_url", "probe URL has no effective port")
        })?;
        Ok(Self {
            scheme: url.scheme().to_string(),
            host,
            port,
        })
    }
}

pub trait ProbeDnsResolver {
    fn resolve(&self, host: &str, port: u16) -> Result<Vec<IpAddr>, ProbeBrokerError>;
}

#[derive(Clone, Copy, Debug, Default)]
pub struct SystemProbeDnsResolver;

impl ProbeDnsResolver for SystemProbeDnsResolver {
    fn resolve(&self, host: &str, port: u16) -> Result<Vec<IpAddr>, ProbeBrokerError> {
        if let Ok(ip) = host.parse::<IpAddr>() {
            return Ok(vec![ip]);
        }
        let addresses = (host, port)
            .to_socket_addrs()
            .map_err(|_| ProbeBrokerError::transport("target DNS resolution failed"))?;
        let mut ips = BTreeSet::new();
        ips.extend(addresses.map(|address| address.ip()));
        if ips.is_empty() {
            return Err(ProbeBrokerError::transport(
                "target DNS resolution returned no addresses",
            ));
        }
        Ok(ips.into_iter().collect())
    }
}

#[derive(Clone, Debug)]
struct TargetAuthorization {
    allowed_ips: BTreeSet<IpAddr>,
}

#[derive(Clone, Debug)]
pub struct ProbeBrokerPolicy {
    targets: HashMap<ProbeOrigin, TargetAuthorization>,
    requests_used: u32,
    request_limit: u32,
}

#[derive(Clone, Debug)]
pub struct AuthorizedProbeTarget {
    url: Url,
    origin: ProbeOrigin,
    socket_addresses: Vec<SocketAddr>,
}

impl ProbeBrokerPolicy {
    pub fn from_targets<R: ProbeDnsResolver>(
        targets: &[String],
        resolver: &R,
    ) -> Result<Self, ProbeBrokerError> {
        if targets.is_empty() {
            return Err(ProbeBrokerError::policy(
                "no_authorized_targets",
                "at least one authorized HTTP target is required",
            ));
        }
        let mut authorizations: HashMap<ProbeOrigin, TargetAuthorization> = HashMap::new();
        for target in targets {
            let url = parse_probe_url(target)?;
            let origin = ProbeOrigin::parse(&url)?;
            let resolved = resolve_origin(&origin, resolver)?;
            authorizations
                .entry(origin)
                .or_insert_with(|| TargetAuthorization {
                    allowed_ips: BTreeSet::new(),
                })
                .allowed_ips
                .extend(resolved);
        }
        Ok(Self {
            targets: authorizations,
            requests_used: 0,
            request_limit: MAX_PROBE_REQUESTS,
        })
    }

    fn authorize<R: ProbeDnsResolver>(
        &mut self,
        url: Url,
        resolver: &R,
    ) -> Result<AuthorizedProbeTarget, ProbeBrokerError> {
        let origin = ProbeOrigin::parse(&url)?;
        let authorization = self.targets.get(&origin).ok_or_else(|| {
            ProbeBrokerError::policy(
                "origin_not_authorized",
                "probe target is outside the explicitly authorized origins",
            )
        })?;
        let current = resolve_origin(&origin, resolver)?;
        if current
            .iter()
            .any(|address| !authorization.allowed_ips.contains(address))
        {
            return Err(ProbeBrokerError::policy(
                "dns_address_not_authorized",
                "target DNS returned an address that requires separate authorization",
            ));
        }
        if self.requests_used >= self.request_limit {
            return Err(ProbeBrokerError::policy(
                "request_limit_exceeded",
                "probe HTTP request limit of 20 has been reached",
            ));
        }
        self.requests_used += 1;
        let socket_addresses = current
            .into_iter()
            .map(|ip| SocketAddr::new(ip, origin.port))
            .collect();
        Ok(AuthorizedProbeTarget {
            url,
            origin,
            socket_addresses,
        })
    }
}

fn resolve_origin<R: ProbeDnsResolver>(
    origin: &ProbeOrigin,
    resolver: &R,
) -> Result<BTreeSet<IpAddr>, ProbeBrokerError> {
    let addresses = resolver.resolve(&origin.host, origin.port)?;
    if addresses.is_empty() {
        return Err(ProbeBrokerError::transport(
            "target DNS resolution returned no addresses",
        ));
    }
    Ok(addresses.into_iter().collect())
}

fn parse_probe_url(value: &str) -> Result<Url, ProbeBrokerError> {
    let mut url = Url::parse(value)
        .map_err(|_| ProbeBrokerError::policy("invalid_url", "probe URL is invalid"))?;
    url.set_fragment(None);
    ProbeOrigin::parse(&url)?;
    Ok(url)
}

#[derive(Clone, Debug)]
pub struct PreparedProbeRequest {
    method: ProbeHttpMethod,
    target: AuthorizedProbeTarget,
    headers: HeaderMap,
    body: Vec<u8>,
    timeout: Duration,
}

pub struct ProbeTransportResponse {
    status: StatusCode,
    headers: HeaderMap,
    body: Box<dyn Read + Send>,
}

pub trait ProbeHttpTransport {
    fn send(
        &self,
        request: &PreparedProbeRequest,
    ) -> Result<ProbeTransportResponse, ProbeBrokerError>;
}

#[derive(Clone, Copy, Debug, Default)]
pub struct ReqwestProbeHttpTransport;

impl ProbeHttpTransport for ReqwestProbeHttpTransport {
    fn send(
        &self,
        request: &PreparedProbeRequest,
    ) -> Result<ProbeTransportResponse, ProbeBrokerError> {
        let mut builder = Client::builder()
            .timeout(request.timeout)
            .connect_timeout(request.timeout)
            .redirect(reqwest::redirect::Policy::none())
            .no_proxy();
        if !matches!(
            request.target.url.host(),
            Some(Host::Ipv4(_)) | Some(Host::Ipv6(_))
        ) {
            builder = builder.resolve_to_addrs(
                &request.target.origin.host,
                &request.target.socket_addresses,
            );
        }
        let client = builder
            .build()
            .map_err(|_| ProbeBrokerError::transport("failed to build bounded HTTP client"))?;
        let mut outbound = client
            .request(request.method.as_reqwest(), request.target.url.clone())
            .headers(request.headers.clone());
        if !request.body.is_empty() {
            outbound = outbound.body(request.body.clone());
        }
        let response = outbound.send().map_err(|error| map_reqwest_error(&error))?;
        response_to_transport(response)
    }
}

fn map_reqwest_error(error: &reqwest::Error) -> ProbeBrokerError {
    use std::error::Error as _;
    let mut cause = error.source();
    let mut tls = false;
    for _ in 0..8 {
        let Some(current) = cause else {
            break;
        };
        let detail = current.to_string().to_ascii_lowercase();
        tls |= ["certificate", "certvalid", "invalidcert", "tls", "ssl"]
            .iter()
            .any(|word| detail.contains(word));
        cause = current.source();
    }
    if tls {
        return ProbeBrokerError {
            code: "tls_error",
            message: "TLS/证书握手未通过，需要按原通报进一步核验".into(),
            retryable: false,
        };
    }
    if error.is_timeout() {
        ProbeBrokerError {
            code: "request_timeout",
            message: "probe HTTP request exceeded the 12 second limit".to_string(),
            retryable: true,
        }
    } else {
        ProbeBrokerError::transport("probe HTTP request failed")
    }
}

fn response_to_transport(response: Response) -> Result<ProbeTransportResponse, ProbeBrokerError> {
    Ok(ProbeTransportResponse {
        status: response.status(),
        headers: response.headers().clone(),
        body: Box::new(response),
    })
}

pub struct ProbeBroker<R = SystemProbeDnsResolver, T = ReqwestProbeHttpTransport> {
    token: String,
    policy: ProbeBrokerPolicy,
    resolver: R,
    transport: T,
}

impl ProbeBroker<SystemProbeDnsResolver, ReqwestProbeHttpTransport> {
    pub fn new(token: String, targets: &[String]) -> Result<Self, ProbeBrokerError> {
        Self::with_components(
            token,
            targets,
            SystemProbeDnsResolver,
            ReqwestProbeHttpTransport,
        )
    }
}

impl<R: ProbeDnsResolver, T: ProbeHttpTransport> ProbeBroker<R, T> {
    pub fn restrict_requests(&mut self, limit: u32) {
        self.policy.request_limit = self.policy.request_limit.min(limit);
    }

    pub fn requests_used(&self) -> u32 {
        self.policy.requests_used
    }

    pub fn with_components(
        token: String,
        targets: &[String],
        resolver: R,
        transport: T,
    ) -> Result<Self, ProbeBrokerError> {
        if token.len() < 32 || token.len() > 256 || !token.is_ascii() {
            return Err(ProbeBrokerError::policy(
                "invalid_broker_token",
                "broker token must contain 32 to 256 ASCII characters",
            ));
        }
        let policy = ProbeBrokerPolicy::from_targets(targets, &resolver)?;
        Ok(Self {
            token,
            policy,
            resolver,
            transport,
        })
    }

    pub fn handle(&mut self, request: ProbeBrokerRequest) -> ProbeBrokerReply {
        let request_id = sanitized_request_id(&request.request_id);
        let result = self.execute(request);
        match result {
            Ok(data) => ProbeBrokerReply::success(request_id, data),
            Err(error) => ProbeBrokerReply::failure(request_id, error),
        }
    }

    pub fn handle_frame(&mut self, frame: &[u8]) -> Result<Vec<u8>, ProbeBrokerError> {
        let reply = match decode_request_frame(frame) {
            Ok(request) => self.handle(request),
            Err(error) => ProbeBrokerReply::failure("invalid-request-id".to_string(), error),
        };
        encode_reply_frame(&reply)
    }

    fn execute(
        &mut self,
        request: ProbeBrokerRequest,
    ) -> Result<ProbeBrokerResponseData, ProbeBrokerError> {
        if request.version != PROBE_BROKER_PROTOCOL_VERSION {
            return Err(ProbeBrokerError::policy(
                "unsupported_protocol",
                "probe broker protocol version is unsupported",
            ));
        }
        if !constant_time_token_eq(request.token.as_bytes(), self.token.as_bytes()) {
            return Err(ProbeBrokerError::policy(
                "authentication_failed",
                "probe broker authentication failed",
            ));
        }
        // The 12 second limit applies to the complete logical request,
        // including all manually-followed redirects.  Reqwest still gets a
        // per-hop timeout, but the deadline below prevents a redirect chain
        // from multiplying that budget.
        let deadline = Instant::now()
            .checked_add(PROBE_REQUEST_TIMEOUT)
            .ok_or_else(|| {
                ProbeBrokerError::policy("request_timeout", "probe request deadline overflow")
            })?;
        let mut url = parse_probe_url(&request.url)?;
        let mut method = request.method;
        let mut headers = validated_headers(&request.headers)?;
        let mut body = decode_upload(&request.body_base64)?;
        let started = Instant::now();
        let mut redirects_followed = 0_usize;

        loop {
            let remaining = deadline.saturating_duration_since(Instant::now());
            if remaining.is_zero() {
                return Err(request_timeout_error());
            }
            let target = self.policy.authorize(url.clone(), &self.resolver)?;
            let prepared = PreparedProbeRequest {
                method: method.clone(),
                target,
                headers: headers.clone(),
                body: body.clone(),
                timeout: remaining.min(PROBE_REQUEST_TIMEOUT),
            };
            let mut response = self.transport.send(&prepared)?;
            if Instant::now() >= deadline {
                return Err(request_timeout_error());
            }
            if request.follow_redirects && is_redirect(response.status) {
                let location = response
                    .headers
                    .get(LOCATION)
                    .and_then(|value| value.to_str().ok())
                    .ok_or_else(|| {
                        ProbeBrokerError::policy(
                            "invalid_redirect",
                            "redirect response has no valid Location header",
                        )
                    })?;
                if redirects_followed >= MAX_PROBE_REDIRECTS {
                    return Err(ProbeBrokerError::policy(
                        "redirect_limit_exceeded",
                        "probe redirect limit has been reached",
                    ));
                }
                let previous_origin = ProbeOrigin::parse(&url)?;
                let next_url = url.join(location).map_err(|_| {
                    ProbeBrokerError::policy(
                        "invalid_redirect",
                        "redirect Location is not a valid URL",
                    )
                })?;
                let mut next_url = next_url;
                next_url.set_fragment(None);
                let next_origin = ProbeOrigin::parse(&next_url)?;
                if next_origin != previous_origin {
                    strip_cross_origin_credentials(&mut headers);
                }
                url = next_url;
                redirects_followed += 1;
                if response.status == StatusCode::SEE_OTHER
                    || ((response.status == StatusCode::MOVED_PERMANENTLY
                        || response.status == StatusCode::FOUND)
                        && method == ProbeHttpMethod::Post)
                {
                    method = ProbeHttpMethod::Get;
                    body.clear();
                    headers.remove(reqwest::header::CONTENT_TYPE);
                }
                continue;
            }

            let content_length = response
                .headers
                .get(CONTENT_LENGTH)
                .and_then(|value| value.to_str().ok())
                .and_then(|value| value.parse::<u64>().ok());
            let (response_body, body_truncated) = read_bounded_response(&mut response.body)?;
            let binary = std::str::from_utf8(&response_body)
                .is_err_and(|error| error.error_len().is_some())
                || response_body.iter().take(1024).any(|byte| *byte == 0);
            if Instant::now() >= deadline {
                return Err(request_timeout_error());
            }
            return Ok(ProbeBrokerResponseData {
                status_code: response.status.as_u16(),
                headers: serialized_headers(&response.headers),
                body_base64: BASE64.encode(&response_body),
                body_text: if binary {
                    String::new()
                } else {
                    String::from_utf8_lossy(&response_body).into_owned()
                },
                body_truncated,
                body_bytes: response_body.len(),
                content_length,
                binary,
                final_url: url.to_string(),
                elapsed_ms: started.elapsed().as_millis().min(u64::MAX as u128) as u64,
                redirects_followed,
            });
        }
    }
}

fn request_timeout_error() -> ProbeBrokerError {
    ProbeBrokerError {
        code: "request_timeout",
        message: "probe HTTP request exceeded the 12 second limit".to_string(),
        retryable: true,
    }
}

/// Manually-followed redirects do not pass through reqwest's normal
/// cross-origin credential policy.  Remove headers that can authenticate the
/// caller before sending a request to a different scheme/host/effective port.
fn strip_cross_origin_credentials(headers: &mut HeaderMap) {
    let names = headers
        .keys()
        .filter(|name| {
            let normalized = name.as_str().replace('-', "");
            name == &AUTHORIZATION
                || name == &COOKIE
                || name == &PROXY_AUTHORIZATION
                || normalized == "setcookie"
                || normalized.contains("apikey")
                || normalized.contains("authtoken")
                || normalized.contains("accesstoken")
                || normalized.contains("refreshtoken")
                || normalized.contains("sessiontoken")
                || normalized == "token"
        })
        .cloned()
        .collect::<Vec<_>>();
    for name in names {
        headers.remove(name);
    }
}

fn constant_time_token_eq(left: &[u8], right: &[u8]) -> bool {
    let mut difference = left.len() ^ right.len();
    let length = left.len().max(right.len());
    for index in 0..length {
        difference |= usize::from(
            left.get(index).copied().unwrap_or_default()
                ^ right.get(index).copied().unwrap_or_default(),
        );
    }
    difference == 0
}

fn sanitized_request_id(value: &str) -> String {
    if !value.is_empty()
        && value.len() <= 128
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'_'))
    {
        value.to_string()
    } else {
        "invalid-request-id".to_string()
    }
}

fn validate_upload_size(length: usize) -> Result<(), ProbeBrokerError> {
    if length > MAX_PROBE_UPLOAD_BYTES {
        return Err(ProbeBrokerError::policy(
            "upload_too_large",
            "probe upload exceeds the 64 MiB limit",
        ));
    }
    Ok(())
}

fn decode_upload(value: &str) -> Result<Vec<u8>, ProbeBrokerError> {
    let maximum_encoded = MAX_PROBE_UPLOAD_BYTES.div_ceil(3) * 4;
    if value.len() > maximum_encoded {
        return Err(ProbeBrokerError::policy(
            "upload_too_large",
            "probe upload exceeds the 64 MiB limit",
        ));
    }
    let body = BASE64.decode(value).map_err(|_| {
        ProbeBrokerError::policy("invalid_body", "probe request body is not valid base64")
    })?;
    validate_upload_size(body.len())?;
    Ok(body)
}

fn validated_headers(values: &BTreeMap<String, String>) -> Result<HeaderMap, ProbeBrokerError> {
    if values.len() > 128 {
        return Err(ProbeBrokerError::policy(
            "too_many_headers",
            "probe request contains too many headers",
        ));
    }
    let mut headers = HeaderMap::new();
    for (name, value) in values {
        if value.len() > 16 * 1024 {
            return Err(ProbeBrokerError::policy(
                "invalid_header",
                "probe request header is too large",
            ));
        }
        let normalized = name.to_ascii_lowercase();
        if matches!(
            normalized.as_str(),
            "host"
                | "content-length"
                | "transfer-encoding"
                | "connection"
                | "proxy-authorization"
                | "proxy-connection"
                | "upgrade"
        ) {
            return Err(ProbeBrokerError::policy(
                "forbidden_header",
                "probe request contains a transport-controlled header",
            ));
        }
        let header_name = HeaderName::from_str(name).map_err(|_| {
            ProbeBrokerError::policy("invalid_header", "probe request header name is invalid")
        })?;
        let header_value = HeaderValue::from_str(value).map_err(|_| {
            ProbeBrokerError::policy("invalid_header", "probe request header value is invalid")
        })?;
        headers.insert(header_name, header_value);
    }
    Ok(headers)
}

fn serialized_headers(headers: &HeaderMap) -> BTreeMap<String, String> {
    let mut output = BTreeMap::new();
    for (name, value) in headers {
        if let Ok(value) = value.to_str() {
            output
                .entry(name.as_str().to_string())
                .and_modify(|existing: &mut String| {
                    existing.push_str(", ");
                    existing.push_str(value);
                })
                .or_insert_with(|| value.to_string());
        }
    }
    output
}

fn read_bounded_response(reader: &mut dyn Read) -> Result<(Vec<u8>, bool), ProbeBrokerError> {
    let mut body = Vec::with_capacity(MAX_PROBE_RESPONSE_BYTES.min(4096));
    reader
        .take((MAX_PROBE_RESPONSE_BYTES + 1) as u64)
        .read_to_end(&mut body)
        .map_err(|_| ProbeBrokerError::transport("failed to read probe HTTP response"))?;
    let truncated = body.len() > MAX_PROBE_RESPONSE_BYTES;
    body.truncate(MAX_PROBE_RESPONSE_BYTES);
    Ok((body, truncated))
}

fn is_redirect(status: StatusCode) -> bool {
    matches!(
        status,
        StatusCode::MOVED_PERMANENTLY
            | StatusCode::FOUND
            | StatusCode::SEE_OTHER
            | StatusCode::TEMPORARY_REDIRECT
            | StatusCode::PERMANENT_REDIRECT
    )
}

pub fn decode_request_frame(frame: &[u8]) -> Result<ProbeBrokerRequest, ProbeBrokerError> {
    if frame.len() > MAX_BROKER_FRAME_BYTES {
        return Err(ProbeBrokerError::policy(
            "frame_too_large",
            "probe broker request frame exceeds the fixed limit",
        ));
    }
    serde_json::from_slice(frame).map_err(|_| {
        ProbeBrokerError::policy(
            "invalid_protocol_message",
            "probe broker request is not valid typed JSON",
        )
    })
}

pub fn encode_reply_frame(reply: &ProbeBrokerReply) -> Result<Vec<u8>, ProbeBrokerError> {
    let payload = serde_json::to_vec(reply).map_err(|_| {
        ProbeBrokerError::policy(
            "protocol_serialization_failed",
            "probe broker response could not be serialized",
        )
    })?;
    if payload.len() > MAX_BROKER_FRAME_BYTES {
        return Err(ProbeBrokerError::policy(
            "frame_too_large",
            "probe broker response frame exceeds the fixed limit",
        ));
    }
    let mut frame = Vec::with_capacity(payload.len() + 4);
    frame.extend_from_slice(&(payload.len() as u32).to_le_bytes());
    frame.extend_from_slice(&payload);
    Ok(frame)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::cell::RefCell;
    use std::collections::VecDeque;
    use std::io::Cursor;
    use std::sync::{Arc, Mutex};

    const TOKEN: &str = "0123456789abcdef0123456789abcdef";

    #[derive(Clone)]
    struct ScriptedResolver {
        answers: Arc<Mutex<HashMap<String, VecDeque<Vec<IpAddr>>>>>,
    }

    impl ScriptedResolver {
        fn fixed(entries: &[(&str, &[IpAddr])]) -> Self {
            let answers = entries
                .iter()
                .map(|(host, addresses)| {
                    ((*host).to_string(), VecDeque::from([addresses.to_vec()]))
                })
                .collect();
            Self {
                answers: Arc::new(Mutex::new(answers)),
            }
        }

        fn scripted(host: &str, answers: Vec<Vec<IpAddr>>) -> Self {
            Self {
                answers: Arc::new(Mutex::new(HashMap::from([(
                    host.to_string(),
                    answers.into(),
                )]))),
            }
        }
    }

    impl ProbeDnsResolver for ScriptedResolver {
        fn resolve(&self, host: &str, _port: u16) -> Result<Vec<IpAddr>, ProbeBrokerError> {
            let mut answers = self.answers.lock().expect("resolver lock");
            let queue = answers
                .get_mut(host)
                .ok_or_else(|| ProbeBrokerError::transport("no scripted DNS answer"))?;
            if queue.len() > 1 {
                queue
                    .pop_front()
                    .ok_or_else(|| ProbeBrokerError::transport("scripted DNS answer is empty"))
            } else {
                queue
                    .front()
                    .cloned()
                    .ok_or_else(|| ProbeBrokerError::transport("scripted DNS answer is empty"))
            }
        }
    }

    struct ScriptedTransport {
        responses: RefCell<VecDeque<ProbeTransportResponse>>,
        calls: RefCell<Vec<(String, Duration, Vec<SocketAddr>)>>,
        headers: RefCell<Vec<HeaderMap>>,
    }

    impl ScriptedTransport {
        fn new(responses: Vec<ProbeTransportResponse>) -> Self {
            Self {
                responses: RefCell::new(responses.into()),
                calls: RefCell::new(Vec::new()),
                headers: RefCell::new(Vec::new()),
            }
        }
    }

    impl ProbeHttpTransport for ScriptedTransport {
        fn send(
            &self,
            request: &PreparedProbeRequest,
        ) -> Result<ProbeTransportResponse, ProbeBrokerError> {
            self.calls.borrow_mut().push((
                request.target.url.to_string(),
                request.timeout,
                request.target.socket_addresses.clone(),
            ));
            self.headers.borrow_mut().push(request.headers.clone());
            self.responses
                .borrow_mut()
                .pop_front()
                .ok_or_else(|| ProbeBrokerError::transport("no scripted response"))
        }
    }

    fn response(
        status: StatusCode,
        headers: &[(&str, &str)],
        body: Vec<u8>,
    ) -> ProbeTransportResponse {
        let mut map = HeaderMap::new();
        for (name, value) in headers {
            map.insert(
                HeaderName::from_str(name).expect("header name"),
                HeaderValue::from_str(value).expect("header value"),
            );
        }
        ProbeTransportResponse {
            status,
            headers: map,
            body: Box::new(Cursor::new(body)),
        }
    }

    fn request(url: &str) -> ProbeBrokerRequest {
        ProbeBrokerRequest {
            version: PROBE_BROKER_PROTOCOL_VERSION,
            token: TOKEN.to_string(),
            request_id: "request-1".to_string(),
            method: ProbeHttpMethod::Get,
            url: url.to_string(),
            headers: BTreeMap::new(),
            body_base64: String::new(),
            follow_redirects: true,
        }
    }

    #[test]
    fn origin_uses_scheme_host_and_effective_port() {
        let https = ProbeOrigin::parse(&Url::parse("https://EXAMPLE.test/a").unwrap()).unwrap();
        let explicit =
            ProbeOrigin::parse(&Url::parse("https://example.test:443/b").unwrap()).unwrap();
        let http = ProbeOrigin::parse(&Url::parse("http://example.test/b").unwrap()).unwrap();
        assert_eq!(https, explicit);
        assert_ne!(https, http);
    }

    #[test]
    fn rejects_cross_origin_redirect_before_second_network_request() {
        let ip = IpAddr::from([127, 0, 0, 1]);
        let resolver = ScriptedResolver::fixed(&[("allowed.test", &[ip])]);
        let transport = ScriptedTransport::new(vec![response(
            StatusCode::FOUND,
            &[("location", "https://evil.test/escape")],
            Vec::new(),
        )]);
        let mut broker = ProbeBroker::with_components(
            TOKEN.to_string(),
            &["https://allowed.test/start".to_string()],
            resolver,
            transport,
        )
        .unwrap();
        let reply = broker.handle(request("https://allowed.test/start"));
        assert!(!reply.ok);
        assert_eq!(reply.error.unwrap().code, "origin_not_authorized");
        assert_eq!(broker.transport.calls.borrow().len(), 1);
    }

    #[test]
    fn strips_credentials_before_an_authorized_cross_origin_redirect() {
        let ip = IpAddr::from([127, 0, 0, 1]);
        let resolver = ScriptedResolver::fixed(&[("allowed.test", &[ip]), ("next.test", &[ip])]);
        let transport = ScriptedTransport::new(vec![
            response(
                StatusCode::FOUND,
                &[("location", "https://next.test/redirected")],
                Vec::new(),
            ),
            response(StatusCode::OK, &[], b"ok".to_vec()),
        ]);
        let mut broker = ProbeBroker::with_components(
            TOKEN.to_string(),
            &[
                "https://allowed.test/start".to_string(),
                "https://next.test/redirected".to_string(),
            ],
            resolver,
            transport,
        )
        .unwrap();
        let mut item = request("https://allowed.test/start");
        item.headers = BTreeMap::from([
            ("Authorization".to_string(), "Bearer secret".to_string()),
            ("Cookie".to_string(), "session=secret".to_string()),
            ("X-Api-Key".to_string(), "secret".to_string()),
            ("X-Request-Id".to_string(), "safe".to_string()),
        ]);
        let reply = broker.handle(item);
        assert!(reply.ok, "authorized redirect should complete: {reply:?}");
        let headers = broker.transport.headers.borrow();
        assert_eq!(headers.len(), 2);
        assert!(headers[0].contains_key(AUTHORIZATION));
        assert!(headers[0].contains_key(COOKIE));
        assert!(!headers[1].contains_key(AUTHORIZATION));
        assert!(!headers[1].contains_key(COOKIE));
        assert!(!headers[1].contains_key("x-api-key"));
        assert_eq!(headers[1].get("x-request-id").unwrap(), "safe");
    }

    #[test]
    fn rejects_dns_rebinding_before_transport_and_pins_validated_address() {
        let original = IpAddr::from([127, 0, 0, 1]);
        let rebound = IpAddr::from([127, 0, 0, 2]);
        let resolver = ScriptedResolver::scripted(
            "allowed.test",
            vec![vec![original], vec![original, rebound]],
        );
        let transport = ScriptedTransport::new(vec![]);
        let mut broker = ProbeBroker::with_components(
            TOKEN.to_string(),
            &["https://allowed.test/".to_string()],
            resolver,
            transport,
        )
        .unwrap();
        let reply = broker.handle(request("https://allowed.test/check"));
        assert!(!reply.ok);
        assert_eq!(reply.error.unwrap().code, "dns_address_not_authorized");
        assert!(broker.transport.calls.borrow().is_empty());
    }

    #[test]
    fn enforces_request_timeout_and_twenty_request_budget() {
        let ip = IpAddr::from([127, 0, 0, 1]);
        let resolver = ScriptedResolver::fixed(&[("allowed.test", &[ip])]);
        let responses = (0..MAX_PROBE_REQUESTS)
            .map(|_| response(StatusCode::OK, &[], b"ok".to_vec()))
            .collect();
        let transport = ScriptedTransport::new(responses);
        let mut broker = ProbeBroker::with_components(
            TOKEN.to_string(),
            &["https://allowed.test/".to_string()],
            resolver,
            transport,
        )
        .unwrap();
        for index in 0..MAX_PROBE_REQUESTS {
            let mut item = request("https://allowed.test/check");
            item.request_id = format!("request-{index}");
            assert!(broker.handle(item).ok);
        }
        let reply = broker.handle(request("https://allowed.test/check"));
        assert!(!reply.ok);
        assert_eq!(reply.error.unwrap().code, "request_limit_exceeded");
        assert!(broker
            .transport
            .calls
            .borrow()
            .iter()
            .all(|(_, timeout, addresses)| *timeout > Duration::ZERO
                && *timeout <= PROBE_REQUEST_TIMEOUT
                && addresses == &[SocketAddr::new(ip, 443)]));
    }

    #[test]
    fn oversized_response_returns_bounded_explicitly_truncated_evidence() {
        let ip = IpAddr::from([127, 0, 0, 1]);
        let resolver = ScriptedResolver::fixed(&[("allowed.test", &[ip])]);
        let transport = ScriptedTransport::new(vec![response(
            StatusCode::OK,
            &[],
            vec![b'x'; MAX_PROBE_RESPONSE_BYTES + 1],
        )]);
        let mut broker = ProbeBroker::with_components(
            TOKEN.to_string(),
            &["https://allowed.test/".to_string()],
            resolver,
            transport,
        )
        .unwrap();
        let reply = broker.handle(request("https://allowed.test/bomb"));
        assert!(reply.ok);
        let data = reply.data.unwrap();
        assert!(data.body_truncated);
        assert_eq!(data.body_bytes, MAX_PROBE_RESPONSE_BYTES);
        assert_eq!(
            BASE64.decode(data.body_base64).unwrap().len(),
            MAX_PROBE_RESPONSE_BYTES
        );
    }

    #[test]
    fn enforces_upload_limit_before_allocation_or_transport() {
        let error = validate_upload_size(MAX_PROBE_UPLOAD_BYTES + 1).unwrap_err();
        assert_eq!(error.code, "upload_too_large");
        let encoded_limit = MAX_PROBE_UPLOAD_BYTES.div_ceil(3) * 4;
        let oversized_length = encoded_limit + 1;
        assert!(oversized_length > encoded_limit);
    }

    #[test]
    fn protocol_rejects_unknown_fields_and_bad_token_without_network() {
        let json = br#"{"version":1,"token":"0123456789abcdef0123456789abcdef","request_id":"r","method":"GET","url":"https://allowed.test/","unknown":true}"#;
        assert_eq!(
            decode_request_frame(json).unwrap_err().code,
            "invalid_protocol_message"
        );

        let ip = IpAddr::from([127, 0, 0, 1]);
        let resolver = ScriptedResolver::fixed(&[("allowed.test", &[ip])]);
        let transport = ScriptedTransport::new(vec![]);
        let mut broker = ProbeBroker::with_components(
            TOKEN.to_string(),
            &["https://allowed.test/".to_string()],
            resolver,
            transport,
        )
        .unwrap();
        let mut bad = request("https://allowed.test/");
        bad.token = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa".to_string();
        let reply = broker.handle(bad);
        assert_eq!(reply.error.unwrap().code, "authentication_failed");
        assert!(broker.transport.calls.borrow().is_empty());
    }

    #[test]
    fn reply_frame_is_length_prefixed_typed_json() {
        let reply = ProbeBrokerReply::failure(
            "request-1".to_string(),
            ProbeBrokerError::policy("denied", "denied"),
        );
        let frame = encode_reply_frame(&reply).unwrap();
        let length = u32::from_le_bytes(frame[..4].try_into().unwrap()) as usize;
        assert_eq!(length, frame.len() - 4);
        let decoded: ProbeBrokerReply = serde_json::from_slice(&frame[4..]).unwrap();
        assert_eq!(decoded, reply);
    }
}
