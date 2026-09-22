# 当前策略全貌（重点：出牌决策的每一个细节）

> 口径：**线上 `smart_bot.py` = 离线冠军 `opt/champion.json`**（本轮已对齐，见 §7）。
> 更新时间 2026-09-25（含 R15「吃多解先消化窄搭子」上线）。所有"实测"数字都来自
> 冻结基准 1000 局 + 独立确认集（`docs/eval-rounds.md` / `data/eval/ledger.tsv`）。

---

## 0. 规则前提（策略形态由它决定）

| 规则 | 对策略的后果 |
|---|---|
| **只能自摸**，没有放炮/点炮 | 防守/喂牌/安全牌**无意义**（唯一例外是庄家吃牌，但那是收益问题不是安全问题） |
| 吃摊 **≤ 2**（v25，服务端强制） | 吃是**有限资源**；满 2 摊后本地自限（不再提交，避免 409） |
| **财神 = 白板**，可代替任意牌 | 财神是"半个胡"；爆头（财神做将、任意摸都胡）×2、财飘可连乘 |
| 番型**乘法** | 平胡×1 / 七对×2 / 豪华七对×4（双豪华×8、三豪华×16）/ 每杠×2 / 每飘×2 / 4 白×2 / **爆头×2** / 庄家×8 |
| 抓打圈（v26） | 别人打财神后的「圈」内，**非打财神者**不能吃/碰/明杠/补杠，且只能打刚摸的那张 |
| 最后 10 墩禁杠 | `wall_remaining > 20` 才考虑任何杠 |
| 庄家赢分 ×8 | 坐庄时"抢速度"比"做大番"更值（`dealer_speed`） |

**一句话策略**：**速度优先**（向听数为纲，进张质量为目），鸣牌是主轴；
番型只当"能抵消 1 向听时的加分项"；财神相关的爆头/财飘是唯一的"故意放慢"理由。

---

## 1. 出牌决策看到的世界（输入）

| 输入 | 来源 | 关键口径 |
|---|---|---|
| `hand` | 服务器快照 `my_hand`（draw 阶段已含刚摸的牌） | 14 张（或 14−3×副露） |
| `melds` | `melds[seat]` 的摊数 | 碰/吃/杠各算 1 个面子 |
| `remain` | `game_state._recalc_remain()` | **贝叶斯期望**：`未见张数 × 牌墙/(牌墙+对手暗手)` —— 用于**相对比较**（进张质量、听口宽度） |
| `raw_unseen` | 同上新增 | **未见的原始张数**（4 − 可见，不缩放）——用于**绝对张数**判据（吃门控的"搭子剩余进张"） |
| `discards` / `melds[*]` | 快照 | 4 家弃牌与副露（算牌/喂庄风险用） |
| `wall_remaining` / `hand_counts` | 快照 | 牌墙剩余、4 家暗手张数 |
| `god` | 快照 `god` | `baotou`（我是否爆头态）、`catch_play` + `god_discarder_seat`（抓打圈）、`chain_count`（财飘链） |
| `cur_dealer` | 客户端维护 | 首局 0；`round_ended` 后 = 赢家；流局 = 连庄（用于 `is_dealer` → 抢速/弃胡判据） |
| `allowed` | 本地构造（线上） | 手里所有牌（**含财神**）；被 409 拒过后剔除白 |

---

## 2. 一次动作的判定顺序（三个窗口）

**draw 窗口（轮到我摸牌/待弃）**——从上到下第一个成立的执行：

1. **能胡就胡**：`can_hu(hand, melds, ycb, drawn, gang_kai)`
   = 张数正确 + `shanten == -1` +（YCB 时）`ycb_can_hu`（无财神 / 杠开 / 真爆头）。
2. **弃胡打财飘**（`DECLINE_HU`）：能胡 **且** 打白后仍爆头（`piao_after_discard`）**且**
   `should_decline_hu` 的 EV 成立 **且** 未超连飘上限（3）→ 提交 `discard 白`。
   EV 判据：`q* = (f0+c)/(2f0+c)`，取 `q=0.75`；闲家 f0=2 → q*=0.70 < 0.75 → **飘**；庄家 → q*=0.83 → **不飘**。
