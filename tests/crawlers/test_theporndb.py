import oshash
import pytest

from mdcx.config.enums import Language, Switch, Website
from mdcx.config.manager import manager
from mdcx.crawlers.base import get_crawler
from mdcx.crawlers.theporndb import (
    ThepornDBCrawler,
    get_real_url,
    get_search_keyword,
    read_data,
)
from mdcx.models.model_types import CrawlerInput


class FakeTheporndbClient:
    def __init__(self):
        self.urls: list[str] = []

    async def get_json(self, url, **kwargs):
        self.urls.append(url)
        if url == "https://api.theporndb.net/scenes/test-scene":
            return {"data": _api_data("test-scene", "scenes")}, ""
        if url == "https://api.theporndb.net/scenes/test-movie":
            return {"data": None}, ""
        if url == "https://api.theporndb.net/movies/test-movie":
            return {"data": _api_data("test-movie", "movies")}, ""
        return None, f"unexpected url: {url}"


class FakeTheporndbSearchClient:
    async def get_json(self, url, **kwargs):
        if url == "https://api.theporndb.net/scenes/hash/fakehash":
            return None, "HTTP 404"
        if url == "https://api.theporndb.net/scenes?parse=nurumassage%202026-02-23&per_page=100":
            return {"data": [_api_data("nurumassage-ellie-nova", "scenes", title="Ellie Nova", date="2026-02-23")]}, ""
        if url == "https://api.theporndb.net/scenes/nurumassage-ellie-nova":
            return {"data": _api_data("nurumassage-ellie-nova", "scenes", title="Ellie Nova", date="2026-02-23")}, ""
        return None, f"unexpected url: {url}"


def _api_data(slug: str, kind: str, title: str | None = None, date: str = "2026-04-03") -> dict:
    return {
        "slug": slug,
        "title": title or f"{kind} title",
        "description": "Outline",
        "date": date,
        "trailer": "https://example.test/trailer.mp4",
        "background": {"large": "https://example.test/cover.jpg"},
        "posters": {"large": "https://example.test/poster.jpg"},
        "duration": 7200,
        "site": {"name": "Series A", "short_name": "seriesa", "network": {"name": "Network A"}},
        "director": {"name": "Director A"},
        "tags": [{"name": "Tag A"}],
        "performers": [
            {"name": "Actor A", "parent": {"extras": {"gender": "Female"}}},
            {"name": "Actor B", "parent": {"extras": {"gender": "Male"}}},
        ],
    }


def _input(appoint_url: str) -> CrawlerInput:
    return CrawlerInput(
        appoint_number="",
        appoint_url=appoint_url,
        file_path=None,
        mosaic="",
        number="SceneTest",
        short_number="SceneTest",
        language=Language.JP,
        org_language=Language.JP,
    )


def _file_input() -> CrawlerInput:
    data = _input("")
    data.number = "Nurumassage.26.02.23"
    data.short_number = "Nurumassage.26.02.23"
    data.file_path = "D:/Code/Personal/daiguaxiao/nurumassage.26.02.23.ellie.nova.mp4"
    return data


@pytest.mark.asyncio
async def test_theporndb_crawler_reads_scene_detail_url():
    old_token = manager.config.theporndb_api_token
    manager.config.theporndb_api_token = "token"
    try:
        crawler = ThepornDBCrawler(client=FakeTheporndbClient())
        res = await crawler.run(_input("https://theporndb.net/scenes/test-scene"))
    finally:
        manager.config.theporndb_api_token = old_token

    assert res.debug_info.error is None
    assert res.data is not None
    assert res.data.source == "ThepornDB"
    assert res.data.number == "SeriesA.26.04.03"
    assert res.data.title == "scenes title"
    assert res.data.actors == ["Actor A"]
    assert res.data.all_actors == ["Actor A", "Actor B"]
    assert res.data.directors == ["Director A"]
    assert res.data.tags == ["Tag A"]
    assert res.data.runtime == "120"
    assert res.data.thumb == "https://example.test/cover.jpg"
    assert res.data.poster == "https://example.test/poster.jpg"
    assert res.data.external_id == "https://api.theporndb.net/scenes/test-scene"


