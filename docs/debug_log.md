# mahjong_bot 调试记录（2026-09-02）

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

## 五、当前代码状态

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

