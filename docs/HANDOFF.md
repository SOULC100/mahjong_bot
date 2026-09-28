# 新窗口交接简报（2026-09-23）

> 用途：新开一个会话继续「真机复盘 + 策略提升」时，把本文件当作唯一入口。
> 本文件自包含：状态、纪律、未决事项、验证命令、关键数字都在这里；细节一律链到仓库文档。

---

## 0. 粘贴即用的开场指令（三选一）

### A. 复盘 + 定方向（推荐先做这个）
```
工作区 H:\L22Trunk\mahjong_bot（杭州麻将 AI 参赛 bot）。
先读 docs/HANDOFF.md（新窗口交接简报），再按它 §3 的清单读文档，不要跳。
然后做三件事：
1) 用 docs/live-data-2026-09-23.md + data/matches/（20 场 1600 局归档）复核当前状态，
   特别是「番型缺口」是否仍是唯一统计显著的系统性缺陷、净分 −0.466 分/局（z=−1.61）有没有新证据；
2) 就 §5 的未决事项给我一份带**证据强度 × 预期收益**排序的行动清单；
3) 对每一条给出可执行的验证方案（A/B 臂名 + 命令 + 判定门槛 + 所需局数），不要直接改策略代码。
纪律见 docs/HANDOFF.md §4（尤其：真机跑分期间禁本地重负载；A/B 臂必须与 base 同底）。
```

### B. 实现 + 验收（已决定要做 plan_commit 时）
```
工作区 H:\L22Trunk\mahjong_bot。读 docs/HANDOFF.md 与 docs/plan-commit-design.md。
按设计稿实现 R21「手级双计划 + 多巡承诺」：
- 先按 §4 实现清单落地（decision.py 的 PlanState/plan_locked、sim 透传、5 个 A/B 臂、≥6 条单测，
  含「PLAN_COMMIT=False 时输出与 base_g 逐字节一致」这条）；
- 再按 §5 的流程跑：发现集 seeds_1000 → 过线才跑两套 holdout（各 2000 局）→ 池化判定；
- 判定用设计稿 §2 写死的门槛（Δ≥+0.10、z≥2、分半同号、机制必须动、胡率降幅 ≤1pp），
  阴性对照 plan_commit_c2 必须显著为负，否则先修装置再谈结论。
全程用 data/_pm_ab.py 并行跑分片；不要改线上常量，晋级后才接 smart_bot。
```

### C. 继续采数据（把样本做大到能判净分）
```
工作区 H:\L22Trunk\mahjong_bot。读 docs/HANDOFF.md。
再跑 N 场自由对战（python match_session.py --sessions N，每场约 15 分钟、80 局），
跑完用 data/_pm_datapack.py + data/_pm_signif.py 出报告，并更新 docs/live-data-*.md。
注意：真机在跑时只允许单局级分析（docs/eval-rounds.md §26）。
目标：把样本从 1600 局推到 ≈6000 局，才能分辨 ±0.3 分/局。
```

---

## 1. 项目一句话

网易 1024「AI 麻将大赛」参赛 bot：`smart_bot.py` 是线上进程（协议循环 + 决策接入），
`mahjong/` 是决策内核，`sim/` 是离线模拟器，`data/eval/` 是**冻结基准 + 全部实验证据**，
判定纪律写在 `docs/eval-rounds.md`。

## 2. 当前状态一页纸

### 已确证（可放心引用）
| 结论 | 证据 |
|---|---|
| **番型缺口是唯一统计显著的系统性缺陷** | 20 场 1600 局：爆头率 我 **5.4%(23/428)** vs 对手 **22.9%(264/1153)**，z=**−8.03**；场均番 1.119 vs 1.298 |
| 缺口在**「到达」不在「转化」** | 爆头听牌态 我 23 vs 对手 330（20 场）；而爆头听→胡转化 83% vs 79%；出牌层 18/18 全抓住 |
| 根因是**牌型构建**（对手开放手多） | 持白碰转化 34.9% vs 68.2%；他们胡牌时副露≥2 占 40.2% vs 我 23.3% |
| **净分仍不显著** | −0.466 分/局、z=−1.61、95% CI [−1.03,+0.10]；分半同号但都不过线；分辨 ±0.3 需 ≈5706 局 |
| **P0 庄家跟踪修复真机生效** | 修复后 10 场：旧告警 2 条、恢复路径 698 条（修复前：244 / 0） |
| **「弃胡敲响」新增番型来源（2026-09-26 已部署）** | 能胡时若打一张非财神牌后 13 张仍「任意摸都胡」→ 下一摸必胡 · 爆头 ×2。配对 A/B：弱场 **+0.883 分/局（z=11.86，12000 局）**、强场 +0.476（z=4.94，6000 局）；触发 **≈37 次/千局**、实测存活 q≈0.89。`DECLINE_KNOCK=True` / `Q=0.90`；见 eval-rounds §30 |

