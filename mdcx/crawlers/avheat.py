#!/usr/bin/env python3
from typing import override

from ..config.models import Website
from .aio_site import AioSiteCrawler


class AVheatCrawler(AioSiteCrawler):
    description = "欧美：欧美番号"
    namespace = "wav"
    domain_site = "avheat"
    fallback_domain = "https://www.avheat.shop/cn"
    mosaic = "欧美"
    with_outline = True
    probe_number = "Men.26.08.17"

    @classmethod
    @override
    def site(cls) -> Website:
        return Website.AVHEAT

    @classmethod
    @override
    def display_name(cls) -> str:
        return "AVheat"
