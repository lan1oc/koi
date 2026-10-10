use super::*;
use std::net::TcpStream;
static NEXT_CONNECTION: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(1);
pub(super) struct ProtocolConnection {
    origin: String,
    channel: Channel,
}
enum Channel {
    Tcp(TcpStream),
    Tls(Box<rustls::StreamOwned<rustls::ClientConnection, TcpStream>>),
}
impl Read for Channel {
    fn read(&mut self, buf: &mut [u8]) -> std::io::Result<usize> {
        match self {
            Self::Tcp(s) => s.read(buf),
            Self::Tls(s) => s.read(buf),
        }
    }
}
impl Write for Channel {
    fn write(&mut self, buf: &[u8]) -> std::io::Result<usize> {
        match self {
            Self::Tcp(s) => s.write(buf),
            Self::Tls(s) => s.write(buf),
        }
    }
    fn flush(&mut self) -> std::io::Result<()> {
        match self {
            Self::Tcp(s) => s.flush(),
            Self::Tls(s) => s.flush(),
        }
    }
}
impl Channel {
    fn set_timeout(&self, timeout: Duration) -> std::io::Result<()> {
        let stream = match self {
            Self::Tcp(s) => s,
            Self::Tls(s) => &s.sock,
        };
        stream.set_read_timeout(Some(timeout))?;
        stream.set_write_timeout(Some(timeout))
    }
}
fn connect(
    target: &AuthorizedProbeTarget,
    request: &ProbeBrokerRequest,
    deadline: Instant,
) -> Result<Channel, ProbeBrokerError> {
    let mut found = None;
    for address in &target.socket_addresses {
        let timeout = deadline.saturating_duration_since(Instant::now());
        if timeout.is_zero() {
            return Err(request_timeout_error());
        }
        if let Ok(s) = TcpStream::connect_timeout(address, timeout) {
            found = Some(s);
            break;
        }
    }
    let stream = found.ok_or_else(|| {
        ProbeBrokerError::transport("specified protocol target could not be connected")
    })?;
    let channel = if request.transport.as_deref() == Some("tls_open") {
        let roots =
            rustls::RootCertStore::from_iter(webpki_roots::TLS_SERVER_ROOTS.iter().cloned());
        let mut config = rustls::ClientConfig::builder()
            .with_root_certificates(roots)
            .with_no_client_auth();
        if request.verify_tls == Some(false) {
            config
                .dangerous()
                .set_certificate_verifier(std::sync::Arc::new(ReportedUnverifiedCertificate));
        }
        let name =
            rustls::pki_types::ServerName::try_from(target.origin.host.clone()).map_err(|_| {
                ProbeBrokerError::policy("invalid_tls_name", "invalid reported TLS name")
            })?;
        let c = rustls::ClientConnection::new(std::sync::Arc::new(config), name).map_err(|e| {
            ProbeBrokerError::transport(format!("TLS session initialization failed: {e}"))
        })?;
        Channel::Tls(Box::new(rustls::StreamOwned::new(c, stream)))
    } else {
        Channel::Tcp(stream)
    };
    channel
        .set_timeout(deadline.saturating_duration_since(Instant::now()))
        .map_err(|e| ProbeBrokerError::transport(e.to_string()))?;
    Ok(channel)
}
fn response(
    target: &AuthorizedProbeTarget,
    request: &ProbeBrokerRequest,
    bytes: Vec<u8>,
    started: Instant,
    id: &str,
) -> ProbeBrokerResponseData {
    ProbeBrokerResponseData {
        status_code: 0,
        headers: BTreeMap::from([
            ("koi-connection-id".into(), id.into()),
            (
                "koi-transport".into(),
                request.transport.clone().unwrap_or_default(),
            ),
        ]),
        body_text: String::from_utf8_lossy(&bytes).into_owned(),
        body_base64: BASE64.encode(&bytes),
        body_truncated: false,
        body_bytes: bytes.len(),
        content_length: None,
        binary: true,
        final_url: target.url.to_string(),
        elapsed_ms: started.elapsed().as_millis() as u64,
        redirects_followed: 0,
    }
}
pub(super) fn execute(
    connections: &mut BTreeMap<String, ProtocolConnection>,
    target: AuthorizedProbeTarget,
    request: &ProbeBrokerRequest,
    deadline: Instant,
) -> Result<ProbeBrokerResponseData, ProbeBrokerError> {
    let started = Instant::now();
    let transport = request.transport.as_deref().unwrap_or_default();
    if matches!(transport, "tcp_open" | "tls_open") {
        if connections.len() >= 16 {
            return Err(ProbeBrokerError::policy(
                "connection_limit",
                "close an existing protocol connection before opening more",
            ));
        }
        let channel = connect(&target, request, deadline)?;
        let id = format!(
            "connection-{}-{}",
            std::process::id(),
            NEXT_CONNECTION.fetch_add(1, std::sync::atomic::Ordering::Relaxed)
        );
        let origin = target.url.origin().ascii_serialization();
        connections.insert(id.clone(), ProtocolConnection { origin, channel });
        return Ok(response(&target, request, Vec::new(), started, &id));
    }
    let id = request.connection_id.as_deref().ok_or_else(|| {
        ProbeBrokerError::policy(
            "missing_connection",
            "protocol action requires connection_id",
        )
    })?;
    let current = connections.get_mut(id).ok_or_else(|| {
        ProbeBrokerError::policy(
            "closed_connection",
            "protocol connection does not exist or is closed",
        )
    })?;
    if current.origin != target.url.origin().ascii_serialization() {
        return Err(ProbeBrokerError::policy(
            "connection_target_mismatch",
            "protocol connection belongs to another origin",
        ));
    }
    current
        .channel
        .set_timeout(deadline.saturating_duration_since(Instant::now()))
        .map_err(|e| ProbeBrokerError::transport(e.to_string()))?;
    let mut bytes = Vec::new();
    match transport {
        "socket_send" => {
            let payload = decode_upload(&request.body_base64)?;
            current
                .channel
                .write_all(&payload)
                .and_then(|_| current.channel.flush())
                .map_err(|e| ProbeBrokerError::transport(format!("protocol send failed: {e}")))?;
        }
        "socket_recv" => {
            bytes.resize(
                request
                    .response_limit
                    .unwrap_or(8192)
                    .clamp(1, MAX_PROBE_RESPONSE_BYTES),
                0,
            );
            let count = current.channel.read(&mut bytes).map_err(|e| {
                if matches!(
                    e.kind(),
                    std::io::ErrorKind::TimedOut | std::io::ErrorKind::WouldBlock
                ) {
                    request_timeout_error()
                } else {
                    ProbeBrokerError::transport(format!("protocol receive failed: {e}"))
                }
            })?;
            bytes.truncate(count);
        }
        "socket_close" => {
            connections.remove(id);
        }
        _ => {
            return Err(ProbeBrokerError::policy(
                "unsupported_protocol_action",
                "unknown protocol connection action",
            ))
        }
    }
    Ok(response(&target, request, bytes, started, id))
}

