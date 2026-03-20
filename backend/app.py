import os
import shutil

from flask import Flask, request, jsonify, Response, stream_with_context
from flask_cors import CORS
import yt_dlp
import tempfile
import glob

print(f"[INFO] deno: {shutil.which('deno')}")
print(f"[INFO] ffmpeg: {shutil.which('ffmpeg')}")

app = Flask(__name__)
CORS(app, expose_headers=["Content-Disposition", "Content-Length", "X-Filename"])

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

# Detecta ffmpeg automaticamente (Windows local ou Linux/Docker)
_ffmpeg = shutil.which("ffmpeg")
if _ffmpeg:
    BASE_OPTS["ffmpeg_location"] = os.path.dirname(_ffmpeg)
elif os.path.isdir(r"C:\ffmpeg"):
    BASE_OPTS["ffmpeg_location"] = r"C:\ffmpeg"


def get_ydl_opts(extra_opts):
    return {**BASE_OPTS, **extra_opts}


def extract_with_fallback(url, ydl_opts):
    should_download = "outtmpl" in ydl_opts

    client_attempts = [
        None,
        ["android"],
        ["web"],
        ["ios"],
        ["mweb"],
        ["tv"],
    ]

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


@app.route("/")
def health():
    return jsonify({"status": "ok"})


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
    except yt_dlp.utils.DownloadError as e:
        msg = str(e)
        if "not available" in msg:
            return jsonify({"error": "Video indisponivel. Pode ser restrito por regiao ou idade."}), 400
        if "Private video" in msg:
            return jsonify({"error": "Este video e privado."}), 400
        return jsonify({"error": msg}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/download")
def download():
    url = request.args.get("url")
    fmt = request.args.get("format", "mp4")
    quality = request.args.get("quality", "720")

    if not url:
        return jsonify({"error": "url is required"}), 400

    tmpdir = tempfile.mkdtemp()

    try:
        output_template = os.path.join(tmpdir, "output.%(ext)s")

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
            content_type = "audio/mpeg"
            ext = "mp3"
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
            content_type = "video/mp4"
            ext = "mp4"

        data = extract_with_fallback(url, ydl_opts)
        title = data.get("title", "video")

        files = glob.glob(os.path.join(tmpdir, "*"))
        if not files:
            shutil.rmtree(tmpdir, ignore_errors=True)
            return jsonify({"error": "Download falhou - nenhum arquivo gerado"}), 500

        filepath = files[0]
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
    except yt_dlp.utils.DownloadError as e:
        shutil.rmtree(tmpdir, ignore_errors=True)
        msg = str(e)
        if "not available" in msg:
            return jsonify({"error": "Video indisponivel. Pode ser restrito por regiao ou idade."}), 400
        if "ffmpeg" in msg.lower() or "ffprobe" in msg.lower():
            return jsonify({"error": "ffmpeg nao encontrado."}), 500
        return jsonify({"error": msg}), 500
    except Exception as e:
        shutil.rmtree(tmpdir, ignore_errors=True)
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(debug=True, port=5000)
