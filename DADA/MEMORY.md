# 用户指令记忆

只记「以后每次都该怎么做」的规则。技术原理与架构见 `docs/Development.md`，版本变更见 `docs/Changelog.md`。

---

## 协作与质量

- 一律用简体中文回复。
- 面向小白的说明按「现象和影响 → 原因 → 可执行步骤」三段写。
- 日期时间用北京时间（UTC+8）并显式注明。
- 本文件不受 150 行限制，只记可复用的做法，不记一次性事实。
- **记忆只写这一个文件**：`D:\@Data\MDCx\DADA\MEMORY.md`。需要长期记住的内容直接改这里，不要另建 `.workbuddy-ai/memory/` 之类的旁路记忆文件（用户 2026-10-23 明确要求）。
- 遇到值得记的内容主动记入，不用等用户提醒。
- 改动前先说明「改什么、为什么」；用户明确要求才提交和推送。
- 直接在当前分支操作，不擅自建分支或改分支策略。

## 检查与提交纪律

- 改代码后跑 `uv run quick-check`。
- 提交前跑 `uv run check --skip-hook-install`。
- 只改 `docs/*.md` 或本文件时只需 `git diff --check`。
- 全绿判定 = 退出码 0，且 `grep -E "\.py:[0-9]+: error|Found [0-9]+ error"` 无输出（mypy 输出可能被 tail 截断）。
- `ruff check` 过 ≠ `ruff format --check` 过；改了 .py 必须 `ruff format` 落地。
- 格式化必须用仓库锁定版 ruff（pyproject pin `ruff>=0.17.1,<0.18.0`，uv.lock 实锁 0.17.1）。裸 `ruff` 只在 pin 与本机版本一致时等价。
- 升 ruff 版本后必须 `uv lock` + `uv sync`，再全量 format + check（新版本会新增规则，0.17.1 新增 `C416`）。
- `scripts/` 也在 check 范围内。
- xlsx 校验按路径跳过：`check_actor_db` / `check_info_db` 只在对应出厂库或校验脚本有改动时跑。
- `check_ui_layout` 已移出门禁，只作手工诊断：`uv run python -m scripts.check_ui_layout`。
- `check.py` 的 ALWAYS 段顺序 = `ruff format --check` → `ruff check` → `mypy mdcx/` → `check_thread_safety`（**不含 pytest**）。全量测试挪到 `--with-tests`。
- 要全量门禁必须显式：`uv run check --skip-hook-install --with-tests`。
- `ci.yaml` 的 `on:` 只有 `pull_request: branches: [main]`，**直推 main 不触发 CI**。门禁靠「PR + 本地自检」两道，别指望 CI 兜底。
- `git add -- <具体文件>`，绝不用 `git add -A`。
- 提交前看 `git status` 的未跟踪文件，运行残留与中间产物不得入库。
- 不改不是自己改的文件（并行会话可能同时改本仓库）。
- 提交信息不要手写 `Co-authored-by` trailer（`prepare-commit-msg` 会无条件追加，手写会重复）。

## pre-push 钩子

- `hooksPath` 是本地 git config，环境重置后静默失效。重置后先 `git config core.hooksPath` 验证，为空则补 `git config core.hooksPath .githooks`。
- 钩子生效时流程 = quick-check → commit → push，钩子会自动跑快速门禁，不要手动多跑。
- 钩子失效期间，推送前手动全量 check 兜底。
- `.pre-commit-config.yaml` 是历史遗留，不依赖。

## 本机环境

- Windows，Python 3.15 装在 `C:\Program Files\Python315`。
- **项目默认 Python = 3.15**（2026-10-23 起）：`requires-python = ">=3.15"`，3.14 及以下不再支持。版本声明五处同步改：`pyproject.toml`、`uv.lock` 的 `requires-python`、`requirements.txt` 头注、`README.md` 徽章、`docs/Development.md` 第 8 节；测试里的 `skipif(sys.version_info < (3, 15))` 守卫同步升版。改依赖下限仍守 cp315 wheel。
- **本机没装 uv，用户 2026-10-21 明确不装** → 一律用 `python main.py`、`python -m pytest tests/ --tb=short -m "not network"`、`python scripts/quick_check.py`、`python scripts/check.py --skip-hook-install`。脚本自带 `resolve_tool()` 兜底退 `-m ruff` / `-m mypy`，不必改 PATH。
- 仓库标准仍是 uv，**别把 CI 写法改成本机口径**。
- **pre-push 钩子会命中哪个 python**：钩子按 uv → python3 → python 逐级兜底。WorkBuddy 会话的 PATH 里 `python3` 是托管版 3.13，而 `scripts/check.py` 用了 PEP 758 的 `except A, B:`（3.14+ 才支持）→ 钩子直接 SyntaxError 拦下推送，看着像代码坏了其实是解释器选错。正解：造一个 `python3` 垫片（`#!/bin/sh` + `exec "/c/Program Files/Python315/python.exe" "$@"`）临时前置到 PATH 再推，**别用 `--no-verify`**。
- GitHub 网络：直连 `github.com:443` TCP 能连但 TLS 被 reset；本机 5915 代理对 github.com 返回 502；**Clash 7897 可用** → `git -c http.proxy=http://127.0.0.1:7897 -c https.proxy=http://127.0.0.1:7897 push origin main`。推送报 schannel「server closed abruptly」时先查是不是已经推上去了（`git ls-remote origin main` 对一下 SHA），别盲目重推。
- 沙箱陷阱：①shell 直接调系统 python 触发 stdout 捕获异常 → 写 .bat 或 Python 包装脚本，命令内 `> file 2>&1` 落盘后再读文件；②`.bat` 里 `set VAR=value` 不传子进程 → 在 PowerShell 里先设 `$env:PYTHONUTF8="1"; $env:PYTHONIOENCODING="utf-8"`；③中文 Windows 子进程默认 GBK，控制台乱码只影响显示不影响数据；④用 `python -m ruff` / `python -m mypy` 走当前解释器。
- pytest 成功时 conftest 的 `pytest_sessionfinish` 会 `os._exit(0)` 丢弃 stdout，**判定只认退出码**，要细节加 `--junitxml`。
- PowerShell 7.6.7 可用（`C:\Program Files\PowerShell\7\pwsh.exe`）。曾因注册表 `HKCU:\Software\Microsoft\Windows NT\CurrentVersion\AppCompatFlags\Layers` 给 pwsh.exe 打过 `~ RUNASADMIN` 导致 740 错误，已 `Remove-ItemProperty` 清除（其余 4 条 RUNASADMIN 按用户要求保留）。再报 740 先查这一层而不是重装，**别用 `-Verb RunAs`**（无头会话弹 UAC 会卡死）。
- pwsh 三个收益：`Set-Content -Encoding utf8NoBOM` 可用（5.1 报 ValidateSet 错且**报错后仍继续执行**）、`$OutputEncoding` 默认 utf-8、`[Console]::OutputEncoding` 仍 gb2312。
- 跨版本传参引号坑：5.1 里 `pwsh -Command '<含双引号脚本>'` 会被改写坏，复杂脚本写成 `.ps1` 再 `pwsh -NoProfile -File`。
- PowerShell 5.1 的 `Set-Content -Encoding utf8NoBOM` 不可用；中文 commit message 一律用 write 工具落盘再 `git commit -F <file>`。
- 仓库无 bash（`bash` 命令不存在）。

