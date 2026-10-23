import os, shutil, tempfile, time, glob, hmac, urllib.request
from urllib.parse import urlparse
from flask import Flask, request, session, jsonify, send_file, send_from_directory
import yt_dlp

app = Flask(__name__, static_folder="static", static_url_path="/static")
app.secret_key = os.environ.get("SECRET_KEY", "change-this-long-random-string")
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
                  PERMANENT_SESSION_LIFETIME=60 * 60 * 24 * 30)
PASSWORD = os.environ.get("APP_PASSWORD", "169023")
ALLOWED = ("youtube.com", "youtu.be", "tiktok.com")
attempts = {}


def allowed(url):
    host = (urlparse(url).hostname or "").lower()
    return any(host == d or host.endswith("." + d) for d in ALLOWED)


def authed():
    return session.get("ok") is True


@app.route("/")
def index():
    return send_from_directory("static", "index.html")


@app.post("/api/login")
def login():
    ip = request.headers.get("X-Forwarded-For", request.remote_addr)
    count, first = attempts.get(ip, (0, time.time()))
    if time.time() - first > 600:
        count, first = 0, time.time()
    if count >= 8:
        return jsonify(error="Too many tries. Please wait a few minutes."), 429
    given = (request.get_json(silent=True) or {}).get("password", "")
    if hmac.compare_digest(str(given), PASSWORD):
        session.permanent = True
        session["ok"] = True
        attempts.pop(ip, None)
        return jsonify(ok=True)
    attempts[ip] = (count + 1, first)
    return jsonify(error="wrong"), 401


@app.get("/api/me")
def me():
    return jsonify(ok=authed())


@app.post("/api/info")
def info():
    if not authed():
        return jsonify(error="locked"), 401
    url = (request.get_json(silent=True) or {}).get("url", "").strip()
    if not allowed(url):
        return jsonify(error="Please paste a YouTube or TikTok link."), 400
    try:
        with yt_dlp.YoutubeDL({"quiet": True, "noplaylist": True}) as y:
            d = y.extract_info(url, download=False)
    except Exception:
        return jsonify(error="Couldn't read that link. Check it and try again."), 400
    return jsonify(title=d.get("title", "Untitled"), thumbnail=d.get("thumbnail"),
                   uploader=d.get("uploader"), duration=d.get("duration"))


@app.get("/api/download")
def download():
    if not authed():
        return jsonify(error="locked"), 401
    url = request.args.get("url", "").strip()
    kind = request.args.get("kind", "video")
    if not allowed(url):
        return jsonify(error="Unsupported link."), 400
    tmp = tempfile.mkdtemp(prefix="dl_")
    try:
        if kind == "photo":
            with yt_dlp.YoutubeDL({"quiet": True, "noplaylist": True}) as y:
                d = y.extract_info(url, download=False)
            thumb = d.get("thumbnail")
            if not thumb:
                raise RuntimeError("no photo")
            ext = os.path.splitext(urlparse(thumb).path)[1] or ".jpg"
            path = os.path.join(tmp, "cover" + ext)
            urllib.request.urlretrieve(thumb, path)
        else:
            fmt = "bestaudio[ext=m4a]/bestaudio" if kind == "audio" else "b[ext=mp4]/b"
            opts = {"outtmpl": os.path.join(tmp, "%(title).80s.%(ext)s"), "format": fmt,
                    "quiet": True, "noplaylist": True}
            with yt_dlp.YoutubeDL(opts) as y:
                y.extract_info(url, download=True)
            files = glob.glob(os.path.join(tmp, "*"))
            if not files:
                raise RuntimeError("empty")
            path = files[0]
        resp = send_file(path, as_attachment=True, download_name=os.path.basename(path))
        resp.call_on_close(lambda: shutil.rmtree(tmp, ignore_errors=True))
        return resp
    except Exception:
        shutil.rmtree(tmp, ignore_errors=True)
        return jsonify(error="That download didn't work. Try again in a moment."), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
