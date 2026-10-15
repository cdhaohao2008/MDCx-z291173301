"""演员头像/信息数据源的展示文案目录（不依赖 Qt）。

原先散在 UI 模块里：模块级的两张「快速设置面板」表，和
``_actor_source_test_execute`` 里的两张「进度提示」表 + 两张「结果框」表。
四张表的 key 集合一致但文案不同（面板标签 / 实时状态 / 结果框），
集中放在一处是为了让「同名不同义」显式可见，而不是让它们漂在两个函数里。
"""

from __future__ import annotations

from typing import Final

# 快速设置面板与设置窗口里显示的标签
IMAGE_SOURCE_NAMES: Final[dict[str, str]] = {
    "gfriends": "Gfriends网络头像",
    "graphis": "Graphis头像/背景",
    "minnano": "Minnano-av.com",
    "local": "本地头像保存目录",
}
INFO_SOURCE_NAMES: Final[dict[str, str]] = {
    "local": "本地演员名数据表",
    "wiki": "维基百科中文网站",
    "minnano": "Minnano-av.com",
    "database": "本地已保存数据库",
}

# 顶部实时状态提示文案（与右侧快速设置面板文案保持一致，不写入底部结果框）
IMAGE_PROGRESS: Final[dict[str, str]] = {
    "local": "正在从本地头像保存目录获取头像",
    "minnano": "正在从Minnano-av.com获取头像",
    "gfriends": "正在从Gfriends仓库获取网络头像",
    "graphis": "正在从Graphis网站获取头像/背景",
}
INFO_PROGRESS: Final[dict[str, str]] = {
    "minnano": "正在从Minnano-av.com获取信息",
    "local": "正在从本地演员名数据表获取信息",
    "wiki": "正在从维基百科中文网站获取信息",
    "database": "正在从本地已保存数据库获取信息",
}

# 底部结果框展示名（用户指定文案）
IMAGE_RESULT_NAMES: Final[dict[str, str]] = {
    "local": "本地头像目录缓存",
    "minnano": "Minnano-av.com",
    "gfriends": "Gfriends网络头像",
    "graphis": "Graphis网站头像",
}
INFO_RESULT_NAMES: Final[dict[str, str]] = {
    "minnano": "Minnano-av.com",
    "local": "本地演员名数据表",
    "wiki": "维基百科中文网站",
    "database": "本地已保存数据库",
}
