"""设置页「提示」与「字段说明」气泡的开关 / 展示 / Esc 收起。

从 `main_window.py` 按集群切出，逻辑与文案逐字不变（含大段 HTML 帮助文本）。"""


class TipsMixin:
    # region 设置-问号
    def pushButton_tips_normal_mode_clicked(self):
        self._show_tips(self.Ui.pushButton_tips_normal_mode.toolTip())

    def pushButton_tips_separate_mode_clicked(self):
        self._show_tips(self.Ui.pushButton_tips_separate_mode.toolTip())

    def pushButton_tips_sort_mode_clicked(self):
        self._show_tips(self.Ui.pushButton_tips_sort_mode.toolTip())

    def pushButton_tips_update_mode_clicked(self):
        self._show_tips(self.Ui.pushButton_tips_update_mode.toolTip())

    def pushButton_tips_read_mode_clicked(self):
        self._show_tips(self.Ui.pushButton_tips_read_mode.toolTip())

    def pushButton_tips_soft_clicked(self):
        self._show_tips(self.Ui.pushButton_tips_soft.toolTip())

    def pushButton_tips_hard_clicked(self):
        self._show_tips(self.Ui.pushButton_tips_hard.toolTip())

    # 设置-显示说明信息
    def _show_tips(self, msg):
        self.Ui.textBrowser_show_tips.setText(msg)
        self.Ui.widget_show_tips.show()

    # ESC 统一入口：编辑 NFO 面板可见时等同点「关闭」按钮（走 _close_nfo_editor，
    # 脏数据照常弹保存确认）；否则才关说明弹窗；两者都没有时收进系统托盘
    # （hide_to_tray），即「按 ESC 隐藏到任务栏托盘图标」。注意 ESC 全应用只许存在
    # 这一条路径——关闭按钮自身不得再设 shortcut，否则与本全局 QShortcut 键序列
    # 相同会被 Qt 判为 ambiguous shortcut，两条都不触发（此前 ESC 毫无反应的根因）。
    def hide_tips_widget_on_escape(self):
        if not self.Ui.widget_nfo.isHidden():
            self._close_nfo_editor()
            return
        if self.Ui.widget_show_tips.isVisible():
            self.Ui.widget_show_tips.hide()
            return
        self.hide_to_tray()

    # 设置-刮削网站和字段中的详细说明弹窗
    def pushButton_scrape_note_clicked(self):
        from mdcx.crawlers import get_registered_crawler_site_values

        sites_html = "".join(f"  <li>{site}</li>\n" for site in get_registered_crawler_site_values())
        self._show_tips(f"""<html>
    <head/>
    <body>
      <p><span style=" font-weight:700;">所有可用网站:</span></p>
    {sites_html}  <p><span style=" font-weight:700;">指定类型影片可指定刮削网站:<span></p>
       <p>· 有码：DMM、DMM_API、TheJavDB_API、LibreDMM、R18.dev、AVBase、Xcity、Prestige、MGStage、Getchu、JavLibrary、FreeJavBT、Lulubar、AVMOO，以及 JavBus、JavDB、MissAV、Official（含 Dahlia/Faleno 厂牌与无码官网路由）、Airav.cc、AVSEX、JavDay、JavFree、IQQTV、7mmtv 等综合站；JavDB_API/JavDB_APP/MissAV_API/R18.dev/TheJavDB_API 是免 CF 直连通道</p>
       <p>· 无码：AVEntertainments、AVSOX，以及 JavBus、JavDB、MissAV、AVSEX、Official、JavDay、IQQTV、7mmtv 等综合站</p>
      <p>· 欧美：AVheat、ThepornDB</p>
      <p>· 国产：AVSEX、IQQTV、JavDay、Madou.club、Madouqu</p>
      <p>· 动漫/里番：Getchu、JavDB、JavDB_API（锁定「动漫」用此三站；DLID 开头或路径含 getchu/里番/动漫自动用 Getchu 单站）</p>
      <p>· MyWife：MyWife </p>
      <p>· 素人：7mmtv、AVBase、DMM、DMM_API、IQQTV、JavBus、JavDB、MGStage、MissAV、MissAV_API、MyWife、Prestige </p>
      <p>· <b>FC2 ：</b>7mmtv、FC2、FC2PPVDB、JavDB、JavFree </p>
    </body>
    </html>""")

    def pushButton_field_tips_nfo_clicked(self):
        msg = """
    <?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n\
    <movie>\n\
    <plot><![CDATA[剧情简介]]></plot>\n\
    <outline><![CDATA[剧情简介]]></outline>\n\
    <originalplot><![CDATA[原始剧情简介]]></originalplot>\n\
    <tagline>发行日期 XXXX-XX-XX</tagline> \n\
    <premiered>发行日期</premiered>\n\
    <releasedate>发行日期</releasedate>\n\
    <release>发行日期</release>\n\
    <num>番号</num>\n\
    <title>标题</title>\n\
    <originaltitle>原始标题</originaltitle>\n\
    <sorttitle>类标题 </sorttitle>\n\
    <mpaa>家长分级</mpaa>\n\
    <customrating>自定义分级</customrating>\n\
    <actor>\n\
        <name>名字</name>\n\
        <type>类型：演员</type>\n\
    </actor>\n\
    <director>导演</director>\n\
    <rating>评分</rating>\n\
    <criticrating>影评人评分</criticrating>\n\
    <votes>想看人数</votes>\n\
    <year>年份</year>\n\
    <runtime>时长</runtime>\n\
    <series>系列</series>\n\
    <set>\n\
        <name>合集</name>\n\
    </set>\n\
    <studio>片商/制作商</studio> \n\
    <maker>片商/制作商</maker>\n\
    <publisher>厂牌/发行商</publisher>\n\
    <label>厂牌/发行商</label>\n\
    <tag>标签</tag>\n\
    <genre>风格</genre>\n\
    <cover>背景图地址</cover>\n\
    <poster>封面图地址</poster>\n\
    <trailer>预告片地址</trailer>\n\
    <website>刮削网址</website>\n\
    </movie>\n\
        """
        self._show_tips(msg)