## 议题定性

- 定性前必须看完用户全部证据，尤其每张截图。日志文本不是证据全集。
- 定性「用户误读」等于断言无 bug，代价很大。
- 报错消息先验证是「真失败」还是「通知被误伤」。
- 版本定性用状态区指纹（配置文件名 + MDCx 数值版本）+ 日志/UI 特征串反推构建落点，不信用户自报版本号。
- 先判「待修复」还是「已修复待发版」。
- 「关工具窗连带主进程退出」有两条独立根因，按触发条件分诊：①主窗藏托盘后关最后可见窗 → `quitOnLastWindowClosed`；②取数中关 `WA_DeleteOnClose` 对话框 → 工作线程未等齐被拆，原生 abort。带工作线程的对话框 closeEvent 必须 cancel / 等齐全部线程，超时 `setParent(None)` 卸父子再放行。

## GitHub 议题处理

- 凭据：`TOKEN=$(printf "protocol=https\nhost=github.com\n\n" | git credential fill | sed -n 's/^password=//p')`。
- 议题截图用 `curl -sL` 下载后 Read。
- 同一报告人连续多议题，先横向看历史。
- 报告人 z291173301 用 Windows 原生边框；界面几何类议题先问是否默认隐藏边框，非默认配置的观感差异用隐藏边框下实测几何仲裁。
- 回帖逐项回应不遗漏，礼貌先行。
- 回帖用 JSON POST：`-d @/tmp/x.json` + `Content-Type: application/json`（勿 `-F`）。多行中文 body 用 `python3` + `json.dump` 生成；POST 失败先 `python3 -m json.tool` 校验；发送后验证返回的 `html_url`。
- 采纳原则：以代码/文档证据 + 根因是否为真为准，不以报告人语气或坚持次数为准。
- **对不尊重开发者的报告人，其个性需求一律不采纳，回帖引导 fork**（用户 2026-09-20 明示）。
- 「真 bug」标准 = 现有功能与自身设计/数据语义矛盾，或渲染错误。与个人审美不符 = 个性需求。
- **历史上为满足其偏好已发版的改动不回滚**，只把口径应用到新诉求。
- 对其议题回帖简短坚定，附依据。
- 诉求摇摆 = 高价值返工源。动手前先锁验收口径；同一块代码被改两次以上就停下来对齐需求。
- 施压型/纯验证型诉求用实测脚本定量证伪后关单，不改代码。
- 软件内说明文本的主句结构 = 用户眼中的事实清单，覆盖面与例外写成显式注记。
- `wiki/` 目录是 GitHub Wiki 内容源，每次回帖议题后把通用答案回填 FAQ。Wiki 仓库需用户先在网页建首页才能克隆。

## 排查与本地验证

- 仓库根的 `config.json` 是脏配置。验证配置/网络栈用 `Config()` 默认配置写临时文件，再指 `manager.path`。
- 行为修复流程：先复现测试跑红 → 修 → 绿 → 反向验证。修复前把当前代码喂给测试确认转红，防止恒真。
- 修复后反向审查边界与调用点语义。
- pytest-asyncio strict 纪律：文件内全是 async 才用顶部 `pytestmark`；混有同步测试必须逐函数加 `@pytest.mark.asyncio`。
- 测试必须喂生产形态数据，不手造。网页解析夹具用真实页面快照放 `tests/fixtures/`。
- 结构约束类修复用 AST 哨兵锁位置，并反向喂哨兵确认判失败。
- conftest dummy 双陷阱：实例属性会遮蔽真实 manager 属性；真实 manager 加新方法必须同步给 dummy 加同名，缺了在 Qt 测试里以 qFatal abort 爆。
- **subagent 结论不可直接采信**（22 项宣称中 11 项编造/夸大）。要求它输出「已排除假设清单 + 理由」，修复前每条独立复现。
- 数据质量治理前必须实证全量抽查，不靠代码推断。
- 触发链「功能上可达」≠「正常路径会走到」。
- `CancelledError` 在 task 收集点与 `Exception` 同级软着陆（记 CANCELLED 继续跑）。整轮取消只由 cancel_event 分支负责；`wait_for` 的 cancel 残留不得穿透。
- **误判家族四条**：①「未命中/空结果」是业务常态，不得与「通道故障」混用（真实限流信号只有 403/429/连接异常）；②模型哨兵默认值（如 `"0000-00-00"`）是 truthy 会被放行，下发前按格式白名单归一化（宽松日期解析支持 `- / .`、年月日、紧凑 YYYYMMDD，补零后交 `date()` 真校验）；③集合合并类 bug 第一嫌疑永远是有无 dedupe；④「不标来源就报结果」的日志/汇总字段是诊断盲区。
- Emby/Jellyfin 同步字段完整性：`UpdateItem` 对缺省 `Genres`/`Tags`/`ProviderIds` 空引用（上游 #17366），payload 三者恒非 null，日期/年份归一化收口在模型层 `dump()` / `update_person_info`。
- **`Taglines` ≠ `Tags`**：演员管理器「标签」列与详情窗、行内编辑一律指 `Taglines`（短词条，替换规则作用对象）；`Tags` 是 Emby 元数据标签，UI 全程不展示、数据清洗不管它。
- 持久化快照三必备：原子写（tmp + `os.replace`）、按快照比对才清 dirty、停止/退出路径强制落盘。传 `Flags` 全局列表一律 `list(...)` 快照。
- 「日志说成功但文件不存在」第一嫌疑 = 写后无回验。防御模板：replace 后 exists 校验，不过退直写，仍不落则抛错（见 `_copy_file_atomic_sync` / `write_file_atomic`）。
- WinError 123 先实测真实失败串再归因。常因云盘/映射盘文件名长度超限，出路是降 `folder_name_max` 或先刮本地盘。命名截断的目录级字段用「稳定预算」；番号识别第一锚点是日志 `[number]` 行。
- 「开关组合不生效」先画清每个开关的写入端与读取端。
- 测试耗时诊断：`--durations=15` → 单测 profile → 打桩计数。两大真凶 = 生产节流真实 sleep、单测偷跑网络。
- 大范围撤回用 `git revert --no-commit <多提交>` 合并成单撤销提交；同域测试文件归一（哨兵被覆盖就删，同 fixture 复现测试并入主回归文件）。
- TRAWL/分发包的打包布局与启动脚本入口假设必须端到点对账（发版前用解压后的真实布局实测一次启动）。大 zip 远程验尸用 HTTP Range 读中央目录。
- cmd/bat 在 chcp 65001 下中文注释会字节错位，注释用 `rem`。
- ruff B010/B009 与 mypy attr-defined 组合写法：`obj._x = v  # type: ignore[attr-defined] # noqa: SLF001` + `getattr(obj, "_x", None)  # noqa: B009`。
- 还原/回程类回归用「三态对比探针」定性（fresh → 最大化 → 还原，并排 dump 几何）。复现 UI 几何时不得 stub QSS。
- QSS 里 `QComboBox` 的 `padding-right` 与 `::drop-down` 的宽度**重复占位**：QSS 样式下文本区 = 控件宽 − 左内边距 − 右内边距 − 边框 − 箭头宽（实测 102px 的框、`padding: 3px 30px 3px 8px` + 26px 箭头，文本区只剩 35px）。所以「宽度不许改、字要显示全」的正解 = 给该控件加 `#objectName` 限定规则把右内边距清零（外框宽与箭头位置都不动），不是加宽、也不是缩字号。全量改通用规则会平移所有下拉框的 sizeHint，别动。
- 离屏平台的中文度量是退化的（4 个汉字只报 28px，真机 Microsoft YaHei UI 13px 报 52px）→ 涉及「裁字/放不下」的回归测试**别比字形宽**（会假红），比结构量：文本区右缘到箭头左缘的间隙、或钉死的 min/max 宽度。
- `edit` 工具会静默忽略缩进差异，改完立刻 `read` 复核真实缩进。
- **回归测试必须在撤掉修复后验证它会红**（`git stash push -- <生产文件>` → 跑 → `git stash pop`），否则排除不了假测试。写 Qt 重入类测试要注意复用 helper 会让一次重入事件被两个实例各处理一次。
- 门禁已知遗留红（2026-10-19 实测）：`tests/test_advanced_page_tail_align.py::test_wide_nav_row_survives_deferred_stage_one[1920-1170]` 在干净树上必红，来自上游旧提交。全量门禁合格线 =「除这条外全绿」；判定时先跑干净树对照，别把自己的改动当元凶，也别顺手去「修」它（需真机逐档量几何）。

