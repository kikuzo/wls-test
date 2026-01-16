import os
import sys
import json
import time
import requests
from requests.auth import HTTPBasicAuth

# 高火力 DOK API のベースURL
API_BASE_URL = "https://secure.sakura.ad.jp/cloud/zone/is1a/api/managed-container/1.0"

# さくらのクラウド APIキー情報を環境変数から取得する想定
#   ACCESS TOKEN          -> SAKURA_CLOUD_ACCESS_TOKEN
#   ACCESS TOKEN SECRET   -> SAKURA_CLOUD_ACCESS_TOKEN_SECRET
ACCESS_TOKEN = os.getenv("SAKURA_CLOUD_ACCESS_TOKEN")
ACCESS_TOKEN_SECRET = os.getenv("SAKURA_CLOUD_ACCESS_TOKEN_SECRET")


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
    print(f"\n=== wait_for_task_completion ===")
    print(f"タスク完了を待機中... (check_interval={check_interval}秒)")

    while True:
        try:
            task_info = get_task_info(task_id)
            status = task_info.get('status')
            updated_at = task_info.get('updated_at')

            print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] status: {status}, updated_at: {updated_at}")

            # statusが'waiting'以外になったら終了
            if status != 'waiting':
                print(f"\n=== Task completed ===")
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


def register_task(name: str, image: str, command: list[str], http_port: int):
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
    # - execution_time_limit_sec（null 可）:contentReference[oaicite:1]{index=1}
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


def main():
    # 1. アカウント情報取得
    print("=== get_cloud_account_info ===")
    info = get_cloud_account_info()
    print(json.dumps(info, ensure_ascii=False, indent=2))

    # 2. タスク登録（サンプルパラメータをコード内に埋め込み）
    #task_name = "sample-nginx-task"
    #image = "nginx:latest"
    #command = ["/bin/sh", "-c", "env"]
    #http_port = 80

    # 2. タスク登録（サンプルパラメータをコード内に埋め込み）
    task_name = "openai-gptoss-task"
    image = "vllm/vllm-openai:gptoss"
    #command = ["--model openai/gpt-oss-20b --gpu-memory-utilization 0.95"]
    command = ["--model openai/gpt-oss-20b"]
    http_port = 8000

    print("\n=== register_task ===")
    print(f"Task name : {task_name}")
    print(f"Image     : {image}")
    print(f"Command   : {command}")
    print(f"HTTP port : {http_port}")

    task = register_task(
        name=task_name,
        image=image,
        command=command,
        http_port=http_port,
    )

    print("\n=== created task ===")
    print(json.dumps(task, ensure_ascii=False, indent=2))

    # よく使いそうな情報を少しだけ抜き出して表示
    print("\n=== task summary ===")
    task_id = task.get('id')
    print(f"task_id : {task_id}")
    print(f"status  : {task.get('status')}")
    print(f"http_uri: {task.get('http_uri')}")

    # 3. タスク情報取得を繰り返す（statusがwaiting以外になるまで）
    if task_id:
        wait_for_task_completion(task_id)

        # 4. 10秒スリープ後、タスク情報を再取得
        print(f"\n=== sleep 10 seconds ===")
        time.sleep(10)

        # 5. タスク情報を取得し、statusがrunningの場合はキャンセル
        print(f"\n=== check task status and cancel if running ===")
        try:
            task_info = get_task_info(task_id)
            status = task_info.get('status')
            print(f"Current status: {status}")

            if status == 'running':
                print(f"Canceling task...")
                canceled_task = cancel_task(task_id)
                print(f"\n=== task canceled ===")
                print(json.dumps(canceled_task, ensure_ascii=False, indent=2))
            else:
                print(f"Task is not running (status={status}). No cancellation needed.")
        except Exception as e:
            print(f"[WARN] タスク情報取得またはキャンセルに失敗しました: {e}", file=sys.stderr)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1)