3. **抓打圈受限**：只能打刚摸的那张（`restricted`）→ 直接返回。
4. **【规则②】残局杠（`GANG_DRAW_WALL=28`）**：`wall_remaining < 28` **且自己未听牌** → 有杠就杠
   （暗杠 4 张优先，其次补杠）。**必须排在下面第 5 步之前**：`angang_tile` 的"听牌才杠"门控正是这条要绕开的东西。
   依据：弱场 3000 局 **+0.527 分/局、+2.07pp 胜率（z=6.16）**；强场逐位相同（0 次触发，代价为 0）。
5. **暗杠**（`wall_remaining>20` 且是真摸牌回合）：`angang_tile()` = 摸前**已听牌**（`shanten(pre)==0`）且
   杠后**仍听**（`shanten(手−4张, melds+1) ≤ 0`）→ 杠（保护七对/豪华七对：靠 quad 听牌的会被自动拦下）。
6. **补杠**（`BUGANG`，`wall>20`，且 **`GANG_TENPAI_ONLY` 时要求"杠完就听牌"**）：已碰 + 手里第 4 张 → 杠。
7. **财飘**：`should_piao(hand)`（4 面子 + 2 财神）→ 打白。
8. **出牌**：`choose_discard(...)`（§3 全部细节）。

**peng 窗口（别人打牌，我可以碰/明杠）**：
1. **明杠优先于碰**（与引擎一致）：`MINGGANG` 且 !`skip_gang` 且 牌≠财神 且 手里 ≥3 张 且 `wall>20` 且 非抓打圈受限
   **且（`GANG_TENPAI_ONLY` 时）杠完就听牌** → 杠。
   依据（2026-09-25 R16 重测，**推翻** R7 旧结论）：加"杠完就听牌"门控 = **+0.230 分/局（z=2.40，池化 3000 局）**、
   场均番 1.104→**1.173**；86% 的明杠原本都是"离听牌还很远就锁面子"。
2. **碰**：`should_peng(hand13, tile, melds, ukeire_gate=True, remain, gate_max_shanten=1)` →
   碰后（副露+打 1 张）**向听下降**，或 **向听不变但进张质量提升**（且前置向听 ≤1）。
3. 否则 pass（不提交，让服务端窗口自然走满，省请求）。

**chi 窗口（上家打牌，我可以吃）**：
1. **吃摊硬门禁**：`chi_meld_count() ≥ 2` → 不吃（v25；解析不出则交给服务端 409 兜底）。
2. **抓打圈受限** → 不吃。
3. **吃**：`should_chi(hand13, tile, melds, ukeire_gate=True, remain, prefer_narrow=True)`
   - 吃后**向听下降** → 吃；
   - 否则**向听不变但进张质量提升** → 吃；
   - 多个吃法都合格时，按 **吃后向听 → 搭子剩余进张（少者优先）→ 吃后进张质量** 排序取第一（R15 晋级）。

**毒丸（防死循环）**：`skip_hu` / `skip_piao` / `skip_gang` —— 对应动作被服务端拒绝（409）后，
在**当前手牌状态**内不再重复提交该动作。

---

## 3. 出牌决策的完整细节（核心）

### 3.1 候选池 `pool`

- **线上**：`allowed` = 手里所有牌（含财神）；`skip_piao` 时剔除白。
- **sim**：`allowed=None` → 手牌里的**非财神**牌（`allow_laizi_discard=True` 时复刻线上口径）；
  YCB 且手里有财神时补上白（"逃回平胡"这条路）。
- 兜底：若全是财神，则候选 = 财神。

### 3.2 第一优先级：财飘直接打白（在打分之前）

```
if piao_enabled and piao_after_discard(hand, melds) and (允许打白):
        return 白
```
`piao_after_discard` = 手里 ≥2 张财神，且**打掉 1 张后仍"任意摸都胡"**（`any_draw_win`）——
这是规则口径的合法前提（否则打出后链断、白丢一个胡）。涵盖 ①4 面子+2 财神 ②七对形（七客）。

