#!/usr/bin/env python3
"""vrt-agent: `register_task()` を通じて vllm モデル用の Docker コンテナを起動するスクリプト。"""
import subprocess
import logging
import time
import sys
import re
from typing import Optional
import requests

logging.basicConfig(level=logging.INFO)
_LOGGER = logging.getLogger(__name__)

# OPEN-WEBUI サーバーホスト（ホスト:ポート）。将来の変更のために変数化。
OPEN_WEBUI_SERVER_HOST = "133.125.84.161:7000"
# 完全な再起動エンドポイントURL
OPEN_WEBUI_SERVER_URL = f"http://{OPEN_WEBUI_SERVER_HOST}/restart_server"
# 再起動時に送信するペイロード（JSON）。将来の変更のために変数化。
RESTART_PAYLOAD = {"OPENAI_API_BASE_URL": "http://133.125.90.81:8000/v1"}


def _strip_ansi_codes(text: str) -> str:
    """テキストから ANSI エスケープシーケンスを除去する。"""
    ansi_escape = re.compile(r'\x1b\[[0-9;]*m')
    return ansi_escape.sub('', text)


def register_task(
    name: str,
    image: str,
    command: list[str],
    http_port: int,
    status_callback: str | None = None,
) -> str:
    """高火力 DOK にタスクを登録する。
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

    返り値:
      起動に成功した場合はコンテナ ID の文字列を返す。

    例外:
      subprocess.CalledProcessError: docker コマンドが失敗した場合に送出される。
    """
    cmd = [
      "docker",
      "run",
      "-d",
      "--name",
      "vllm-openai",
      "--gpus",
      "all",
      "-p",
      f"{http_port}:{http_port}",
      "--ipc=host",
      image,
    ] + command

    _LOGGER.info("Starting docker container: %s", " ".join(cmd))
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=None)

    if result.returncode != 0:
        _LOGGER.error("Docker run failed: %s", result.stderr.strip())
        raise subprocess.CalledProcessError(result.returncode, cmd, output=result.stdout, stderr=result.stderr)

    container_id = result.stdout.strip()
    _LOGGER.info("Started container: %s", container_id)
    return container_id


def watch_task_status(container_id: str, timeout: Optional[int] = None, poll_interval: int = 10) -> bool:
    """`docker logs <container_id>` を `poll_interval` 秒ごとにポーリングし、
    起動完了を示すログ行を監視する。

    対象のログ行:
      (APIServer pid=1) INFO:     Application startup complete.

    見つかった場合は "起動完了しました" を表示して True を返す。`timeout` が設定され
    て時間を超過した場合は False を返す。
    """
    target = "(APIServer pid=1) INFO:     Application startup complete."
    start_ts = time.time()

    _LOGGER.info("Watching logs for container %s", container_id)
    while True:
      try:
        cmd = ["docker", "logs", container_id]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
      except Exception as exc:
        _LOGGER.error("Failed to run docker logs: %s", exc)
        # 待機して再試行する
        time.sleep(poll_interval)
        continue

      if result.returncode != 0:
        _LOGGER.warning("docker logs が非ゼロを返しました: %s", result.stderr.strip())

      logs = result.stdout or ""
      if logs:
        print(logs)

      # 検索前に ANSI エスケープコードを除去する
      logs_clean = _strip_ansi_codes(logs)
      if target in logs_clean:
        print("起動完了しました")
        _LOGGER.info("Detected startup completion in logs for %s", container_id)
        return True
      # まだ見つかっていない — 待機中を表示
      print("waiting...", flush=True)

      if timeout is not None and (time.time() - start_ts) > timeout:
        _LOGGER.error("起動ログ待機のタイムアウト: %s", container_id)
        return False

      time.sleep(poll_interval)


def cancel_task() -> None:
    """vllm-openai コンテナを停止・削除する。
    
    `docker stop vllm-openai` と `docker rm vllm-openai` を実行する。
    """
    try:
        # コンテナ停止
        _LOGGER.info("Stopping container vllm-openai")
        stop_result = subprocess.run(
            ["docker", "stop", "vllm-openai"],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if stop_result.returncode != 0:
            if "No such container" not in stop_result.stderr:
                _LOGGER.warning("docker stop failed: %s", stop_result.stderr.strip())
        
        # コンテナ削除
        _LOGGER.info("Removing container vllm-openai")
        rm_result = subprocess.run(
            ["docker", "rm", "-f", "vllm-openai"],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if rm_result.returncode != 0:
            if "No such container" not in rm_result.stderr:
                _LOGGER.warning("docker rm failed: %s", rm_result.stderr.strip())
        
        _LOGGER.info("Container vllm-openai stopped and removed")
        
    except subprocess.TimeoutExpired:
        _LOGGER.error("Docker command timeout while stopping container")
        raise
    except Exception as e:
        _LOGGER.error("Failed to stop/remove container: %s", e)
        raise


if __name__ == "__main__":
  try:
    cid = register_task()
    print(cid)

    # Monitor container logs until startup is confirmed
    started = watch_task_status(cid)
    if started:
      # 起動確認後、別サーバーの `/restart_server` エンドポイントへ POST を送信する
      try:
        _LOGGER.info("Posting restart request to %s", OPEN_WEBUI_SERVER_URL)
        resp = requests.post(OPEN_WEBUI_SERVER_URL, json=RESTART_PAYLOAD, headers={"Content-Type": "application/json"}, timeout=10)
        _LOGGER.info("Restart request sent, status=%s", resp.status_code)
        print("Restart request response:", resp.status_code, resp.text)
      except Exception as e:
        _LOGGER.error("Failed to send restart request: %s", e)

      sys.exit(0)
    else:
      sys.exit(1)

  except subprocess.CalledProcessError as e:
    print("Failed to start container:", e.stderr or e)
    sys.exit(1)
