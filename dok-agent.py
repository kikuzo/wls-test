from __future__ import annotations

import os
import sys
import json
import time
import threading
import requests
from requests.auth import HTTPBasicAuth
from flask import Flask, jsonify, request

# 高火力 DOK API のベースURL
API_BASE_URL = "https://secure.sakura.ad.jp/cloud/zone/is1a/api/managed-container/1.0"

# さくらのクラウド APIキー情報を環境変数から取得する想定
#   ACCESS TOKEN          -> SAKURA_CLOUD_ACCESS_TOKEN
#   ACCESS TOKEN SECRET   -> SAKURA_CLOUD_ACCESS_TOKEN_SECRET
ACCESS_TOKEN = os.getenv("SAKURA_CLOUD_ACCESS_TOKEN")
ACCESS_TOKEN_SECRET = os.getenv("SAKURA_CLOUD_ACCESS_TOKEN_SECRET")

app = Flask(__name__)


def get_cloud_account_info():
    """
    高火力 DOK API 経由でクラウドアカウント情報を取得する。
    GET /auth/
    """
    if not ACCESS_TOKEN or not ACCESS_TOKEN_SECRET:
        raise RuntimeError(
            "環境変数 SAKURA_CLOUD_ACCESS_TOKEN / "
            "SAKURA_CLOUD_ACCESS_TOKEN_SECRET を設定してください。"
        )

    url = f"{API_BASE_URL}/auth/"
    try:
        response = requests.get(
            url,
            auth=HTTPBasicAuth(ACCESS_TOKEN, ACCESS_TOKEN_SECRET),
            timeout=10,
        )
    except requests.RequestException as e:
        raise RuntimeError(f"高火力 DOK API への接続に失敗しました: {e}") from e

    try:
        response.raise_for_status()
    except requests.HTTPError as e:
        raise RuntimeError(
            f"API呼び出しに失敗しました (status={response.status_code}): "
            f"{response.text}"
        ) from e

    return response.json()


def get_task_info(task_id: str):
    """
    高火力 DOK API 経由で登録済みのタスク情報を取得する。
    GET /tasks/{taskId}/

    Parameters
    ----------
    task_id : str
        タスクID（UUID形式）

    Returns
    -------
    dict
        タスク情報（id, created_at, updated_at, status, containers, tags など）
    """
    if not ACCESS_TOKEN or not ACCESS_TOKEN_SECRET:
        raise RuntimeError(
            "環境変数 SAKURA_CLOUD_ACCESS_TOKEN / "
            "SAKURA_CLOUD_ACCESS_TOKEN_SECRET を設定してください。"
        )

    url = f"{API_BASE_URL}/tasks/{task_id}/"
    try:
        response = requests.get(
            url,
            auth=HTTPBasicAuth(ACCESS_TOKEN, ACCESS_TOKEN_SECRET),
            timeout=10,
        )
    except requests.RequestException as e:
        raise RuntimeError(f"高火力 DOK API への接続に失敗しました: {e}") from e

    try:
        response.raise_for_status()
    except requests.HTTPError as e:
        if response.status_code == 404:
            raise RuntimeError(
                f"タスクが見つかりません (task_id={task_id})"
            ) from e
        raise RuntimeError(
            f"API呼び出しに失敗しました (status={response.status_code}): "
            f"{response.text}"
        ) from e

    return response.json()


def wait_for_task_completion(task_id: str, check_interval: int = 10):
    """
    タスクの完了を待つ。10秒ごとにタスク情報を取得し、
    statusが'waiting'以外になったら終了する。

    Parameters
    ----------
    task_id : str
        タスクID（UUID形式）
    check_interval : int
        チェック間隔（秒）。デフォルト：10秒
    """
    print("\n=== wait_for_task_completion ===")
    print(f"タスク完了を待機中... (check_interval={check_interval}秒)")

    while True:
        try:
            task_info = get_task_info(task_id)
            status = task_info.get('status')
            updated_at = task_info.get('updated_at')

            print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] status: {status}, updated_at: {updated_at}")

            # statusが'waiting'以外になったら終了
            if status != 'waiting':
                print("\n=== Task completed ===")
                print(f"status: {status}")
                print(json.dumps(task_info, ensure_ascii=False, indent=2))
                break

            # check_interval秒待機
            time.sleep(check_interval)

        except Exception as e:
            print(f"[ERROR] タスク情報取得に失敗しました: {e}", file=sys.stderr)
            raise


