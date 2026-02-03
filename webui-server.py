import os
import subprocess
from flask import Flask, jsonify, request

app = Flask(__name__)

@app.route('/')
def index():
    """メインページ"""
    return 'WebUI Server is running'

@app.route('/health')
def health():
    """ヘルスチェック"""
    return {'status': 'ok'}

@app.post('/restart_server')
def restart_server():
    """
    サーバーを再起動する
    JSONパラメータ: OPENAI_API_BASE_URL (文字列)
    """
    payload = request.get_json(silent=True)
    if payload is None:
        return jsonify({"error": "Invalid or missing JSON payload"}), 400
    
    openai_api_base_url = payload.get("OPENAI_API_BASE_URL")
    if openai_api_base_url is None:
        return jsonify({"error": "Missing required parameter: OPENAI_API_BASE_URL"}), 400
    
    if not isinstance(openai_api_base_url, str):
        return jsonify({"error": "OPENAI_API_BASE_URL must be a string"}), 400
    
    try:
        # 既存のコンテナを削除（存在する場合）
        subprocess.run(
            ['docker', 'rm', '-f', 'open-webui'],
            capture_output=True,
            timeout=30
        )
        
        # 新しいコンテナを起動
        docker_cmd = [
            'docker', 'run', '-d', '--name', 'open-webui',
            '-p', '3000:8080',
            '-v', 'open-webui:/app/backend/data',
            '-e', f'OPENAI_API_BASE_URL={openai_api_base_url}',
            '--restart', 'always',
            'ghcr.io/open-webui/open-webui:main'
        ]
        result = subprocess.run(
            docker_cmd,
            capture_output=True,
            text=True,
            timeout=60
        )
        
        if result.returncode != 0:
            return jsonify({"error": f"Docker run failed: {result.stderr}"}), 500
        
        # ログを取得
        logs_result = subprocess.run(
            ['docker', 'logs', 'open-webui'],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        return jsonify({
            "status": "ok",
            "message": "Container started successfully",
            "OPENAI_API_BASE_URL": openai_api_base_url,
            "container_id": result.stdout.strip(),
            "logs": logs_result.stdout
        }), 200
        
    except subprocess.TimeoutExpired:
        return jsonify({"error": "Docker command timeout"}), 500
    except Exception as e:
        return jsonify({"error": f"Failed to start container: {str(e)}"}), 500

@app.post('/stop_server')
def stop_server():
    """
    サーバー（open-webui コンテナ）を停止・削除する
    引数なし。docker stop と docker rm を実行する。
    """
    try:
        # コンテナ停止（存在しない場合はエラーになるが無視する）
        stop_res = subprocess.run(
            ['docker', 'stop', 'open-webui'],
            capture_output=True,
            text=True,
            timeout=30
        )

        # コンテナ削除（存在しない場合も rm -f 相当で強制削除）
        rm_res = subprocess.run(
            ['docker', 'rm', '-f', 'open-webui'],
            capture_output=True,
            text=True,
            timeout=30
        )

        response = {
            "status": "ok",
            "stopped": stop_res.stdout.strip(),
            "stopped_err": stop_res.stderr.strip(),
            "removed": rm_res.stdout.strip(),
            "removed_err": rm_res.stderr.strip(),
        }

        # docker コマンドの戻り値で失敗を判定
        if stop_res.returncode != 0 and 'No such container' in stop_res.stderr:
            # コンテナが存在しなかった場合は警告扱いで OK
            pass
        if rm_res.returncode != 0 and 'No such container' in rm_res.stderr:
            pass
        if rm_res.returncode != 0 and stop_res.returncode != 0 and 'No such container' not in (stop_res.stderr + rm_res.stderr):
            return jsonify({"error": f"Failed to stop/remove container: {rm_res.stderr or stop_res.stderr}"}), 500

        return jsonify(response), 200

    except subprocess.TimeoutExpired:
        return jsonify({"error": "Docker command timeout"}), 500
    except Exception as e:
        return jsonify({"error": f"Failed to stop/remove container: {str(e)}"}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=7000, debug=True)