### 3.3 第二优先级：爆头路线（向听口径切换）

非 YCB 且手里有财神时：
```
s_std = shanten(hand, melds)            # 标准/七对
s_bao = shanten_baotou(hand, melds)     # 财神做将（爆头 ×2）
baotou_route = (s_bao <= s_std + baotou_slack) and (s_bao <= baotou_max_shanten)
```
- `baotou_slack=1`、`baotou_max_shanten=1`（冠军值）→ **只在爆头路线最多慢 1 向听、且已到 ≤1 向听时**才切过去。
- 一旦 `baotou_route=True`，**所有候选的向听数都用 `shanten_baotou` 计**（即"财神留着做将"的世界），
  并且进张项改用 `ukeire_quality`（`ukeire_depth` 在爆头形态下无意义）。

### 3.4 YCB 分支（当前主场**关闭**：赛事按 YouCaiBiKao=off 准备）

`youcai_bikao=True` 且手里有财神时，每个候选的向听改为：
- **打出最后一张财神**（逃回平胡）→ `shanten(打后, melds) + ycb_escape_gap`，冠军 `ycb_escape_gap=1`
  （虚向听 +1 = 更难逃、更坚持追爆头；该参数**只在 YCB 下参与决策**，非 YCB 完全惰性）；
- **留财神** → `knock_shanten(打后, melds)` = min(标准爆头, 七客=七对+财神单吊)。
- 实测：YCB 场 `ycb_escape_gap=1` 值 **+1.57 分/局（z=8.5）**，是本项目最大单项，但**当前不计入预期收益**。

### 3.5 每个候选的向听数 `s_map[d]`

```
c = hand − d
s_map[d] = shanten_baotou(c)  if baotou_route      # §3.3
         = shanten(c)         otherwise            # 标准/七对取 min（shanten 内部已取）
# knock=True 时再加一条：s_map[d] = min(s_map[d], knock_shanten(c))  ← 冠军 False（已证惰性）
```

### 3.6 打分范围 `bound`（性能与"番型抵消向听"的边界）

```
bound = min_s + 1     # fan_override=True（线上恒开）
      = min_s         # fan_override=False（旧行为）
```
只有 `s_map[d] ≤ bound` 的候选才算进张项与番型项。**这就是"番型最多抵消 1 向听"的实现**：
差 2 向听以上的候选直接出局。

### 3.7 进张项（ukeire）——按形态四选一

| 条件 | 口径 | 含义 |
|---|---|---|
| `s_map[d] == 0`（已听牌） | `ting_count(c)` | **听口宽度**：能胡的牌按 `remain` 加权的张数（愚形 ~3、两面 ~8） |
| `wait_width == "full"` | `ukeire_wait_width` | 进张 × **落地听口宽度**的解析式（冠军未开） |
| `baotou_route` 或 `depth=False` | `ukeire_quality` | `Σ remain[t] × (1 + max(0, 3 − s2))`，只统计**降低向听**的进张 t |
| 否则 | `ukeire_depth` | 二次进张（一步前瞻）——**线上/冠军均未使用**（`USE_DEPTH=False`、`fast=True`） |

（`s2` = 摸到进张 t 后的向听数；权重 `1+max(0,3−s2)` 让"摸到即听/即胡"的进张更值钱。）

### 3.8 番型项 `fan`

冠军 `fan_est="heuristic"` → `_fan_value(打后的 13 张, melds, melds_aware=False)`：

```
fan = 财神张数 × 3
    + (对子数 ≥ 4 ? 对子数 : 0)      # 七对路线潜力（melds_aware=False 时即使有副露也给）
    + 刻子数 × 1                     # 杠潜力
```
其他可选口径（未启用）：`real`（听牌时用 `calc_fan` 试算真实期望倍率）、`real_k1`、`real_ting`。

### 3.9 庄家倍数 `dealer_mult`

```
dealer      = is_dealer and (dealer_aware or piao_dealer_only or dealer_policy=="bigfan")
dealer_mult = 8 if dealer else 1
```
- **冠军 `dealer_aware=false`** → 打分里 `dealer_mult` **恒为 1**（庄家×8 不参与出牌打分）。
- 坐庄的影响走 `dealer_speed`（`dealer_policy="aggr"`）这条独立通道，它**改三个参数**：