## Qt 生命周期

- 测试里 `w.deleteLater()` ≠ 销毁。`processEvents()` 不投递 DeferredDelete，须显式 `sendPostedEvents(None, QEvent.Type.DeferredDelete)`。全仓 92 处 deleteLater 实际都没生效。
- 从未 `show()` 过的窗口，`close()` 不发 `hideEvent`。
- `MyMAinWindow.closeEvent` 由 `WindowOpsMixin` 提供，末尾总是 `a0.ignore()`。要在主窗口加 closeEvent 清理，**绝不能新写同名方法**（会遮蔽 mixin）；应加在 mixin 内部（新增 `hideEvent` 安全）。
- 多继承查处理器归属用 `"closeEvent" not in MyMAinWindow.__dict__` 或 `WindowOpsMixin.closeEvent is MyMAinWindow.closeEvent`，别用 isinstance 比 method。

## 崩溃与内存

- access violation 根因（2026-10-17 已修）：崩溃在跑到一半的 `app.processEvents()` 内，位置随缘漂移，不能靠输出尾部丢没丢区分。真凶链 = deleteLater 从未生效 → 40+ 测试文件各自造 MyMainWindow 泄漏 → 每个窗口挂 100ms 热表 `self.timer.start(100)`（另有 timer_scrape / timer_update.start(43200000) / timer_remain_task.start(1500)）→ 只有 `tests/test_window_state_matrix.py` fixture 停了这 4 个表 → 后续任意 processEvents 派发几百个陈旧回调 → AV；拦路虎是 `init.py:488 _SiteComboTipFilter.eventFilter` 无限递归爆栈（`stack overflow` / `0xC0000409`）。
- 三条走不通的路（实测更差，别再走）：补 sendPostedEvents 真析构（采样 1 绿 1 崩）；`TerminateProcess(GetCurrentProcess())`（对当前进程调用立即返回不终止自身，副作用是杀别的线程，退出码被伪造成 0）；DLL pinning（探针 5 次崩 1 次）。
- 教训：15~20 个窗口规模的探针复现不出崩溃，唯一可信判据是全量跑。间歇性原生崩溃**不适合靠反复全量跑来验证**。
- 已落地三处缺一不可：`483cee1` 给 `_SiteComboTipFilter.eventFilter` 加重入守卫；`bab49bd` 让窗口隐藏/关闭时停掉四个轮询定时器；`tests/conftest.py::_teardown_qt()` 补 `sendPostedEvents(None, QEvent.Type.DeferredDelete)`（连投两次 + processEvents）并把 `topLevelWidgets()` 套 `list()`。
- 崩溃分 A/B 面：A 面 = 跑到一半 processEvents 里 AV，退出码非 0，必须治；B 面 = `os._exit(0)` 内部 Qt DLL detach 析构存活对象导致 AV，退出码仍 0，对门禁无害。A 面的量级才关键（每个窗口带 QThread + 线程池 + asyncio 事件循环，几百个线程常驻）。验证要在单文件上做因果验证再下沉 conftest。

## UI 开发与排错

