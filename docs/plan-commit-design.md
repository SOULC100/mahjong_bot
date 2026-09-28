# 设计稿：`plan_commit` —— 手级双计划 + 多巡承诺（R21）

> 状态：**设计完成，未实现**（2026-09-23）。前置结论见 `docs/eval-rounds.md` §27~§29、
> 对手画像见 `docs/opp-baotou-teardown.md`、真机样本见 `data/matches/`（≥20 场归档）。

## 1. 为什么要做（三条轴关闭后的唯一路）

| 已关闭的轴 | 证据 |
|---|---|
| ×2 爆头"主动追"（单步偏置 / 换主项 / bonus） | `bao_plan` **−1.105 分/局（z=−4.82）**、场均番反降 −0.028；`bao_w` 恒惰性（0 翻转） |
| 放宽鸣牌换爆头（保路线版 / 宽松版） | 保路线版**恒不触发**；宽松版 **−0.296 / −0.346** |
| ×4 财飘 | 探针：**可飘点双方都是 0**（要求「已爆头态 + ≥2 白」）⇒ 无可用性，不是决策问题 |
| 双计划 EV（手级、逐巡重评） | 机制上恒不触发：`EV_爆头/EV_标准` **中位 0.38**，只有 2.93% 的点会切；需 **5.2×** 番型倍数才翻转一半 |

**唯一剩下的缺口**：爆头听牌态**到达率** 我 0.94% vs 对手 3.05%（3.2×），而听牌→胡转化率相同
（83% vs 79%）、出牌层 18/18 全抓住。对手的爆头来自**开放手（副露多）让白自然留成将**
（持白碰转化 68.2% vs 我 34.9%；他们胡牌时副露≥2 占 40.2% vs 我 23.3%）—— 即**整手牌型构建**的差异。

**为什么必须"承诺"而不能"逐巡挑最优"**：R20 v2 已证逐巡重评 ⇒ 因为爆头计划在**单巡**尺度上总是
劣于标准计划（EV 0.38），逐巡比较自然会一直选标准计划；但换成"整局走开放+留白"这条**计划**，
它的收益来自**多巡累积的形状协同**（白不必进面子、面子靠鸣牌补），单巡 EV 估计**系统性低估**它。
所以本设计的核心不是"换个打分"，而是**给计划一个承诺期**，让它的价值有机会显形。

## 2. 成功判据（写死，避免事后挪靶）

**晋级门槛（三条全过）**
1. 确认集池化（`holdout2000` + `holdout2_2000` = 4000 局/臂）**Δ分 ≥ +0.10** 且 **z ≥ 2** 且**分半同号**；
2. **机制必须动**：场均番 **≥ +0.02**（相对 `base_g`）或爆头率 **≥ +1.0pp**；
3. **安全闸**：胡牌率相对 `base_g` 下降 **≤ 1.0pp**；吃摊 ≤2、抓打圈受限、最后 10 墩禁杠**零违规**
   （服务端 409 计数不高于基线）。

**阴性对照（闸门测试）**
- `plan_commit_c2`（允许追两巡）**必须显著为负**（探针预测代价 ≥2 无效）。若它不为负，说明实验装置
  没打通（承诺没生效），本轮结论作废、先修装置。

**止损**：确认集 Δ < +0.10 或分半异号 ⇒ **归档为证否**，不再重试同一形态（避免 R20 式反复）。

## 3. 设计

### 3.1 两个计划

| 计划 | 白的使用 | 目标形状 | 速度口径 | 番型倍数 |
|---|---|---|---|---|
| `P_closed` | 百搭（`shanten`） | 现行（门清/七对/标准 4 面子 + 将） | `shanten` | 1.0 |
| `P_open` | **留作将**（`shanten_baotou`） | **4 面子（允许副露补）+ 单张白** = 爆头 | `shanten_baotou` | 2.0 |

### 3.2 计划评估（复用 §29 已实现的部件）

```python
EV(plan) = 该计划最优 13 张的进张质量 / (1 + max(0, 计划向听)) × 计划番型倍数
```
- `P_closed`：`_draw_quality()` + `shanten`
- `P_open`：`_draw_quality_bao()` + `shanten_baotou`（**已实现**，与标准同单位）
- 硬门：`P_open` 仅当 `shanten_baotou − shanten ≤ plan_max_cost`（默认 **1**）时可被考虑
  （探针：代价 ≥2 时双方转化都是 0%）

