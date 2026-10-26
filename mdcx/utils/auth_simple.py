"""加密授权：用户发设备 ID → 开发者加密生成授权文件 → 启动时本机加密后与文件比对。

密钥由分散代码片段通过 PBKDF2 派生（比硬编码单一 AES 密钥更难提取）。
文件内容为设备指纹的 HMAC-SHA256（对用户不可读，复制到其他机器无法直接修改匹配）。
如果攻击者反编译提取所有密钥片段并重现派生过程，仍可伪造——但这已是 Python 生态下对称方案的强度上限。
"""

import base64
import hashlib
import hmac
from pathlib import Path

from mdcx.consts import MAIN_PATH
from mdcx.utils.machine_binding import processor_id

AUTH_FILE = MAIN_PATH / "userdata" / "auth.enc"

# 密钥材料分散在代码中，不是单一可提取字符串（增加反编译提取成本）
_KEY_FRAG_A = "MDCx"
_KEY_FRAG_B = "License"
_KEY_FRAG_C = "20261026"
_KEY_FRAG_D = "Premium"
_KEY_SALT = b"mdcx_auth_salt_v1"
_KEY_ITER = 200000  # PBKDF2 迭代次数，提高暴力破解成本


def _derive_key() -> bytes:
    """从分散代码片段派生加密密钥（每次启动重新计算，不缓存，避免内存转储直接拿到密钥）。"""
    raw = f"{_KEY_FRAG_A}:{_KEY_FRAG_B}:{_KEY_FRAG_C}:{_KEY_FRAG_D}".encode()
    return hashlib.pbkdf2_hmac("sha256", raw, _KEY_SALT, _KEY_ITER)


def encrypt_device_id(device_id: str) -> str:
    """对设备 ID 执行加密（HMAC-SHA256 派生密钥），返回 Base64 编码密文。"""
    key = _derive_key()
    digest = hmac.new(key, device_id.encode("utf-8"), hashlib.sha256).digest()
    return base64.b64encode(digest).decode("ascii")


def is_authorized() -> bool:
    """读取授权文件，计算本机加密值并比对。"""
    if not AUTH_FILE.exists():
        return False
    try:
        encrypted_file_value = AUTH_FILE.read_text(encoding="utf-8").strip()
        current_encrypted = encrypt_device_id(processor_id())
        return current_encrypted == encrypted_file_value
    except Exception:
        return False


def generate_license_file(device_id: str, output_path: Path | None = None) -> Path:
    """开发者手动调用：输入用户发来的设备 ID，生成加密授权文件。"""
    path = output_path or AUTH_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    encrypted = encrypt_device_id(device_id)
    path.write_text(encrypted, encoding="utf-8")
    return path


def get_device_request_path() -> Path:
    return MAIN_PATH / "userdata" / "device_request.txt"


def write_device_request() -> bool:
    try:
        path = get_device_request_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        # 用户发送的设备 ID 直接写入文件（开发者收到后直接用 generate_license_file 生成 auth.enc）
        path.write_text(processor_id(), encoding="utf-8")
        return True
    except Exception:
        return False
