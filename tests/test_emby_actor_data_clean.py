"""议题 #149: 演员数据清洗——简介噪声(`<br>`/`=====` 段落标题/占位文案)与非法生日。

- clean_overview_text 纯函数: 四类噪声规则、幂等、正常文本(含英文逗号)不动
- EMbyActressInfo.dump() 出口统一套用清洗(增量写入不再产生噪声)
- update_person_info 对存量脏简介先清洗再写回(同一出口)
- scan_actor_data_noise 扫描口径(脏简介/脏标签/非法生日/Emby 零值不算噪声)
- 清洗替换规则同时作用于详情(Overview)与标签(Taglines), 两处共用同一清洗口径
- actress_db 不再写入 minnano 占位文案(断「占位→判缺→重抓→再写占位」死循环)
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import json

import pytest

from mdcx.models.emby import EMbyActressInfo, clean_overview_text

pytestmark = pytest.mark.asyncio


class TestCleanOverviewText:
    def test_br_variants_preserved(self):
        """议题 #171: <br> 属合法结构, 客户端渲染分行, 原样保留不压成逗号。"""
        assert clean_overview_text("中文名: 葵つばさ<br>罗马音: Aihara") == "中文名: 葵つばさ<br>罗马音: Aihara"
        for br in ("<br/>", "<br />", "<BR>", "<Br/>"):
            assert clean_overview_text(f"a{br}b") == f"a{br}b", br

    def test_section_headers_preserved(self):
        """===== 段落标题是合法分段结构, 原样保留（#171 实证 Jellyfin 靠其分行渲染）。"""
        text = "简介文本<br>===== 个人资料 =====<br>中文名: X<br>===== 外部链接 =====<br>TheMovieDb: https://x"
        assert clean_overview_text(text) == text

    def test_screenshot_external_links_shape(self):
        """议题 #149 截图1 实貌: 整段以外部链接段落标题开头, 链接内容保留。"""
        text = "<br>===== 外部链接 =====<br>TheMovieDb: https://www.themoviedb.org/person/42257 <br>"
        assert clean_overview_text(text) == text

    def test_placeholder_cleared(self):
        assert clean_overview_text("无维基百科信息, 从 minnano-av 数据库补全女优信息") == ""
        assert clean_overview_text("无维基百科信息，从 minnano-av 数据库补全女优信息") == ""

    def test_newlines_preserved(self):
        """议题 #171: 换行符保留, 不压成逗号（客户端渲染分行列表）。"""
        assert clean_overview_text("a\nb\r\nc") == "a\nb\r\nc"

    def test_placeholder_mixed_with_clean_content(self):
        """占位文案夹在合法内容之间: 删占位, 保留剩余结构与换行。"""
        assert (
            clean_overview_text("正常段\n无维基百科信息, 从 minnano-av 数据库补全女优信息\n外部段")
            == "正常段\n\n外部段"
        )

    def test_normal_text_untouched(self):
        """正常英文简介(含 ASCII 逗号)必须原样保留, 不被折叠成中文逗号。"""
        text = "English theatre and film director and producer, known for X."
        assert clean_overview_text(text) == text

    def test_idempotent(self):
        text = "简介<br>===== 个人资料 =====<br>中文名: X，已有逗号"
        once = clean_overview_text(text)
        assert clean_overview_text(once) == once

    def test_non_str_returns_empty(self):
        assert clean_overview_text(None) == ""
        assert clean_overview_text(123) == ""


def test_dump_cleans_overview():
    """dump() 出口统一清洗: 占位文案清除, 合法结构(<br>/换行/段标题)原样保留(#171)。"""
    info = EMbyActressInfo(name="x", server_id="s", id="i", overview="a<br>===== 外部链接 =====<br>b")
    assert info.dump()["Overview"] == "a<br>===== 外部链接 =====<br>b"


class _JsonResp:
    """伪造 httpx.Response 的轻量子集 (轻量直连 _emby_request 返回它)。"""

    def __init__(self, status_code: int = 200, json_data: dict | None = None):
        self.status_code = status_code
        self._json_data = json_data
        self.text = ""

    def json(self):
        return self._json_data