- 改 UI 先改 `.ui`（唯一权威源）→ `uv run python -m PyQt6.uic.pyuic`（相对路径）→ `scripts/fix_qt_enums.py` → `ruff format` → `tests/test_ui_structure.py`。禁止手工改 `MDCx.py`。
- Qt 布局问题先写最小复现脚本验证 Qt 原生行为，再动项目代码。根因常是 BoxLayout 缺末尾 Expanding spacer，而非 setVisible。`setVisible(False)` 管不到 QSpacerItem 等非 widget 占位项。
- `WA_DeleteOnClose` 对话框带工作线程时，closeEvent 必须等齐。
- **重影/重叠先问「渲染层还是定义层」**。定义层同 cell 多控件的几何检测抓不到，须 .ui 文本级哨兵 grep 该 grid 全部 `<item row=` 确认严格递增。实机截图是最终判据。
- **富余高度被独占一行的 wordWrap 标签吃掉**（翻译页「翻译引擎」组实证）：绝对定位容器声明高 ≫ 网格自然高且网格末尾没有 Expanding 间隔时，QGridLayout 把富余灌给该行唯一控件（垂直策略非 Fixed 的 wordWrap QLabel，表现为文字垂直居中留白 + 其下各行被整体下推）。根治要两处同改 = .ui 末尾补垂直 Expanding 间隔（防复发）+ 运行期把该行标签按纯宽度函数贴合、容器高钉成 `layout.sizeHint().height()`（`main_window.py::_sync_fanyi_group_spacing` 第 0 步，配套 `_FANYI_TRANS_BOT_PAD` / `_FANYI_TRANS_FOLLOW_GROUPS`）。
- **末尾 Expanding 间隔的 `sizeHint` 高度必须写 0**（默认 20×20 会被 sizeHint 累加成末行下方死空白，仓库已有多处 `0x0` Expanding 间隔可参照）。通用判据 = 容器高钉成 sizeHint() 前先对一遍「sizeHint() 是否 == 各控件实际几何的末行底」；回归测试要把 `spacer.sizeHint().height() == 0` 与「容器高 == 末行底」一起钉死。
- **富余被「均分」吃掉时先分清是哪一种**：①灌给该行唯一控件（见上）；②在「顶/行间/底」之间均分（表现为首行被整体顶下来、组底还剩底）。②的治法是不动容器高度逻辑，只要把行首留白显式收成常量并折进 `contentsMargins`（`_FANYI_ACTOR_TOP_PAD` 30→0），组高按「容器底 + 固定底留白」收紧，其后各组随 delta 上移，组间距不变。
- **要真机字体度量就别用 offscreen**（offscreen 下 `QFontDatabase.families()` 返回 0 个字族），改用默认 windows 插件。探针按 `tests/test_window_state_matrix.py` 的 `win` fixture 思路 monkeypatch 掉 `run_startup_health_checks` / `check_version` / `set_style` + `chdir(tmp_path)`，再 `groupBox.grab().save(png)` 与用户截图对拍。
- **通用宽幅同步只改宽不改高**（`CustomScrollArea.sync_wide_children_width()` 每遍按登记的设计几何 setGeometry，高度恒为设计值；组里有 wordWrap 标签时窗口拉宽折行减少、高度变矮，空出来的高度堆在网格底部且越宽越大）。治法 = 静态 .ui 收紧只对设计宽度成立（不够）+ 给该页挂 `_post_wide_sync_hook`（按 `extra > 0` 判宽态，`invalidate()+activate()` 之后用 `childrenRect().bottom() + 1` 量真实底边，组框高 = 容器设计 y + 容器高，其后各组按 delta 同步平移，窄态必须显式复位）。
- **窗口状态汇聚点审计**：修窗口联动 bug 时，grep `setWindowState|activateWindow|showNormal|show|hide` 全库枚举汇聚点，逐一加「可见且未最小化」守卫。配置保存/加载等业务函数不得顺手操控窗口状态。托盘隐藏后 eventFilter 不得自动 `show()`。
- **PyQt6 测试纪律**：每个含 Qt 的测试文件顶部（PyQt6 导入前）自持 `os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")`；fixture 构造后立即停全部 QTimer；qFatal abort（栈无 Python 行号）查 QTimer 槽与 dummy 桩缺方法；Qt 同名 API 重载签名不同，改前确认目标类签名；测试桩显式枚举属性方法；隔离配置目录用 `monkeypatch.chdir(tmp_path)`，勿把 dummy 的 Path 属性改成 str。
- **主窗最小尺寸是动态的**（`init.py::Init_Ui` 按 primaryScreen 可用区算 `_adaptive_window_sizes`，offscreen 虚拟屏 800x800 → min 480x600、启动 720x680）。写矮窗口几何回归测试前必须 `win.setMinimumSize(0, 0)` 解耦；断言 label 裁切用 `win.height()` 而非目标 resize 值。
- 主窗口全局绝对定位：长文本 QLabel 用 wordWrap 查 sizeHint；新增顶层控件要纳入 resizeEvent 手动几何同步；QComboBox 装饰后缀用 `addItem(icon, 文本, UserRole 纯值)`，消费点统一 `currentData()`，信号 handler 收文本须剥后缀。
- **把行内末位项（teal 提示词/说明标签）右移到某条竖线的通用手法**：在末位项之前插一个 `Fixed` 的 `QSpacerItem`（`insertSpacing` + `changeSize`），宽度 = 锚点 x − 前导项右缘 − spacing，并按「列宽 − 行内最小宽」夹到 `[0, slack]`（超了会撑破网格列宽、把不许动的锚点一起推走；夹到 0 即拆除间隔、保持自然位）。不要改用 `_pin_row_lead_width` 钉前导控件：QComboBox 会被撑成几百像素，复选框则把可点击区吞掉本该留白的区域（用户点空白处误触开关）。
- **间隔插在「前导控件之前」时，禁止用实测坐标反推同一行后续间隔**：宽→窄过渡那一拍行里还挂着上一遍的宽间隔，QHBoxLayout 会把 Fixed 间隔与前缀一起压扁（实测菜单图标 417→304），据此算出的间隔会一路自我强化，并把同一方法后面「拿该坐标当基准」的钉宽一起带歪（表现为窄→宽→窄往返后 `checkBox_auto_start` 宽度漂移 9px）。必须用**本遍刚算出的 gap** 反推意图落点；这类「自己的产物又被自己下一段当基准」的段，写进产生 gap 的那个方法内部，别拆到独立方法里。
- 造「本需求之前」的基线：把该需求的**唯一落点写入口**桩成 no-op（如 `_set_adv_hint_gap`）比另起窗口逐个摘方法更省；但入口被多处共用时，桩掉等于整体关掉功能，测试里要同时断言「目标确实被搬走了」，否则删掉整段实现也能通过。
- 极窄窗宽下的对齐需求，判据写「不劣于关掉本功能的基线」，不要写绝对的 `width >= sizeHint`——有些行在 820 宽本来就装不下（`label_421` sizeHint 288 / 实测 257），那是既有挤压，与本需求无关，写绝对判据会得到一条永远红的假用例。
- **删掉某行唯一的可拉伸项（末位提示词/说明标签）前，必须先确认那行还剩伸展能力**：QGridLayout 的列上限取「该列各行最大宽的最小值」，一行全 Fixed 就会把整列上限压到 sizeHint，超出的空间改为把整列居中 —— 表现为整页右移（实测 col1 左缘 101 → 805，`cellRect` 从 0 变成 352）。治法 = 该行末尾补一枚 `QSizePolicy::Expanding`、`sizeHint` 写 `0×0` 的间隔（与「BoxLayout 缺末尾 Expanding spacer」同源），补完列上限恢复成无界、间隔自己吃掉余量，视觉零变化。
- **删 `.ui` 控件 = 删代码里的 `ui.<name>`**：动手前 grep 全仓（控制器、`_snapshot`/`_STATICS` 名单、`sizeHint` 参与的行内最小宽算式），删完必须重跑 pyuic 并跑 `test_ui_structure`。参与「行内最小宽」的项（如 `tail_b` / `need_d` / `room`）要同步去掉它的 sizeHint，否则会按一个不存在的宽度卡门、整段对齐永远放弃。
- **位置类需求（「X 右缘与 Y 右缘严格对齐」）不要自作聪明加「不裁字」下限**：`max(锚点宽, 控件.minimumSizeHint())` 在小比例界面缩放（真机 80%）下会让控件停在最小可用宽、比锚点右出约 20px，用户直接返工。判据只有锚点坐标；宽度因此小于 minimumSizeHint、档位文字略挤，是用户自己选的取舍，最多在回帖里提一句。同理，锚点必须用 `sizeHint()` 而不是 `width()`——被 `pin_d` 钉过的复选框，`width()` 是钉宽不是文字宽。
- **行首「空 QLabel 做缩进」是对齐需求的隐形敌人**：这类标签（如已删的 `label_252`，10px Fixed + 空文本）只贡献宽度，grep 文案永远搜不到；把它的最小宽改 0 也不行——QHBoxLayout 的 spacing 还会再留 6px。要左对齐就直接从 `.ui` 删掉那枚 item，删完 pyuic 重生成即可（`horizontalLayout_85` 只剩一个子布局也合法）。排查手法 = 打印 `mapTo(content, (0,0))` 的 x 与父 cell 的 `cellRect(row, col)` 左缘做差，差值就是行首占位项总宽。