| `dealer_speed=True` 时 | 效果 |
|---|---|
| `baotou_slack → 0`、`baotou_max_shanten → 0` | 当庄**不为爆头牺牲任何向听**（宝押胡牌率，不押 ×2） |
| `gang_keep_pen → 0` | 取消"杠子保留分"，不为未来的杠压牌速 |
| （另在鸣牌侧）`chi/peng` 的 ukeire 门控**对庄家放宽**（`gate = 门控 or 当庄抢速`） | 当庄更积极地吃碰抢速度 |

闲家完全不触发 → 与基线逐决策一致。

### 3.10 惩罚项

| 项 | 当前状态 | 公式 |
|---|---|---|
| 杠子保留分 `protect_gang` | **开**（`GANG_KEEP_PEN=10`） | 若 `hand[d] ≥ 4` → `score += 10`（同向听内重排，绝不越过向听界） |
| 喂庄防守 `defend_dealer` | **关**（冠军 `false`） | `_d1_penalty_vector`：按庄家弃牌猜"可能在被吃的花色/牌"，`suit` 或 `pair` 两种模式，罚分 40 |

### 3.11 打分与并列

```
score(d) = s_map[d] × SHANTEN_COST(100)
         − ukeire_val × UKEIRE_W(0.1)
         − fan × FAN_W(5) × god_fan_boost(1) × dealer_mult(1)
         + 杠子保留分(0/10)  + 喂庄罚分(0)
取 score 最小者。
```
**量纲**（为什么这样取值）：
- 1 向听 = 100 = 1 个"单位"；进张项一般几十~几百 ×0.1 → 十几~几十 → **只能在同向听内翻盘**（这是设计意图）；
- 1 张财神 ≈ 3 fan ≈ 15 分（闲家）→ 远小于 100 ⇒ **闲家不会为财神牺牲向听**；
- 庄家若开 `dealer_aware`，3×5×8 = 120 > 100 ⇒ 会为财神牺牲 1 向听（**当前关闭**）。

**并列处理**：冠军 `wait_width=None`（关）→ 分数精确并列时取**遍历顺序里的第一个**。
线上候选池是 `set`（顺序由哈希决定：确定、但**不保证**按牌值升序），sim 是 `unique_tiles`（升序）
→ 精确并列时线上/sim 理论上可能选不同的那张（影响极小：分数含 `ukeire×0.1` 浮点项，精确并列罕见）。
`wait_width="tiebreak"` 版本（并列时按"进张×落地听口"破平）实测 **+0.055（z=1.91，未晋级）**，冠军未开。

### 3.12 一个真实算例（可复现：`python data/_discard_trace.py`）

手牌 14 张 `2w4w4w5w6w2t1b3b4b东西西中白` = `2万4万4万5万6万2条1筒3筒4筒东西西中白`（`melds=0`，标准向听 2、爆头向听 3）：

| 打 | 打后向听 | 进张口径 | 进张值 | 番型 | 杠保留 | 得分 |
|---|---:|---|---:|---:|---:|---:|
| **东** | 2 | ukeire_quality | 144.0 | 3 | 0 | **170.6** ← 选中 |
| 中 | 2 | ukeire_quality | 144.0 | 3 | 0 | 170.6 |
| 1筒 | 2 | ukeire_quality | 114.0 | 3 | 0 | 173.6 |
| 2条 | 2 | ukeire_quality | 108.0 | 3 | 0 | 174.2 |
| 4筒 | 2 | ukeire_quality | 102.0 | 3 | 0 | 174.8 |
| 2万 | 3 | ukeire_quality | 132.0 | 3 | 0 | 271.8 |
| … | 3 | … | … | 3 | 0 | 271.8~274.8 |
| 白 | 3 | ukeire_quality | 102.0 | **0** | 0 | 289.8 |

