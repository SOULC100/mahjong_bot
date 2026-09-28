# 自动匹配赛果的自动收集（兜底归档）

> 需求（2026-09-23 用户）：**以后只要触发自动匹配都要收集数据。**
> 结论：归档从「人记得手动跑」变成「默认发生 + 漏了自动补」。

---

## 1. 三层装置

| 层 | 谁 | 做什么 | 失败会怎样 |
|---|---|---|---|
| ① 触发点 | `match_session.py` / `smart_bot.py` / `live_loop.py` / `live_smoke.py` | 入席成功即落标记 `data/matches/_pending/<room>.json`，并调 `collect_auto.py ensure` 把 ③ 拉起 | 落标记/拉起失败只打一行，**绝不影响对局** |
| ② 扫 | `python collect_auto.py`（= `sweep`） | 逐标记校验归档完整性 → 缺件就调 `match_session.py --archive` 补档 → 状态写回 | 失败留在清单里（`list` 可见），不会静默丢 |
| ③ 守 | `python collect_auto.py daemon`（**由 ① 自动 ensure**，幂等 PID 锁） | 常驻按周期重复 ②，房间还在打就等它打完 | 单轮异常只记日志继续；`stop` 可停 |

四个触发点都落标记，所以**不管这场是谁起的进程**（`match_session` 连场、`live_loop` 波次、人肉手跑 `smart_bot.py @data/global_token.txt x`），漏归档都会被扫出来补。

**③ 什么时候起、能活多久（2026-09-23 实测的重要限制）**：不在开机项里挂，而是在**真正触发自动匹配
的那一刻**由触发点 `python collect_auto.py ensure` 拉起。`ensure` 幂等（PID 锁 `data/_collector.pid`，
`O_CREAT|O_EXCL` 原子抢锁 + `OpenProcess` 存活检查），并发调用只会有一个常驻，并且会**等常驻把 PID
写出来再返回**。

但要注意：`ensure` 用 `DETACHED_PROCESS` 起的常驻，**在父 shell 退出后会被回收**（实测只活了 ~30s；
同条件的纯 sleep 子进程却活得好好的，说明是 shell/沙箱的进程组清理）。所以「自动开收」只是**尽力拉起**，
真正保证"一直有人收"的是让常驻跑在活得住的宿主里：

```powershell
collect_watch.bat                                  # 看门狗：每 60s ensure 一次（推荐）
python collect_auto.py daemon --interval 300       # 或直接常驻（前台/计划任务里）
python collect_auto.py watch  --interval 300       # 同上，但不写 PID 锁（调试用）
schtasks /Create /TN MahjongAutoCollect /SC ONLOGON /RL LIMITED /TR "H:\L22Trunk\mahjong_bot\collect_watch.bat"
```

即便常驻不在，**数据也不会丢**：触发点落的标记一直在 `data/matches/_pending/`，事后任何一次
`python collect_auto.py` 都会把欠的房补上（房间关停后免认证端点仍可读，见 §2）。

## 2. 关键事实：归档窗口不是 60 秒

旧结论「房间关停后取不到数据」只对**玩家** API（`/api/tournaments/{room}` → 404）成立。
**免认证**端点仍然长期可读（2026-09-23 20:46 实测）：

```
GET /api/test-rooms/a_f5e3bb628234/games            → 200 status=closed，10 场全 finished
GET /api/test-rooms/a_f5e3bb628234/games/0/events   → 200，153931 bytes，blocks=17 seats=4
```

该房 17:44 就已关停（关了约 3 小时）。所以收集器可以「事后补」，不必抢 60 秒；但**越早越好**，
因为平台随时可能清理（`NOT_FOUND: no such batch` 就是清理后的形态）。

## 3. 完整性判据（`archive_state`）

- `session.json`、`stats.json`、`games.json` 都在且能解析；
- `events/` 里可解析的 `b*.json` 数 == `games.json` 里的场次数。

缺任何一项 → 判为「不完整」→ 补档（`--require-complete` 让 `match_session.py` 在事件流缺件时返回 3，
收集器据此重试，而不是把半截归档当成功）。

## 4. 常用命令

```powershell
python collect_auto.py                     # 扫一遍，把待归档的全收掉
python collect_auto.py list                # 看待归档/失败清单（含缺件说明）
python collect_auto.py sweep --dry         # 只看要收哪些，不真归档
python collect_auto.py sweep --force       # 已有完整归档也重收（校验装置用）
python collect_auto.py ensure              # 确保常驻在跑（幂等；触发点自动调的就是这个）
python collect_auto.py status              # 常驻状态 + 待归档 + 日志尾部（排查先看它）
python collect_auto.py stop                # 停掉常驻
python collect_auto.py watch --interval 300   # 前台常驻（调试用，不写 PID 锁）
python collect_auto.py add --room a_xxx --log data/smart_gm.log --source manual
```

产物：标记目录 `data/matches/_pending/`、日志 `data/_collector.log`（常驻自身的 stdout 在
`data/_collector.out`）、PID 锁 `data/_collector.pid`、归档 `data/matches/<room>/`
（`session.json` / `events/b*.json` / `stats.json` / `stats.md` / `bot.log`）+ 总索引 `index.tsv`。

## 5. 自检（离线，不依赖新真机、不碰真服务器）

```powershell
python data\_collect_auto_test.py        # 沙箱 + 本地假服务端：成功路径/失败路径/清理全测
python data\_collect_hooks_check.py      # 触发点键一致性 + smart_bot 钩子真跑 + 补档命令组装
python collect_auto.py ensure            # 幂等自检：连调两次，第二次必须 already（只一个常驻）
```