async def _capture_update_payload(monkeypatch: pytest.MonkeyPatch, actor) -> dict:
    from mdcx.config.manager import manager
    from mdcx.tools import emby_actor_manager

    captured: dict = {}

    async def handler(method, url, *, headers=None, data=None, token=None, **kwargs):
        captured["data"] = data
        return _JsonResp(204), ""

    monkeypatch.setattr(manager.config, "server_type", "emby")
    monkeypatch.setattr(manager.config, "emby_url", "http://127.0.0.1:8096")
    monkeypatch.setattr(manager.config, "api_key", "token")
    monkeypatch.setattr(emby_actor_manager, "_emby_request", handler)

    ok, msg = await emby_actor_manager.update_person_info(actor)
    assert ok is True, msg
    return json.loads(captured["data"])


async def test_update_person_info_cleans_legacy_overview(monkeypatch: pytest.MonkeyPatch):
    """议题 #149: 存量脏简介随同步自愈——清洗后经同一出口写回。"""
    from mdcx.tools.emby_actor_manager import ActorInfo

    actor = ActorInfo(
        name="测试",
        actor_id="id1",
        server_id="srv1",
        existing_overview="a<br>===== 个人资料 =====<br>b",
    )
    payload = await _capture_update_payload(monkeypatch, actor)
    assert payload["Overview"] == "a<br>===== 个人资料 =====<br>b"


async def test_update_person_info_placeholder_becomes_empty_and_omitted(monkeypatch: pytest.MonkeyPatch):
    """占位简介清洗后为空: 同步出口省略 Overview(显式清空由数据清洗按钮负责)。"""
    from mdcx.tools.emby_actor_manager import ActorInfo

    actor = ActorInfo(
        name="测试",
        actor_id="id1",
        server_id="srv1",
        existing_overview="无维基百科信息, 从 minnano-av 数据库补全女优信息",
    )
    payload = await _capture_update_payload(monkeypatch, actor)
    assert "Overview" not in payload


async def test_clean_actor_data_writes_empty_overview_and_resets_birth(monkeypatch: pytest.MonkeyPatch):
    """议题 #149: 清洗路径显式写空简介(清占位) + 非法生日重置为 Emby 零值。"""
    from mdcx.config.manager import manager
    from mdcx.tools import emby_actor_manager
    from mdcx.tools.emby_actor_manager import ActorInfo

    captured: dict = {}

    async def handler(method, url, *, headers=None, data=None, token=None, **kwargs):
        captured["data"] = data
        return _JsonResp(204), ""

    monkeypatch.setattr(manager.config, "server_type", "emby")
    monkeypatch.setattr(manager.config, "emby_url", "http://127.0.0.1:8096")
    monkeypatch.setattr(manager.config, "api_key", "token")
    monkeypatch.setattr(emby_actor_manager, "_emby_request", handler)

    actor = ActorInfo(
        name="测试",
        actor_id="id1",
        server_id="srv1",
        existing_overview="无维基百科信息, 从 minnano-av 数据库补全女优信息",
        existing_premiere_date="0000-00-00T00:00:00.0000000Z",
    )
    ok, msg = await emby_actor_manager.clean_actor_data(actor, "", fix_birth=True)
    assert ok is True, msg
    payload = json.loads(captured["data"])
    assert payload["Overview"] == ""
    assert payload["PremiereDate"] == "0001-01-01T00:00:00.0000000Z"
    # 议题 #148 防线: Genres/Tags/ProviderIds 恒为集合, 不得缺省
    assert payload["Genres"] == [] and payload["Tags"] == [] and payload["ProviderIds"] == {}


async def test_clean_actor_data_writes_cleaned_taglines(monkeypatch: pytest.MonkeyPatch):
    """清洗路径把规则清洗后的标签(Taglines)一并写回服务器。"""
    from mdcx.config.manager import manager
    from mdcx.tools import emby_actor_manager
    from mdcx.tools.emby_actor_manager import ActorInfo

    captured: dict = {}

    async def handler(method, url, *, headers=None, data=None, token=None, **kwargs):
        captured["data"] = data
        return _JsonResp(204), ""

    monkeypatch.setattr(manager.config, "server_type", "emby")
    monkeypatch.setattr(manager.config, "emby_url", "http://127.0.0.1:8096")
    monkeypatch.setattr(manager.config, "api_key", "token")
    monkeypatch.setattr(emby_actor_manager, "_emby_request", handler)

    actor = ActorInfo(
        name="测试",
        actor_id="id1",
        server_id="srv1",
        existing_overview="简介",
        existing_taglines=["日本女演员", "噪声标签"],
    )
    ok, msg = await emby_actor_manager.clean_actor_data(actor, "简介", False, ["日本女演员"])
    assert ok is True, msg
    payload = json.loads(captured["data"])
    assert payload["Taglines"] == ["日本女演员"]


