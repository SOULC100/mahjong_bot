"""正式参赛 Bot —— 接入决策引擎。

用法：python smart_bot.py <令牌> [编号] [--m N] [--r N]

- 参赛令牌（scoped，门户「报名」/「测试房间」派发）：报名 → 到位 → 多阶段主循环。
- 全局令牌（门户「我的 AI 身份」签发，v24 起匿名注册已删除）：走 POST /api/match
  入席自动匹配房（v13 起自动房唯一入口，直连 register/ready 恒 409 AUTO_MATCH_ONLY）。
  --m/--r 声明可承受上限（须 ≥ 服务默认 M=10/Rounds=8，v15，否则永久 404）；缺省 = 不限。

决策策略：
1. 能胡就胡（有财必拷响下须真·爆头或杠开，v21/对齐 sim/engine）
2. 杠：墙 > 20 就暗杠（杠开 ×2；暗杠在抓打圈内也合法）
3. 碰/吃：碰/吃后向听数下降才碰/吃（含副露数；吃满 2 摊不再吃，v25）
4. 出牌：在合法牌内选向听数最小 + 进张最多的牌（含副露数）

协议对齐的规则版本：接入指南 v29（2026-09-09）。启动时做 guide/version 自检（指南 §2.2）。
"""

import json
import ssl
import sys
import threading
import time
import urllib.request

sys.path.insert(0, ".")

from mahjong.game_state import GameState
from mahjong.tiles import tile_from_str, tile_to_str, LAIZI_INDEX
from mahjong.decision import should_piao, should_peng, should_chi, discard_decision, angang_tile
from mahjong.shanten import shanten
from mahjong.fan import ycb_can_hu

SERVER = "https://10.240.169.190:18080"

# 本代码已核对的接入指南版本（GET /portal/api/guide/version，2026-09-09 = v29）
KNOWN_GUIDE_VERSION = 29


def _parse_args(argv):
    """解析 CLI：<令牌> [编号] [--m N] [--r N]。返回 (token, bot_id, m, rounds)。"""
    token = argv[1].strip() if len(argv) > 1 else ""
    bot_id, m, r = "x", None, None
    i = 2
    while i < len(argv):
        a = argv[i]
        if a == "--m" and i + 1 < len(argv):
            m = int(argv[i + 1]); i += 2; continue
        if a == "--r" and i + 1 < len(argv):
            r = int(argv[i + 1]); i += 2; continue
        if bot_id == "x":
            bot_id = a.strip()
        i += 1
    return token, bot_id, m, r


try:
    TOKEN, BOT_ID, MATCH_M, MATCH_ROUNDS = _parse_args(sys.argv)
except ValueError:
    print("参数错误：--m/--r 需要整数")
    raise SystemExit(2)
if not TOKEN:
    print("用法: python smart_bot.py <令牌> [编号] [--m N] [--r N]")
    raise SystemExit(2)
LOG = open("data/smart_%s.log" % BOT_ID, "w", encoding="utf-8")


# ---- 出牌深度开关 ----
# True 用二次进张(ukeire_depth，慢但更准，最坏 ~370ms/次)；False 用进张质量
# (ukeire_quality，~1ms)。实测 10 线程并发 + GIL 下 True 单次可拖到 ~1.9s，
# 逼近 3s 出牌窗口——先关。等提速验证有效后，用 sim_ab 对比深度对胡牌率的影响再决定。
USE_DEPTH = False


def log(*a):
    print(*a, file=LOG, flush=True)


# ---- 全局限速（跨并发局线程共享）----
# 服务器 state 轮询限速已放宽至 16/s（v11，历次上限：5/s → 8/s → 16/s）。GET（轮询+快照）
# 与控制面（/api/me、/api/tournaments/{id}，约 2/s）共用一个桶，故自限留余量。
# POST 动作稀疏且时间敏感（3s 出牌窗口），不参与限速，避免排队拖垮出牌。
POLL_INTERVAL = 0.08  # ~12.5/s（+控制面 ≈14.5/s < 16/s 墙）
_get_lock = threading.Lock()
_last_get = [0.0]


