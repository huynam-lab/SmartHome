import subprocess

QUERY = "Sự Thật Đã Bỏ Quên"

yt = subprocess.Popen(
    [
        "python3.10", "-m", "yt_dlp",
        "--js-runtimes", "deno",
        "--extractor-args", "youtube:player_client=web_embedded",
        "-f", "bestaudio/best",
        "-o", "-",
        f"ytsearch1:{QUERY}",
    ],
    stdout=subprocess.PIPE,
)

mpv = subprocess.Popen(
    [
        "mpv",
        "--no-video",
        "--cache=yes",
        "--cache-secs=5",
        "--volume=50",
        "-"
    ],
    stdin=yt.stdout,
)

if yt.stdout:
    yt.stdout.close()

mpv.wait()

if yt.poll() is None:
    yt.terminate()