## 并发与网络库

- curl_cffi 0.16 流式关闭 = `quit_now.set()` + `await aclose()`。单独 aclose 会拉满响应体阻塞；单独 close 把 handle 置 None 后 cleanup 抛 TypeError。
- 同步 close() 只是发起 abort。「Task was destroyed」第一怀疑 = 某个 cancel 没人消费或某个内部任务没人等（shield 模式 cancel 后必须 gather）。
- 内网/自建服务（Emby/Jellyfin）不得复用爬虫重型指纹栈（只对 127.0.0.1 免检）。控制面 API 用轻量 httpx 直连客户端（无指纹/无池/无限流/显式超时），返回形状对齐 `(data, error)`。
- 「取消打断收尾」租约泄漏定性法：双残留 = Computed 级，单残留 = CrawlerProvider 级。防护三件套 = 释放路径 shield / try-finally 恒释放 / 逐实例 suppress；`__exit__` 与 `__aexit__` 成对入口要成对审计。
- LogBuffer 任务树归因：写入按 `_ROOT` contextvar，`process_one_file` 入口 `new_root()` 切断兄弟继承。
- 后台线程跑异步一律走全局 `AsyncBackgroundExecutor`（app 持久后台循环），禁用 QThread 内自建一次性 loop（curl_cffi 定时器注册到死 loop → Windows 弹 "Python-CFFI error"）。AST 哨兵锁方法内不得出现 `new_event_loop` / `run_until_complete`。
- 并发范式：文件间用 `asyncio.wait(FIRST_COMPLETED)` 滑动窗口，文件内多站点用 `gather`；后台协程统一走 `utils/qt_thread.py::run_in_background`，结果经 Qt signal 回主线程。新增后跑 `scripts/check_thread_safety.py`。
- asyncio 线程池归属：`AsyncBackgroundExecutor` 的 default executor 与主 loop 是两个池。「嵌套 to_thread 死锁」先实测两池是否同一个。
- devbox 代理 127.0.0.1:7890 可能无进程。

## 站点与网络

- 各站探测番号与收录依据见爬虫类注释。javdb 仅搜 FC2 时需要 Cookie。
- 站点 API 坑：missav_api 的 Recombee 仅 POST；DMM Affiliate v3 必需 site/service/floor 且 keyword 用 content_id 形态；madouqu 域名动态维护（24h 缓存）；madou_club 番号无横杠；parsel `Selector.get()` 纯 JSON 返回 dict（解析要兼容 str/dict/Selector 三态）。
- 站点增删史：2026-08 删 15 站（48→33），后增 javfree / aventertainments / madou_club，getchu_dmm 并入 getchu，7mmtv 回归。**当前注册爬虫 36**（Features.md 同步）。数字开头模块名（7mmtv.py）用 `importlib.import_module` 加载。
- **站点收录边界**（同 `docs/Development.md` 10.8）：AVEntertainments 只在无码组；Getchu、AVSEX 大陆 IP 过不了 CF 墙故从六组移除；Official 只在有码/无码两组。
- **「素人番号」已改名「国产短剧」**（枚举值/配置字段名仍是 `SUREN` / `website_suren`）。2.6.0 起该组默认名单只剩 JavDay。短剧无番号格式无法自动识别，只有锁定刮削类型才走这一组；原素人番号（LUXU/SIRO/259LUXU 等）一律按有码番号刮削，`_is_suren_number()` 自动分支已删除。
- **七组名与「锁定刮削类型」下拉文案（2.6.0 统一）**：组名 = 有码番号/无码番号/个摄番号/欧美视频/国产传媒/国产短剧/动漫里番；下拉八项 = 自动判断/有码番号/无码番号/个摄番号/欧美视频/国产传媒/国产短剧/动漫里番。设置页行序与下拉序都把国产短剧放在国产传媒之后、动漫里番之前。候选区七个 chip 短名 = 有码/无码/个摄/欧美/传媒/短剧/动漫。`PALETTE_GROUP_TYPES` 组序与设置页行序一致（`CONFIGURABLE_SCRAPING_TYPES` 只用于遍历配置项，次序无关）。`_CAPTION_HIDDEN_TYPES` 随短名改为 `("动漫","个摄")`。悬停/下拉那行 `<定位>：<类型名单>` 与七个 chip 同源。不属任何类型组的站（MyWife/AVSEX/Getchu/FC2）落回爬虫自己的 `description`。
- **下拉框顺序与枚举声明序不再相同**：`load_config.py` / `save_config.py` 的下标↔值映射改读 `FixedScrapingType.dropdown_values()`（顺序源 `dropdown_order()`，**不能写成类体里的常量** —— Enum 会当成员报 `TypeError: too many arguments for str()`）。
- **「锁定类型」运行期只有一张真相表（2.6.2 收敛）**：锁定分支查 `models.SCRAPING_TYPE_SITE_FIELDS`，不再在 `core/file_crawler.py` 里自带硬编码的「类型 → website_* 字段」字典。保留 `getattr(config, field, None)` 惰性取值（旧配置与测试桩类 `_ClassificationConfig` / `_SkipFieldConfig` 只带部分 `website_*` 属性、没有 `get_type_sites`，去掉会 AttributeError）。锁定分支只给 `GUOCHAN` 硬塞 `mosaic="国产"`，其余档留空（给 WUMA/DONGMAN 加会被 `is_plain_uncensored_mosaic()` 推成 wuma=True 写成「无码」）。`type_field_configs` 回退到类型名单时必须用有序的 `get_type_sites()`，不能用 `list(set)`（Website 枚举 str 的 hash 按进程随机化，每次重启命中不同站点）。
- 无码官网五站由 `official_uncensored.py` 统一路由，均需代理。1pondo / pacopacomama / 10musume 的 dyn/phpauto JSON API 直通。
- 被墙站测试：`uv run python -m scripts.dev_proxy start|status|test <url>|stop`；日本 IP 限制站用 `--port 7891 --regions "jp|日本"`。devbox 限制：超时 ≠ 站点死亡；连通性验证必须用 curl_cffi impersonate；批量探测要校验 `data.title` 防假阳性。
- **HTTP 4xx/5xx 错误串必须携带截断响应体**（保留 `"HTTP {status}"` 前缀不破坏匹配）。
- **番号归一化：前导单数字双重语义**（studio 名单数字保留 vs DMM 预约版 `9` 前缀剥掉）。改正则前 grep 全部分支，改后跑相邻语义的既有测试。
- **站点域名优先级与删站属产品取舍，查证给方案不擅动**。删站影响面 = 注册表 + Website 枚举 + 默认 proxy 列表 + `migrations.py` 清洗 + UI 列表。
- **javdb 三源**：javdb（网页）/ javdb_api（镜像站）/ javdb_app（App API，免 CF 最稳）。thejavdb 与 javdb 无关。App 签名机制见 `docs/Javdb_App_Signature.md`，排障锚点 = 三主机同时 4xx 或 InvalidSignature，环境变量 `MDCX_JAVDB_APP_SIG_*` 可免改码覆盖。搜索 limit ≤ 50，分页须 `movie_sort_by=release`。
- **javdb 图源无水印体系**：`tp.spfcas.com` 是 App 专用（单字节 XOR，首字节 key），`c0.jdbstatic.com` 带水印。解密/变换集中在 `base/web.py`。加密流尺寸探测 (0,0) 属预期。