def set_poll_interval_for_m(m):
    """按赛事并发场数 M 调整自限：v15 起自动匹配房默认 M=10，需求 ≈ M×1.34/s ≈ 13.4/s，
    旧自限 12.5/s 会掉吃碰窗口（v11 收益场景正是这个）。M≥8 时提到 ~13.3/s（+控制面 ≈15.3 < 16）。"""
    global POLL_INTERVAL
    if m and int(m) >= 8:
        POLL_INTERVAL = 0.075
    log("POLL_INTERVAL = %.3fs（≈%.1f/s，赛事 M=%s）" % (POLL_INTERVAL, 1.0 / POLL_INTERVAL, m))


def _throttle_get():
    """GET 请求（state 轮询 / 权威快照）前调用：全局最小间隔，串行化到安全频率。"""
    with _get_lock:
        now = time.time()
        wait = POLL_INTERVAL - (now - _last_get[0])
        if wait > 0:
            time.sleep(wait)
            now = time.time()
        _last_get[0] = now


class ApiError(Exception):
    def __init__(self, status, body):
        self.status, self.body = status, body


def _err_code(e):
    """取服务端错误码。v29 起判型必须用 code 而非状态码（吃摊满=409 INVALID_ACTION、
    功能关闭=403 FEATURE_DISABLED、身份未绑定=403 PORTAL_BINDING_REQUIRED…）。
    响应体形如 {"code":"INVALID_ACTION","message":"..."}。"""
    try:
        d = json.loads(e.body or "{}")
        if isinstance(d, dict):
            return str(d.get("code") or d.get("error") or "")
    except Exception:
        pass
    return ""


def api(method, path, body=None, auth=True):
    if method == "GET":
        _throttle_get()  # 只对 state 轮询限速；POST 动作时间敏感不排队
    req = urllib.request.Request(
        SERVER.rstrip("/") + path,
        data=json.dumps(body).encode() if body is not None else None,
        method=method)
    req.add_header("Content-Type", "application/json")
    if auth:
        req.add_header("Authorization", "Bearer " + TOKEN)
    ctx = ssl._create_unverified_context()
    for attempt in range(8):
        try:
            with urllib.request.urlopen(req, timeout=35, context=ctx) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                # GET 轮询指数退避（上限 1s）；POST 动作短退避保 3s 出牌窗口
                backoff = (min(0.1 * (2 ** attempt), 1.0) if method == "GET"
                           else 0.05 * (attempt + 1))
                time.sleep(backoff)
                continue
            raise ApiError(e.code, e.read().decode(errors="replace"))
    raise ApiError(429, "rate limited after retries")


def choose_discard(hand, allowed_set, remain, melds=0, youcai_bikao=False):
    """在允许打出的牌集合内选最优出牌（复用 decision 引擎，depth 由 USE_DEPTH 控制）。

    fan_override（番型抵消 1 向听的 EV 框架）：仅非 YouCaiBiKao 时开——
    sim 同 seed A/B 复验 +0.65pp 胡牌率 / +0.25 平均分（2000 局）；YCB 下手持财神必爆头，
    EV 框架未经该模式标定，保守关闭。
    """
    return discard_decision(hand, remain, melds, depth=USE_DEPTH,
                            dealer=False, fan_override=(not youcai_bikao), allowed=allowed_set,
                            youcai_bikao=youcai_bikao)


def can_hu(hand, melds=0, youcai_bikao=False, drawn=-1, gang_kai=False):
    """判断 14 张手牌能否自摸胡（含 YouCaiBiKao 约束）。

    drawn: 本回合刚摸的牌索引（用于还原摸前 13 张判真·爆头）。
    gang_kai: 本回合是否为杠后补牌（杠上花）——YCB 的免爆头胡法。
    """
    # 张数校验：胡牌需 14-3*melds 张（含财神）；否则 shanten 假阳性 → 假胡被拒死循环
    if sum(hand) != 14 - 3 * melds:
        return False
    if shanten(hand, melds) != -1:
        return False
    # 有财必拷响：手有财神须真·爆头（摸前 13 张任意摸都胡）或杠开。
    # 2026-09-09 修正：旧判据 `shanten_baotou(hand) != -1` 对 14 张胡牌恒真
    # （shanten_baotou 最小值恒为 0、永不为 -1）→ 所有持财神的胡全被拒，
    # YCB 赛事里会主动把胡牌打掉。判据与 sim/engine._can_win 统一到 mahjong.fan.ycb_can_hu。
    if youcai_bikao and not ycb_can_hu(hand, drawn, melds, gang_kai):
        return False
    return True


