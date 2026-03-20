import os
import shutil
import subprocess
import requests as http_requests

from flask import Flask, request, jsonify, Response, stream_with_context, send_file
from flask_cors import CORS
import yt_dlp
import tempfile
import glob

print(f"[INFO] deno: {shutil.which('deno')}")
print(f"[INFO] ffmpeg: {shutil.which('ffmpeg')}")

app = Flask(__name__)
CORS(app, expose_headers=["Content-Disposition", "Content-Length", "X-Filename"])

# Caminho do arquivo de cookies
COOKIES_PATH = os.path.join(os.path.dirname(__file__), "cookies.txt")

# Instancias Invidious (fallback quando YouTube bloqueia)
INVIDIOUS_INSTANCES = [
    "https://inv.nadeko.net",
    "https://invidious.fdn.fr",
    "https://yewtu.be",
    "https://vid.puffyan.us",
    "https://invidious.nerdvpn.de",
    "https://inv.tux.pizza",
]

# Opcoes base do yt-dlp
BASE_OPTS = {
    "quiet": True,
    "no_warnings": True,
    "geo_bypass": True,
    "nocheckcertificate": True,
    "http_headers": {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    },
}

_ffmpeg = shutil.which("ffmpeg")
if _ffmpeg:
    BASE_OPTS["ffmpeg_location"] = os.path.dirname(_ffmpeg)
elif os.path.isdir(r"C:\ffmpeg"):
    BASE_OPTS["ffmpeg_location"] = r"C:\ffmpeg"


def get_ydl_opts(extra_opts):
    opts = {**BASE_OPTS, **extra_opts}
    if os.path.isfile(COOKIES_PATH):
        opts["cookiefile"] = COOKIES_PATH
    return opts


def is_bot_blocked(error_msg):
    """Verifica se o erro eh de bloqueio por bot do YouTube."""
    keywords = ["Sign in", "bot", "confirm you", "cookies", "authentication"]
    return any(k.lower() in error_msg.lower() for k in keywords)


# ========== INVIDIOUS FALLBACK ==========
def invidious_get_info(video_id):
    """Busca info do video via Invidious API."""
    for inst in INVIDIOUS_INSTANCES:
        try:
            r = http_requests.get(
                f"{inst}/api/v1/videos/{video_id}?local=true",
                timeout=15,
            )
            if r.status_code == 200:
                return r.json(), inst
        except Exception:
            continue
    return None, None


def invidious_download(video_id, fmt, quality, tmpdir):
    """Baixa video/audio via Invidious e retorna (filepath, title, ext)."""
    data, inst = invidious_get_info(video_id)
    if not data:
        raise Exception("Nenhuma instancia Invidious disponivel.")

    title = data.get("title", "video")
    ffmpeg_path = shutil.which("ffmpeg") or "ffmpeg"

    if fmt == "mp3":
        # Pega melhor audio
        audio_streams = [f for f in data.get("adaptiveFormats", []) if f.get("type", "").startswith("audio/")]
        if not audio_streams:
            raise Exception("Nenhum stream de audio encontrado.")
        audio_streams.sort(key=lambda f: f.get("bitrate", 0), reverse=True)
        audio_url = audio_streams[0]["url"]

        # Baixa e converte para MP3
        audio_path = os.path.join(tmpdir, "audio_raw")
        output_path = os.path.join(tmpdir, "output.mp3")

        r = http_requests.get(audio_url, stream=True, timeout=300)
        with open(audio_path, "wb") as f:
            for chunk in r.iter_content(65536):
                f.write(chunk)

        subprocess.run([
            ffmpeg_path, "-y", "-i", audio_path,
            "-codec:a", "libmp3lame", "-b:a", f"{quality}k",
            output_path
        ], capture_output=True, timeout=300)

        if not os.path.exists(output_path):
            raise Exception("Falha na conversao para MP3.")

        return output_path, title, "mp3"

    else:
        # Pega melhor formato progressivo (video+audio junto)
        target = int(quality)
        progressive = data.get("formatStreams", [])
        if not progressive:
            raise Exception("Nenhum formato de video disponivel.")

        # Ordena por qualidade, pega o mais proximo do target
        progressive.sort(key=lambda f: abs(int(f.get("size", "0x360").split("x")[1]) - target))
        stream = progressive[0]
        video_url = stream["url"]
        actual_quality = stream.get("qualityLabel", "")

        # Baixa o video
        raw_path = os.path.join(tmpdir, "video_raw")
        output_path = os.path.join(tmpdir, "output.mp4")

        r = http_requests.get(video_url, stream=True, timeout=600)
        with open(raw_path, "wb") as f:
            for chunk in r.iter_content(65536):
                f.write(chunk)

        # Re-encode audio para AAC (compatibilidade)
        subprocess.run([
            ffmpeg_path, "-y", "-i", raw_path,
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            output_path
        ], capture_output=True, timeout=600)

        if not os.path.exists(output_path):
            # Se ffmpeg falhar, usa o raw
            shutil.copy(raw_path, output_path)

        return output_path, title, "mp4"


