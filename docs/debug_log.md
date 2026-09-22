# mahjong_bot 调试记录（2026-09-02 起；§九 版本漂移审计、§十 真机联调均为 2026-09-10）

> 记录本轮真实对局调试发现的所有问题、修复、以及未解决的核心矛盾。

## 一、规则/API 变更（v2/v3）

- 快照移除 `allowed_actions`，客户端自研动作判定，依 `seat/phase/turn/responding_seats/drawn_tile/last_discard/god.catch_play`
- `phase ∈ deal|draw|response_peng|response_chi|settled|finished`
- `god` 字段从 `piao_count` 改为 `chain_count`
- `responding_seats` 是座位列表（如 `[1,2,3]`），draw 阶段为 null；`waited_seat` 仍存在
- 碰后禁止胡牌；chi 支持 tiles；state 轮询 8/s
- 七对允许财飘，最大番型 ×512

## 二、已修复的 bug（smart_bot.py）

1. **串行打牌**：`main()` 原来 `for g in active_games: play(g)` 串行，10 局只有 1 局在打、其余 9 局全超时。修复：每局一个线程并发（`threading.Thread`），每局独立 `GameState()`
2. **抓打圈死循环**：`catch_play=True` 时只能打刚摸的牌，原逻辑打了「最优牌」被 409 拒绝死循环。修复：catch_play 时只打 `drawn_tile`、跳过吃/碰/明杠
3. **杠死循环**：暗杠/明杠提交被 409 拒绝死循环。修复：直接禁用杠（+0.2pp 不值）
4. **碰后禁胡死循环**：碰/吃/杠后 `full_hand()` 变少（11 张），`shanten(11张, melds=1)==-1` 误判能胡，反复提交 hu 被拒死循环。修复：`drawn_tile` 空则不判胡
5. **hu 误判死循环**：`can_hu`（shanten==-1）罕见假阳性，被 `invalid hu` 拒绝死循环。修复：hu 被拒后 `skip_hu=True`（本次手牌回退出牌），新摸牌重置
6. **CPU 争抢超时**：`depth=True`（ukeire_depth 0.4s）× 10 线程并发 → CPU 争抢拖到 >3s → 出牌超时自动打最右（乱打）。修复：`depth=False`（ukeire_quality ~1ms）
7. **register/ready 非幂等**：房间开赛后重启崩（409 TOURNAMENT_STARTED）。修复：捕获 409
8. **409 错误不可见**：409 被吞掉看不到。修复：日志打印 409 拒绝原因

## 三、未解决的核心矛盾 ⚠️（最重要）

**已排查清楚（子 agent 报告）**：模拟器与服务器规则口径一致，99% vs 10% 的差异不是规则问题，而是线上 bot 的两个工程损耗：

1. **状态不同步**（最致命）：bot 本地手牌与服务器漂移 → 20% 手动出牌次优（含 6 次打掉财神白板）、5 次假胡（stale 状态）
2. **出牌超时**：645 次出牌 290 次（45%）是 3s 超时后服务器自动打

**本地真 bug**：`shanten()` 不校验张数，`shanten(14张标准胡, melds=1)==-1` 假阳性 → 碰/杠后 full_hand 张数错时 can_hu 假胡。

**修复清单（ROI 排序）**：
- P0 状态同步：动作后强制 seq=0 权威快照 + 张数守恒 `sum(full_hand())==14-3*melds` 校验，不符则重同步
- P0 出牌提速：一次动作一次往返、429 不 sleep(2)、长轮询增量维护状态
- P1 can_hu 加张数校验
- P1 choose_discard 的 allowed 排除财神（对齐 sim 默认）

**证据缓存**：真实 10 局 events 在 `data/fetch_t_f1ca3c4b7506/`（房间 t_f1ca3c4b7506，`/api/test-rooms/{id}/games/{batch}/events` 可重拉）

## 四、待排查方向（派子 agent）