def my_meld_count(snap):
    """本人副露数（碰/吃/杠各 1 摊），从快照 melds[seat] 权威读取；解析失败返回 None。"""
    seat = snap.get("seat")
    melds = snap.get("melds")
    if seat is None or not isinstance(melds, list) or not (0 <= seat < len(melds)):
        return None
    row = melds[seat]
    return len(row) if isinstance(row, list) else None


def _hand_drift(state, snap, melds):
    """手牌 + 副露张数守恒校验，返回是否漂移。

    我的回合（draw 阶段 turn==seat）应为 14（摸牌或碰/吃后待弃 1 张），
    其余（等待/响应窗口）应为 13。deal/settled/finished 阶段手牌不完整，不校验。
    """
    phase = snap.get("phase", "")
    if phase in ("deal", "settled", "finished"):
        return False
    total = sum(state.full_hand()) + 3 * melds
    my_turn = phase == "draw" and snap.get("turn") == snap.get("seat")
    return total != (14 if my_turn else 13)


def determine_action(snap):
    """根据快照自研判定当前阶段与相关牌（allowed_actions 已移除）。

    返回 (phase, tile_str) 或 None（无需动作）。
    phase ∈ draw / response_peng / response_chi。
    """
    phase = snap.get("phase", "")
    seat = snap.get("seat", -1)
    turn = snap.get("turn", -1)
    responding = snap.get("responding_seats") or []
    drawn = snap.get("drawn_tile", "")
    last_discard = snap.get("last_discard", "")
    if seat < 0:
        return None
    if phase == "draw" and turn == seat:
        return ("draw", drawn)
    if phase == "response_peng" and seat in responding:
        return ("peng", last_discard)
    if phase == "response_chi" and seat in responding:
        return ("chi", last_discard)
    return None


def choose_action(state, phase_info, melds=0, youcai_bikao=False, skip_hu=False,
                  chi_count=None, gang_kai=False):
    """根据局面和当前阶段选择动作。返回动作 dict 或 None。

    chi_count: 本人已有吃摊数（v25 服务端强制 ≤2；None = 解析不出，交服务端 409 兜底）。
    gang_kai: 本回合是否杠后补牌（YCB 免爆头胡法）。

    None 表示「无需提交」：要么非己方动作，要么 pass（碰/吃窗口固定走满，
    不 POST 让服务器自然超时，省请求）。"""
    if phase_info is None:
        return None
    phase, tile_str = phase_info
    hand = state.full_hand()
    # 抓打圈受限 ⇔ catch_play 且本人非打财神者（v26：打财神者本人豁免）
    restricted = state.is_catch_restricted()

    if phase == "draw":
        # 1. 能胡就胡（仅当真的摸了牌；碰/吃/杠后 drawn_tile 为空禁止胡；误判被拒后跳过）
        if tile_str and not skip_hu and can_hu(hand, melds, youcai_bikao,
                                               state.drawn_tile, gang_kai):
            return {"action": "hu", "tile": ""}
        # 2. 抓打圈受限方：只能打刚摸的牌（跳过杠/财飘/择优）；豁免方不受此限
        if restricted:
            if tile_str:
                return {"action": "discard", "tile": tile_str}
            return None
        # 3. 暗杠：听牌才杠 + 墙剩>20（angang_tile 已含七对/豪华七对保护），杠开 ×2 × 庄家×8。
        #    只在真摸牌回合评估（tile_str 有值），碰/吃后待弃回合不杠。
        #    抓打圈内「其余玩家」也允许暗杠（规则：圈内仅禁吃/碰/明杠），故不设圈门禁。
        #    只做暗杠：明杠需响应他人弃牌窗口、补杠需解析 melds 里的杠/碰类型，
        #    两者历史上都触发过牌数/死循环，暂缓（留待实房验证）。
        if tile_str and state.wall_remaining > 20:
            gt = angang_tile(hand, state.drawn_tile, melds)
            if gt is not None:
                return {"action": "gang", "tile": tile_to_str(gt)}
        # 4. 财飘
        if should_piao(hand):
            return {"action": "discard", "tile": tile_to_str(LAIZI_INDEX)}
        # 5. 出牌
        allowed_set = set(t for t in range(34) if hand[t] > 0)
        d = choose_discard(hand, allowed_set, state.remain, melds, youcai_bikao)
        return {"action": "discard", "tile": tile_to_str(d)}

    if phase == "peng":
        t = tile_from_str(tile_str)
        hand13 = state.full_hand()  # 13 张（响应他人弃牌，无 drawn）
        if restricted:
            return None  # 抓打圈受限方不能碰/明杠（打财神者本人豁免）
        if should_peng(hand13, t, melds):
            return {"action": "peng", "tile": tile_str}
        return None

    if phase == "chi":
        t = tile_from_str(tile_str)
        hand13 = state.full_hand()
        if restricted:
            return None  # 抓打圈受限方不能吃（打财神者本人豁免）
        if chi_count is not None and chi_count >= 2:
            return None  # v25：吃最多 2 摊（服务端 409 强制，本地先自限）
        if should_chi(hand13, t, melds):
            return {"action": "chi", "tile": tile_str}
        return None

    return None