# ========== YT-DLP PRINCIPAL ==========
def extract_with_fallback(url, ydl_opts):
    should_download = "outtmpl" in ydl_opts

    client_attempts = [None, ["android"], ["web"], ["ios"], ["mweb"], ["tv"]]

    last_error = None
    for client in client_attempts:
        try:
            opts = {**ydl_opts}
            if client:
                opts["extractor_args"] = {"youtube": {"player_client": client}}
            with yt_dlp.YoutubeDL(opts) as ydl:
                return ydl.extract_info(url, download=should_download)
        except yt_dlp.utils.DownloadError as e:
            last_error = e
            continue
        except Exception as e:
            last_error = e
            continue

    raise last_error or yt_dlp.utils.DownloadError("Todas as tentativas falharam")


# ========== ROTAS ==========
@app.route("/")
def index():
    index_path = os.path.join(os.path.dirname(__file__), "index.html")
    if os.path.exists(index_path):
        return send_file(index_path)
    return jsonify({"status": "ok"})


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


@app.route("/api/cookies", methods=["GET"])
def cookies_status():
    exists = os.path.isfile(COOKIES_PATH)
    size = os.path.getsize(COOKIES_PATH) if exists else 0
    return jsonify({"active": exists and size > 100, "size": size})


@app.route("/api/cookies", methods=["POST"])
def cookies_upload():
    if "file" not in request.files:
        text = request.get_data(as_text=True)
        if text and "# Netscape HTTP Cookie File" in text:
            with open(COOKIES_PATH, "w", encoding="utf-8") as f:
                f.write(text)
            return jsonify({"ok": True, "message": "Cookies salvos!"})
        return jsonify({"error": "Envie um arquivo cookies.txt"}), 400

    file = request.files["file"]
    content = file.read().decode("utf-8", errors="ignore")
    if "# Netscape HTTP Cookie File" not in content and "# HTTP Cookie File" not in content:
        return jsonify({"error": "Arquivo invalido. Use a extensao 'Get cookies.txt LOCALLY' para exportar."}), 400

    with open(COOKIES_PATH, "w", encoding="utf-8") as f:
        f.write(content)
    return jsonify({"ok": True, "message": "Cookies salvos!"})


@app.route("/api/cookies", methods=["DELETE"])
def cookies_delete():
    if os.path.isfile(COOKIES_PATH):
        os.remove(COOKIES_PATH)
    return jsonify({"ok": True})


