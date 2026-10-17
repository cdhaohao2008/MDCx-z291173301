from mdcx.config.enums import Website
from mdcx.config.models import Config
from mdcx.crawlers import get_registered_crawler_site_values


def test_fc2ppvdb_is_available_in_single_website_options():
    registered_sites = get_registered_crawler_site_values()

    assert Website.FC2PPVDB.value in registered_sites


def test_dmm_api_is_available_in_single_website_options():
    registered_sites = get_registered_crawler_site_values()
    assert Website.DMM_API.value in registered_sites


def test_brand_official_sites_available_in_type_site_editor():
    """Dahlia / FALENO 独立成站后须出现在「编辑网站→可用网站」面板里。

    该面板由 _open_site_editor 用 get_registered_crawler_site_values() 直接喂给
    SiteListEditorDialog，故只要爬虫已注册即可见，无需额外的 UI 适配。
    """
    registered_sites = get_registered_crawler_site_values()

    assert Website.DAHLIA.value in registered_sites
    assert Website.FALENO.value in registered_sites

    config = Config()
    assert Website.DAHLIA in config.website_youma
    assert Website.FALENO in config.website_youma


def test_config_website_schema_uses_registered_crawler_sites():
    website_schema = Config.json_schema()["$defs"]["Website"]
    registered_sites = get_registered_crawler_site_values()

    assert website_schema["enum"] == registered_sites
    assert Website.AIRAV.value not in website_schema["enum"]