async def test_clean_actor_data_omits_taglines_when_unchanged(monkeypatch: pytest.MonkeyPatch):
    """new_taglines 与服务器现值相同则不发 Taglines; None(旧调用)更不发。"""
    from mdcx.config.manager import manager
    from mdcx.tools import emby_actor_manager
    from mdcx.tools.emby_actor_manager import ActorInfo

    captured: dict = {}

    async def handler(method, url, *, headers=None, data=None, token=None, **kwargs):
        captured["data"] = data
        return _JsonResp(204), ""

    monkeypatch.setattr(manager.config, "server_type", "emby")
    monkeypatch.setattr(manager.config, "emby_url", "http://127.0.0.1:8096")
    monkeypatch.setattr(manager.config, "api_key", "token")
    monkeypatch.setattr(emby_actor_manager, "_emby_request", handler)

    actor = ActorInfo(
        name="测试", actor_id="id1", server_id="srv1", existing_overview="简介", existing_taglines=["日本女演员"]
    )
    ok, _ = await emby_actor_manager.clean_actor_data(actor, "简介", False, ["日本女演员"])
    assert ok is True
    assert "Taglines" not in json.loads(captured["data"]), "无变化不应写标签"

    ok, _ = await emby_actor_manager.clean_actor_data(actor, "简介", False)
    assert ok is True
    assert "Taglines" not in json.loads(captured["data"]), "旧调用(None)不碰标签"


async def test_clean_actor_data_clears_all_taglines_when_rules_empty_them(monkeypatch: pytest.MonkeyPatch):
    """规则把标签全删空时写空列表=服务器清空标签(与「写空简介」同一口径)。"""
    from mdcx.config.manager import manager
    from mdcx.tools import emby_actor_manager
    from mdcx.tools.emby_actor_manager import ActorInfo

    captured: dict = {}

    async def handler(method, url, *, headers=None, data=None, token=None, **kwargs):
        captured["data"] = data
        return _JsonResp(204), ""

    monkeypatch.setattr(manager.config, "server_type", "emby")
    monkeypatch.setattr(manager.config, "emby_url", "http://127.0.0.1:8096")
    monkeypatch.setattr(manager.config, "api_key", "token")
    monkeypatch.setattr(emby_actor_manager, "_emby_request", handler)

    actor = ActorInfo(
        name="测试", actor_id="id1", server_id="srv1", existing_overview="简介", existing_taglines=["噪声"]
    )
    ok, msg = await emby_actor_manager.clean_actor_data(actor, "简介", False, [])
    assert ok is True, msg
    assert json.loads(captured["data"])["Taglines"] == []


def test_apply_tagline_clean_rules_unit():
    """纯函数口径: 非列表入参返回空列表, 非字符串元素跳过, 首尾空白去掉。"""
    from mdcx.models.emby import apply_tagline_clean_rules

    assert apply_tagline_clean_rules(None, [("a", "b")]) == []
    assert apply_tagline_clean_rules("不是列表", [("a", "b")]) == []
    assert apply_tagline_clean_rules([None, 123, "  x  "], []) == ["x"]
    # 无规则时等价于仅内置占位清洗
    assert apply_tagline_clean_rules(["无维基百科信息, 从 minnano-av 数据库补全女优信息"], None) == []
    # 规则命中才替换
    assert apply_tagline_clean_rules(["演员A", "演员B"], [("演员B", "演员C")]) == ["演员A", "演员C"]