## Windows 打包与发布

- 只有「字符串动态导入」才必须显式 `--hidden-import`（函数体内的静态 import 会被正常收集）。`tests/test_build_hidden_imports.py` 哨兵锁定全仓动态导入 ⊆ hidden-import，CI Windows job 有 PyInstaller 冒烟。
- **一体包硬失败后，所有调用 `scripts/build.py` 的工作流必须先 `fetch_sr_tools`**（`tests/test_sr_bundling.py::test_packaging_workflows_fetch_sr_tools_before_build` 锁顺序）。目录存在但缺 realesrgan / waifu2x 子目录同样硬失败。
- **一体包内置资源的运行时查找必须 fail-loud**：①查找失败给原因码并打结论日志，只有冻结运行（`sys._MEIPASS` 非空）且平台属于 `_SR_BUNDLED_PLATFORMS`（Windows/Linux；macOS 不内嵌属设计）却找不到才算异常；②释放到 userdata 后校验可执行文件真的落盘；③清理旧目录**禁用 `shutil.rmtree(..., ignore_errors=True)`**（Windows 上被占用文件被静默吞掉后紧接着 copytree 必抛 FileExistsError），改用 `onexc` 收集失败项（只读属性先 chmod 再删）后抛错并点名。回归在 `tests/test_super_resolution.py`（10 条）。
- EXCLUDED_MODULES 中 rich/typer 只供构建/CLI。Windows 上 curl_cffi.libs 需显式 `--add-binary`。
- **GitHub Actions 两坑**：①runner 标签会整体下线（macos-13 已关闭，macos-15-intel 已于 2027 秋整体退役，本仓库不再用 macOS Intel runner）；②`astral-sh/setup-uv` 无裸主版本浮动标签（写 `@v10` 报错，须全版本号）。
- **Release 发版**：唯一工作流 `build-py315.yml`。推纯数字 tag `2*` 自动发正式版，或 `workflow_dispatch` 手动补发（tag 留空取 `consts.py::LOCAL_VERSION`，prerelease 只对手动触发生效）。资产名 `MDCx-<tag>-<平台>-<arch>-<40位sha>.<exe|dmg>`，Release 标题 `MDCx <日期版本号>`。tag 必须纯数字（`check_version` 取 `tag_name.isdigit()`），客户端只读 `tag_name` 不解析资产名。macOS DMG 按架构命名，`overwrite: true` 故重跑只覆盖同名资产。Windows zip 版走 `package-trawl.yml` 单独管道。
- **Release 正文只能按文件写**（2026-10-22 修）：不得经 step output 塞进 action 的 `body` 输入。runner 会把每个 `with:` 变成 `INPUT_*` 环境变量，Linux 单个环境变量上限 128 KiB，正文一超限 node 进程起不来 → publish-release 在第一个 Create Release 就崩，而包已传上去，留下没正文的半成品 Release。改用 `gh release edit --notes-file`。
- **Actions 版本**：Node 20 已于 2025-09-19 弃用，`actions/cache@v4` 会刷 deprecation 警告（不影响成败）。本仓库统一 `actions/cache@v6`（v5 起 node24 runtime，v6 是 ESM 迁移），最低要求 runner ≥ 2.327.1（全为 GitHub 托管 runner，无自建）。

## 版本号与配置迁移

