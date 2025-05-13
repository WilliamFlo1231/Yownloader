from flask import Flask, request, send_file, jsonify, after_this_request
from flask_cors import CORS
import os
import yt_dlp
import uuid
from datetime import datetime

app = Flask(__name__)
CORS(app)

DOWNLOAD_FOLDER = "downloads"
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)

@app.route("/download", methods=["POST"])
def download_video():
    data = request.get_json()
    url = data.get("url")
    format_id = data.get("format_id")

    if not url or not format_id:
        return jsonify({"error": "Missing URL or format_id"}), 400

    video_id = str(uuid.uuid4())
    output_path = os.path.join(DOWNLOAD_FOLDER, f"{video_id}.mp4")

    try:
        with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
            info = ydl.extract_info(url, download=False)
            selected_format = next((f for f in info['formats'] if f['format_id'] == format_id), None)

            if not selected_format:
                return jsonify({"error": "Invalid format_id"}), 400

            has_audio = selected_format.get("acodec") != "none"
            has_video = selected_format.get("vcodec") != "none"

            if has_video and not has_audio:
                best_audio = next(
                    (f for f in reversed(info['formats'])
                     if f['acodec'] != 'none' and f['vcodec'] == 'none' and f['ext'] in ['m4a', 'mp4']),
                    None
                )
                if not best_audio:
                    return jsonify({"error": "No suitable audio format found"}), 500

                combined_format = f"{format_id}+{best_audio['format_id']}"
            else:
                combined_format = format_id

        ydl_opts = {
            'format': combined_format,
            'outtmpl': output_path,
            'merge_output_format': 'mp4',
            'quiet': True
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        @after_this_request
        def remove_file(response):
            try:
                import threading
                def delayed_delete(path):
                    import time
                    while True:
                        time.sleep(4)
                        try:
                            os.remove(path)
                            print(f"Deleted temp file: {path}")
                            break
                        except Exception as e:
                            print(f"Error deleting temp file: {e}")
                threading.Thread(target=delayed_delete, args=(output_path,)).start()
            except Exception as e:
                print(f"Error scheduling temp file deletion: {e}")
            return response

        return send_file(output_path, as_attachment=True)

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/formats", methods=["POST"]) 
def list_formats():
    data = request.get_json()
    url = data.get("url")
    ALLOWED_FORMATS = ['mp4', 'm4a']

    if not url:
        return jsonify({"error": "No URL provided"}), 400

    try:
        ydl_opts = {'quiet': True}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        formats_data = info.get("formats", [])
        best_by_height = {}

        best_audio = next(
            (f for f in reversed(formats_data)
             if f.get("vcodec") == "none" and f.get("acodec") != "none"
             and f.get("filesize") and f.get("ext") in ALLOWED_FORMATS),
            None
        )

        for fmt in formats_data:
            ext = fmt.get("ext")
            filesize = fmt.get("filesize")
            height = fmt.get("height")

            if ext not in ALLOWED_FORMATS or not filesize:
                continue

            has_audio = fmt.get("acodec") != "none"
            has_video = fmt.get("vcodec") != "none"
            resolution = fmt.get("format_note") or f"{height or 'audio'}p"

            key = height or "audio"
            existing = best_by_height.get(key)

            total_size = filesize
            if has_video and not has_audio and best_audio:
                total_size += best_audio["filesize"]

            if not existing or total_size > existing["total_size"]:
                best_by_height[key] = {
                    "format_id": fmt.get("format_id"),
                    "ext": ext,
                    "resolution": resolution,
                    "filesize_mb": round(total_size / 1024 / 1024, 2),
                    "fps": fmt.get("fps", ""),
                    "has_audio": has_audio or (has_video and best_audio is not None),
                    "has_video": has_video,
                    "height": height,
                    "total_size": total_size
                }

        formats = [
            {k: v for k, v in fmt.items() if k != "total_size"}
            for fmt in best_by_height.values()
        ]

        return jsonify({"formats": formats})

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/details", methods=["POST"])
def get_video_details():
    data = request.get_json()
    url = data.get('url')
    ydl_opts = {'quiet': True}
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        timestamp = info.get('timestamp')
        date_uploaded = datetime.fromtimestamp(timestamp)
        return jsonify(
            {
                'title': info.get('title'),
                'thumbnail': info.get('thumbnail'),
                'channel': info.get('channel'),
                'uploaded': date_uploaded.strftime("%d/%m/%Y")
            }
        )

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