### 已关闭的轴（**别再重复走**，全有实验记录）
| 轴 | 结论 | 位置 |
|---|---|---|
| ×2 爆头"主动追"（偏置/换主项/bonus/手级双计划） | **全负或惰性**：`bao_plan` −1.105（z=−4.82，番型反降）；`bao_w` 0 翻转；双计划 EV 中位 0.38（需 5.2× 才翻转一半） | eval-rounds §28/§29 |
| 放宽鸣牌换爆头 | 保路线版恒不触发；宽松版 **−0.296 / −0.346** | §28 |
| ×4 财飘 | **我可用性 0**（可飘点 0 vs 对手 17/20 场）；对手同样靠"到达" | live-data §5 |
| 边张优先 / `god_fan_boost` / `knock`（**出牌向听**）/ `baotou_slack` 放宽 | 证否或可证 no-op。注意 `knock` 只关了"出牌路线"那条；**能胡时的「弃胡敲响」是另一条已部署的路**（eval-rounds §30） | §25/§27/§28/§30 |
| 整体放宽爆头（`baotou_slack+max=2`） | −0.455 且全半同号 | §25 |

### 未决（本轮要定的）
1. **`DEFEND_DEALER`（D1 防庄）**：线上开着；干净口径（ref=`base_g`）发现集 **−0.262（z=−2.48）**、
   确认集 −0.045（z=−0.58）、池化 ≈**−0.117（z≈−1.87）** ⇒ 负向但未过线，且**没有任何干净正证据**。
   决策：关掉（回冻结冠军口径）还是再补 3000 局判死？`docs/live-data-2026-09-23.md` §6。
2. **`plan_commit`（R21）**：设计稿完成、未实现。诚实上界 **+0.10~0.20 分/局**（决策层余量 ≤9~27 个
   爆头机会 vs 差 172）。`docs/plan-commit-design.md`。
3. **样本量**：净分要判显著需 ≈5700 局（现在 1600）。继续跑是纯机械成本（每场 15 分钟 / 80 局）。
   采集已自动化（`docs/auto-collect.md`）：任何入口触发自动匹配都会落待归档标记，`collect_auto.py`
   负责补档（`ensure` 会在触发时尽力拉起常驻；想"一直有人收"就挂 `collect_watch.bat` 看门狗/计划任务）；
   但**「起批次」本身仍需手动**（`match_session.py --sessions N`）——没人在跑就没有新样本
   （2026-09-23 实测：17:58 之后 2.7 小时零新增，因为没人起）。
4. **对手画像**：对手不固定、我们不知道是谁；若要判断"是否真的落后"，需要跨场累积对手维度
   （现有 1600 局里对手是若干不同 bot）。

## 3. 必须按顺序读的文件

1. `docs/HANDOFF.md`（本文件）
2. `docs/live-data-2026-09-23.md` —— 20 场数据整理（逐场表 / 分队列 / 显著性 / ×4 / D1）
3. `docs/postmortem-2026-09-22.md` —— 前 10 场深度复盘（含逐条复现判定与证据强度标记）
4. `docs/eval-rounds.md` —— **判定纪律 + 全部实验台账**；至少读 §25（边张）、§26（真机期间禁本地重负载）、
   §27（A/B 臂必须与 base 同底）、§28/§29（追爆头四轮 + 双计划 EV）
5. `docs/opp-baotou-teardown.md` —— 对手爆头路线逆向工程（789/789 重建、162/162 标签一致）
6. `docs/plan-commit-design.md` —— R21 设计稿（要做实现就读这份的 §2/§4/§5）
7. `docs/strategy-current.md` —— 当前参数总表 + §3.13「边际进张：单牌靠张不能相加」
8. `docs/debug_log.md` §十二~§十八 —— 近期审计与修复留档（花色口径、chi tiles、清理、P0、R20）
9. `docs/auto-collect.md` —— 自动匹配赛果的自动收集（触发点标记 → 根目录 `collect_auto.py` 扫 → 补档）

## 4. 纪律（违反则结论无效）

- **证据分级**：机制明确（可复现的因果/可证 no-op）＞ 统计显著（z≥2 且分半同号）＞ 噪声。
  单场输赢**永远不是**证据（会话间 sd ≈ 60~100 分）。
- **A/B 臂必须与 base 同底**：含 `_BG` 门控的臂必须同 run 带 `base_g`，报告用 `--base base_g` 取净效应；
  `eval_run.py` 已加启动断言（§27）。已证：门控常量按种子集为 **+0.41（seeds_1000）/ +0.19（holdout2000）**。
- **真机跑分期间禁本地重负载**（§26）：只允许单局级分析（`explain_round.py` 单局、`why_discard.py`）；
  禁 `eval_run.py` 多分片、禁跨场全量重建 —— 已实测会让超时以**同一秒的跨场次簇**爆发
  （§26 两例：3 次全在 16:18:10、4 次全在 21:17:31–32，与本机分片时间完全重合）；
  **真机超时率只有在无本地负载时才是指标**（历史基线 0.0~0.3%）。