1. 胡牌判定：模拟器 `shanten==-1`（财神当百搭）vs 服务器 fan-calc `hu` 字段，逐手牌 diff
2. 吃碰杠机制：触发条件、副露后手牌数是否一致
3. 流局条件：牌墙剩余 20 张的语义
4. 线上出牌决策 vs 模拟器决策逐一对比
5. 真实对局 bot 是否真的「没听牌」（还是听了但胡牌判定不一致）

## 五、当前代码状态（2026-09-02 当时；最新状态见 §九）

- `smart_bot.py`：动作判定重写 + 并发线程 + 各 bug 修复 + `depth=False` 快速出牌
- `mahjong/fan.py`：对齐 v3 规则（七对允许财飘、最大 ×512、4白板=手留+飘出=4）
- `sim/`：模拟器 + 对手建模(infer.py) + sim_analyze.py/sim_ab.py
- 测试全绿（6 个测试文件）

## 六、历史已实证结论（模拟器，可信度待查证）

- 吃 +5.0pp、碰 +3.2pp、杠 +0.2pp
- EV番型抵消 +0.4pp（已关）、庄家×8 -0.7pp（已关）
- 对手建模：上帝视角 +4.3pp 但公开信息只 +0.5pp（死胡同）
- 4-smart 自对弈 99% 结算（**此数字不可信，见第三节**）

## 七、P0 修复（2026-09-02 深夜，已改 smart_bot.py）

### 精确根因（逐事件统计 data/fetch_t_f1ca3c4b7506/）

| 指标 | 数值 |
|------|------|
| 事件速率 | ~1.6 ev/s/局 × 10 局 = **16 ev/s** |
| 出牌超时率 | **318/616 = 52%**（<1s 仅 97 次） |
| 全部 10 局 | **100% 流局**（`is_draw:1, winner:-1`） |
| 429 次数 | 0（不是限速拒绝，是排队延迟） |
| 409 次数 | 18（stale 竞态） |

**为什么超时**：旧代码每收到一批事件就 `GET seq=0` 拉全量快照 + 对每个碰/吃窗口 POST `pass`，10 局并发请求量 ≈ 36/s，被全局 4/s 限速压成 ~9× 积压 → 出牌 POST 排到积压后面 → 超时 → 服务器自动打刚摸的牌 → 手牌永远成不了型 → 100% 流局。

### 改动

1. **快照按需拉取**（核心）：只在「我摸牌 / 他人弃牌 / 我碰窗口走满」时 `GET seq=0`，其余事件只推进 seq 继续长轮询（`_needs_snapshot` 纯函数，9/9 用例通过）
2. **跳过 pass**：碰/吃窗口固定走满，`pass` 不 POST（省 ~550 请求）；`choose_action` 的 pass 返回 None
3. **GET/POST 分流限速**：GET 限速 0.15s（~6.7/s，v2 上限 8/s）；POST 动作不排队（时间敏感）
4. **状态同步**：动作后 `seq=0` 重建权威快照 + 张数守恒校验（`full_hand()+3*melds` 应=13/14，连续 3 次放弃）
5. 新增 `USE_DEPTH` 开关（默认 False）

### depth（二次进张）评估

实测 `ukeire_depth` vs `ukeire_quality`（14 张手牌）：
- 一向听：2.8ms vs 0.2ms（13×）
- 二向听：18ms vs 0.2ms（95×）
- 散牌：22ms vs 0.1ms（211×），完整 `discard_decision(depth=True)` 最坏 **~370ms**

10 线程并发 + GIL（28 核机器实测）：depth=True 单次决策最坏 **~1.9s**、墙钟 3.2s → 逼近 3s 出牌窗口，**线上 10 并发不安全**。

**但 depth 对胜率的影响 = 0**（已实证）：
- 80 局 A/B（同牌墙 seed=7）：`fast=True(depth OFF)` 与 `fast=False(depth ON)` 结果**完全一致**（胡 46/80=57.5%、平均分 +14.60、流局 38%）。
- 3 组代表手牌直接对比 `discard_decision`，depth 开关**打出的牌相同**。
- 原因：决策由向听数主导（`SHANTEN_COST=100`），进张只是弱 tiebreak（`UKEIRE_W=0.1`），二次进张几乎不改变最终出牌。