def _needs_snapshot(events, my_seat):
    """判断一批增量事件里是否含「可能轮到己方动作」的触发，需要拉权威快照。

    触发三类：
    - tile_drawn(我)：我摸牌，要出牌/胡；
    - tile_discarded(他人)：碰窗口；
    - timeout window=peng(我)：我碰窗口走满，吃窗口开启。
    """
    for ev in events:
        t = ev.get("type")
        if t == "tile_drawn" and ev.get("seat") == my_seat:
            return True  # 我摸牌 → 出牌/胡
        if t == "tile_discarded" and ev.get("seat") != my_seat:
            return True  # 他人弃牌 → 碰窗口
        if (t == "timeout" and ev.get("seat") == my_seat
                and (ev.get("data") or {}).get("window") == "peng"):
            return True  # 我碰窗口走满 → 吃窗口
    return False


def play(gid, state, youcai_bikao=False):
    seq = 0
    my_seat = -1
    melds = 0  # 我的副露数（碰/吃/杠）——快照 melds[seat] 权威
    chi_count = None  # 我的吃摊数（v25 ≤2）——快照 melds[seat] 中 kind=="chi"
    responded_key = None  # 当前响应窗口 key，已响应则不再重复提交
    skip_hu = False  # hu 误判被拒后，本次手牌状态跳过 hu
    last_drawn = None
    gang_pending = False  # 刚提交过杠 → 下一张摸牌是杠后补牌
    gang_kai_for = None  # 杠后补牌的那张（字符串）：仅该摸牌回合算杠开（YCB 免爆头）
    drift_streak = 0  # 连续守恒校验失败计数，防死循环
    while True:
        try:
            res = api("GET", "/api/games/%s/state?seq=%d" % (gid, seq))
        except ApiError as e:
            if e.status == 429:
                time.sleep(1.0)  # 轮询超频退避后重试，不崩线程
                continue
            if e.status == 404:
                # v13：自动房整场打完（finished 约 60s 宽限）自动关停 → 玩家 API 一律 404
                log("对局 %s 已不存在（房间关停/回收），结束本场" % gid)
                return
            raise
        if res.get("finished"):
            snap = res.get("snapshot") or {}
            log("本场结束 积分:", snap.get("scores"))
            return
        if res.get("pending"):
            continue
        snap = res.get("snapshot")
        if snap is None:
            # 增量事件：推进 seq，仅当「可能轮到己方动作」才拉权威快照，否则继续长轮询省请求
            events = res.get("events") or []
            for ev in events:
                seq = ev.get("seq", seq)
            if not _needs_snapshot(events, my_seat):
                continue
            res0 = api("GET", "/api/games/%s/state?seq=0" % gid)
            seq = res0.get("seq", seq)  # 权威快照的 seq 更新，避免重拉已见事件
            snap = res0.get("snapshot")
        else:
            seq = res.get("seq", seq)
        if snap is None:
            continue
        if my_seat < 0:
            my_seat = snap.get("seat", -1)
        state.update_from_snapshot(snap)
        if my_seat != state.my_seat:
            my_seat = state.my_seat
        # 状态同步：副露数优先读快照 melds[seat]（消除本地 +1 漂移）
        mc = my_meld_count(snap)
        if mc is not None:
            melds = mc
        cc = state.chi_meld_count()  # v25：吃摊数（解析不出返回 None → 不做本地门禁）
        if cc is not None:
            chi_count = cc
        # 张数守恒校验：不符则 seq=0 重建权威快照；连续失败则放弃校验继续（防死循环）
        if _hand_drift(state, snap, melds):
            drift_streak += 1
            log("张数守恒异常 x%d! 手牌+副露=%d melds=%d drawn=%s phase=%s"
                % (drift_streak, sum(state.full_hand()) + 3 * melds, melds,
                   state.drawn_tile, snap.get("phase")))
            if drift_streak < 3:
                seq = 0
                continue
            log("连续漂移，放弃校验继续")
        else:
            drift_streak = 0
        # 新摸牌（drawn_tile 变化）则重置 hu 拦截；杠后补牌只对紧接着的这一张生效
        drawn = snap.get("drawn_tile", "")
        if drawn != last_drawn:
            last_drawn = drawn
            skip_hu = False
            gang_kai_for = drawn if (gang_pending and drawn) else None
            gang_pending = False
        gang_kai = bool(drawn) and drawn == gang_kai_for
        phase_info = determine_action(snap)
        if phase_info is None:
            continue
        phase, tile_str = phase_info
        # 响应窗口「已响应」跟踪：同一窗口不重复提交
        if phase in ("peng", "chi"):
            key = (phase, snap.get("turn"), tile_str, tuple(snap.get("responding_seats") or []))
            if key == responded_key:
                continue
        act = choose_action(state, phase_info, melds, youcai_bikao, skip_hu,
                            chi_count, gang_kai)
        if act is None:
            continue  # pass 或无需动作：不 POST，窗口自然走满
        log("提交:", json.dumps(act, ensure_ascii=False),
            "phase=", phase, "god=", snap.get("god"))
        try:
            api("POST", "/api/games/%s/action" % gid, act)
            if act.get("action") == "gang":
                gang_pending = True  # 等杠后补牌（下一张 drawn）判杠开
            if phase in ("peng", "chi"):
                responded_key = (phase, snap.get("turn"), tile_str,
                                 tuple(snap.get("responding_seats") or []))
        except ApiError as e:
            code = _err_code(e)
            if e.status == 404:
                log("对局 %s 已不存在（404 %s），结束本场" % (gid, code))
                return
            if e.status != 409:
                log("action 错误:", e.status, code, e.body[:300])
                raise
            if act["action"] == "hu":
                skip_hu = True  # 误判能胡被拒，本次手牌回退出牌
            if act["action"] == "gang":
                gang_pending = False  # 杠被拒 → 别把下一张摸牌误当杠后补牌（杠开）
            log("409 拒绝:", code, json.dumps(act, ensure_ascii=False), e.body[:150])
        seq = 0