- **版本号纪律**：`LOCAL_VERSION` 领先当天是既定口径、不是缺陷（用户 2026-10-19 明示，不许提醒、不许顺手改）。`LOCAL_VERSION` 大于当天日期、多个展示版本号共用同一 `LOCAL_VERSION`、同 tag 复用 `overwrite: true` 重建 Release、`check_version()` 取数字 tag 最大值 —— 这四类日期/版本疑问一律先问用户，别写进文档、changelog 或 commit message。真正要守的只有版本号同步点一致（`scripts/bump.py --check` + `tests/test_version_consistency.py` + `tests/test_version_metadata.py`）。
- 提交前把变更写进当天日期段；用 `scripts/bump.py --version`。
- bump 升展示版本号有坑：LOCAL_VERSION 未变会误报「版本号替换失败」，需手改三处。
- Windows 跑 `bump.py` 需设 `PYTHONIOENCODING` 并 `stdout.reconfigure`。
- 「已发版」判据 = 数字 tag 已推送。
- **`config_version` 永久固定为 2**（用户 2026-10-19 定规）。三个版本点必须一致：`migrations.py::CURRENT_CONFIG_VERSION`、`Config.config_version` 默认值、`resources/config/default_config.json`，由 `tests/test_config_conversion.py::test_config_version_frozen_at_two_everywhere` 钉死。
- **连带后果：`config_version` 不能再当迁移判据**。`_migrate_main_mode()` 原本判 `version >= 3` 恒假 → 每次启动都重迁 → 选了分离/视频/更新的用户连开三次软件被改成「读取模式」。现为结构性判据 `_SEPARATE_MODE_KEYS`（`separate_success_file_move` / `separate_failed_file_move` / `separate_success_file_rename` / `separate_del_empty_folder`，是真模型字段、随 save 落盘、也会被 `Config.update()` 的 `separate_*` 继承分支补上）。**规律：版本号一旦冻结（或不可靠），一切依赖它的迁移判据都要换成结构性判据 —— 判据和它的前提必须一起改。**
- **2026-10-19 回退记录**（`git revert b04e2ec`，只退「旧配置自动升级」那一块）：已删除的符号（不要照着记忆去找）= `Config.factory_defaults()`、`migrations.backfill_missing_keys()` / `_migrate_missing_keys()`、`NEW_LIST_ITEMS` / `_ensure_list_items()` / `_migrate_new_list_items()`、`ConfigManager._needs_upgrade_persist()`，以及 `tests/test_config_auto_upgrade.py` 整个删除。回退代价 = 旧配置缺失的顶层键与列表新增项不再自动补齐、升级结果不再写回磁盘。教训 = 取「字段声明层的默认值」只能遍历 `Config.model_fields`，**绝不能用 `Config().model_dump()`**（`model_post_init` 会调 `ensure_type_field_configs()` 把 `type_field_configs` 填成 7 组，覆盖用户自定义）。仍未被回退波及的更早成果 = `load_config.py` 里 `checkBox_ignore_duanju` / `checkBox_ignore_dongman` 回填、`Config.download_files` 出厂默认里的 `IGNORE_SUREN` / `IGNORE_DONGMAN`、`default_config.json` 里的 `ignore_suren` / `ignore_dongman`（来自 `aa2151f`），`_normalize_type_field_config()` 回退取**有序** `type_sites`（不能用 `list(type_site_set)`）（来自 `58faf8e`）。教训 = 撤销一批范围不明的工作区改动一律用 `git revert --no-commit <sha>` 让 Git 自己算，复现的 diff 必须逐条核对「这段是哪个提交引入的」。
- **功能开关类配置项不得充当「逃生通道」的过滤器**：「当前配置」下拉框必须列出配置目录下**每一个** `.json`，不做任何有效性过滤（`load()` 在 errors 时会 `switch_to_failed_session()` 切到 `_failed.json`，下拉框是用户唯一切回通道）。`list_configs()` 只列 `.json`、不做有效性过滤、目录读不到时 `OSError` 兜底返回 `[]`、按文件名排序。
- **尚未落地（2026-10-19 记录，别当成已修）**：①`load_config()` 的填表仍在 `if errors: switch_to_failed_session(); return` 之后（`load_config.py:91-103`），必须把填表提到 errors 分支之前，届时可抽成 `_refresh_config_file_combos()`（**该函数目前并不存在**，曾有文档写成「已抽成」属未兑现描述）。②下标查找仍是裸 `all_config_files.index("config.json")`（`load_config.py:102`），目录里没有 config.json 时会 ValueError，应改「当前配置 → config.json → 首项 → 清空」逐级兜底。教训 = 凡是「失败时切到临时文件保护」的设计，都必须把「切回去」的 UI 通道放在失败分支之前构建。
- **⚠️ 互调型递归必须自带重入保护，终止条件不能建立在「下一次外部副作用恰好生效」上**（2026-10-19 实战，诊断已完成、修复尚未落地，勿当成已修）：`load_config()` 结尾在「读不到配置文件」时调 `self.pushButton_init_config_clicked()`，后者 `manager.reset()` 完又调回 `self.load_config()`，终止只靠「第二轮 `os.path.exists(config_path)` 变成 True」，而 `reset()` 补出来的文件不保证与 config_path 同一个 → else 分支永远成立 → 互调约百次 → `RecursionError`。拟用修法 = 回调前置 `_xxx_in_progress` 标志，第二轮若前置条件仍不满足就只做一次兜底然后 return；代码里目前**没有** `_creating_config` 标志。三条配套纪律 = ①判定互调是否真循环不要看栈尾（先把可疑的配置/输入单独喂给最深那层函数复现）②一处崩溃可能长期掩盖另一处（别以为「不崩了」就是修完了）③本地状态文件会被探针污染（仓库根未跟踪的 `MDCx.config` 曾残留 Temp 目录路径，排查「启动即崩」前先 `Get-Content MDCx.config` 看它指向哪）。
- **配置加载路径上的对象构造必须「无前置条件」**：`Computed()` 在 `ConfigManager.load()` 里被**同步**构造，而 `manager = ConfigManager()` 是**模块级实例化** → 任何在 `Computed()` 里构造的外部客户端构造失败都不得抛异常（否则第一次抛错被 load() 的 except 抓住 → 回退 `_replace_config(Config())` → 用同样坏的输入再抛一次 → 无人接管 → 模块导入失败 → 软件起不来）。实例 `LLMClient.__init__` 原先无条件 `AsyncOpenAI(api_key=...)`，`llm_key` 为空（出厂默认空）时 OpenAI SDK 抛 `OpenAIError: Missing credentials`。**修法不是给密钥塞占位符，而是缺凭据就不构造客户端**（`self.client: ... | None = None`，`close()` 加空值保护，`ask()` 打可执行提示并返回 None）。推广检查清单 = 改动 `Computed.__init__` 或其下游构造链时逐个问「它需要的凭据/网络/文件，用户没配时会抛吗」，会抛就改成惰性或兜底。**判据：可选功能（LLM 翻译、Emby、同步服务）的凭据永远不能是启动前置条件。**
- 用户在安装目录自己维护多个并列配置 json（`actor.json` / `default.json` / `studios.json` / `theporndb.json` + 各 `*bak.txt`），是针对不同命名方式/刮削网站的独立配置，不是出厂数据文件。①在用户安装目录看到同名 json 不要凭仓库同名文件断定是数据文件，先看有没有 `config_version` / `main_mode` 这类配置字段。②`list_configs()` 无差别列出目录内所有 `.json` / `.ini` 供「切换配置」选用是既有设计不是缺陷，没有用户要求不要动。
- 手工改用户真配置按**字节级单行替换**（`ReadAllText` / `WriteAllText` + `UTF8Encoding($false)`，无 BOM、纯 CRLF），改完逐项回验：JSON 可解析、`main_mode` 等行为字段未变、键集合一致、差异行只有目标行、CRLF 计数不变。

## 通用纪律