@pytest.mark.asyncio
async def test_theporndb_appoint_url_works_without_api_token():
    """议题 #81：指定网址（公开 slug 端点）不能因缺 Token 被拒。

    ThePornDB 的 /scenes/{slug} 是公开端点（实测无 Bearer 也能 200），
    此前 _headers() 无论场景都先校验 Token 直接拒绝，导致用户改输入网址也刮不出。
    """
    old_token = manager.config.theporndb_api_token
    manager.config.theporndb_api_token = ""

    class NoTokenClient:
        async def get_json(self, url, **kwargs):
            assert "Authorization" not in (kwargs.get("headers") or {})
            if url == "https://api.theporndb.net/scenes/test-scene":
                return {"data": _api_data("test-scene", "scenes")}, ""
            return None, f"unexpected url: {url}"

    try:
        crawler = ThepornDBCrawler(client=NoTokenClient())
        res = await crawler.run(_input("https://theporndb.net/scenes/test-scene"))
    finally:
        manager.config.theporndb_api_token = old_token

    assert res.debug_info.error is None
    assert res.data is not None
    assert res.data.title == "scenes title"


@pytest.mark.asyncio
async def test_theporndb_appoint_movie_url_does_not_probe_scenes():
    """指定网址已写明 /movies/ 时不应先向 /scenes/ 发一个注定 404 的请求。"""
    old_token = manager.config.theporndb_api_token
    manager.config.theporndb_api_token = "token"
    client = FakeTheporndbClient()
    try:
        crawler = ThepornDBCrawler(client=client)
        res = await crawler.run(_input("https://theporndb.net/movies/test-movie"))
    finally:
        manager.config.theporndb_api_token = old_token

    assert res.debug_info.error is None
    assert res.data is not None
    assert res.data.title == "movies title"
    assert res.data.external_id == "https://api.theporndb.net/movies/test-movie"
    assert client.urls == ["https://api.theporndb.net/movies/test-movie"]