def _play_safe(gid, state, youcai_bikao):
    """包一层防线程静默崩溃：任何异常都记日志并返回 False（外层据此重试）；正常结束返回 True。"""
    try:
        play(gid, state, youcai_bikao)
        return True
    except Exception as e:
        log("对局 %s 线程异常退出: %r" % (gid, e))
        return False


def check_guide_version():
    """启动版本自检（指南 §2.2，免认证）：服务器指南版本高于本代码已知版本时告警并列出新 breaking。

    2026-09 就吃过这个亏：本仓库文档快照停在 v11，服务器实际已到 v29。
    """
    try:
        meta = api("GET", "/portal/api/guide/version", auth=False)
    except Exception as e:
        log("版本自检跳过:", repr(e))
        return
    try:
        srv = int(meta.get("version") or 0)
    except (TypeError, ValueError):
        log("版本自检跳过: version 解析失败", meta.get("version"))
        return
    if srv <= KNOWN_GUIDE_VERSION:
        log("接入指南版本自检 ok: 服务器 v%d ≤ 本代码已知 v%d" % (srv, KNOWN_GUIDE_VERSION))
        return
    log("⚠️ 服务器接入指南 v%d > 本代码已知 v%d（updated_at %s）"
        % (srv, KNOWN_GUIDE_VERSION, meta.get("updated_at")))
    for c in meta.get("changes") or []:
        try:
            cv = int(c.get("version") or 0)
        except (TypeError, ValueError):
            continue
        if c.get("type") == "breaking" and cv > KNOWN_GUIDE_VERSION:
            log("  BREAKING v%d: %s" % (cv, c.get("summary")))


