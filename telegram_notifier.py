import os
import threading
from pathlib import Path

import requests as _requests


def _env_dir():
    if (Path.cwd() / ".env").exists():
        return Path.cwd()
    return Path(__file__).parent


def _load_config():
    env_path = _env_dir() / ".env"
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    enabled = os.environ.get("TELEGRAM_ENABLED", "")
    return token, chat_id, enabled.lower() in ("1", "true", "yes", "si")


def is_configured():
    token, chat_id, enabled = _load_config()
    return bool(token and chat_id and enabled)


def _send(text, parse_mode="HTML"):
    token, chat_id, enabled = _load_config()
    if not (token and chat_id and enabled):
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": parse_mode}
    try:
        _requests.post(url, json=payload, timeout=10)
    except Exception:
        pass


def send_async(text, parse_mode="HTML"):
    t = threading.Thread(target=_send, args=(text, parse_mode), daemon=True)
    t.start()


def notify_download_ok(title, episode=None, size_mb=0, path=""):
    ep = f" ep {episode}" if episode else ""
    size = f"{size_mb:.1f} MB" if size_mb else ""
    msg = (
        f"✅ <b>Download complete</b>\n"
        f"<b>{title}</b>{ep}\n"
        f"📦 {size}\n"
        f"📁 <code>{path}</code>"
    )
    send_async(msg)


def notify_download_fail(title, episode=None, reason=""):
    ep = f" ep {episode}" if episode else ""
    msg = (
        f"❌ <b>Download failed</b>\n"
        f"<b>{title}</b>{ep}\n"
        f"⚠️ {reason}"
    )
    send_async(msg)


def notify_batch_start(title, total, ep_range=""):
    rng = f" (ep {ep_range})" if ep_range else ""
    msg = (
        f"🚀 <b>Batch download started</b>\n"
        f"<b>{title}</b>{rng}\n"
        f"📊 {total} files to download"
    )
    send_async(msg)


def notify_batch_complete(title, ok=0, failed=0, skipped=0, total_size=""):
    msg = (
        f"🏁 <b>Batch download finished</b>\n"
        f"<b>{title}</b>\n"
        f"✅ {ok} downloaded\n"
        f"⏭️ {skipped} skipped\n"
        f"❌ {failed} failed\n"
        f"💾 {total_size}"
    )
    send_async(msg)


def notify_convert_ok(filename):
    send_async(f"🔄 <b>Converted to MP4</b>\n<code>{filename}</code>")


def test_connection():
    token, chat_id, _ = _load_config()
    if not token or not chat_id:
        return False, "Token or Chat ID missing"
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": "🔮 <b>Magia</b> connected!\nYou'll receive download notifications here.",
        "parse_mode": "HTML",
    }
    try:
        r = _requests.post(url, json=payload, timeout=10)
        data = r.json()
        if data.get("ok"):
            return True, "Message sent"
        return False, data.get("description", "Unknown error")
    except Exception as e:
        return False, str(e)
