import json
import os
import shutil
import subprocess
from pathlib import Path

_av = None
_av_import_attempted = False


def _load_av():
    global _av, _av_import_attempted
    if not _av_import_attempted:
        _av_import_attempted = True
        try:
            import av
        except ImportError:
            _av = None
        else:
            _av = av
    return _av


def get_video_metadata_pyav(p: Path) -> tuple[int, str]:
    av = _load_av()
    if av is None:
        raise ImportError("Should not be called if pyav is not available")
    height = 0
    codec_fourcc = ""
    with av.open(p) as container:
        # 查找第一个视频流
        video_stream = next((s for s in container.streams.video), None)
        if video_stream:
            height = video_stream.height
            codec_fourcc = video_stream.codec_context.name.upper()
    return height, codec_fourcc


def get_video_metadata_ffmpeg(p: Path) -> tuple[int, str]:
    if shutil.which("ffprobe") is None:
        raise RuntimeError("当前版本无 opencv/pyav. 若想获取视频分辨率请安装 ffprobe 或改用带 opencv/pyav 版本.")
    # Use ffprobe to get video information
    cmd = ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", str(p)]

    # macOS and Linux use default flags
    creationflags = 0
    # Windows use CREATE_NO_WINDOW to suppress the console window
    if os.name == "nt":
        creationflags = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, creationflags=creationflags, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return 0, ""
    if result.returncode != 0 or not result.stdout:
        return 0, ""
    try:
        data = json.loads(result.stdout)
    except (json.JSONDecodeError, ValueError):
        return 0, ""
    streams = data.get("streams")
    if not isinstance(streams, list):
        return 0, ""

    # Find video stream
    video_stream = next((stream for stream in streams if isinstance(stream, dict) and stream.get("codec_type") == "video"), None)

    if video_stream:
        try:
            height = int(video_stream.get("height", 0) or 0)
        except (ValueError, TypeError):
            height = 0
        codec_name = video_stream.get("codec_name") or ""
        codec_fourcc = str(codec_name).upper()
    else:
        height = 0
        codec_fourcc = ""
    return height, codec_fourcc


def get_video_metadata(p: Path) -> tuple[int, str]:
    try:
        return get_video_metadata_pyav(p)
    except ImportError:
        pass
    except Exception:
        return 0, ""
    try:
        return get_video_metadata_ffmpeg(p)
    except Exception:
        return 0, ""


def get_video_backend() -> str:
    return "pyav" if _load_av() is not None else "ffmpeg"