def check_match_enabled():
    """GET /portal/api/features（免认证，v29）：自由匹配是否被管理员关闭。"""
    try:
        f = api("GET", "/portal/api/features", auth=False)
        return bool(f.get("match_enabled", True))
    except Exception as e:
        status = getattr(e, "status", "?")
        log("features 查询失败（按开启处理）: %s %r" % (status, e))
        return True


def match_room():
    """POST /api/match 入席自动匹配房（v13 全自动；v24 须门户绑定全局令牌；v29 可被关闭）。

    返回 room_id；永久条件（FEATURE_DISABLED / PORTAL_BINDING_REQUIRED / 显式上限过低 404）返回 None。
    """
    if not check_match_enabled():
        log("自由匹配已被管理员关闭（v29，永久条件）——改用参赛令牌或稍后再试")
        return None
    body = None
    if MATCH_M is not None or MATCH_ROUNDS is not None:
        # v15：显式上限 < 服务默认（M=10/Rounds=8）→ 永久 404 NO_ROOM_AVAILABLE，先本地拦掉
        if (MATCH_M is not None and MATCH_M < 10) or (MATCH_ROUNDS is not None and MATCH_ROUNDS < 8):
            log("--m/--r 低于服务默认（M=10/Rounds=8，v15）→ 必然 404；去掉参数或调高")
            return None
        body = {}
        if MATCH_M is not None:
            body["M"] = MATCH_M
        if MATCH_ROUNDS is not None:
            body["Rounds"] = MATCH_ROUNDS
    for attempt in range(30):
        try:
            r = api("POST", "/api/match", body)
            log("匹配成功 room=%s round_no=%s config=%s"
                % (r.get("room_id"), r.get("round_no"),
                   json.dumps(r.get("config"), ensure_ascii=False)))
            return r.get("room_id")
        except ApiError as e:
            code = _err_code(e)
            if code == "FEATURE_DISABLED":
                log("自由匹配已关闭（403 FEATURE_DISABLED），永久条件，退出")
                return None
            if code == "PORTAL_BINDING_REQUIRED":
                log("全局令牌未绑定门户身份（v24）——请用门户「我的 AI 身份」签发/轮换令牌")
                return None
            if code == "TOKEN_NOT_SCOPED":
                log("该令牌是参赛令牌，不能用于 /api/match（需全局令牌）")
                return None
            if code == "NO_ROOM_AVAILABLE" and body is not None:
                log("显式上限过低导致 NO_ROOM_AVAILABLE（永久条件）——去掉 --m/--r 或调高")
                return None
            # 瞬态/等待类：NO_ROOM_AVAILABLE(无房)、MATCH_BUSY(在途房满 50)、
            # MATCH_LIMIT_REACHED(16 场上限)、429 限速 → 退避自重试（等待期重复调用幂等返原房）
            if e.status in (404, 409, 429):
                wait = min(2.0 * (attempt + 1), 15.0)
                log("匹配暂不可用（%s %s）→ %.0fs 后重试 #%d：%s"
                    % (e.status, code, wait, attempt + 1, e.body[:120]))
                time.sleep(wait)
                continue
            log("匹配失败（%s %s）：%s" % (e.status, code, e.body[:200]))
            return None
        except Exception as e:
            # 网络抖动（URLError/超时）或响应体异常 → 退避重试，别让瞬时故障打死进程
            wait = min(2.0 * (attempt + 1), 15.0)
            log("匹配请求异常（%r）→ %.0fs 后重试 #%d" % (e, wait, attempt + 1))
            time.sleep(wait)
            continue
    log("匹配重试耗尽（无可用房/在途房满），退出")
    return None