读法：①`东/中` 得分并列 170.6（孤张字牌，打哪张一样）→ 按遍历顺序取 `东`；
②凡 `s=3` 的候选都被 `+100` 压下去，**进张再好也翻不过来**（这就是"速度优先"）；
③打白那一行 `番型=0`：财神打掉后爆头潜力归零，双重变差。

### 3.13 边际进张：**单牌靠张不能相加**（2026-09-22，真机复盘带出的反直觉点）

真机 room `a_5b83c31e82d3` 第 3 局第 5 巡（打 `2w` 而非 `9t`）常被质疑：
「`2w` 能配 `1w-4w`、`6w` 能配 `4w-8w`，靠张明明比边张 `9t`（只能配 `7t/8t/9t`）多，为什么先打 `2w`？」

单张看确实如此，但判据不是单牌靠张、而是**打掉它之后整手牌还剩多少进张**——差别在于**靠张会重叠**：

| 牌 | 自己的靠张（未见） | 与手里别的牌重叠 | **独占进张** |
|---|---|---|---|
| `2w` | `1w`3 `2w`3 `3w`2 `4w`4 = 12 张 | `4w`（`4w6w` 也是嵌张，6w 一样要它）= 4 张 | **8 张**（`1w/2w/3w`） |
| `9t` | `7t`4 `8t`3 `9t`3 = 10 张 | 无（手里条子是 `2344t`，只管 `1t-6t`） | **10 张** |
| `6w` | `4w`4 `5w`4 `6w`2 `7w`3 `8w`2 = 15 张 | `4w`（如上） | **11 张**（`5w/6w/7w/8w`） |

→ 留牌价值 **`6w`(11) > `9t`(10) > `2w`(8)**：最不值钱的恰恰是中张 `2w`，它的靠张被 `6w` 抢走了一张（`4w`）。
实算：打 `2w` 余 72 张进张、打 `9t` 余 70 张、打 `6w` 余 69 张 —— 差的 2 张正是 `10（条 7t/8t/9t）− 8（万 1w/2w/3w）`。
第 6 巡（摸 `4b` 后）`6w` 的独占掉到 2 张（`6w×2`，它的 `5w/7w/8w` 已被别家打出消耗），于是那一巡才打 `6w`（15 张 vs 打 `9t` 的 14 张）。

**一般结论**：越靠中间、彼此越近的孤张，靠张重叠越大（`2w` 与 `6w` 抢 `4w`）；**边张的独占性反而更"纯"**。
把每张牌的靠张数直接相加（12 + 15）会重复计算重叠部分 —— 这正是引擎按「打掉后整手牌的进张」而不是「单牌靠张」打分的原因。

复现：`python data/_marginal.py a_5b83c31e82d3 0 3 5 2w 9t 6w`（两两列出独占进张）、
`python why_discard.py a_5b83c31e82d3 0 3 5`（全部候选排序）。

---

## 4. 当前参数总表（线上 = 冠军）

### 4.1 `smart_bot.py` 常量