pub(super) fn udp_exchange(
    target: AuthorizedProbeTarget,
    request: &ProbeBrokerRequest,
    deadline: Instant,
) -> Result<ProbeBrokerResponseData, ProbeBrokerError> {
    let payload = decode_upload(&request.body_base64)?;
    if payload.len() > 65507 {
        return Err(ProbeBrokerError::policy(
            "datagram_limit",
            "UDP payload exceeds 65507 bytes",
        ));
    }
    let started = Instant::now();
    let mut last = None;
    for address in &target.socket_addresses {
        let bind = if address.is_ipv4() {
            "0.0.0.0:0"
        } else {
            "[::]:0"
        };
        let socket = std::net::UdpSocket::bind(bind)
            .map_err(|error| ProbeBrokerError::transport(error.to_string()))?;
        let timeout = deadline.saturating_duration_since(Instant::now());
        if timeout.is_zero() {
            return Err(request_timeout_error());
        }
        socket
            .set_read_timeout(Some(timeout))
            .map_err(|error| ProbeBrokerError::transport(error.to_string()))?;
        socket
            .set_write_timeout(Some(timeout))
            .map_err(|error| ProbeBrokerError::transport(error.to_string()))?;
        if let Err(error) = socket.connect(address).and_then(|_| socket.send(&payload)) {
            last = Some(error.to_string());
            continue;
        }
        let limit = request.response_limit.unwrap_or(65507).clamp(1, 65507);
        let mut bytes = vec![0u8; 65508];
        let count = socket.recv(&mut bytes).map_err(|error| {
            if matches!(
                error.kind(),
                std::io::ErrorKind::TimedOut | std::io::ErrorKind::WouldBlock
            ) {
                request_timeout_error()
            } else {
                ProbeBrokerError::transport(error.to_string())
            }
        })?;
        let truncated = count > limit;
        bytes.truncate(count.min(limit));
        let mut data = response(&target, request, bytes, started, "");
        data.body_truncated = truncated;
        return Ok(data);
    }
    Err(ProbeBrokerError::transport(
        last.unwrap_or_else(|| "UDP target is unavailable".into()),
    ))
}
