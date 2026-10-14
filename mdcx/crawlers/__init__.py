from ..config.models import Website
from . import (
    avbase,
    avsox,
    dmm_api,
    javday,
    lulubar,
    madouqu,
    mgstage,
    missav,
    thejavdb_api,
    xcity,
)
from .airav_cc import AiravCcCrawler
from .avbase import AVBaseCrawler
from .aventertainments import AVEntertainmentsCrawler
from .avheat import AVheatCrawler
from .avmoo import AvmooCrawler
from .avsex import AVSEXCrawler
from .avsox import AVSOXCrawler
from .base import get_crawler, get_registered_crawler_sites, register_crawler
from .dmm import DmmCrawler
from .fc2 import Fc2Crawler
from .fc2ppvdb import Fc2ppvdbCrawler
from .freejavbt import FreejavbtCrawler
from .getchu import GetchuCrawler
from .iqqtv import IQQTVCrawler
from .javbus import JavBusCrawler
from .javday import JavDayCrawler
from .javdb import JavDBCrawler
from .javdb_api import JavdbApiCrawler
from .javdb_app import JavdbAppCrawler
from .javfree import JavFreeCrawler
from .javlibrary import JavLibraryCrawler
from .libredmm import LibreDMMCrawler
from .lulubar import LulubarCrawler
from .madou_club import MadouClubCrawler
from .madouqu import MadouquCrawler
from .mgstage import MGStageCrawler
from .missav import MissAVCrawler
from .missav_api import MissavApiCrawler
from .mywife import MyWifeCrawler
from .official import OfficialCrawler
from .prestige import PrestigeCrawler
from .r18dev import R18DevCrawler
from .thejavdb_api import TheJavDBAPICrawler
from .theporndb import ThepornDBCrawler
from .xcity import XcityCrawler

register_crawler(DmmCrawler)
register_crawler(JavDBCrawler)
register_crawler(JavdbApiCrawler)
register_crawler(JavdbAppCrawler)
register_crawler(dmm_api.DmmApiCrawler)
register_crawler(TheJavDBAPICrawler)
register_crawler(AVBaseCrawler)
register_crawler(missav.MissAVCrawler)
register_crawler(MissavApiCrawler)
register_crawler(MadouquCrawler)
register_crawler(MadouClubCrawler)
register_crawler(AVSOXCrawler)
register_crawler(AvmooCrawler)
register_crawler(AVheatCrawler)
register_crawler(LibreDMMCrawler)
register_crawler(LulubarCrawler)
register_crawler(XcityCrawler)
register_crawler(MGStageCrawler)
register_crawler(JavDayCrawler)
register_crawler(Fc2ppvdbCrawler)
register_crawler(PrestigeCrawler)
register_crawler(R18DevCrawler)
register_crawler(Fc2Crawler)
register_crawler(JavBusCrawler)
register_crawler(FreejavbtCrawler)
register_crawler(IQQTVCrawler)
register_crawler(JavFreeCrawler)
register_crawler(AiravCcCrawler)
register_crawler(AVSEXCrawler)
register_crawler(GetchuCrawler)
register_crawler(MyWifeCrawler)
register_crawler(JavLibraryCrawler)
register_crawler(OfficialCrawler)
register_crawler(ThepornDBCrawler)

# 模块名以数字开头（7mmtv），无法用常规 import 语法，走 importlib
from importlib import import_module as _import_module  # noqa: E402

_7mmtv = _import_module("mdcx.crawlers.7mmtv")
register_crawler(_7mmtv.MmtvCrawler)


def get_registered_crawler_site_values(*, include_hidden: bool = False) -> list[str]:
    """返回已注册刮削器的网站值, 用于 UI 动态填充."""
    return [site.value for site in get_registered_crawler_sites(include_hidden=include_hidden)]