**结论：`USE_DEPTH=False` 是正确默认**——depth 省下 12× 延迟却零胜率收益，印证 roadmap「更深的 ukeire 搜索边际递减」。

## 八、真实房间实测（t_3dabb03bed6c）+ 根因修复

### 实测结果（子 agent 端到端，2026-09-02）

| 指标 | 修复前 t_f1ca3c4b7506 | 本次 t_3dabb03bed6c |
|---|---|---|
| 出牌超时率 | 47.6% | **81.4%**（526/646，反而恶化） |
| 胡牌 / 流局 | 0 / 10 | 2 / 8（2 局是服务器超时自动胡，**bot 全程 0 次提交 hu**） |
| 张数守恒异常（误报） | 0 | 每 bot 247~290 次 |
| 429 线程崩溃 | 0 | bot3 Thread-8 崩（429 重试耗尽） |

### 根因：`full_hand()` 双计数（game_state.py）

服务器快照的 `my_hand` **已含刚摸的牌**（draw 阶段 14 张、不是 13 张）。但 `full_hand()` 又把 `drawn_tile` 叠加一次 → 手牌恒多 1 张（日志「手牌+副露=15」）。

后果链：
1. `can_hu()` 的 `sum(hand)!=14-3*melds` 永远成立 → **bot 从不胡**（4 个日志 0 次 hu）。
2. `_hand_drift` 守恒校验每次误报（247~290 次/bot），每次做 2~3 次多余 `seq=0` 全量拉取 → 重新放大 GET 压力 → 超时反升 + GET 429 打死线程。

### 修复

- `game_state.py`：`full_hand()` 直接返回 `my_hand`（去掉 drawn 叠加）；`_recalc_remain()` 的 `visible` 同样去掉 drawn 叠加；docstring 修正为「my_hand 已含摸牌」。已验证 draw=14、响应=13。
- `smart_bot.py`：`api()` 的 GET 429 改指数退避（上限 1s）；`play()` GET 捕获 429 退避重试不崩线程；新增 `_play_safe` 包裹每局线程防静默崩溃。
- 单元测试全绿（7 个测试文件）。

### 验证（重跑 room `t_12695c311dd3`，修复后）

| 指标 | 修复前 | 旧 bug | **修复后** |
|---|---|---|---|
| 出牌超时率 | 47.6% | 81.4% | **0.2%（1/456）** |
| bot 主动 hu | 0 | 0 | **9 次 = 9 胜** |
| 张数守恒异常/bot | — | 235~290 | **0** |
| 线程崩溃 | — | 1 | **0** |
| 胡牌/流局 | 1/9 | 2/8 | **9/1** |

**结论：修复生效。** 超时率 81.4%→0.2%，bot 首次主动胡牌（9 胜），守恒误报归零、无线程崩溃。残留：1 次网络抖动超时（0.2%）+ 2 次良性 409 竞态（碰窗口已过/非己回合），已捕获无影响。

## 九、指南版本漂移审计与修复（2026-09-10）

> 后续（同日真机联调时）：服务器又发布 **v30**（他人姓名字段收口，schema 不变、bot 零影响），
> 自检立刻报出 → 已把 `KNOWN_GUIDE_VERSION` 提到 30、权威正文换成 `docs/guide-v30.txt`
> （该文件名会随版本滚动：**当前权威正文是 `docs/guide-v34.txt`**，见 §十一）。
> 本节记录的是 v11→v29 的那次漂移审计，结论仍然成立。

### 起因

手工拉 `GET /portal/api/guide/version`：**服务器 v29（updated_at 2026-09-09）**，而本仓库文档快照是
**v11（2026-09-04）**，落后 18 个版本。指南 §2.2 本来就要求 bot 启动时做版本自检——没做，于是漂移了 5 天。