def cancel_task(task_id: str):
    """
    高火力 DOK のタスクをキャンセルする。
    POST /tasks/{taskId}/cancel/

    Parameters
    ----------
    task_id : str
        タスクID（UUID形式）

    Returns
    -------
    dict
        キャンセル後のタスク情報
    """
    if not ACCESS_TOKEN or not ACCESS_TOKEN_SECRET:
        raise RuntimeError(
            "環境変数 SAKURA_CLOUD_ACCESS_TOKEN / "
            "SAKURA_CLOUD_ACCESS_TOKEN_SECRET を設定してください。"
        )

    url = f"{API_BASE_URL}/tasks/{task_id}/cancel/"
    try:
        response = requests.post(
            url,
            auth=HTTPBasicAuth(ACCESS_TOKEN, ACCESS_TOKEN_SECRET),
            timeout=10,
        )
    except requests.RequestException as e:
        raise RuntimeError(f"高火力 DOK API への接続に失敗しました: {e}") from e

    try:
        response.raise_for_status()
    except requests.HTTPError as e:
        if response.status_code == 404:
            raise RuntimeError(
                f"タスクが見つかりません (task_id={task_id})"
            ) from e
        elif response.status_code == 403:
            raise RuntimeError(
                f"タスクをキャンセルできません。キャンセル可能な状態にあります (task_id={task_id})"
            ) from e
        raise RuntimeError(
            f"API呼び出しに失敗しました (status={response.status_code}): "
            f"{response.text}"
        ) from e

    return response.json()


def register_task(
    name: str,
    image: str,
    command: list[str],
    http_port: int,
    status_callback: str | None = None,
):
    """
    高火力 DOK にタスクを登録する。
    POST /tasks/

    Parameters
    ----------
    name : str
        タスク名
    image : str
        コンテナイメージ（例: 'nginx:latest'）
    command : list[str]
        コンテナ内で実行するコマンド（例: ['/bin/sh', '-c', 'env']）
    http_port : int
        公開する HTTP ポート番号（例: 80）
    status_callback : str | None
        タスク状態のコールバック先URL
    """
    if not ACCESS_TOKEN or not ACCESS_TOKEN_SECRET:
        raise RuntimeError(
            "環境変数 SAKURA_CLOUD_ACCESS_TOKEN / "
            "SAKURA_CLOUD_ACCESS_TOKEN_SECRET を設定してください。"
        )

    url = f"{API_BASE_URL}/tasks/"

    # 必須パラメータ:
    # - name
    # - containers (ContainerDefinition の配列)
    # - tags（文字列配列）
    # - execution_time_limit_sec（null 可）
    payload = {
        "name": name,
        "containers": [
            {
                "image": image,
                # 公開レジストリを使うので registry は省略
                "command": command,
                "http": {
                    "port": http_port,
                    "path": "/",
                },
                # プランはサンプルとして v100-32gb を固定
                "plan": "h100-80gb",
            }
        ],
        # タグはサンプルとして固定
        "tags": ["example"],
        "execution_time_limit_sec": None,
    }
    if status_callback:
        payload["status_callback"] = status_callback

    try:
        response = requests.post(
            url,
            auth=HTTPBasicAuth(ACCESS_TOKEN, ACCESS_TOKEN_SECRET),
            headers={"Content-Type": "application/json"},
            data=json.dumps(payload),
            timeout=10,
        )
    except requests.RequestException as e:
        raise RuntimeError(f"高火力 DOK API への接続に失敗しました: {e}") from e

    try:
        response.raise_for_status()
    except requests.HTTPError as e:
        raise RuntimeError(
            f"タスク登録に失敗しました (status={response.status_code}): "
            f"{response.text}"
        ) from e

    return response.json()


def _normalize_callback_url(status_callback: str) -> str:
    if "://" not in status_callback:
        return f"http://{status_callback}"
    return status_callback


def _post_status_callback(status_callback: str, task_id: str, status: str) -> None:
    callback_url = _normalize_callback_url(status_callback)
    try:
        requests.post(
            callback_url,
            json={"task_id": task_id, "status": status},
            timeout=10,
        )
    except requests.RequestException as e:
        print(f"[WARN] status_callback failed: {e}", file=sys.stderr)


def _watch_task_status(task_id: str, status_callback: str, check_interval: int = 10) -> None:
    while True:
        try:
            task_info = get_task_info(task_id)
            status = task_info.get("status")
            if status == "running":
                http_uri = task_info.get("http_uri")
                print(f"[INFO] Task running: task_id={task_id}, http_uri={http_uri}")
            _post_status_callback(status_callback, task_id, status)

            if status != "waiting":
                break

            time.sleep(check_interval)
        except Exception as e:
            print(f"[WARN] タスク情報取得に失敗しました: {e}", file=sys.stderr)
            break


@app.post("/register_task")
def register_task_api():
    payload = request.get_json(silent=True)
    if payload is None:
        return jsonify({"error": "Invalid or missing JSON payload"}), 400

    task_name = payload.get("task_name")
    image = payload.get("image")
    command = payload.get("command")
    http_port = payload.get("http_port")
    status_callback = payload.get("status_callback")

    if not task_name or not image or command is None or http_port is None:
        return jsonify({"error": "Missing required fields"}), 400

    try:
        task = register_task(
            name=task_name,
            image=image,
            command=command,
            http_port=http_port,
            status_callback=status_callback,
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    if status_callback and task.get("status") == "waiting":
        task_id = task.get("id")
        if task_id:
            thread = threading.Thread(
                target=_watch_task_status,
                args=(task_id, status_callback),
                daemon=True,
            )
            thread.start()

    return jsonify(task), 200


@app.post("/cancel_task")
def cancel_task_api():
    _ = request.get_json(silent=True)
    return jsonify({"status": "not_implemented"}), 501


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8081)
