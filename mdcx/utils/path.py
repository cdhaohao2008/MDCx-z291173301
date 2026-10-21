import os
import shutil
from pathlib import Path


def safe_rmtree(path: str | Path) -> None:
    """删除目录, 但拒绝灾难性目标, 防止路径计算错误误删用户文件。

    拒绝以下情况:
      - 空路径
      - 解析后为文件系统根/盘符根(如 C:\\ 或 /), 即 p.parent == p
      - 恰好等于用户主目录本身(如 C:\\Users\\name)

    注意: 只拦截"主目录本身", 不拦截主目录下的子目录 —— Windows 上媒体库
    常位于主目录之下(如 C:\\Users\\name\\Videos), 拦截整棵子树会误伤正常删除。
    真正灾难性的路径计算错误(退化到盘符根/主目录顶层)已被上述两项覆盖。
    """
    if not path:
        raise ValueError("safe_rmtree: 空路径, 拒绝删除")
    try:
        p = Path(path).resolve()
    except (OSError, ValueError) as exc:
        raise ValueError(f"safe_rmtree: 无法解析路径 {path!r}: {exc}") from exc
    # 拒绝文件系统根/盘符根(无父目录)
    if p.parent == p:
        raise PermissionError(f"safe_rmtree: 拒绝删除文件系统根 {p}")
    # 拒绝用户主目录本身(不含其子目录)
    # 注意: PermissionError 是 OSError 子类, raise 必须放在 try 外,
    # 否则会被 Path.home() 的 except(OSError) 自己吞掉, 导致守护失效。
    try:
        home = Path.home().resolve()
    except OSError, RuntimeError:
        # Path.home() 解析失败时不阻断正常删除
        home = None
    if home is not None and p == home:
        raise PermissionError(f"safe_rmtree: 拒绝删除用户主目录 {p}")
    shutil.rmtree(p)


def showFilePath(file_path: str) -> str:
    if len(file_path) > 55:
        show_file_path = file_path[-50:]
        # 兼容 Windows(\\) 与 POSIX(/) 路径分隔符; 用首个分隔符截断, 避免 Windows 路径下 find('/') 返回 -1 导致显示错位
        sep = "\\" if "\\" in show_file_path else "/"
        idx = show_file_path.find(sep)
        if idx == -1:
            show_file_path = ".." + show_file_path
        else:
            show_file_path = ".." + show_file_path[idx:]
        if len(show_file_path) < 25:
            show_file_path = ".." + file_path[-40:]
    else:
        show_file_path = file_path
    return show_file_path


def _normcase(path: str | Path) -> str:
    """词法规范化: 转绝对路径 + 统一大小写与分隔符(Windows)。"""
    try:
        return os.path.normcase(os.path.abspath(path))
    except OSError, ValueError:
        return os.path.normcase(str(path))


def _realpath(path: str | Path) -> str | None:
    """解析符号链接后的规范化路径; 解析失败时返回 None。

    注意: 这里必须使用 realpath 的默认 strict=False 语义, 不能传
    strict=os.path.ALLOW_MISSING —— 网络盘/云盘挂载盘(CloudDrive2 等)上
    realpath 会抛出 OSError(WinError 1005 "此卷不包含可识别的文件系统"),
    旧实现在那里直接返回 False, 导致挂在网盘上的媒体库永远认不出
    "文件已在成功输出目录内", 整理模式也就无法自动切换到读取模式
    (左下角文案一直停留在"整理模式")。
    """
    try:
        return os.path.normcase(os.path.realpath(path))
    except OSError, ValueError:
        return None


def _is_within(child: str, parent: str) -> bool:
    """child 是否位于 parent 之内(含 parent 自身)。

    用 os.path.commonpath 而不是简单前缀判断: parent = /foo/bar 时,
    /foo/barbar 不应被算作后代。
    """
    try:
        return os.path.commonpath([child, parent]) == parent
    except OSError, ValueError:
        # 跨盘符(如 C:\\ 与 K:\\)时 commonpath 会抛 ValueError → 不属于同一棵树
        return False


def is_descendant(p: str | Path, parent: str | Path) -> bool:
    """
    检查 p 是否是 parent 或者 parent 的后代.

    先按 realpath(可识别符号链接)比较, 再按词法绝对路径比较; 任意一种
    成立即视为后代。网盘/云盘挂载盘上 realpath 解析不出来时, 词法比较
    仍然有效, 不会把"文件已在成功输出目录内"误判成"不在目录内"。
    """
    child_real = _realpath(p)
    parent_real = _realpath(parent)
    if child_real is not None and parent_real is not None and _is_within(child_real, parent_real):
        return True
    return _is_within(_normcase(p), _normcase(parent))


def is_any_descendant(p: str | Path, *parents: str | Path) -> bool:
    """
    检查 p 是否是 parents 中某路径的后代.
    """
    return any(is_descendant(p, parent) for parent in parents)