### 3.3 承诺状态机（本轮新增的核心）

```
每局开始：plan = P_closed, streak = 0

每个决策点（摸牌后 / 鸣牌窗口）：
    ev_closed, ev_open = plan_eval(hand, melds, remain)
    lead = 领先者及其相对幅度 = |ev_a − ev_b| / max(ev_a, ev_b)

    if 当前计划死亡:                      # P_open：白被消耗（shanten_baotou == 99）
        plan = 另一计划; streak = 0
    elif 领先者 != plan and lead >= plan_margin:
        streak += 1
        if streak >= plan_k:              # 默认 k = 2：连续两巡领先才切换
            plan = 领先者; streak = 0
    else:
        streak = 0

    # 按 plan 执行（三条链路必须同口径，否则形状成不了 —— R20 的教训）
    出牌    : discard_decision(..., plan_locked=plan)      # 主项/进张项用该计划口径
    鸣牌    : should_peng/best_chi(..., plan_locked=plan)  # P_open 放宽到"不升向听"即鸣
    弃胡/胡 : should_decline_hu(..., plan_locked=plan)     # P_open 下更愿意弃胡保形状（见 3.4）
```

**可退出性**（关键）：
- `P_open` 在**白被消耗**（打白 / 被抓打圈逼出 / 形状破坏）时立即死亡 → 回落 `P_closed`；
- 反过来 `P_closed` 不设死亡条件，只要 `ev_open` 连续 `plan_k` 巡领先 `plan_margin` 就切过去；
- 每局结束重置（**不跨局继承** —— 白是每局重发的，跨局承诺会污染下一局）。

### 3.4 与弃胡/财飘的关系（避免踩 §29 的坑）

- `P_open` 的收益来自**爆头 ×2**，**不**来自财飘（探针：可飘点双方都是 0，无可用性）⇒ 设计里
  **不**为财飘做任何额外优化，`DECLINE_HU` 保持现状（只在"打白后仍爆头"时触发）；
- `P_open` 下**允许**在"已能胡且是爆头"时照常胡（×2 到手），不做"为了 ×4 再等"的赌博
  —— 那需要「≥2 白」的罕见条件，赌它没有正 EV（§29 的 5.2× 阈值）。

### 3.5 参数与开关（全部默认关）

| 开关 | 默认 | 含义 |
|---|---|---|
| `PLAN_COMMIT` | `False` | 主开关（关 = 现行行为，逐字节不变） |
| `plan_k` | `2` | 连续领先几巡才切换计划 |
| `plan_margin` | `0.20` | 切换所需的相对 EV 领先幅度 |
| `plan_max_cost` | `1` | `P_open` 允许的最大向听代价（探针硬门） |
| `plan_open_claim` | `True` | `P_open` 期间鸣牌门控是否放宽到"不升向听" |

## 4. 实现清单（落地时逐项打勾）

1. `mahjong/decision.py`
   - [ ] `class PlanState`（`plan`, `streak`）+ `plan_eval()`（复用 `_plan_choice`/`_draw_quality_bao`）
   - [ ] `discard_decision(..., plan_locked=None)`：为 `"open"` 时主项/进张项换 `P_open` 口径
         （**已有** `plan_mode="ev"` 的换口径代码可复用，只是触发条件从"当巡 EV 更高"改成"被承诺"）
   - [ ] `should_peng/best_chi(..., plan_locked=None)`：`"open"` 时放宽到「鸣牌后向听不变差即鸣」
   - [ ] `should_decline_hu(..., plan_locked=None)`：`"open"` 时保持现状（见 3.4），只加日志
2. `sim/players.py::Smart`
   - [ ] 持有 `self.plan`（**每局重置**：在 `Game.play_round` 给策略一个 `on_round_start()` 钩子，
         或首次 `choose_discard` 时检测 `game.round_no` 变化）
   - [ ] `want_peng/want_chi/choose_discard` 透传 `plan_locked`
