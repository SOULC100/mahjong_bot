# mahjong_bot 后续规划：提高胡牌率与胜率

> 更新时间：2026-09-10。基线：离线模拟器 smart vs 3 随机 baseline ≈ 55% 胡牌率 / +13 平均分。
> **注意（2026-09-10）**：v21① 白板口径修正改动了七对分支倍率（见 §5），旧基线数值需重跑后再引用。

## 0. 现状与关键事实（已实证）

| 改动 | 胡牌率影响 | 结论 |
|------|-----------|------|
| 吃 chi | **+5.0pp** | 最大杠杆 |
| 碰 peng | +3.2pp | 次之 |
| 杠 gang | +0.2pp | 噪声级 |
| EV 番型抵消 1 向听 | +0.4pp | 弱正向，保留 |
| 庄家×8 位置权重 | -0.7pp | 反向，已关 |

- **核心洞察：向听数完全主导决策**。加速（吃/碰）是唯一大杠杆；番型/位置/进张质量都是弱信号。
- **真实对手是 AI，不是随机 baseline**：55% 不能直接外推为夺冠概率，只能作相对比较。
- 规则约束：只能自摸胡、禁止点炮 → 本质是纯竞速 + 番型计分，无防守（点炮）可言。

## 1. 目标：单家胜率 + 积分（结算率已不是瓶颈）

- **结算率**（非流局率）= 这局是否有人胡成。4-smart 自对弈实测已 ≥90%（60 局 0 流局，1000 局精确值见 baseline）——**已基本达标，不再是瓶颈**。
- **单家胜率**（胡牌效率）= 我方赢的占比。公平局 ~25%，要超过 25% 得比对手更快听牌/更宽听牌/更会吃碰杠。
- **积分**（对局得分）= 番型倍率 × 庄家×8。赢的时候多赢，靠爆头×2 / 财飘×4 / 七对 / 抓庄家×8。

## 2. 迭代路线图（自迭代：每项 A/B 打旧版，赢则进新基线）

**工作流**：维护一个「当前最优」策略（起点 `Smart()`）→ 每项改动生成「候选」→ 用 `sim_ab.py` A/B（候选 vs 当前最优，相同牌墙）→ 候选显著更优则成为新基线 → 下一项。看胡牌率 + 平均分两列。

### A. 提单家胜率（胡牌效率）

| # | 项 | 现状 | 动作 | 预期 |
|---|----|------|------|------|
| A1 | 吃/碰触发精细化 | 只在「向听数-1」触发 | ~~向听不变但「进张质量提升」也吃碰~~ **已试：碰 ukeire 门控三 seed 合并 +1.93pp(1.5σ 不显著)、独立 seed 复验不过 → 证伪，不晋级** | 再挤 1~3pp → **证伪** |
| A2 | 听牌宽度强化 | 已用 ting_count 做 tiebreak | 已听牌时更激进选宽听（多胡牌张），减少「等死张」 | 小 |
| A3 | 财神使用优化 | 财神仅当百搭 | 权衡「提前用财神加速」vs「留财神走爆头×2」 | 中等 |

### B. 提积分（番型 × 庄家）

| # | 项 | 现状 | 动作 | 预期 |
|---|----|------|------|------|
| B1 | 财飘(×4)决策 | `should_piao` 简单规则 | ~~优化何时飘财~~ **已试：sim 里财飘空转（引擎自动胡抢在飘之前，piao=0），证伪** | 番型×4 加成 → **证伪** |
| B2 | 爆头路线优化 | `baotou_route` 已做 | ~~精细阈值~~ **已试：300 局 4012 次出牌改 0 次，与向听数最小化冗余，证伪** | 小 → **证伪** |
| B3 | 庄家×8 策略 | 已关（-0.7pp） | 换「庄家激进抢胡、闲家博番型」的风险用法 | 不确定 |
| B4 | 真实番型倍率 | `_fan_value` 启发式 | ~~用 calc_fan 真实倍率做番型项~~ **已试：calc_fan 精确倍率系统性降胡牌率(-1.6~-4.6pp)，「赢得更大但赢得更少」，自摸竞速局净负 EV，证伪** | +0.4pp 级 → **证伪** |