抓取产物：`data/guide_version_raw.json`（版本+53 条变更）、`data/guide_version_changes.txt`（变更全文）、
`docs/guide-v29.txt`（`GET /portal/api/guide?format=text` 权威正文，取代旧的 guide-api/guide-rules v11 快照；
现已滚动为 `docs/guide-v34.txt`）。

### 发现的代码问题（严重度排序）

| # | 位置 | 问题 | 证据 |
|---|------|------|------|
| C | `smart_bot.can_hu` | YCB 判据 `shanten_baotou(hand) != -1` 对 14 张胡牌**恒真**（最小值为 0）→ 持财神的胡全被拒，YCB 赛事里 bot 直接把胡牌打掉。同一 bug 2026-09-03 已在 `sim/engine` 修过，**上线 bot 没同步** | 真·爆头 14 张 `can_hu(YCB=True) → False`；`can_hu(YCB=False) → True` |
| A | `mahjong/fan.py::seven_pairs_branch` | `laizi == 4` 无条件 +1 组四张 → 七对豪华组多算一层（v21①） | `1w×4 2w×4 5w 6w + 白×4`：本码 ×64 / fan-calc ×32 |
| B | `sim/engine.py::_any_draw_win`、`fan.is_baotou` | 排除「正好 4 张白板」（v21② 已撤销） | `1w1w2w2w3w3w4w4w5w5w + 白×4`：本码 ×8 / fan-calc ×16 |
| D | `smart_bot` | 未实现 v25「吃最多 2 摊」本地自限（`should_chi` 只拿到副露总摊数）→ 第 3 次 chi 吃 409，在 1s 窗口内反复提交空转 | fan-calc/指南 §2.1：吃摊数 = `melds[seat]` 中 `kind=="chi"` 组数 |
| E | `smart_bot` | 未实现 v26 抓打圈豁免：`catch_play` 一律不碰不吃、只能打刚摸的牌 → 打财神者本人白丢吃碰/自由出牌/续飘 | 指南：受限 ⇔ `catch_play && god_discarder_seat != seat` |
| F | `smart_bot` | `register/ready` 只吞 409，403 直接 `raise` 杀进程；v29 把 test 房重开由 409 改成 403 → 判型必须用 `code` | v24 `PORTAL_BINDING_REQUIRED`、v29 `FEATURE_DISABLED` |
| G | 无 | 缺 `/api/match` 客户端 → v13 起 auto 房直连 register/ready 恒 409，机器人进不了自由匹配 | 指南：auto 房唯一入口 `POST /api/match` |
| H | 无 | 无启动版本自检（本轮漂移的直接原因） | 指南 §2.2 |

**核对无影响**：v7 多阶段主循环（已落地）、v13「开赛 90s 内需已认证请求」（主循环 1s 轮询天然满足）、
v10 跨局快照、v11 16/s、v9 per-room 限速、v12 SSE / v14 guide / v18 seats / v19 `round_no,dealer`（纯加性）、
v17/v20/v22/v23/v27/v28（门户-only）。

### 修复与验证（2026-09-10）