3. `data/eval_run.py` 臂（**每个都 `dict(_BG, …)` 且同 run 带 `base_g`**，§27 纪律）
   - [ ] `plan_commit`（默认参数）
   - [ ] `plan_commit_k3`、`plan_commit_m40`（更严：k=3 / margin=0.40）
   - [ ] `plan_commit_noclaim`（只换出牌口径、不放宽鸣牌 → 用来分离"承诺"与"鸣牌"的贡献）
   - [ ] `plan_commit_c2`（**阴性对照**：`plan_max_cost=2`，预期显著为负）
4. `tests/test_decision.py`（≥6 条）
   - [ ] EV 相当时**不**切换；连续 `plan_k` 巡领先才切换
   - [ ] `P_open` 白被消耗 → 立即回落 `P_closed`
   - [ ] `plan_max_cost=1` 硬门：代价 2 的手**永不**激活 `P_open`
   - [ ] `plan_locked="open"` 时鸣牌门控确实放宽（构造成立/不成立两例）
   - [ ] `PLAN_COMMIT=False` 时输出与 `base_g` **逐字节一致**（默认零影响）
   - [ ] 性能：单次决策耗时不高于现基线 **1.5×**（`plan_eval` 候选池裁剪到 `s_map ≤ min_s+1`）
5. `smart_bot.py`（**只在晋级后**才接线）
   - [ ] `PLAN_COMMIT` 常量 + `choose_action/choose_discard` 透传；`opt/champion.json` 同步

## 5. 验证流程（按纪律，顺序不能变）

```bash
# ① 发现集（1000 局/臂，10 分片并行，约 5 分钟）
python data/_pm_ab.py --run r21_discovery --configs base,base_g,plan_commit,plan_commit_noclaim,plan_commit_c2 \
    --field strong --seeds data/eval/seeds_1000.txt --shards 10 --parallel 10 --base base_g

# ② 过线才跑确认集（两套 holdout，各 10 分片；池化 4000 局/臂）
python data/_pm_ab.py --run r21_holdout  --configs base_g,plan_commit --field strong \
    --seeds data/eval/seeds_holdout2000.txt --shards 10 --parallel 10 --base base_g
python data/_pm_ab.py --run r21_holdout2 --configs base_g,plan_commit --field strong \
    --seeds data/eval/seeds_holdout2_2000.txt --shards 10 --parallel 10 --base base_g

# ③ 机制读数（不看分数）：场均番 / 爆头率 —— 用 eval_report 的「场均番型」列 + teardown 口径复算
python data/eval_report.py --run r21_holdout --field strong --base base_g --append-ledger
```

**真机阶段只验机制**（分数在 800 局尺度判不了）：下一批自由对战看
① 爆头率是否上升、② 场均番是否上升、③ 无回归（0 Traceback/409/超时异常、chi 对拍 100%）。

## 6. 风险与前置条件

| 风险 | 处置 |
|---|---|
| **性能**：`plan_eval` 每决策 2×~50 次向听调用 | 只对 `s_map ≤ min_s+1` 的候选算；上线前用真机 M=10 并发实测单次决策耗时（>150ms 就进一步裁剪或缓存） |
| **规则风险**：放宽鸣牌可能撞 吃≤2 摊 / 抓打圈 / 禁杠 | 放宽**只在硬门之内**（本地门禁照旧 + 服务端 409 兜底）；单测覆盖 |
| **回归风险**：默认关，但实现会动 `discard_decision` 主路径 | 用 `PLAN_COMMIT=False` 的逐字节一致单测兜住（§27 的同配置复跑纪律） |
| **反复投入** | 已写死止损：确认集 Δ<+0.10 或分半异号 ⇒ 归档证否，不重试同形态 |

## 7. 诚实预期

- **上界 +0.10~0.20 分/局**（来自 `opp-baotou-teardown` 的机会计数：决策层余量 ≤9~27 个爆头机会 vs 差 172，
  最多补 5~16% 的缺口）。这**不是**"追上对手"的方案，而是把"到达率"从 0.94% 往 1.1~1.3% 推一点。
- 若要真正接近对手的 3.05%，需要**对手引擎级别**的牌型搜索（多计划 + rollout + 对手建模），
  那是另一个量级的工程；本设计是它能被验证的最小前身。