### C. 锦标赛全局 —— **不做**（每场对局独立，收益线性，最大化单局期望分即最优）

| # | 项 | 原因 |
|---|----|------|
| C1 | 落后追分博番型 / 领先求稳 | 每场独立 + 总分为线性求和 → 无「位置博弈」，单局最优即全局最优 |
| C2 | M=10 并发分配、连庄 ×8 利用 | 连庄是局内机制，非跨局策略 |

### D. 防守（喂庄 / 破坏庄家）

| # | 项 | 现状 → 动作 | 预期 |
|---|----|------------|------|
| D1 | 庄家上家防守 | 出牌纯看自己向听，不避庄 | ~~避让庄家可能吃的牌~~ **已试：4-Smart 自对弈 + Oracle 上限诊断，净平均分 +0.23(≈1σ)、Oracle 上限仅 +0.17~+0.23，证伪（上家防守是纯公共品）** | 待 A/B → **证伪** |

### 已证伪 / 已关闭（不再投入）

- P0 对手建模：上帝视角 +4.3pp 但公开弃牌只 +0.5pp（信息论卡死），保留 empirical、不深挖
- 庄家×8「统一放大番型」：-0.7pp，已关

## 3. 明确不做

- 更深的 ukeire 搜索（2/3 步前瞻）：边际递减 + 慢（1 步已改变 14% 决策）。
- 点炮防守 / 弃牌安全：只能自摸、禁止点炮，无可防。**（注意区分：喂庄吃的防守见 D1，不是点炮防守）**
- 更多番型启发式：已证弱信号。

## 4. 每步验证方法

1. 所有策略改动先在 `sim_ab.py` 跑 A/B（相同牌墙、隔离开关），拿胡牌率 + 平均分。
2. 胡牌率改动看「胡牌率」列；胜率改动看「平均分」列（含番型/庄家计分）。
3. 上线前用真实 test room 跑几局烟测（`sim_run.py` + 线上 `smart_bot.py`）。
4. **番型/规则口径改动**：改 `mahjong/fan.py` 或 `sim/engine.py` 判据时，先与免认证
   `POST /portal/api/tools/fan-calc` 对拍（`python data/_probe_fancalc.py`），把权威期望值写进
   `tests/test_fan.py`，再谈胜率——口径错会让 sim 的"证伪/晋级"结论整体失真（v21 就吃过，见 §5.3 A/B）。
5. `python tests/test_smart_bot.py` 覆盖协议层回归（YCB 判胡、吃摊 ≤2、抓打圈豁免、`play()` 假 api 全链路），改动 `smart_bot.py` 后必跑。
6. 上线 bot 启动会做 `guide/version` 自检；日志出现「⚠️ 服务器接入指南 vN > 本代码已知 vM」时先核 breaking 再跑比赛。
7. **真机联调（改完必跑）**：`python create_room.py`（4 令牌）→ `python live_smoke.py`（并发 4 bot 打完一轮 + 归档 + 日志关键字扫描）
   → `python verify_live.py <归档目录>`（吃摊 ≤2 / 抓打圈圈内合规 / 番型与服务器 `fan` 及 fan-calc 三方对拍）。
   验收线：bot 日志 0 Traceback/0 线程异常/0 409/0 张数守恒异常、出牌超时率 0%、番型对拍全 OK、违规计数 0。

## 5. 2026-09 规则更新（**已到 v30**，2026-09-10 live 核对；以 GET /portal/api/guide/version 为准）

> 全量变更日志：`data/guide_version_changes.txt`（54 条 detail）；权威正文：`docs/guide-v30.txt`
> （= `GET /portal/api/guide?format=text`，取代旧的 guide-api.txt / guide-rules.txt v11 静态快照）。
> 版本自检：`smart_bot.py` 启动时比对 `KNOWN_GUIDE_VERSION = 30`（指南 §2.2 推荐做法）。
> 真机实测：v30 是本地联调当天发布的——4 个 bot 启动即打出「⚠️ 服务器接入指南 v30 > 本代码已知 v29」，
> 这正是自检要起的作用；核对 v30 详情（仅姓名字段）后把基准提到 30，重跑烟测输出变为 ok。