`_collect_auto_test.py` **不再碰真实归档**：整场跑在 `data/_selftest/`（收集器与 `match_session.py`
都认 `COLLECT_DATA_DIR`），服务端指向本地假服务端（认 `COLLECT_SERVER`），素材取自
`data/_selftest/_server/`（与"被破坏的归档"分开）。四个场景：

| 场景 | 期望 | 2026-09-23 实测 |
|---|---|---|
| A 归档半途而废（events 没了） | sweep 补齐、清标记、索引一行 | `ok 10/10`，`b0.json` 177956 bytes ✓ |
| B 已完整 | SKIP 并清标记 | ✓ |
| C 服务端不可达 | **非零退出**且保留标记 | rc=1、标记 `failed` 带原因 ✓ |
| D 空壳 + 假索引行 | 全清 | `['session.json','stats.json','stats.md','games.json','index.tsv 行']` ✓ |

## 6. 排错记录（2026-09-23 实测踩到过，都已修）

| 症状 | 根因 | 处置 |
|---|---|---|
| `ensure` 抛 `SystemError: <class 'OSError'> returned a result with an exception set` | Windows 上 `os.kill(pid, 0)` 探测不存在的进程抛 `OSError(WinError 87)` 并被包成 SystemError，绕过 `except OSError` | 存活判定改走 ctypes `OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION)` + `GetExitCodeProcess` |
| `ensure` 报 `ValueError: unsupported format character` | 日志格式串里写了中文全角 `（%）` | 改 `（%s）` |
| 起了两个常驻 | "先看有没有、再写 PID 文件" 非原子，且 `ensure` 没等常驻写完 PID 就返回 | `O_CREAT\|O_EXCL` 原子抢锁 + 等 PID 落盘（≤10s）再报成功 |
| `stop` 报 `Access denied` | 受限会话里 `taskkill /F` 被拒 | 改用 ctypes `OpenProcess(PROCESS_TERMINATE)`+`TerminateProcess` |
| 房间还在 `registering` 就被补档 → 写出 0 场假归档 + 假索引行 | 只按"有没有在跑的对局"判 live | `live = status ∉ {closed,finished,void}`；发现仍 live 就 `purge_partial` 清空壳并把标记降回 `pending` |
| 假索引行清不掉 | `purge_partial` 里用了未定义的 `INDEX`，异常被 `except` 静默吞 | 定义 `INDEX`；异常必须记日志（不许静默） |
| 补档失败但标记已清 → 再也没人重试 | `finalize` 无条件 `clear_marker` | `keep_marker_on_fail=True`：事件流没抓全**保留**标记 |
| "服务器根本没连上"被当成补档成功 | `fetch_events` 在列表为空时提前返回，`st!=200` 与"0 场"分不清 | 显式区分 `st != 200`（网络/HTTP 失败）与"200 但 0 场"；`--require-complete` 两者都判失败（rc=3） |
| 自检把**真机正在打的房**的 events 删了 | 自检直接在 `data/matches/` 上做破坏 | 自检改为沙箱（`COLLECT_DATA_DIR`）+ 假服务端（`COLLECT_SERVER`） |
| 沙箱没生效，补档仍写真归档 | `match_session.MATCHES` 写死 `ROOT/data/matches`，只定义变量没读 | 让 `match_session.py` 也读 `COLLECT_DATA_DIR` |
| 沙箱里 `b0.json` 全都 404 | 自检自己的假服务端也从"被破坏的归档"取素材（删了源又指望源在） | 素材单独放 `data/_selftest/_server/` |
| 假服务端返回的中文 JSON 解析失败 | `http.server` 按 latin-1 输出，未声明 charset | `Content-Type: application/json; charset=utf-8` + 显式 UTF-8 编码 |

## 7. 真机端到端验收（2026-09-23 已通过）

`python match_session.py --sessions 1` → 房 `a_4f8c8881807b`，80 局 / 16.3 分钟，链路每一步都有证据：

| 环节 | 证据 |
|---|---|
| 入席即落标记 | `data/matches/_pending/a_4f8c8881807b.json`（`source=match_session`） |
| 触发点自动拉起常驻 | `collector.log`：`ensure 已拉起收集器常驻 pid=… `；再 ensure 得 `already` |
| 对"进行中"的房**不误档** | `WAIT a_4f8c8881807b 房间进行中 status=running 9/10 场完成` |
| bot 退出后立即归档 | `bot 退出 code=0，用时 16.3 分钟 → 立刻归档事件流`；`归档完成：data\matches\a_4f8c8881807b` |
| 完整 + 标记清除（闭环） | `archive_state → 归档完整（10 场事件流）`；`_pending/` 空；索引 27 → 28 行 |
| 归档自带质检 | chi 对拍 ✅ 39/39、零和 ✅、Traceback 0、守恒异常 0、429 0、超时 4（0.55%） |

## 8. 与其他文档的关系

- 归档目录结构与字段语义：`docs/README.md`「每一场自由匹配都留档」一节（本文补充"自动"部分）；
- 判定纪律：`docs/eval-rounds.md`（收集是采数据，不改变任何判定门槛）；
- 真机跑分期间禁本地重负载：`docs/eval-rounds.md` §26 —— 收集器只在**真机跑分期**工作、
  自身只做 GET + 一次归档子进程，不参与 A/B，所以不与该纪律冲突。
- 本文对应的事件台账：`docs/debug_log.md` §二十（含 8 个真 bug 的根因与修法）。