- **判定门槛**：发现集 1000 局过线 → 跑两套 holdout（各 2000 局）→ 池化 z≥2 且分半同号才晋级；
  `z ≤ −2` 判疑似有害；其余噪声。分辨 ±0.16 分/局 ≈ 4500 局/臂（本机 10 分片并行约 25 分钟）。
- **止损**：确认集不过线就归档为证否，不重试同形态（R20 已在同一形态上花了四轮）。
- **口径**：逐局真值取 `events/blocks` 的 `round_ended`（`rounds[]` 会漏流局）；
  牌码 **t=条、b=筒**（§十四）。

## 5. 未决事项清单（带优先级与验证方案）

| 优先级 | 事项 | 预期 | 验证 |
|---|---|---|---|
| P0 | D1 去留 | 若真有害：**+0.12~0.26 分/局** | 再跑 `holdout2_2000` 池化到 5000 局；或直接关掉（`smart_bot.DEFEND_DEALER=False`）+ 10 场真机对照 |
| P1 | `plan_commit` 实现与验收 | **+0.10~0.20 分/局**（上界） | `docs/plan-commit-design.md` §4/§5 |
| P2 | 样本量推到 ≈6000 局 | 让"是否落后"可判 | `python match_session.py --sessions N` → `_pm_datapack.py` |
| P3 | 对手维度数据 | 判断差距是否稳定 | 归档里已有对手 user_id；可做"同一对手多次相遇"的分层 |

## 6. 关键数字速查（对账用）

```
场次            20 场（每场 10 batch × 8 局；10 个场次并发，单场约 15 分钟）
局数            1600 = round_ended 事件数（显著性口径）＝ 有胡 1581 + 流局 19
我胡/对手胡     428（27.1% of 1581） / 1153
净分            −746（−0.466 分/局，z=−1.61，95% CI [−1.03,+0.10]）
场均番          我 1.119 / 对手 1.298
爆头率          我 5.4%（23） / 对手 22.9%（264）  z=−8.03
出牌超时        60 次（409 拒绝 44 次）
完整性          零和不符 0、chi 对拍 20/20、Traceback 0、缺件 0
冻结基准        门控常量 +0.41(seeds_1000) / +0.19(holdout2000)；`base_g` = dict(_BG) 作 ref
口径注意        `data/matches/<room>/games.json` 的 rounds 只记胡局（1581），
                blocks 的 `round_ended` 才含流局（1600）；**真值一律取后者**
```

## 7. 常用命令

```bash
# 数据整理 / 体检
python data/_pm_archive_check.py      # 归档完整性 + P0 标记
python data/_pm_datapack.py           # 生成 docs/live-data-*.md + data/_datapack.json
python data/_pm_signif.py             # 逐局得分 z / CI / 所需局数
python data/_pm_x4.py                 # ×4 财飘可用性探针
python match_stats.py                 # 跨场累计（读 index.tsv）

# A/B（并行分片）
python data/_pm_ab.py --run <名> --configs base,base_g,<候选> --field strong \
    --seeds data/eval/seeds_1000.txt --shards 10 --parallel 10 --base base_g
python data/_pm_ab.py --run <名>_h --configs base_g,<候选> --field strong \
    --seeds data/eval/seeds_holdout2000.txt --shards 10 --parallel 10 --base base_g

# 真机（每场 15 分钟 / 80 局；跑分期间禁本地重负载）
python match_session.py --sessions 10

# 单局级复盘（真机在跑时唯一允许的分析）
python explain_round.py <room> <batch> <round> u_307259698ca9
python why_discard.py <room> <batch> <round> <巡数> u_307259698ca9
```

## 8. 环境与红线

- Windows / PowerShell。python 调用前加：
  `$env:PYTHONIOENCODING='utf-8'; [Console]::OutputEncoding=[System.Text.Encoding]::UTF8;`
  **bash heredoc（`<<'PY'`）在 PowerShell 里不可用**，脚本一律用 write 工具落盘再跑。
- 全局 token：`data/global_token.txt`（64 字符）。**任何输出里都不要打印它**；测试房 token 在 `data/tokens.txt`。
- 平台限流：`POST /api/match` **10 次/分钟/用户**；单房间接口 5/s；并发局上限 16；
  events 接口在房间进行中返回 403 → **必须在 bot 退出后立刻归档**。
- 房间生命周期：auto 房结束约 60 秒后关闭，玩家 API 永久 404 ⇒ 每场都是新房间，跑完即归档。
- 我方 user_id：`u_307259698ca9`（报表里的「我」）；bot 昵称见 `session.json`。
- **不要**在没有真机任务时把真机进程和本地多分片 A/B 同时跑（§26）。
- 归档结构：`data/matches/<room>/{session.json,games.json,stats.json,stats.md,bot.log,events/b*.json}`
  ＋ 总索引 `data/matches/index.tsv`；归档入口是 `match_session.py`（跑完自动归档＋出统计）。