- 把常量/枚举值当判据时，改那个值必须连带 grep 所有读它的地方。没有幂等保护的迁移就是定时炸弹 —— 判据失效时不报错，几个月后以「我的设置怎么变了」出现。
- 写死数字前 grep 代码核实。高频漂移锚点：默认网站源顺序、代理域名列表、命名变量表、设置 Tab 名、字段优先级数、演员库列、指纹池、主窗口行数。README 爬虫数四处同步，Features.md 标题是独立第五处。
- 长时间任务标准做法：后台终端 + checkpoint 断点续传（state 落盘，后台终端 1 小时上限连 wrapper 一起回收）+ 分批处理批间落盘 + wrapper 45-50 分钟自重启。进度看落盘文件，不看终端日志（stdout 全缓冲可能 0 字节假象）。
- 功能移除类需求先调研证据再答：查活跃度、底层共享依赖、移除成本。用户转述与代码证据矛盾时以代码为准。
- **刮削模式值全表**（2026-10-23 起）：1 正常 / 2 分离 / 3 视频 / 4 更新 / 5 读取（只读展示）/ 6 整理 / 7 补全（本地优先、只补缺失）。新增或改动模式必须同步这些点：`config/extend.py` 常量与 `is_xxx_mode()/is_xxx_selected()`、`load_config.py` / `save_config.py` 的 `mode_mapping` 与 radio 映射、`MDCx.ui` 单选项与说明、`core/file.py` 的 `creat_folder` / `_get_folder_path` / `move_movie` 模式元组、`base/file.py::get_movie_list` 的 `include_success` 与 `.strm`、`core/scraper.py` 的断点续刮排除列表与扫描排除目录、`init.py` 提示词、软件内使用说明。
- **番号 ↔ 伴生文件关联只在 `core/file_association.py`**（`OrganizeIndex` / `build_organize_index` / `collect_media_assets`），整理、视频、补全三种模式共用；`core/organize.py` 只保留「移动计划 + 事务 + 回滚」。改归属规则只改前者，别再往 organize.py 里加。
- **补全模式的「先搬后补」顺序不能反**：先补字段/图片再搬，会把刚写好的 nfo 当成旧 nfo 再搬一次，补全结果被覆盖。已在成功输出目录内的文件走 `complete_inplace_locked`，只补内容不移动。
- **补全模式下方选项 2026-10-23 已收敛**（详见 `docs/Development.md` 3.7）：删掉「允许更新 NFO 文件」「无 NFO 按正常模式重新刮削」两项（连同 `ReadMode` 的两个枚举值，旧配置由 `_migrate_read_mode_options` 清理）；NFO 合并策略删掉 `prefer_nfo` / `preserve_existing`，只剩 3 档且默认 `fill_missing_only`——它的含义已改成「本地已有值一律保留、只补本地空字段」，旧配置由 `_migrate_nfo_merge_strategy` 映射。**仍保留的已知冲突只有「按更新模式重新整理分类」**（会把文件放到成功输出目录之外、对目录内文件无效），改它之前先确认归档口径。
- **「重新下载封面图片等文件」不存在「重下不打水印」缺陷**：下载函数每成功写出一张新图都会把对应 `*_marked` 复位为 False，`add_mark` 照常执行；给已存在图预标记 True 只是防二次水印。别按「修 bug」的思路去给它加 `READ_DOWNLOAD_AGAIN` 条件——那会让被「保留目标文件」挡住、根本没重下的旧图被重复打水印。

## 日亚 ASIN 数据库与校验方法论

- **证据强度排序**：tenhow cid 结构化映射 > EAN/JAN 条码 > 标题 NFKC 系列互含 > 图像相似度（重压缩分数带重叠，只能兜底；`_cover_similarity` 三阈值 0.82 / 0.86 / 0.70）。
- **软校验架构**：条码/EAN = hard 免验；ASIN 库命中 = 信任免验；软匹配 = v2 三步链必验（cid 旁证 → 标题门 + 真合集词一票否决（BEST/コンプリート/N時間；特典/限定版不否决）→ 图像兜底）。入库时序延迟到采信点。演员名兜底是错挂重灾区，全链必走。
- **出厂库权威合并**：同番号覆盖用户库 5 列，用户独有保留，出厂独有追加。
- **待修正 sheet 三分类**：①主表已有番号一致 → 残留直接删；②番号不同 → 主表番号反查标题比对裁决；③主表未有 → 标题法 / cid 反查裁决。批量行先按 ASIN 去重再分类。
- **列写入走显式列号映射/查表，不手数 index**（注记写进 ASIN 列污染 9 行实证）。入库后 sanity check `r[1]` 应是纯 ASIN。出厂库更新仍须用户明确确认。
- 评估库存价值先问「生产会不会走到那一步」。裁决图遍历全部候选取最高分（同番号 digital/mono 双封面并存为真）。番号规范化预检防缩位假冲突（比对 key = (系列字母, int(数字))）。批量导入 xlsx 必须走去重入口 `save_asin_to_excel`。
- cid → 番号规则 `^(\d*)([a-z]+)(\d+)([a-z]?)$` → `系列大写-{int:03d}`。tenhow cid 离线索引 `resources/userdata/tenhow_asin_cids.json`（36441 条）。
- **外部归纳数据接入先做候选顺序回归**（覆盖率会掩盖顺序污染）。防污染按「顺序影响」分级（append 兜底）而非二元弃用。DMM 路由表再生后必须先全量验证死链再推生产。
- **DMM cid 结构**：前缀映射 + 数字双态（5 位补零 digital 与 3 位 mono 同系列可并存）+ 双路径。
- DMM 图床站点下架时 CDN 不删对象，占位图 200+ 且 <4KB 已拒收。
- 日亚图 SL1500 物理无条码；老商品标题是半角片假名（NFKC 必做）；日亚 DVD 封与 DMM digital 封版本不同（比对天花板 ~0.62）。tenhow.net 图床 `images/{ASIN}.jpg` 与日亚 SL1500 同源，免代理直取。
- **ASIN 校验工程散点**：①数据治理前先 `Counter` 关键列识别导入批次残留；②openpyxl 迭代中 `delete_rows` 跳行，稳定模式 = 读出 → 去重 → 清空重写；③javbus 搜索不识别 ASIN，正查 = 番号 → 详情页标题比对；④**合并判定禁用 or 链**（`a.get(x) or b.get(x)` 短路吞判定值；`if dict1.pop(k, None) is not None or dict2.pop(k, None) is not None` 使 dict2 的 pop 副作用不执行。凡 or 链任一侧带副作用必须先求值再合并）；⑤外部 API 错误码 marker 取响应原文字面值；⑥v2 裁决链覆盖 95%+，剩余人工行给用户一句话差什么证据。
