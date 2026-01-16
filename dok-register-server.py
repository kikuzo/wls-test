from __future__ import annotations

import json
import sys
import threading

import requests
from flask import Flask, jsonify, request

REGISTER_URL = "http://localhost:8081/register_task"
DEFAULT_PAYLOAD = {
    "task_name": "openai-gptoss-task",
    "image": "vllm/vllm-openai:gptoss",
    "command": ["--model openai/gpt-oss-20b"],
    "http_port": 8000,
    "status_callback": "localhost:8082/task_status",
}

app = Flask(__name__)


def _post_register_task(payload: dict) -> None:
    try:
        response = requests.post(REGISTER_URL, json=payload, timeout=10)
        response.raise_for_status()
    except requests.RequestException as exc:
        print(f"[ERROR] register_task failed: {exc}", file=sys.stderr)
        return

    try:
        data = response.json()
    except ValueError:
        print(f"[WARN] Non-JSON response: {response.text}")
        return

    print("[INFO] register_task response:")
    print(json.dumps(data, ensure_ascii=False, indent=2))


def _stdin_watcher() -> None:
    print("Type anything and press Enter to call /register_task.")
    print("If you paste JSON, it will be used as the payload.")
    while True:
        line = sys.stdin.readline()
        if line == "":
            break

        line = line.strip()
        if not line:
            continue

        payload = DEFAULT_PAYLOAD
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            pass

        _post_register_task(payload)


@app.post("/task_status")
def task_status():
    payload = request.get_json(silent=True)
    if payload is None:
        return jsonify({"error": "Invalid or missing JSON payload"}), 400

    print("[INFO] /task_status payload:")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return jsonify({"status": "ok"}), 200


def main() -> None:
    thread = threading.Thread(target=_stdin_watcher, daemon=True)
    thread.start()
    app.run(host="0.0.0.0", port=8082)


if __name__ == "__main__":
    main()