@app.route("/api/info")
def info():
    url = request.args.get("url")
    if not url:
        return jsonify({"error": "url is required"}), 400

    try:
        ydl_opts = get_ydl_opts({"skip_download": True})
        data = extract_with_fallback(url, ydl_opts)

        qualities = set()
        for f in data.get("formats", []):
            h = f.get("height")
            if h and f.get("vcodec") != "none":
                qualities.add(h)

        return jsonify({
            "title": data.get("title"),
            "channel": data.get("channel") or data.get("uploader"),
            "thumbnail": data.get("thumbnail"),
            "duration": data.get("duration"),
            "qualities": sorted(qualities),
        })
    except Exception as e:
        msg = str(e)
        # Se yt-dlp falhar, tenta Invidious para info
        try:
            from urllib.parse import parse_qs, urlparse
            parsed = urlparse(url)
            video_id = parse_qs(parsed.query).get("v", [None])[0]
            if video_id:
                inv_data, _ = invidious_get_info(video_id)
                if inv_data:
                    qs = set()
                    for f in inv_data.get("formatStreams", []):
                        h = int(f.get("size", "0x360").split("x")[1])
                        if h: qs.add(h)
                    return jsonify({
                        "title": inv_data.get("title"),
                        "channel": inv_data.get("author"),
                        "thumbnail": inv_data.get("videoThumbnails", [{}])[0].get("url", ""),
                        "duration": inv_data.get("lengthSeconds"),
                        "qualities": sorted(qs),
                        "source": "invidious",
                    })
        except Exception:
            pass

        if "not available" in msg:
            return jsonify({"error": "Video indisponivel."}), 400
        return jsonify({"error": msg}), 500


@app.route("/api/download")
def download():
    url = request.args.get("url")
    fmt = request.args.get("format", "mp4")
    quality = request.args.get("quality", "720")

    if not url:
        return jsonify({"error": "url is required"}), 400

    # Extrai video_id
    from urllib.parse import parse_qs, urlparse
    parsed = urlparse(url)
    video_id = parse_qs(parsed.query).get("v", [None])[0]

    tmpdir = tempfile.mkdtemp()
    use_invidious = False

    try:
        output_template = os.path.join(tmpdir, "output.%(ext)s")

        # Tenta yt-dlp primeiro
        try:
            if fmt == "mp3":
                ydl_opts = get_ydl_opts({
                    "format": "bestaudio/best",
                    "outtmpl": output_template,
                    "postprocessors": [{
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": "mp3",
                        "preferredquality": quality if quality in ("64", "128", "192", "256", "320") else "192",
                    }],
                })
            else:
                ydl_opts = get_ydl_opts({
                    "format": f"bestvideo[height<={quality}]+bestaudio/best[height<={quality}]/best",
                    "merge_output_format": "mp4",
                    "outtmpl": output_template,
                    "postprocessors": [{
                        "key": "FFmpegVideoConvertor",
                        "preferedformat": "mp4",
                    }, {
                        "key": "FFmpegMetadata",
                    }],
                    "postprocessor_args": {
                        "merger": ["-c:a", "aac", "-b:a", "192k"],
                    },
                })

            data = extract_with_fallback(url, ydl_opts)
            title = data.get("title", "video")

        except Exception as e:
            msg = str(e)
            if is_bot_blocked(msg) and video_id:
                print(f"[INFO] yt-dlp bloqueado, usando Invidious para {video_id}")
                use_invidious = True
            else:
                raise

        if use_invidious:
            filepath, title, ext = invidious_download(video_id, fmt, quality, tmpdir)
        else:
            ext = "mp3" if fmt == "mp3" else "mp4"
            files = glob.glob(os.path.join(tmpdir, "*"))
            if not files:
                raise Exception("Download falhou - nenhum arquivo gerado")
            filepath = files[0]

        content_type = "audio/mpeg" if ext == "mp3" else "video/mp4"
        file_size = os.path.getsize(filepath)
        safe_title = "".join(c for c in title if c.isalnum() or c in " -_(),.").strip()
        filename = f"{safe_title}.{ext}"
        filename_utf8 = filename.encode("utf-8", errors="ignore").decode("utf-8")

        def generate():
            try:
                with open(filepath, "rb") as f:
                    while True:
                        chunk = f.read(65536)
                        if not chunk:
                            break
                        yield chunk
            finally:
                shutil.rmtree(tmpdir, ignore_errors=True)

        return Response(
            stream_with_context(generate()),
            content_type=content_type,
            headers={
                "Content-Disposition": f"attachment; filename=\"{filename_utf8}\"; filename*=UTF-8''{filename_utf8}",
                "X-Filename": filename_utf8,
                "Content-Length": str(file_size),
            },
        )
    except Exception as e:
        shutil.rmtree(tmpdir, ignore_errors=True)
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(debug=True, port=5000)