- A/B：`fan.py` 口径修正 + 新增 `any_draw_win` / `ycb_can_hu` 共享判据，`engine._any_draw_win` 改为委托。
- C：`can_hu` 走 `ycb_can_hu`；杠开窗口用 `gang_kai_armed` 跟踪（不断言"摸到的牌变了"——杠后补牌可能与杠前同值）。
- D/E：`GameState.chi_meld_count()`（非 `{kind,tiles}` 旧格式返回 None → 交服务端 409 兜底）、`GameState.is_catch_restricted()`（缺 `god_discarder_seat` 时退化为旧"一律受限"）；另放开圈内**暗杠**（规则只禁吃/碰/**明**杠）。
- F：`_err_code()` 按响应体 `{"code":...}` 判型（实测 `{"code":"INVALID_ACTION","message":...}`）；403/404/401 分支各自收场，不杀进程。
- G/H：全局令牌走 `POST /api/match`（先查 `GET /portal/api/features`，永久条件退出、瞬态退避 30 次；`--m/--r` 低于服务默认直接拒绝）；启动拉 `guide/version` 比对 `KNOWN_GUIDE_VERSION=29`。

**验证**：`data/_probe_fancalc.py` 对拍 fan-calc **5/5 一致**（修复前 2 例 DIFF）；
`tests/test_fan.py` 新增 v21 用例（期望值取权威端点）、`tests/test_smart_bot.py` 新增协议层回归
（YCB 真爆头必须提交 hu、非爆头不得提交、吃摊门禁、抓打圈豁免、`play()` 假 api 全链路）；
全部测试 PASS，`test_sim.py` 300 局不变量 PASS。

### 仍未做

- **sim 未建模抓打圈**：`sim/engine.py` 无 `catch_play`/`god_discarder_seat`，财飘收益被高估（B1 结论需重验）。
- 线上仍只做暗杠（明杠/补杠待做）。
- `decision._fan_ting_expect` 调 `calc_fan` 不传 `baotou`（仅 `fan_est=real*` 用到，B4 已证伪）。
- 番型口径改动后基线未重跑（旧 A/B 数值引用需谨慎）。
- 遗留脚本：`bot.py`/`debug_bot.py` 是 allowed_actions 时代产物（v2+ 必失效）；`wait_room.py` 等的 `"全部完成"` 只有 `bot.py` 打印。

## 十、真机联调（2026-09-10）：跑通、零报错、20 局全量校验

### 环境与起局

- 门户会话过期（`data/portal_session.json` 的 `majiang_sid` 已失效 → `401 session expired`），改走
  `~/.config/netease_auth` 凭据 + `create_room.py`（Playwright 自动登录）→ 新建测试房 **`t_c84f53481cbf`**，
  4 个令牌落 `data/tokens.txt`。
- 房规：`M=10 / Rounds=1 / BaseScore=1 / YouCaiBiKao=false / Kind=test / TimeoutMin=30`。
- 连打 2 轮（各 10 局），编排与校验脚本：`live_smoke.py`（并发 4 bot + 归档 + 日志扫描）、
  `verify_live.py`（事件回放校验）、`data/_stats_by_user.py`（按 user 汇总）。

### 结果：能不能跑通 —— 能，且零报错

| 维度 | 结果 |
|------|------|
| 进程 | 4 bot × 2 轮全部 exit=0 |
| 日志关键字 | `Traceback`=0、`线程异常`=0、`action 错误`=0、`409 拒绝`=0、`429`=0、`张数守恒异常`=0（8 个日志文件全清） |
| 出牌超时 | **0.0%**（第 1 轮 439 出牌、第 2 轮 396 出牌，`timeout.discard` 均为 0） |
| 窗口走满 | `timeout.response` 1682 + 1513（碰/吃窗口固定走满，bot 不 POST pass，属预期） |
| 结算 | 20 局 19 胡 1 流局 |
| 番型对拍 | `calc_fan` vs 服务器 `round_ended.data.fan` **19/19 一致**；同手牌再打免认证 `fan-calc` **19/19 一致**；分布 = 18 平胡 + 1 七对 |
| v25 吃摊 ≤2 | 0 越限；3 局出现某座位吃满 2 摊（本地门禁被真实触发过） |
| v26 抓打圈 | 0 违规（圈内无非豁免方吃/碰/明杠；圈内非豁免方出牌 = 刚摸牌） |
| F 错误码容忍 | 真机日志 `进场 register/ready 被拒（409 TOURNAMENT_STARTED），按最新 status 继续`——不崩 |
| H 版本自检 | 第 1 轮打出 `⚠️ 服务器接入指南 v30 > 本代码已知 v29`（当天服务器又发了 v30）；核对后基准升 30，第 2 轮输出 `ok: 服务器 v30 ≤ 本代码已知 v30` |
| 轮询自限 | `POLL_INTERVAL = 0.075s（≈13.3/s，赛事 M=10）`，全程 0 次 429 |

### 联调中发现并修掉的两个问题

1. **取证脚本跨轮覆盖（真机复现）**：房间累计 20 条局列表，`fetch_room_stats.py` 按 `batch` 命名存档 →
   第 2 轮把第 1 轮的 `events_0..9.json` 全部覆盖（`games.json` 20 条、实际落盘 10 个文件，且全是 `r2_*`）；
   免认证数据端点按 batch 也只回**当前轮**，第 1 轮事后不可得。
   修复：文件名改 `events_r{round}_b{batch}.json`；拉到的 `game_id` 与局列表期望值不符则跳过并计入
   `summary.json` 的 `unavailable_old_rounds`；汇总行区分「房间场次总数 / 本次可统计」。
2. **座位与庄家口径**：`seats[]` 是座位序数组，实测每局重洗（10 局里 9 局与首局不同），而 `dealer` 恒为 seat 0
   ——庄家身份在用户间轮转。**跨座位聚合比分是错的**（第 1 轮按 seat 看 seat0 = −24、seat1 = +19，纯属混淆），
   必须按 `user_id` 汇总（第 1 轮按 user：青龙 +76 / 白虎 −49 / 朱雀 +1 / 玄武 −28）。
   另：`features` 免认证端点同样有 5/s 限速，并发探测会 429（代码按"查不到当开启"兜底）。

### 样本覆盖不足（未在真机覆盖的路径）

20 局里没有 `catch_play=true`（无人打财神）、没有杠、没有爆头/财飘/4 白板大番型，因此：

- v21 的大番分支（4 白板豪华组、4 白爆头）、v26 豁免方吃碰续飘、`gang_kai_armed` 杠开豁免
  **只在单元测试与 fan-calc 对拍层面验证**，真机未触达。
- 要真机覆盖需更多局（大番型概率低）或构造房规（提高 Rounds / 专门脚本逼出财飘）。
- 另记一条 micro-gap：庄家首巡第 14 张无 `tile_drawn`，`can_hu` 要求"有摸牌才判胡" → **天胡不会被判胡**
  （概率极低；历史上该门禁是挡「碰后假胡」死循环的，动它需先能区分两种 14 张无 drawn 情形）。

## 十一、v31–v34 复核 + 多局房真机验证（2026-09-18）

### 版本

`GET /portal/api/guide/version` → **v34（updated_at 2026-09-14）**，本地基准此前是 v30 → 中间 4 个版本：

| 版本 | 类型 | 要点 | 代码结论 |
|------|------|------|---------|
| v31 | changed | 局间固定停 5 秒：窗口内 `phase="settled"`、`round_no` 仍是上一局、任意 seq 都拿到上一局终态 | 见下（新增 settled 处理 + 2 条单测） |
| v32 | changed | **杠爆判定修正**：摸牌后杠的爆头状态改在杠动作时重算（修前被静默判成普通杠开 ×2，应为 ×4） | **零改动**：`fan.py` 的「爆头×2 × 杠开×2」本就是 ×4；此修复让**我们的自研校验（`verify_live.py`）与服务器终于一致** |
| v33 | changed | **杠后补牌停弃胡决策窗口**：补牌与普通摸牌同构（`phase=draw`、`drawn_tile=补牌`、事件带 `gang_replenish:true`），可 hu / 续杠 / **弃胡打财神续飘**，超时自动胡兜底 | **零改动**（指南⑤：主动判胡的 bot 零改动）：`gang_kai_armed` 置位 → 补牌 `tile_drawn(me)` 触发快照 → 以 `gang_kai=True` 判胡。**v33 把"弃胡续飘"写进补牌窗口 → 我们的 E1 适用面扩大** |
| v34 | added | 门户今日榜加 `last`（垫底）行，完全匿名 | 门户-only，零影响 |

### 代码检查结果

1. **`KNOWN_GUIDE_VERSION` 30 → 34**（真机日志确认：`接入指南版本自检 ok: 服务器 v34 ≤ 本代码已知 v34`）。
2. **`play()` 新增 settled 处理**（v31）：识别 `phase="settled"` → 记一次日志、清 `gang_kai_armed`（防跨局误判杠开）、继续用当前 seq 轮询等下一局；
   单测新增两条（settled 不发动作 / settled 后能继续处理下一局）。
3. **`verify_live.py` 支持杠局**（呼应 v32）：此前杠局因"全手 15 张"被整体跳过；现按「每个 4 张副露折算 3 张」归一化到 14 张等效，杠爆局也能做番型对拍。
4. **守恒公式复核（结论：无需改）**：曾怀疑「暗杠后 `sum(hand)+3*melds` 少 1」会误报 `张数守恒异常`，
   推导后确认**杠的 4 张恰好被杠后补牌抵消**（杠后 concealed 11 + 3×1 melds = 14 ✓），现有校验正确。
5. **`create_room.py` 改为走门户 API**（`POST /portal/api/test-rooms`，蛇形 body）：旧实现靠抓 DOM 里的 64-hex，
   实测会因渲染时序偶发"提取令牌失败"（房间其实已建好）；API 版直接从响应 JSON 取 `room_id` + 4 `tokens`，
   并支持 `--m/--r/--base/--ycb` 指定房规（**Rounds≥2 是验证 v31 局间停顿与连庄的必要条件**）。
6. **两个"服务端先于文档"的发现**：
   - `GET /portal/api/features` 现在返回 **4 个** 开关：`{match_enabled, replay_enabled, substitute_enabled, test_rooms_enabled}`，
     后两个键在 v34 指南正文与变更日志里**都查不到**（`features` 字样在正文出现 0 次）。我们只读 `match_enabled`（用途正确），其余**记录待观察**。
   - `POST /portal/api/test-rooms` 有配额：**409 `QUOTA_EXCEEDED`（an active test room already exists）**，v34 错误码表亦未收录。

### 真机验证（v34）

- 第 3 轮（新房 `t_6e00736f97c5`，M=10/Rounds=1）：4 bot 全 exit=0、10 局 10 胡、日志零错误、
  `verify_live.py` 番型 **10/10 一致**（`calc_fan` 与 `fan-calc` 双对拍）、0 违规。
- 第 4 轮（`t_39891e80399a`，**M=4 / 每场 3 局**，共 12 局）：
  - 4 bot 全 exit=0、日志零错误、0 出牌超时；12 局 12 胡、番型对拍 **12/12 一致**、0 违规。
  - **v31 局间停顿实测复现**：日志出现 `phase=settled（局间 5s 停顿）round_no=N，等待下一局`（4 个 bot 均有），
    等待后正常接下一局（单局房 Rounds=1 测不到，这也是把 `create_room.py` 改成支持 `--r` 的原因）。
  - **豪华七对 ×4 真机验证**：`4t4t5t5t6t6t7t7t4b4b4b6b6b` 摸 `4b` → `4b` 成组四张 → 服务器 `detail=['豪华七对×1']`/`fan=4`，
    `calc_fan`=4、`fan-calc`=4 三方一致 —— 直接验证了 v21① 修正后的七对分支因子。
  - **庄家轮转规则确认**：`rounds[].dealer` 显示「赢家成为下一局庄家、庄家自己赢则续坐」
    （`dealer0→winner2` ⇒ 下局 dealer=2；`dealer2→winner2` ⇒ 下局仍 dealer=2；`dealer0` 连赢两局则连续当庄）。
    → `sim` 未建模这条（引擎 dealer 固定），已记入 `rules-strategy.md` 的保真度清单，E6 前要补。
- 累计 4 轮 42 局：41 胡 1 流局、番型对拍 41/41 一致、违规 0。


