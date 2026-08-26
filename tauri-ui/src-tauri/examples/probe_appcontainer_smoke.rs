#[allow(dead_code)]
#[path = "../src/backend/probe_broker.rs"]
mod probe_broker;
#[allow(dead_code)]
#[path = "../src/backend/probe_runner.rs"]
mod probe_runner;
#[path = "../src/backend/probe_sandbox.rs"]
mod probe_sandbox;
#[allow(dead_code)]
#[path = "../src/backend/probe_wheels.rs"]
mod probe_wheels;

use serde_json::{json, Value};
use std::fs;
use std::io::{Read, Write};
use std::net::TcpListener;
use std::path::PathBuf;
use std::process::ExitCode;
use std::thread;
use std::time::{Duration, Instant};

fn main() -> ExitCode {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../..")
        .join(".tmp-probe-appcontainer-interactive");
    let result = run_smoke(&root);
    let report = match result {
        Ok(value) => json!({"ok": true, "result": value}),
        Err(error) => json!({"ok": false, "error": error}),
    };
    let _ = fs::create_dir_all(&root);
    let _ = fs::write(
        root.join("latest.json"),
        serde_json::to_vec_pretty(&report).unwrap_or_else(|_| b"{\"ok\":false}".to_vec()),
    );
    if report["ok"] == Value::Bool(true) {
        ExitCode::SUCCESS
    } else {
        ExitCode::FAILURE
    }
}

fn run_smoke(root: &PathBuf) -> Result<Value, String> {
    fs::create_dir_all(root).map_err(|error| error.to_string())?;
    let listener = TcpListener::bind("127.0.0.1:0").map_err(|error| error.to_string())?;
    listener
        .set_nonblocking(true)
        .map_err(|error| error.to_string())?;
    let address = listener.local_addr().map_err(|error| error.to_string())?;
    let server = thread::spawn(move || -> Result<(), String> {
        let deadline = Instant::now() + Duration::from_secs(30);
        loop {
            match listener.accept() {
                Ok((mut stream, _)) => {
                    stream
                        .set_read_timeout(Some(Duration::from_secs(5)))
                        .map_err(|error| error.to_string())?;
                    let mut request = Vec::new();
                    let mut buffer = [0_u8; 4096];
                    while !request.windows(4).any(|item| item == b"\r\n\r\n") {
                        let count = stream
                            .read(&mut buffer)
                            .map_err(|error| error.to_string())?;
                        if count == 0 {
                            break;
                        }
                        request.extend_from_slice(&buffer[..count]);
                        if request.len() > 64 * 1024 {
                            return Err("mock request exceeded 64 KiB".to_string());
                        }
                    }
                    let body = b"probe-broker-ok";
                    write!(
                        stream,
                        "HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
                        body.len()
                    )
                    .and_then(|_| stream.write_all(body))
                    .map_err(|error| error.to_string())?;
                    return Ok(());
                }
                Err(error) if error.kind() == std::io::ErrorKind::WouldBlock => {
                    if Instant::now() >= deadline {
                        return Err("mock server did not receive the broker request".to_string());
                    }
                    thread::sleep(Duration::from_millis(50));
                }
                Err(error) => return Err(error.to_string()),
            }
        }
    });
    let target = format!("http://{address}/probe");
    let result = probe_runner::execute(
        root,
        &json!({
            "script": "def run(targets, context):\n    import idna\n    response = http_request('GET', targets[0])\n    return {'status': response.status_code, 'text': response.text, 'marker': context.get('marker'), 'idna': idna.encode('example.com').decode('ascii')}\n",
            "targets": [target],
            "context": {"marker": "interactive-appcontainer-ok"},
            "packages": ["idna"]
        }),
    );
    let probe_result = result.map_err(|error| error.to_string());
    let server_result = server
        .join()
        .map_err(|_| "mock HTTP server panicked".to_string())?;
    let result = probe_result?;
    server_result?;
    if result["result"]["status"] != 200
        || result["result"]["text"] != "probe-broker-ok"
        || result["result"]["marker"] != "interactive-appcontainer-ok"
        || result["result"]["idna"] != "example.com"
    {
        return Err(format!("unexpected AppContainer probe result: {result}"));
    }
    Ok(result)
}
