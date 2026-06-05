"""
SageMath HTTP API Wrapper for CTF Agent.

Accepts Sage code via POST /execute, runs it, and returns stdout/stderr.
Designed to run inside the sagemath/sagemath Docker container.
"""

import os
import sys
import json
import base64
import tempfile
import subprocess
import time
from flask import Flask, request, jsonify

app = Flask(__name__)

# Configuration
API_KEY = os.environ.get("SAGE_API_KEY", "")
MAX_TIMEOUT = int(os.environ.get("SAGE_MAX_TIMEOUT", "120"))
MAX_OUTPUT = int(os.environ.get("SAGE_MAX_OUTPUT", "100000"))  # 100KB


def verify_api_key():
    """Check API key if configured."""
    if not API_KEY:
        return True
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:] == API_KEY
    key = request.headers.get("X-API-Key", "")
    return key == API_KEY


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "sage-api"})


@app.route("/execute", methods=["POST"])
def execute():
    if not verify_api_key():
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json(force=True, silent=True)
    if not data or "code" not in data:
        return jsonify({"error": "Missing 'code' field"}), 400

    code = data["code"]
    timeout = min(data.get("timeout", MAX_TIMEOUT), MAX_TIMEOUT)

    # Write uploaded files to /tmp before execution
    uploaded_files = []
    files_dict = data.get("files", {})
    for filename, b64content in files_dict.items():
        # Sanitize filename: only allow writing to /tmp
        safe_name = os.path.basename(filename)
        dest = os.path.join("/tmp", safe_name)
        try:
            raw = base64.b64decode(b64content)
            with open(dest, "wb") as uf:
                uf.write(raw)
            uploaded_files.append(dest)
        except Exception as e:
            return jsonify({"error": f"Failed to write file {safe_name}: {e}"}), 400

    # Write code to a temp file
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".sage", delete=False, dir="/tmp"
    ) as f:
        f.write(code)
        tmp_path = f.name

    start_time = time.time()
    try:
        result = subprocess.run(
            ["sage", tmp_path],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd="/tmp",
        )
        elapsed = round(time.time() - start_time, 2)

        stdout = result.stdout
        stderr = result.stderr

        # Truncate output if too long
        if len(stdout) > MAX_OUTPUT:
            stdout = stdout[:MAX_OUTPUT] + "\n... [output truncated]"
        if len(stderr) > MAX_OUTPUT:
            stderr = stderr[:MAX_OUTPUT] + "\n... [stderr truncated]"

        return jsonify({
            "stdout": stdout,
            "stderr": stderr,
            "exit_code": result.returncode,
            "elapsed": elapsed,
        })

    except subprocess.TimeoutExpired:
        elapsed = round(time.time() - start_time, 2)
        return jsonify({
            "stdout": "",
            "stderr": f"Execution timed out after {timeout}s",
            "exit_code": -1,
            "elapsed": elapsed,
        })
    except Exception as e:
        return jsonify({
            "stdout": "",
            "stderr": str(e),
            "exit_code": -1,
            "elapsed": round(time.time() - start_time, 2),
        })
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        # Clean up uploaded files
        for uf in uploaded_files:
            try:
                os.unlink(uf)
            except OSError:
                pass


@app.route("/version", methods=["GET"])
def version():
    """Return SageMath version."""
    if not verify_api_key():
        return jsonify({"error": "Unauthorized"}), 401
    try:
        result = subprocess.run(
            ["sage", "--version"], capture_output=True, text=True, timeout=10
        )
        return jsonify({"version": result.stdout.strip()})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8617"))
    app.run(host="0.0.0.0", port=port, debug=False)