**免认证番型端点**：`POST /portal/api/tools/fan-calc`（每 IP 10/s），入参 `{hand:[13张], draw:"<单张>", chain:{count,piao}, base}`（**draw 是单张字符串，不是数组**），返回 `{hu, baotou, fan, detail, scores}`。对拍脚本：`data/_probe_fancalc.py`（当前 5/5 一致）；对拍结论已固化为 `tests/test_fan.py` 的 v21 用例；真机 20 局又做了三方对拍（见 §5.7）。

### 5.1 v1–v11（历史，早期已对齐）

v2(breaking) 快照移除 `allowed_actions`（客户端自研判定）+ 快照加 `seat` + chi 支持 `tiles`；v1(breaking) 碰后禁胡；v1 番数体系重构（总番=分支 × 2^链 × 4白板 × 爆头）；v3 七对允许财飘（全局最大 ×512）；v2/v11 state 轮询 5/s→8/s→**16/s**；v6 fan-calc 修 4白板链内飘出 + chain 0-6；v7(breaking) 普通锦标赛多阶段化；v9 测试房数据 API 限速 per-IP→per-房间；v10 /state 跨局边界立即回全量快照。

### 5.2 v12–v30 变更（本轮审计结果）

**影响 bot 行为的 breaking**

| 版本 | 内容 | 代码现状 |
|------|------|---------|
| v13 | 分桌实到 = 开赛时刻「已确认 ∧ 90s 内已认证请求在线」；`/api/match` 全自动入席（auto 房唯一入口）；409 `AUTO_MATCH_ONLY`/`MATCH_BUSY`/`MATCH_LIMIT_REACHED`；auto 房 finished 宽限 60s 后关停 → 玩家 API 一律 404 | 主循环 1s 轮询满足在线要求 ✅；404 优雅收场 ✅；**已补 `/api/match` 客户端** ✅ |
| v15 | `/api/match` 服务默认 M=1/Rounds=2 → **M=10/Rounds=8**；显式上限低于默认 → 永久 404 `NO_ROOM_AVAILABLE` | 本地先拒绝 `--m<10`/`--r<8` ✅；M≥8 时轮询自限提到 ≈13.3/s ✅ |
| v24 | 删除 `POST /api/users`（匿名注册）；存量匿名全局令牌 match/register → 403 `PORTAL_BINDING_REQUIRED` | 按 code 判型、给出门户取令牌提示 ✅ |
| v25 | **吃最多 2 摊服务端强制**（第 3 次 chi → 409 `INVALID_ACTION`）；吃摊数 = `melds[seat]` 中 `kind=="chi"` 组数 | `GameState.chi_meld_count()` + `choose_action` 本地自限 ✅ |
| v29 | 全服开关：关自由匹配/自建测试房后 → 403 `FEATURE_DISABLED`（含 test 房「重开下一轮」，此前是 409）；新增免认证 `GET /portal/api/features` | 入场 403 不杀进程 ✅；match 前查 `features` ✅ |

**规则/番型口径（changed）**

- **v21①** 七对「豪华组」：4 张真白板**已用于补落单**时不再额外计 1 组四张（×8→×4）；其余牌全为自然对、白板两两自配时仍计。**实测差异**：`1w×4 2w×4 5w 6w + 白×4` 旧码 ×64、权威端点 ×32。
- **v21②** 爆头：撤销「正好 4 张白板不算爆头」，4 白听任意即胡按爆头计并与「4 个白板 ×2」叠加。**实测差异**：`1w1w…4w4w5w5w + 白×4` 旧码 ×8、权威端点 ×16。
- **v26** 抓打圈**豁免方**：圈内打财神者本人可吃/碰/明杠/补杠且出牌不受限；圈内非财神出牌只对豁免方开响应窗口；快照 `god` 新增 `god_discarder_seat`（无圈 = -1）；受限 ⇔ `catch_play && god_discarder_seat != seat`。

