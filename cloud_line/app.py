from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import uuid
from pathlib import Path

import requests
from flask import Flask, jsonify, request, send_file
from google.cloud import secretmanager


app = Flask(__name__)
LINE_PUSH_URL = "https://api.line.me/v2/bot/message/push"
LINE_REPLY_URL = "https://api.line.me/v2/bot/message/reply"
TARGET_SECRET_ID = "money-trade-line-target"
CARD_DIR = Path("/tmp/line-cards")
CARD_DIR.mkdir(parents=True, exist_ok=True)


def _secret_client() -> secretmanager.SecretManagerServiceClient:
    return secretmanager.SecretManagerServiceClient()


def _project_id() -> str:
    project_id = os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("GCP_PROJECT_ID")
    if not project_id:
        raise RuntimeError("Google Cloud project ID is unavailable")
    return project_id


def _load_targets() -> list[str]:
    name = f"projects/{_project_id()}/secrets/{TARGET_SECRET_ID}/versions/latest"
    value = _secret_client().access_secret_version(request={"name": name}).payload.data.decode("utf-8")
    return list(dict.fromkeys(target.strip() for target in value.split(",") if target.strip()))


def _add_target(user_id: str) -> bool:
    targets = _load_targets()
    if user_id in targets:
        return False
    targets.append(user_id)
    client = _secret_client()
    parent = f"projects/{_project_id()}/secrets/{TARGET_SECRET_ID}"
    new_version = client.add_secret_version(
        request={
            "parent": parent,
            "payload": {"data": ",".join(targets).encode("utf-8")},
        }
    )
    for version in client.list_secret_versions(request={"parent": parent}):
        if version.name != new_version.name and version.state.name in {"ENABLED", "DISABLED"}:
            client.destroy_secret_version(request={"name": version.name})
    return True


def _reply(reply_token: str, text: str) -> None:
    token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
    requests.post(
        LINE_REPLY_URL,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        json={
            "replyToken": reply_token,
            "messages": [{"type": "text", "text": text}],
        },
        timeout=30,
    ).raise_for_status()


@app.get("/")
def health():
    return jsonify({"ok": True, "service": "money-trade-line-push"})


@app.post("/notify")
def notify():
    expected_key = os.environ.get("LINE_CLOUD_PUSH_KEY", "")
    supplied_key = request.headers.get("X-Push-Key", "")
    if not expected_key or not hmac.compare_digest(supplied_key, expected_key):
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    body = request.get_json(silent=True) or {}
    message = str(body.get("message", "")).strip()
    if not message:
        return jsonify({"ok": False, "error": "message is required"}), 400
    if len(message) > 5000:
        return jsonify({"ok": False, "error": "message exceeds 5000 characters"}), 400

    token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
    targets = _load_targets()
    if not token or not targets:
        return jsonify({"ok": False, "error": "LINE secrets are not configured"}), 500

    for target in dict.fromkeys(targets):
        response = requests.post(
            LINE_PUSH_URL,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json={"to": target, "messages": [{"type": "text", "text": message}]},
            timeout=30,
        )
        if not response.ok:
            app.logger.error("LINE API %s: %s", response.status_code, response.text)
            return jsonify({"ok": False, "error": "LINE API rejected the request"}), 502

    return jsonify({"ok": True, "recipients": len(set(targets))})


@app.get("/cards/<card_id>.png")
def card(card_id: str):
    if not card_id.replace("-", "").isalnum():
        return jsonify({"ok": False, "error": "invalid card"}), 404
    path = CARD_DIR / f"{card_id}.png"
    if not path.exists():
        return jsonify({"ok": False, "error": "card not found"}), 404
    response = send_file(path, mimetype="image/png", max_age=86400)
    response.headers["Cache-Control"] = "public, max-age=86400"
    return response


@app.post("/notify-image")
def notify_image():
    expected_key = os.environ.get("LINE_CLOUD_PUSH_KEY", "")
    supplied_key = request.headers.get("X-Push-Key", "")
    if not expected_key or not hmac.compare_digest(supplied_key, expected_key):
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    image = request.files.get("image")
    if not image:
        return jsonify({"ok": False, "error": "image is required"}), 400
    image_bytes = image.read()
    if not image_bytes or len(image_bytes) > 10 * 1024 * 1024:
        return jsonify({"ok": False, "error": "invalid image size"}), 400

    card_id = uuid.uuid4().hex
    
    bucket_name = os.environ.get("LINE_CARD_BUCKET", "").strip()
    if not bucket_name:
        return jsonify({"ok": False, "error": "LINE_CARD_BUCKET is not configured"}), 500

    # Upload to GCS bucket instead of ephemeral /tmp to guarantee availability
    from google.cloud import storage
    storage_client = storage.Client()
    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(f"{card_id}.png")
    blob.upload_from_string(image_bytes, content_type="image/png")
    
    image_url = f"https://storage.googleapis.com/{bucket_name}/{card_id}.png"

    token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
    targets = _load_targets()
    for target in targets:
        response = requests.post(
            LINE_PUSH_URL,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json={
                "to": target,
                "messages": [
                    {
                        "type": "image",
                        "originalContentUrl": image_url,
                        "previewImageUrl": image_url,
                    }
                ],
            },
            timeout=30,
        )
        if not response.ok:
            app.logger.error("LINE API %s: %s", response.status_code, response.text)
            return jsonify({"ok": False, "error": "LINE API rejected the image"}), 502

    return jsonify({"ok": True, "recipients": len(targets), "imageUrl": image_url})


@app.post("/callback")
def callback():
    channel_secret = os.environ.get("LINE_CHANNEL_SECRET", "")
    signature = request.headers.get("X-Line-Signature", "")
    raw_body = request.get_data()
    expected = base64.b64encode(
        hmac.new(channel_secret.encode("utf-8"), raw_body, hashlib.sha256).digest()
    ).decode("ascii")
    if not channel_secret or not hmac.compare_digest(signature, expected):
        return jsonify({"ok": False, "error": "invalid signature"}), 401

    payload = json.loads(raw_body or b"{}")
    enrolled = 0
    for event in payload.get("events", []):
        if event.get("type") != "message":
            continue
        message = event.get("message", {})
        source = event.get("source", {})
        text = str(message.get("text", "")).strip()
        user_id = str(source.get("userId", "")).strip()
        if message.get("type") != "text" or text != "加入選股通知":
            continue
        if not (user_id.startswith("U") and len(user_id) == 33):
            continue
        added = _add_target(user_id)
        _reply(
            str(event.get("replyToken", "")),
            "已加入每日選股通知。" if added else "你已經在每日選股通知名單中。",
        )
        enrolled += int(added)

    return jsonify({"ok": True, "enrolled": enrolled})