@pytest.mark.asyncio
async def test_theporndb_crawler_continues_search_when_hash_misses(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(oshash, "oshash", lambda file_path: "fakehash")
    old_token = manager.config.theporndb_api_token
    old_switch_on = list(manager.config.switch_on)
    manager.config.theporndb_api_token = "token"
    manager.config.switch_on = [switch for switch in manager.config.switch_on if switch != Switch.THEPORNDB_NO_HASH]
    try:
        crawler = ThepornDBCrawler(client=FakeTheporndbSearchClient())
        res = await crawler.run(_file_input())
    finally:
        manager.config.theporndb_api_token = old_token
        manager.config.switch_on = old_switch_on

    assert res.debug_info.error is None
    assert res.data is not None
    assert res.data.title == "Ellie Nova"
    assert res.debug_info.search_urls == [
        "https://api.theporndb.net/scenes/hash/fakehash",
        "https://api.theporndb.net/scenes?parse=nurumassage%202026-02-23&per_page=100",
    ]


def test_theporndb_crawler_is_registered():
    assert get_crawler(Website.THEPORNDB) is ThepornDBCrawler


def _scene_hit(slug: str, title: str, date: str, site_short: str, site_url: str, performers: list[str]) -> dict:
    return {
        "slug": slug,
        "title": title,
        "date": date,
        "site": {"short_name": site_short, "url": site_url},
        "performers": [{"name": p} for p in performers],
    }


def test_get_real_url_prefers_title_hit_over_date_bucket():
    """议题 #94 实测误配：ThePornDB 同日同厂多部作品，日期桶命中 Wanilianna
    《The Squirting Harlot》（错的），真正目标的站点归属 HobbyPorn（非 Faphouse）。
    标题精确命中必须优先于日期桶。"""
    from mdcx.crawlers.theporndb import get_real_url

    file_path = (
        r"U:\Service\欧美转移\FapHouse.25.06.28.Comatozze.Fucking.My.Big.Tit.Best.Friend.Friendship.Is.Over.strm"
    )
    payload = {
        "data": [
            _scene_hit(
                "faphouse-wanilianna-the-squirting-harlot",
                "The Squirting Harlot",
                "2025-06-28",
                "Faphouse",
                "https://faphouse.com",
                ["Wanilianna"],
            ),
            _scene_hit(
                "hobbyporncomatozze-fucking-my-big-tit-best-friend-friendship-is-over",
                "Fucking My Big Tit Best Friend - Friendship Is Over",
                "2025-06-28",
                "HobbyPorn",
                "https://hobbyporn.com",
                ["Comatozze"],
            ),
        ]
    }
    got = get_real_url(payload, file_path, "faphouse", "2025-06-28", "scenes")
    assert (
        got == "https://api.theporndb.net/scenes/hobbyporncomatozze-fucking-my-big-tit-best-friend-friendship-is-over"
    )


def test_get_real_url_matches_hyphenated_site_url():
    """站点 URL 里的连字符不应影响系列匹配（TeamSkeet -> team-skeet.com）。"""
    from mdcx.crawlers.theporndb import get_real_url

    payload = {
        "data": [
            _scene_hit(
                "teamskeet-some-title",
                "Some Title",
                "2026-01-01",
                "TeamSkeet",
                "https://www.team-skeet.com",
                [],
            )
        ]
    }
    got = get_real_url(payload, "TeamSkeet.26.01.01.Some.Title.mp4", "teamskeet", "2026-01-01", "scenes")
    assert got == "https://api.theporndb.net/scenes/teamskeet-some-title"


def test_get_real_url_date_bucket_rejects_low_similarity_candidates():
    """日期桶候选与文件名毫无标题/演员重合时不得硬配（宁可未命中交给下一搜索词/其它站点）。"""
    from mdcx.crawlers.theporndb import get_real_url

    file_path = r"U:\Media\FapHouse.25.06.28.Comatozze.Fucking.My.Big.Tit.Best.Friend.Friendship.Is.Over.strm"
    payload = {
        "data": [
            _scene_hit(
                "faphouse-wanilianna-the-squirting-harlot",
                "The Squirting Harlot",
                "2025-06-28",
                "Faphouse",
                "https://faphouse.com",
                ["Wanilianna"],
            ),
            _scene_hit(
                "faphouse-someone-else-same-day",
                "Totally Different Scene",
                "2025-06-28",
                "Faphouse",
                "https://faphouse.com",
                ["Someone Else"],
            ),
        ]
    }
    assert get_real_url(payload, file_path, "faphouse", "2025-06-28", "scenes") is False


def test_get_real_url_bare_number_file_does_not_guess_from_date_bucket():
    """裸番号文件（无标题信息）不得从日期桶里随便挑一条押中——宁可报未找到。"""
    from mdcx.crawlers.theporndb import get_real_url

    file_path = r"U:\Media\FapHouse.25.06.28.strm"
    payload = {
        "data": [
            _scene_hit(
                "faphouse-wanilianna-the-squirting-harlot",
                "The Squirting Harlot",
                "2025-06-28",
                "Faphouse",
                "https://faphouse.com",
                ["Wanilianna"],
            )
        ]
    }
    assert get_real_url(payload, file_path, "faphouse", "2025-06-28", "scenes") is False


def test_get_real_url_date_bucket_still_accepts_title_like_filename():
    """既有语义保真：文件名含完整标题时，日期桶仍按相似度选中正确条目。"""
    from mdcx.crawlers.theporndb import get_real_url

    file_path = (
        r"U:\Media\manyvids.26.05.04.ittybittycherry.rough.fuckdoll.free.use."
        "titty.slapping.degrading.sex.xxx.strm"
    )
    payload = {
        "data": [
            _scene_hit(
                "manyvids-wrong-same-day",
                "Something Else Entirely",
                "2026-05-04",
                "manyvids",
                "https://manyvids.com",
                ["Someone Else"],
            ),
            _scene_hit(
                "manyvidsittybittycherry-rough-fuckdoll",
                "Rough Fuckdoll Free Use Titty Slapping Degrading Sex",
                "2026-05-04",
                "manyvids",
                "https://manyvids.com",
                ["IttyBittyCherry"],
            ),
        ]
    }
    got = get_real_url(payload, file_path, "manyvids", "2026-05-04", "scenes")
    assert got == "https://api.theporndb.net/scenes/manyvidsittybittycherry-rough-fuckdoll"


@pytest.mark.asyncio
async def test_theporndb_search_falls_through_when_date_bucket_mismatches(monkeypatch: pytest.MonkeyPatch):
    """端到端复现议题 #94：首个搜索词（厂牌+日期）只回同日不同片 → 拒收 →
    第二个搜索词（厂牌+演员/标题）命中真正目标。"""
    from mdcx.crawlers.theporndb import get_real_url  # noqa: F401

    monkeypatch.setattr(oshash, "oshash", lambda file_path: "fakehash")
    old_token = manager.config.theporndb_api_token
    old_switch_on = list(manager.config.switch_on)
    manager.config.theporndb_api_token = "token"
    manager.config.switch_on = [switch for switch in manager.config.switch_on if switch != Switch.THEPORNDB_NO_HASH]

    wrong_slug = "faphouse-wanilianna-the-squirting-harlot"
    right_slug = "hobbyporncomatozze-fucking-my-big-tit-best-friend-friendship-is-over"

    class Issue94Client:
        async def get_json(self, url, **kwargs):
            if url == "https://api.theporndb.net/scenes/hash/fakehash":
                return None, "HTTP 404"
            if url == "https://api.theporndb.net/scenes?parse=faphouse%202025-06-28&per_page=100":
                return {
                    "data": [
                        _scene_hit(
                            wrong_slug,
                            "The Squirting Harlot",
                            "2025-06-28",
                            "Faphouse",
                            "https://faphouse.com",
                            ["Wanilianna"],
                        )
                    ]
                }, ""
            if url == "https://api.theporndb.net/scenes?parse=faphouse%20COMATOZZE%20FUCKING&per_page=100":
                return {
                    "data": [
                        _scene_hit(
                            right_slug,
                            "Fucking My Big Tit Best Friend - Friendship Is Over",
                            "2025-06-28",
                            "HobbyPorn",
                            "https://hobbyporn.com",
                            ["Comatozze"],
                        )
                    ]
                }, ""
            if url == f"https://api.theporndb.net/scenes/{right_slug}":
                return {"data": _api_data(right_slug, "scenes", title="Fucking My Best Friend", date="2025-06-28")}, ""
            return None, f"unexpected url: {url}"

    data = _input("")
    data.number = "Faphouse.25.06.28"
    data.short_number = "Faphouse.25.06.28"
    data.file_path = (
        "U:/Service/欧美转移/FapHouse.25.06.28.Comatozze.Fucking.My.Big.Tit.Best.Friend.Friendship.Is.Over.strm"
    )
    try:
        crawler = ThepornDBCrawler(client=Issue94Client())
        res = await crawler.run(data)
    finally:
        manager.config.theporndb_api_token = old_token
        manager.config.switch_on = old_switch_on

    assert res.debug_info.error is None
    assert res.data is not None
    assert res.data.title == "Fucking My Best Friend"
    assert res.debug_info.detail_urls == [f"https://api.theporndb.net/scenes/{right_slug}"]


def _deeper_conflict_search() -> dict:
    """2026-10-19 实测：搜 `Deeper.26.06.17` 时 ThePornDB 递回来的同名无关作品。

    搜索关键词退化成纯系列名（"Deeper "）后，`scenes?parse=deeper ` 把 2016 年的
    SketchySex.16.10.19「Deeper!」捞了回来；标题去空格后是 "deeper"，正好是文件名
    归一化串 "deeper260617" 的子串，于是被旧逻辑当成目标。
    """
    return {
        "data": [
            {
                "slug": "sketchysex-deeper",
                "title": "Deeper!",
                "date": "2016-10-19",
                "site": {"short_name": "SketchySex", "url": "https://sketchysex.com"},
                "performers": [{"name": "Someone Else"}],
            }
        ]
    }


def test_get_real_url_rejects_candidate_whose_date_contradicts_number():
    """番号日期与候选条目日期矛盾时不得采纳。"""
    assert (
        get_real_url(
            _deeper_conflict_search(),
            "Deeper.26.06.17.mp4",
            "Deeper",
            "2026-06-17",
            "scenes",
        )
        is False
    )


def test_get_real_url_accepts_candidate_whose_date_matches():
    """阳性对照：日期一致时照常采纳，不能把这条路径改死。"""
    search = _deeper_conflict_search()
    search["data"][0]["date"] = "2026-06-17"

    assert (
        get_real_url(
            search,
            "Deeper.26.06.17.mp4",
            "Deeper",
            "2026-06-17",
            "scenes",
        )
        == "https://api.theporndb.net/scenes/sketchysex-deeper"
    )


def test_get_real_url_no_date_in_filename_keeps_scenes_shortcut():
    """文件名里没有日期（date 为空）时不判矛盾，scenes 无条件兜底必须保留。"""
    assert (
        get_real_url(
            _deeper_conflict_search(),
            "some scene title.mp4",
            "",
            "",
            "scenes",
        )
        == "https://api.theporndb.net/scenes/sketchysex-deeper"
    )


def test_get_search_keyword_lowercase_bare_number_has_no_trailing_space():
    """小写文件名也要能识别番号；裸番号的退化搜索词不能再带尾空格。"""
    keywords, series_ex, date = get_search_keyword(r"D:\Media\deeper.26.06.17.mp4")

    assert keywords == ["deeper 2026-06-17", "deeper"]
    assert series_ex == "deeper"
    assert date == "2026-06-17"


def test_get_search_keyword_uses_basename_and_excludes_series_from_title():
    """目录名里的日期不能抢先匹配；标题词过滤系列名时要忽略大小写。"""
    keywords, series_ex, date = get_search_keyword(r"D:\Media\Deeper.25.01.01\Deeper.26.06.17.Break.In.mp4")

    # remove_escape_string() 会统一转成大写，这是既有行为，不在本次改动范围内。
    assert keywords == ["deeper 2026-06-17", "deeper BREAK IN"]
    assert series_ex == "deeper"
    assert date == "2026-06-17"


def test_get_real_url_skips_malformed_candidate_instead_of_dropping_all():
    """单条候选缺字段只跳过该条，不能让整批搜索结果一起作废。"""
    file_path = (
        r"U:\Service\欧美转移\FapHouse.25.06.28.Comatozze.Fucking.My.Big.Tit.Best.Friend.Friendship.Is.Over.strm"
    )
    payload = {
        "data": [
            {"slug": "broken-candidate"},
            _scene_hit(
                "hobbyporncomatozze-fucking-my-big-tit-best-friend-friendship-is-over",
                "Fucking My Big Tit Best Friend - Friendship Is Over",
                "2025-06-28",
                "HobbyPorn",
                "https://hobbyporn.com",
                ["Comatozze"],
            ),
        ]
    }

    assert (
        get_real_url(payload, file_path, "faphouse", "2025-06-28", "scenes")
        == "https://api.theporndb.net/scenes/hobbyporncomatozze-fucking-my-big-tit-best-friend-friendship-is-over"
    )


def test_read_data_keeps_actors_when_one_performer_lacks_parent():
    """单个演员缺 parent/gender 不能让后面的演员全部丢失，也不能阻断时长解析。"""
    data = _api_data("test-scene", "scenes")
    data["duration"] = "7200.9"
    data["performers"] = [
        {"name": "Actor A", "parent": {"extras": {"gender": "Female"}}},
        {"name": "Actor B"},
        {"name": "Actor C", "parent": {"extras": {}}},
    ]

    result = read_data(data, "scenes")

    assert result.all_actors == ["Actor A", "Actor B", "Actor C"]
    assert result.actors == ["Actor A"]
    assert result.runtime == "120"


@pytest.mark.asyncio
async def test_theporndb_search_urls_are_percent_encoded_and_movies_use_parse(
    monkeypatch: pytest.MonkeyPatch,
):
    """搜索 URL 统一百分号转义；movies 也用 parse，不再出现 ?q= 与裸空格。"""
    monkeypatch.setattr(oshash, "oshash", lambda file_path: "fakehash")
    old_token = manager.config.theporndb_api_token
    old_switch_on = list(manager.config.switch_on)
    manager.config.theporndb_api_token = "token"
    manager.config.switch_on = [switch for switch in manager.config.switch_on if switch != Switch.THEPORNDB_NO_HASH]

    candidate = _api_data("movie-break-in", "movies", title="Break In", date="2025-06-28")
    candidate["site"] = {
        "name": "Blacked",
        "short_name": "Blacked",
        "url": "https://blacked.com",
        "network": {"name": "Blacked"},
    }
    seen_urls: list[str] = []

    class EncodingClient:
        async def get_json(self, url, **kwargs):
            seen_urls.append(url)
            if "/hash/" in url:
                return None, "HTTP 404"
            if "/scenes?" in url:
                return {"data": []}, ""
            if "/movies?" in url:
                return {"data": [candidate]}, ""
            if url == "https://api.theporndb.net/movies/movie-break-in":
                return {"data": candidate}, ""
            return None, f"unexpected url: {url}"

    data = _input("")
    data.number = "Blacked.25.06.28"
    data.short_number = "Blacked.25.06.28"
    data.file_path = "D:/Media/Blacked.25.06.28.Break.In.mp4"
    try:
        crawler = ThepornDBCrawler(client=EncodingClient())
        res = await crawler.run(data)
    finally:
        manager.config.theporndb_api_token = old_token
        manager.config.switch_on = old_switch_on

    assert res.debug_info.error is None
    assert res.data is not None
    assert res.data.title == "Break In"
    assert "https://api.theporndb.net/scenes?parse=blacked%202025-06-28&per_page=100" in seen_urls
    assert "https://api.theporndb.net/scenes?parse=blacked%20BREAK%20IN&per_page=100" in seen_urls
    assert "https://api.theporndb.net/movies?parse=blacked%202025-06-28&per_page=100" in seen_urls
    assert all(" " not in url for url in seen_urls)
    assert all("?q=" not in url for url in seen_urls)
    # ctx.debug 也不能再把 %20 还原成空格，否则日志里又看不出尾随空格。
    assert any("parse=blacked%202025-06-28" in log for log in res.debug_info.logs)
    assert not any("parse=blacked 2025-06-28" in log for log in res.debug_info.logs)


@pytest.mark.asyncio
async def test_theporndb_bare_number_failure_reports_nearest_site_candidate(
    monkeypatch: pytest.MonkeyPatch,
):
    """裸番号搜不到时只提示相邻日期的同站点条目，不自动采纳。"""
    monkeypatch.setattr(oshash, "oshash", lambda file_path: "fakehash")
    old_token = manager.config.theporndb_api_token
    old_switch_on = list(manager.config.switch_on)
    manager.config.theporndb_api_token = "token"
    manager.config.switch_on = [switch for switch in manager.config.switch_on if switch != Switch.THEPORNDB_NO_HASH]

    nearest = _api_data("deeper-break-in", "scenes", title="Break In", date="2026-06-18")
    nearest["site"] = {
        "name": "Deeper",
        "short_name": "Deeper",
        "url": "https://deeper.com",
        "network": {"name": "Deeper"},
    }

    class HintClient:
        async def get_json(self, url, **kwargs):
            if "/hash/" in url:
                return None, "HTTP 404"
            if "site=deeper&" in url and "/scenes?" in url:
                return {"data": [nearest]}, ""
            if "/scenes?" in url or "/movies?" in url:
                return {"data": []}, ""
            return None, f"unexpected url: {url}"

    data = _input("")
    data.number = "Deeper.26.06.17"
    data.short_number = "Deeper.26.06.17"
    data.file_path = "D:/Media/Deeper.26.06.17.mp4"
    try:
        res = await ThepornDBCrawler(client=HintClient()).run(data)
    finally:
        manager.config.theporndb_api_token = old_token
        manager.config.switch_on = old_switch_on

    assert res.data is None
    message = str(res.debug_info.error)
    assert "2026-06-18《Break In》" in message
    assert "未自动采用" in message


def test_url_log_display_encodes_spaces_and_non_ascii():
    from mdcx.web_async import AsyncWebClient

    assert (
        AsyncWebClient._escape_url_for_log("https://api.theporndb.net/movies?q=deeper &per_page=100")
        == "https://api.theporndb.net/movies?q=deeper%20&per_page=100"
    )
    assert (
        AsyncWebClient._escape_url_for_log("https://example.test/a%20b?q=中文")
        == "https://example.test/a%20b?q=%E4%B8%AD%E6%96%87"
    )