| 常量 | 值 | 作用 |
|---|---|---|
| `USE_DEPTH` | `False` | 用 `ukeire_quality`（快，~1ms）而非二次进张（旧版对听牌候选恒 0 且 ~6.9s） |
| `DECLINE_HU` / `DECLINE_Q` / `DECLINE_MAX_CHAIN` | `True` / `0.75` / `3` | 弃胡打财飘的开关 / 存活率估计 / 连飘上限 |
| `CLAIM_UKEIRE_GATE` / `CLAIM_GATE_MAX_SHANTEN` | `True` / `1` | 鸣牌 ukeire 门控（+0.33 分/局，3000 局 z=3.42） |
| `CHI_PREFER_NARROW` | `True` | 吃多解时先消化"补不上"的搭子（+0.265 分/局，3000 局 z=2.66） |
| `MINGGANG` / `BUGANG` | `True` / `True` | 明杠/补杠开关 |
| `GANG_TENPAI_ONLY` | `True` | **只在"杠完就听牌"（能杠开 ×2）时才明杠/补杠**（R16：+0.230 分/局，z=2.40，3000 局） |
| `GANG_DRAW_WALL` | `28` | **残局杠**：墙<28 且未听牌 → 照杠（弱场 +0.527、z=6.16；强场 0 次触发、代价 0） |
| `DEFEND_DEALER` / `DEFEND_PEN` / `DEFEND_MODE` | `True` / `40.0` / `"suit"` | **防庄（D1）**：只在"我是庄家上家且庄家吃未满 2 摊"时，对危险牌加罚分（同向听内重排）。三套种子池化 5000 局 **+0.180 分/局、z=2.18**（场均番 1.109→1.179） |
| `DEALER_POLICY` | `"aggr"` | 坐庄抢速（+0.29 分/局） |
| `YCB_ESCAPE_GAP` | `1` | YCB 逃回门限（**仅 YCB 场生效**，当前不计入预期） |
| `EDGE_W` | `0.0`（**关**） | **边张优先偏置**（用户假设：中张靠张多 → 先打 9t 这种边张）。>0 时同向听内给边张减分（1/9=3、2/8=2、3/7=1，约 0.1 分 ≈ 1 张进张）。**与现行「整手牌进张」判据可能相反**（靠张重叠只算一次，见 §3.13）→ 结论以冻结基准配对 A/B 为准（`data/eval_run.py` 的 `edge1/edge3/edge10`），未过确认集不得打开 |

### 4.2 `opt/champion.json`（出牌打分相关的）

| 键 | 值 | 说明 |
|---|---|---|
| `use_chi` / `use_peng` / `use_gang` | true | 鸣牌全开（关掉吃/碰实测 −1.20 / −1.51 分/局） |
| `chi_ukeire_gate` / `peng_ukeire_gate` | true | 与 `CLAIM_UKEIRE_GATE` 一致 |
| `peng_gate_max_shanten` | null | 碰门控用默认 1 |
| `chi_prefer_narrow` | **true** | R15 晋级项 |
| `shanten_cost` / `ukeire_w` / `fan_weight` | 100 / 0.1 / 5.0 | 打分权重（单位 = 1 向听） |
| `god_fan_boost` | 1.0（默认） | 手握财神时番型权重放大（**惰性**，实测无差别） |
| `baotou_slack` / `baotou_max_shanten` | 1 / 1 | 爆头路线阈值（当庄时被抢速覆盖为 0/0） |
| `piao_enabled` / `piao_dealer_only` | true / false | 财飘开；庄闲都飘 |
| `decline_hu` / `decline_q` / `decline_max_chain` | true / 0.75 / 3 | 弃胡 |
| `dealer_policy` | `"aggr"` | 坐庄抢速 |
| `dealer_aware` | **false** | 出牌打分里**不用**庄家×8 |
| `use_ev`（= `fan_override`） | true | 番型可抵消 1 向听（**恒开**；关掉 YCB 下 −0.67） |
| `protect_gang` | true | 杠子保留分 10 |
| `angang_tenpai_only` | true | 暗杠只在听牌时 |
| `fan_est` | `"heuristic"` | 番型估计口径 |
| `ycb_escape_gap` | 1 | 仅 YCB |
| `defend_dealer` / `knock` / `fan_value_melds` | false / false / false | 防守、敲响路线、去幻影七对 —— 均未启用 |

---

## 5. 已关闭 / 已证惰性（不要再花算力）

| 项 | 结论 |
|---|---|
| `ukeire_depth`（`USE_DEPTH=True`） | 对听牌候选恒 0，且 ~6.9s/次（超 3s 窗口） |
| `knock`（敲响/七客路线） | 数学上惰性（3.5 万随机手 0 次改变决策） |
| 权重类（`ukeire_w`/`fan_weight`/`god_fan_boost`） | 改 2~4 倍 → 0/475 个决策变化（向听项主导） |
| `wait_width`（含 `full`） | 破平版 +0.055（z=1.91）；`full` 版 **有害**（−0.634） |
| `defend_dealer`（喂庄防守） | 冠军 `false`；本轮**未单独 A/B**（规则"只能自摸"不影响它的动机——防的是庄家吃牌抢速） |
| `fan_value_melds`（去幻影七对） | +0.018（z=1.38）→ 不启用 |
| 所有**终盘门控**（`claim_min_wall`、`ww_late*`） | 对局在墙剩 ~40 张时就结束 → **从不触发**（Δ 恰好 0） |
| `claim_max_shanten`/`claim_min_wall`/`keep_pairs_min`（收紧鸣牌） | 每个环境都有害（关碰 −1.51、关吃 −1.20） |
| 「为吃额度留额」「第 2 摊挑食」 | 池化 3000 局 z≈1.1；且"向听≥3 不吃宽搭子"确认集崩到 +0.02（§22） |