def main():
    log("=== smart bot %s 启动 ===" % BOT_ID)
    check_guide_version()
    try:
        me = api("GET", "/api/me")
    except ApiError as e:
        if e.status == 401:
            log("令牌无效或已吊销（401 UNAUTHORIZED）——门户「我的 AI 身份」可轮换重取（v12）")
            return
        raise
    tid = me["tournament_id"]
    scoped = bool(tid)
    if not scoped:
        # 全局令牌（门户「我的 AI 身份」/管理面造号，v24 起唯一来源）：
        # 自动匹配房（kind=auto）玩家 API 直连 register/ready 恒 409 AUTO_MATCH_ONLY（v13），
        # 唯一入席入口是 POST /api/match。
        log("全局令牌（未绑定锦标赛）→ 走 POST /api/match 自动匹配")
        tid = match_room()
        if not tid:
            log("未能入席自动匹配房，退出")
            return
    # 进场：报名 + 到位（幂等）——仅参赛令牌路径。开赛后/阶段确认期返回 409（TOURNAMENT_STARTED 等）
    # 忽略即可（stage_open 的出席确认由下方主循环负责）；403（v24 PORTAL_BINDING_REQUIRED 等永久条件）
    # 也吞掉交主循环按 status 兜底，绝不因一个错误码杀进程。
    if scoped:
        for action in ("register", "ready"):
            try:
                api("POST", "/api/tournaments/%s/%s" % (tid, action))
            except ApiError as e:
                if e.status not in (403, 409):
                    raise
                log("进场 %s 被拒（%s %s），按最新 status 继续" % (action, e.status, _err_code(e)))
    # 读规则 config：有财必拷响（YouCaiBiKao）决定财神策略（赛程多阶段共用同一 config）。
    # 参赛令牌走 /me/rules 直达；全局令牌（自动房）该端点 400 TOKEN_NOT_SCOPED → 退回锦标赛详情。
    cfg = {}
    try:
        cfg = api("GET", "/api/tournaments/me/rules").get("config") or {}
    except ApiError:
        try:
            cfg = api("GET", "/api/tournaments/%s" % tid).get("config") or {}
        except ApiError:
            pass
    youcai_bikao = bool(cfg.get("YouCaiBiKao", cfg.get("you_cai_bi_kao", False)))
    set_poll_interval_for_m(cfg.get("M"))
    log("有财必拷响 YouCaiBiKao =", youcai_bikao,
        "| M =", cfg.get("M"), "| Rounds =", cfg.get("Rounds"), "| scoped =", scoped)

    # ---- v7 多阶段主循环 ----
    # 普通锦标赛按报名人数多阶段晋级（海选→…→决赛，v7 breaking）：顶层 status ∈
    # registering | running | stage_open | stage_done | finished | closed | void。
    # - running：扫 /api/me active_games 并发打新场（每场一线程）。决赛平局自动加赛时
    #   新 game_id 静默出现、running 态延续——必须持续扫 active 接续，不能打完一波就退出。
    # - stage_open（阶段 2+ / 崩溃重赛确认期）：ready = 阶段出席确认，不跨阶段继承，须每阶段
    #   重新确认；名单外（海选已淘汰）409 NOT_QUALIFIED → 本 bot 止步，退出。
    # - stage_done / 阶段间隙：active_games 为空 ≠ 结束/异常，须继续轮询 status 直至
    #   finished/closed/void（候补/降档/中断待重赛都可能长时间无场）。
    running = {}          # gid -> {"thread", "ok":线程写回, "retries"}
    done = set()          # 已正常打完 / 放弃重试的 gid，不再重复拉起
    confirmed_stage = None
    last_status = last_stage = None
    heartbeat = time.time()
    retire = None
    while True:
        try:
            me = api("GET", "/api/me")
            st = api("GET", "/api/tournaments/%s" % tid)
        except ApiError as e:
            if e.status == 429:
                time.sleep(1.0)  # 轮询超频退避后重试，不崩主循环
                continue
            if e.status == 404:
                # v13：自动房整场打完（finished 约 60s 宽限）自动关停 → 房间/对局一律 404
                log("房间 %s 已不存在（404 %s），终止" % (tid, _err_code(e)))
                retire = "closed"
                break
            raise
        status = st.get("status")
        stage = (st.get("stage") or {}).get("no")
        active = [g["game_id"] for g in me.get("active_games", [])]
        if not scoped:
            # 全局令牌（自动匹配房/多房在途）：/api/me active_games 是全站并集，
            # 按本房 my_games 过滤，别把别的房的对局拉起来。
            mine = set(st.get("my_games") or [])
            if mine:
                active = [g for g in active if g in mine]

        # 收尾已结束线程；异常退出且对局仍 active 时重试（每场最多 3 次），防静默丢场
        for gid in list(running):
            if running[gid]["thread"].is_alive():
                continue
            info = running.pop(gid)
            if info["ok"]:
                done.add(gid)
                log("对局正常结束:", gid)
            else:
                info["retries"] += 1
                if info["retries"] < 3:
                    log("对局 %s 线程异常，重试 #%d" % (gid, info["retries"]))
                else:
                    done.add(gid)
                    log("对局 %s 重试 3 次仍失败，放弃" % gid)
        # 终态判定放在「本场线程都已收尾」之后：status 转 finished/closed 时可能还有在途场次，
        # 提前退出会把它们丢掉（自动房整场打完有约 60s 宽限）。
        if status in ("finished", "closed", "void") and not active and not running:
            log("终止:", status)
            retire = status
            break
        # 拉起新对局（每局一个线程并发打，M 并发局串行会互相超时；决赛加赛新 ID 静默出现也被覆盖）
        for gid in active:
            if gid in running or gid in done:
                continue
            info = {"thread": None, "ok": False, "retries": 0}

            def runner(gid=gid, info=info):
                info["ok"] = _play_safe(gid, GameState(), youcai_bikao)

            t = threading.Thread(target=runner, daemon=True)
            info["thread"] = t
            running[gid] = info
            log("对局:", gid)
            t.start()

        # stage_open 出席确认（每阶段只 POST 一次；失败未记录 confirmed，下轮重试）
        if status == "stage_open" and confirmed_stage != stage:
            try:
                r = api("POST", "/api/tournaments/%s/ready" % tid)
                confirmed_stage = stage
                log("阶段出席确认 ok stage=%s %r" % (stage, r))
            except ApiError as e:
                if _err_code(e) == "NOT_QUALIFIED":
                    log("未晋级阶段 %s（NOT_QUALIFIED），本赛事止步" % stage)
                    retire = "not_qualified"
                    break
                log("阶段确认异常（稍后重试）: %s %s" % (e.status, (e.body or "")[:120]))

        if (status, stage) != (last_status, last_stage):
            log("status=%s stage=%s active=%d running=%d"
                % (status, stage, len(active), len(running)))
            last_status, last_stage = status, stage
        # 阶段间隙 / 候补 / 加赛编排 / 自动房等对手：无 active 也无存活线程时静默轮询，心跳防误判卡死
        if not running and not active and status in ("registering", "running", "stage_open", "stage_done"):
            now = time.time()
            if now - heartbeat > 600:
                heartbeat = now
                log("空闲无对局（status=%s），继续等待下一阶段/加赛/确认窗口/匹配对手" % status)
        time.sleep(1.0)

    # 退出前给存活线程一点收尾时间（多阶段场景主循环常驻，正常走到这里已是终态/NOT_QUALIFIED）
    for info in running.values():
        info["thread"].join(timeout=3)
    log("退出:", retire or "无")
    LOG.close()


if __name__ == "__main__":
    main()