**纯加性 / 无影响**：v12 SSE `GET /api/games/{id}/notify`（可选，不占 16/s 额度）、v14 `GET /portal/api/guide`、v16 无、v17/v20/v22/v23/v27/v28 门户-only、v18 auto 房 seats 只下昵称、v19 `round_ended` 加 `round_no/dealer`。

### 5.3 2026-09-10 代码修复（本轮已落地）

| # | 位置 | 修复 |
|---|------|------|
| A | `mahjong/fan.py::seven_pairs_branch` | v21① 白板补单不再计豪华组 |
| B | `mahjong/fan.py::any_draw_win`（新）+ `sim/engine.py::_any_draw_win` | v21② 撤 4 白板排除；爆头判据收敛为一处共享函数 |
| C | `mahjong/fan.py::ycb_can_hu`（新）+ `smart_bot.can_hu` | **致命 bug**：旧判据 `shanten_baotou(hand) != -1` 对 14 张恒真 → YCB 赛事持财神的胡全被拒、直接出牌打掉；现按「真·爆头 or 杠开」，杠开窗口由 `gang_kai_armed` 跟踪 |
| D | `mahjong/game_state.py::chi_meld_count` + `smart_bot.choose_action` | v25 吃摊 ≤2 本地自限（旧格式解析不出则交服务端 409 兜底） |
| E | `mahjong/game_state.py::is_catch_restricted` + `smart_bot.choose_action` | v26 豁免方可吃/碰/任意出牌；另放开圈内暗杠（规则只禁吃/碰/**明**杠） |
| F | `smart_bot.py::_err_code` | 一律按响应体 `{"code":...}` 判型；403（v24/v29）、404（v13 auto 房关停）、401 均不再杀进程 |
| G | `smart_bot.py::match_room/check_match_enabled` | 全局令牌走 `POST /api/match`：永久条件直接退出并提示，瞬态退避重试；auto 房按 `my_games` 过滤在途场、终态判定等线程收尾 |
| H | `smart_bot.py::check_guide_version` | 启动拉 `guide/version` 比对 `KNOWN_GUIDE_VERSION`，列出新增 breaking |

### 5.4 尚未做的规则对齐（已知缺口）

- **sim 未建模抓打圈**（`sim/engine.py` 无 `catch_play`/`god_discarder_seat`）：财飘/打财神的收益在模拟器里被高估（§2 B1「财飘证伪」的结论受此影响），需要建模后重验。
- **线上只做暗杠**：明杠需响应他人弃牌窗口、补杠需解析 `melds` 里的杠/碰类型（历史死循环风险），暂缓。
- `decision._fan_ting_expect` 调 `calc_fan` 不传 `baotou`（仅 `fan_est=real*` 路径用到，B4 已证伪）。
- 抓到 v30+ 时的应对：版本自检已就位，发现 breaking 先看 `detail` 再动代码。


### 5.5 番型 / 抓打圈口径（代码对齐基准）

**番型规则**（`mahjong/fan.py` 已对齐 v21）：
- 爆头：摸任意牌即胡（含七客=6对+财神；**v21② 起正好 4 张白板也算**——4 白听任意即胡按爆头计且与「4 个白板 ×2」叠加）
- 豪华七对 ×4 / 双豪华 ×8 / 三豪华 ×16；**v21①：4 张真白板仅在其余牌全为自然对（白板两两自配、未用于补落单）时才算 1 组四张**
- **v3：七对允许财飘**（撤销「不能财飘」）——七对形爆头听牌可弃胡打白飘，飘/杠链与七对分支连乘
- 总番公式：`分支因子 × 2^动作链 × (4白板×2) × (爆头×2)`
- 4白板：**手留 + 链内飘出的白板 = 4**（白板共4张；普通打出/杠出不算）
- 动作链：飘/杠每个动作 ×2，可组合；打出非飘非杠牌则链断
- **最大牌型 ×512** = 三豪华七对×16 × 三财飘×8 × 4白板×2 × 爆头×2

**抓打圈（v26）**：圈内**打财神者本人豁免**（可吃/碰/明杠/补杠、可任意出牌；吃碰后再打财神 = 财飘链 +1 且圈以本人重启，打别的牌 = 链断且圈解除）；其余三家仍禁吃/碰/明杠、只能打刚摸的牌，暗杠与自摸胡照常。快照 `god.god_discarder_seat`（无圈 = -1）；**受限 ⇔ `catch_play && god_discarder_seat != seat`**。

### 5.6 v2 协议要点（客户端自研动作判定）

**API 变更（v2 breaking，影响 smart_bot.py）**：
- **快照移除 `allowed_actions`**——客户端须依 `seat/phase/turn/responding_seats/drawn_tile/melds/god` 自研判定动作（phase ∈ deal|draw|response_peng|response_chi|settled|finished）
- 快照新增 `seat`（本人座位 0-3）——解决此前 my_seat 无法获取的问题
- chi 可附加 `"tiles":["1w","2w"]` 指定吃组合（缺省回退第一组）
- **碰后禁止胡牌**（v1）：碰/吃/杠后、摸牌前提交 hu 返回 409，须先等摸牌
- state 轮询限速：5/s → 8/s（v1）→ **16/s（v11）**；smart_bot 自限 ~12.5/s（M≥8 时 ≈13.3/s）
- `melds` 四家副露结构为 `{kind,tiles}`——`kind=="chi"` 组数即吃摊数（v25）

## 6. smart_bot 主循环（v7 多阶段 + v13/v24/v29 自动房，2026-09-10 更新）

`smart_bot.py main()` 原为单阶段：等 running → 打当前 active_games 一波 → 退出（普通锦标赛多阶段后只能靠 live_loop 反复拉起补位，且会漏决赛加赛）。现为常驻主循环，覆盖 v7/v10/v11/v13/v15/v24/v29：

- **令牌分流**：参赛令牌（`/api/me` 的 `tournament_id` 非空）→ 报名+到位+赛程循环；全局令牌（空）→ `POST /api/match` 入席 auto 房（v13 起 auto 房唯一入口；先在 `GET /portal/api/features` 查 v29 开关，永久条件直接退出、瞬态退避重试 30 次）。`--m/--r` 声明上限须 ≥ 服务默认 M=10/Rounds=8（v15），否则本地直接拒绝。
- **状态机**：持续轮询 `/api/me` + `/api/tournaments/{id}`，`status ∈ registering|running|stage_open|stage_done` 均不退出，仅 `finished/closed/void`（且在途场次线程已收尾）、房间 404（auto 房关停）、或出席确认 `NOT_QUALIFIED`（被淘汰）时退出。
- **running 动态扫场**：每轮扫 `active_games`（全局令牌按 `my_games` 过滤本房），未见过的 `game_id` 起新线程 `_play_safe` 并发打；决赛平局自动加赛新 `game_id` 静默出现时同样接续。
- **线程生命周期**：正常结束记入 `done` 不重拉；异常退出且对局仍 active 时重试 ≤3 次（防静默丢场）。阶段间隙/候补/加赛编排/auto 房等对手时静默轮询，600s 心跳日志一次防误判卡死。
- **stage_open 出席确认**：阶段 2+ 每阶段 POST ready 一次（`confirmed_stage` 去重）；`NOT_QUALIFIED` → 淘汰退出；`TOURNAMENT_STARTED/CLOSED` 等瞬时错误不记录、下轮重试。
- **错误码纪律（v29）**：一律按响应体 `{"code":...}` 判型（`FEATURE_DISABLED`/`PORTAL_BINDING_REQUIRED`/`AUTO_MATCH_ONLY`/`NO_ROOM_AVAILABLE`…），不按 HTTP 状态码——403/404/409 都不许杀进程。
- **兼容性**：单阶段测试房间路径不变——finished 后照常退出（live_loop 逐波拉起/归档流程不受影响）；start 前 registering 阶段与旧"等开赛"行为等价。