def test_scan_actor_data_noise():
    """扫描口径: 脏简介/脏标签/非法生日入选; 正常值、空值、Emby 零值(0001-01-01)不算噪声。"""
    from mdcx.tools.emby_actor_manager import ActorInfo
    from mdcx.tools.emby_actor_manager_ui import scan_actor_data_noise

    clean = ActorInfo(
        name="正常",
        actor_id="1",
        server_id="s",
        has_overview=True,
        existing_overview="正常简介",
        existing_premiere_date="1984-08-22T00:00:00.0000000Z",
    )
    emby_zero = ActorInfo(
        name="零值", actor_id="2", server_id="s", existing_premiere_date="0001-01-01T00:00:00.0000000Z"
    )
    # 议题 #171: <br>/换行属合法结构, 不算脏(清洗不再压平), 不进噪声名单
    dirty_ov = ActorInfo(
        name="占位", actor_id="3", server_id="s", existing_overview="无维基百科信息, 从 minnano-av 数据库补全女优信息"
    )
    bad_birth = ActorInfo(
        name="坏生日", actor_id="4", server_id="s", existing_premiere_date="0000-00-00T00:00:00.0000000Z"
    )
    dirty_tags = ActorInfo(
        name="脏标签",
        actor_id="5",
        server_id="s",
        existing_taglines=["日本女演员", "无维基百科信息, 从 minnano-av 数据库补全女优信息"],
    )

    items = scan_actor_data_noise([clean, emby_zero, dirty_ov, bad_birth, dirty_tags])
    by_id = {a.actor_id: (ov, tags, fix) for a, ov, tags, fix in items}
    assert set(by_id) == {"3", "4", "5"}
    assert by_id["3"] == ("", [], False)
    assert by_id["4"] == ("", [], True)
    # 标签里出现内置占位文案同样算脏, 清洗后该条被删除
    assert by_id["5"] == ("", ["日本女演员"], False)


def test_scan_actor_data_noise_applies_user_rules_to_taglines():
    """自定义替换规则同时作用于详情与标签(表格「标签」列 = Taglines)。"""
    from mdcx.tools.emby_actor_manager import ActorInfo
    from mdcx.tools.emby_actor_manager_ui import scan_actor_data_noise

    actor = ActorInfo(
        name="待清洗",
        actor_id="1",
        server_id="s",
        has_overview=True,
        existing_overview="简介里的 minnano 噪声",
        existing_taglines=["minnano 标签", "正常标签"],
    )
    items = scan_actor_data_noise([actor], [("minnano", "")])
    assert len(items) == 1
    _actor, new_ov, new_tags, fix_birth = items[0]
    assert new_ov == "简介里的  噪声", "简介仍按字面量替换(不去空白, 保持旧口径)"
    assert new_tags == ["标签", "正常标签"], "标签同样过替换规则, 且首尾空白被去掉"
    assert fix_birth is False


def test_scan_actor_data_noise_keeps_untouched_tags_clean():
    """规则不命中时标签原样保留, 且不进噪声名单(避免无意义写回服务器)。"""
    from mdcx.tools.emby_actor_manager import ActorInfo
    from mdcx.tools.emby_actor_manager_ui import scan_actor_data_noise

    actor = ActorInfo(
        name="干净",
        actor_id="1",
        server_id="s",
        has_overview=True,
        existing_overview="正常简介",
        existing_taglines=["日本女演员", "AV女优"],
    )
    assert scan_actor_data_noise([actor], [("不会命中", "X")]) == []


def test_actress_db_no_longer_writes_placeholder():
    """议题 #149: minnano 命中无简介时不再写占位文案(死循环根源)。"""
    import inspect

    from mdcx.tools import actress_db

    assert "从 minnano-av 数据库补全" not in inspect.getsource(actress_db)