---

## 6. 与出牌耦合的其它决策（速查）

| 决策 | 判据 | 关键参数 |
|---|---|---|
| 胡 | 张数正确 + `shanten==-1` +（YCB）`ycb_can_hu` | — |
| 弃胡打财飘 | 见 §2 第 2 步 | `DECLINE_Q=0.75`、`max_chain=3` |
| 财飘（主动） | `piao_after_discard` | `piao_enabled=true` |
| 暗杠 | 摸前听牌 + 杠后仍听（**残局未听牌时例外**：墙<28 → 照杠） | `angang_tenpai_only=true`、`GANG_DRAW_WALL=28` |
| 补杠 | 已碰 + 手第 4 张，`wall>20`，**杠完就听牌**（`GANG_TENPAI_ONLY`） | `BUGANG=true` |
| 明杠 | 手 ≥3 张，`wall>20`，非受限，**杠完就听牌** | `MINGGANG=true`、`GANG_TENPAI_ONLY=true` |
| 碰 | 向听下降，或（≤1 向听且质量提升） | `peng_gate_max_shanten=1` |
| 吃 | 向听下降，或（质量提升）；**≤2 摊**；多解先消化窄搭子 | `CHI_PREFER_NARROW=true` |
| 抓打圈 | 受限方只能打刚摸的牌、不能吃碰明杠 | v26 |

---

## 7. 线上 / 离线一致性

| 项 | 状态 |
|---|---|
| `dealer_speed` | ✅ 线上已传（2026-09-21 补齐，此前线上比冠军保守） |
| `fan_override` | ✅ 线上恒 `True`（与冠军 `use_ev=true` 一致） |
| 吃/碰 `ukeire` 门控 | ✅ 线上与冠军一致；`remain` 口径已修（含 4 家副露） |
| `prefer_narrow` | ✅ 线上已传（R15）；**只做同一次决策内的张数比较 → 与 `remain` 缩放无关，天然一致** |
| 绝对张数阈值（`narrow_max_accept` 类） | ⚠️ 若要用，必须传**原始未见张数**：线上 `remain` 是牌墙缩放口径（≈0.47×），sim 是原始张数 → 新增 `GameState.raw_unseen` 就是为它准备的（当前未部署该轴） |
| `allowed`（可打牌集合） | 线上 = 手里所有牌（含财神）；sim 默认**不含财神** → 已量化 **+0.088（噪声）**（R8 `live_allowed`） |
| 轮庄口径 | 线上 = 赢家坐庄/流局连庄；冻结基准 = 确定性轮庄（`seed%4`）→ 见 P0-10 |
| 真机验证 | ✅ 非 YCB 主场 100 局：出牌超时 **0/3574**、0 报错、番型三方对拍 **98/98**、0 规则违规 |

---

## 8. 复现 / 验证命令

```bash
python data/_discard_trace.py                                  # 单次出牌的完整打分表（自检 argmin）
python data/_discard_trace.py --hand 1w2w3w5w6w7w8t8t3b4b5bZZE # ASCII 牌串（避免 GBK 控制台转码）
python data/_chi_budget_probe.py --archive data/fetch_<room>   # 吃摊使用分布 + 额度绑定率
python data/eval_guard.py                                      # 冻结基准漂移哨兵（改完决策代码必跑）
python data/eval_run.py --run r16 --configs base,<候选> --field strong --shard 0 --shards 8
python data/eval_report.py --run r16 --field strong --base base [--append-ledger]
for f in tests/test_*.py; do python "$f"; done                 # 11 个测试文件
```