class TestDefaultCleanRules:
    """内置默认规则: 两条占位文案(删噪声) + 四条英文身份文案(译名)。"""

    #: 用户 2026-10-17 指定的四条英文身份译文, 逐条锁定防漂移。
    ENGLISH_IDENTITY_RULES = [
        ("Japanese AV actress", "日本AV女优"),
        ("American pornographic actress", "美国色情女演员"),
        ("American pornographic performer", "美国色情演员"),
        ("Brazilian pornographic actress", "巴西色情女演员"),
    ]

    def test_defaults_contain_placeholder_and_english_identity(self):
        from mdcx.tools.emby_actor_clean_rules import DEFAULT_CLEAN_RULES

        assert DEFAULT_CLEAN_RULES[:2] == [
            ("无维基百科信息, 从 minnano-av 数据库补全女优信息", ""),
            ("无维基百科信息，从 minnano-av 数据库补全女优信息", ""),
        ]
        assert DEFAULT_CLEAN_RULES[2:] == self.ENGLISH_IDENTITY_RULES

    def test_config_model_default_matches_constant(self):
        """模型默认值必须与常量一致, 否则新装用户和常量兜底看到的规则不同。"""
        from mdcx.config.models import Config
        from mdcx.tools.emby_actor_clean_rules import DEFAULT_CLEAN_RULES

        assert Config().actor_clean_rules == [list(rule) for rule in DEFAULT_CLEAN_RULES]

    def test_ensure_appends_missing_to_existing_config(self):
        """老配置存盘只有占位两条时, 英文四条补齐追加到末尾, 已有条目顺序与改过的替换值不变。"""
        from mdcx.tools.emby_actor_clean_rules import _ensure_default_clean_rules

        stored = [
            ("无维基百科信息, 从 minnano-av 数据库补全女优信息", ""),
            ("无维基百科信息，从 minnano-av 数据库补全女优信息", ""),
            ("Japanese AV actress", "用户自己改的译名"),
        ]
        result = _ensure_default_clean_rules(stored)
        # 用户改过的替换值不被默认值覆盖回去, 且仍在原位
        assert result[0] == stored[0]
        assert result[1] == stored[1]
        assert result[2] == ("Japanese AV actress", "用户自己改的译名")
        # 其余三条缺失默认追加到末尾
        assert result[3:] == self.ENGLISH_IDENTITY_RULES[1:]

    def test_defaults_are_always_restored_after_deletion(self):
        """用户把默认规则全删掉, 也会被补回(兜底语义)。"""
        from mdcx.tools.emby_actor_clean_rules import _ensure_default_clean_rules

        assert _ensure_default_clean_rules([]) == [
            ("无维基百科信息, 从 minnano-av 数据库补全女优信息", ""),
            ("无维基百科信息，从 minnano-av 数据库补全女优信息", ""),
            *self.ENGLISH_IDENTITY_RULES,
        ]

    def test_english_identity_rules_translate_overview_and_taglines(self):
        """四条默认规则同时作用于简介与标签(Taglines), 是译名而非删噪声。"""
        from mdcx.models.emby import apply_overview_clean_rules, apply_tagline_clean_rules
        from mdcx.tools.emby_actor_clean_rules import DEFAULT_CLEAN_RULES

        # 简介: 英文身份短语换成中文, 其余内容保留
        assert apply_overview_clean_rules("She is a Japanese AV actress.", DEFAULT_CLEAN_RULES) == (
            "She is a 日本AV女优."
        )
        # 标签: 同一条规则命中, 且首尾空白被去掉
        assert apply_tagline_clean_rules(
            ["American pornographic actress", "Brazilian pornographic actress"],
            DEFAULT_CLEAN_RULES,
        ) == ["美国色情女演员", "巴西色情女演员"]
        # actress/performer 是两条不同规则, 互不串味
        assert apply_tagline_clean_rules(["American pornographic performer"], DEFAULT_CLEAN_RULES) == ["美国色情演员"]

    def test_english_identity_actor_enters_noise_list(self):
        """简介/标签命中英文身份规则的演员要进噪声名单(否则规则不生效)。"""
        from mdcx.tools.emby_actor_clean_rules import DEFAULT_CLEAN_RULES
        from mdcx.tools.emby_actor_manager import ActorInfo
        from mdcx.tools.emby_actor_manager_ui import scan_actor_data_noise

        actor = ActorInfo(
            name="英文身份",
            actor_id="1",
            server_id="s",
            has_overview=True,
            existing_overview="She is a Japanese AV actress from Tokyo.",
            existing_taglines=["American pornographic performer"],
        )
        items = scan_actor_data_noise([actor], DEFAULT_CLEAN_RULES)
        assert len(items) == 1, "命中默认规则的演员必须进噪声名单"
        _actor, new_ov, new_tags, fix_birth = items[0]
        assert new_ov == "She is a 日本AV女优 from Tokyo."
        assert new_tags == ["美国色情演员"]
        assert fix_birth is False
