"""真机对局数据校验：吃摊 ≤2（v25）、抓打圈豁免（v26）、番型口径对拍（v21）。

用法：
    python verify_live.py [归档目录]         # 默认取 data/fetch_<room.txt 的房号>
    python verify_live.py data/_smoke_fetch_t_xxx_1234

数据来源：fetch_room_stats.py 归档的 events_*.json（GET /api/test-rooms/{id}/games/{batch}/events）。

注意：一个 batch 的事件流会被拆成多个 block 续传（seq_start/seq_end），同一 round_no 的
多个 block 必须**连续回放**（start_hands 只在首块初始化）。

校验项：
  A. 每局每座位 chi 事件数 ≤ 2（v25 服务端强制，越限应被 409 拒）
  B. 抓打圈（v26）：圈内（打财神者 D 的圈）非 D 座位不得出现 peng/chi/明杠；
     圈内非 D 座位的出牌必须等于该座位刚摸的牌
  C. 番型对拍（v21）：回放重建胡牌者 14 张（含副露）+ 动作链 → mahjong.fan.calc_fan 与
     服务器 round_ended.data.fan 比对；再与免认证 fan-calc 端点比对（权威口径）
"""
import glob
import io
import json
import os
import ssl
import sys
import time
import urllib.request
from collections import Counter, OrderedDict

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from mahjong.tiles import tile_from_str, tile_to_str, LAIZI_INDEX, NUM_TILES
from mahjong.fan import calc_fan, any_draw_win

LAIZI_STR = "白"
SERVER = "https://10.240.169.190:18080"
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE

OUT = io.TextIOWrapper(open(os.path.join(ROOT, "data", "_verify_report.txt"), "wb"), encoding="utf-8")


def op(*a):
    print(*a, file=OUT, flush=True)


def fan_calc(hand13, draw, chain_count, chain_piao):
    body = {"hand": list(hand13), "draw": draw, "base": 1,
            "chain": {"count": chain_count, "piao": chain_piao}}
    data = json.dumps(body).encode()
    for attempt in range(5):
        req = urllib.request.Request(SERVER + "/portal/api/tools/fan-calc", data=data, method="POST")
        req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=20, context=CTX) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(0.5 * (attempt + 1))
                continue
            return {"_http": e.code}
        except Exception as e:
            return {"_err": repr(e)}
    return {"_err": "429"}


class Replay:
    def __init__(self):
        self.hands = None
        self.last_drawn = [None] * 4
        self.chain = [0] * 4
        self.chi_seat = [0] * 4
        self.melds = [[] for _ in range(4)]
        self.kongs = [0] * 4
        self.circle = None
        self.viol = Counter()
        self.viol_samples = []
        self.hus = []

    def init(self, start_hands):
        self.hands = []
        for sh in start_hands:
            h = [0] * NUM_TILES
            for s in sh:
                h[tile_from_str(s)] += 1
            self.hands.append(h)
        self.last_drawn = [None] * 4
        self.last_replenish = [False] * 4   # 当前手上那张牌是否「杠后补牌」（v33 判定杠开用）
        self.chain = [0] * 4
        self.chi_seat = [0] * 4
        self.melds = [[] for _ in range(4)]
        self.kongs = [0] * 4
        self.circle = None

    def _is_baotou(self, seat):
        """赢家的**暗手**摸前是否「任意摸都胡」（真·爆头）；带副露数。"""
        pre = list(self.hands[seat])
        d = self.last_drawn[seat]
        if not d:
            return False
        idx = tile_from_str(d)
        pre[idx] -= 1
        if pre[idx] < 0:
            return False
        return bool(any_draw_win(pre, len(self.melds[seat])))

    def bad(self, kind, info):
        self.viol[kind] += 1
        if len(self.viol_samples) < 8:
            self.viol_samples.append((kind, info))

    def feed(self, ev, round_no):
        t = ev.get("type")
        seat = ev.get("seat", -1)
        tile = ev.get("tile") or ""
        data = ev.get("data") or {}
        if self.hands is None:
            return
        if t == "tile_drawn" and 0 <= seat < 4 and tile:
            self.hands[seat][tile_from_str(tile)] += 1
            self.last_drawn[seat] = tile
            self.last_replenish[seat] = bool(data.get("gang_replenish"))  # v33：杠后补牌
            if self.circle == seat:
                self.circle = None          # 一圈回到打财神者本人 → 圈结束
        elif t == "tile_discarded" and 0 <= seat < 4 and tile:
            idx = tile_from_str(tile)
            if self.circle is not None and seat != self.circle:
                if self.last_drawn[seat] and tile != self.last_drawn[seat]:
                    self.bad("v26_discard", (round_no, seat, tile, self.last_drawn[seat]))
            if tile == LAIZI_STR:
                if self.hands[seat][idx] - 1 >= 1:
                    self.chain[seat] += 1
                else:
                    self.chain[seat] = 0
            else:
                self.chain[seat] = 0
            self.hands[seat][idx] -= 1
            if data.get("catch_play") and tile == LAIZI_STR:
                self.circle = seat
            elif self.circle is not None and seat == self.circle:
                self.circle = None          # 豁免方打非财神 → 链断且圈解除
        elif t == "chi" and 0 <= seat < 4:
            self.chi_seat[seat] += 1
            if self.chi_seat[seat] > 2:
                self.bad("v25_chi", (round_no, seat, self.chi_seat[seat]))
            if self.circle is not None and seat != self.circle:
                self.bad("v26_act", (round_no, "chi", seat, self.circle))
            for s in (data.get("tiles") or []):
                if s != tile:
                    self.hands[seat][tile_from_str(s)] -= 1
            self.melds[seat].append(list(data.get("tiles") or []))
            self.last_drawn[seat] = None
            self.last_replenish[seat] = False
            self.chain[seat] = 0
        elif t == "peng" and 0 <= seat < 4:
            if self.circle is not None and seat != self.circle:
                self.bad("v26_act", (round_no, "peng", seat, self.circle))
            if tile:
                self.hands[seat][tile_from_str(tile)] -= 2
                self.melds[seat].append([tile] * 3)
            self.last_drawn[seat] = None
            self.last_replenish[seat] = False
            self.chain[seat] = 0
        elif t in ("gang", "angang", "minggang", "bugang") and 0 <= seat < 4:
            if self.circle is not None and seat != self.circle and t == "minggang":
                self.bad("v26_act", (round_no, t, seat, self.circle))
            if tile:
                # 2026-09-21 修正：线上把三种杠都发成 `type="gang"`，靠 `data.kind` 区分：
                #   an=暗杠（手里 4 张→副露 4 张） / ming=明杠（手里 3 张 + 别人弃牌） / bu=补杠（碰过 + 手里第 4 张）
                # 旧实现一律按「手里 -3」处理 → 暗杠少扣 1、补杠多扣 2 → 手牌负计数、
                # 进而把杠局的全手牌重建错，导致 calc_fan 对拍假 DIFF（2026-09-21 真机 100 局里 4 例）。
                kind = str(data.get("kind") or "").lower()
                idx = tile_from_str(tile)
                if t == "angang" or kind in ("an", "angang"):
                    self.hands[seat][idx] -= 4
                    self.melds[seat].append([tile] * 4)
                elif t == "bugang" or kind in ("bu", "bugang"):
                    self.hands[seat][idx] -= 1          # 碰的 3 张已在副露里
                    for i, m in enumerate(self.melds[seat]):
                        if len(m) == 3 and m and m[0] == tile:
                            self.melds[seat][i] = [tile] * 4
                            break
                    else:
                        self.melds[seat].append([tile] * 4)
                else:                                    # ming（默认）：手里 3 张 + 弃牌
                    self.hands[seat][idx] -= 3
                    self.melds[seat].append([tile] * 4)
                self.kongs[seat] += 1
            self.chain[seat] += 1
            self.last_drawn[seat] = None
            self.last_replenish[seat] = False
        elif t == "round_ended" and not data.get("draw") and 0 <= seat < 4:
            full = list(self.hands[seat])
            for m in self.melds[seat]:
                for s in m:
                    full[tile_from_str(s)] += 1
            # 杠（4 张一副露）在「4 面子+将」结构里只算 3 张：去掉那 1 张，全手才回到 14 张等效。
            # v32（2026-09-12）修的正是「杠爆」判定，这里必须能验杠局，否则杠局会被整体跳过。
            n_kong = 0
            for m in self.melds[seat]:
                if len(m) == 4:
                    full[tile_from_str(m[0])] -= 1
                    n_kong += 1
            self.hus.append({
                "round_no": data.get("round_no", round_no),
                "winner": seat,
                "hand": full,
                "n_melds": len(self.melds[seat]),
                "melds": [list(m) for m in self.melds[seat]],
                "kongs": n_kong,
                "drawn": self.last_drawn[seat],
                "chain": self.chain[seat],
                "server_fan": data.get("fan"),
                "server_detail": data.get("detail"),
                "dealer": data.get("dealer"),
                # 2026-09-21 修正：这两个标记必须**按事件**判定，不能靠"有没有杠"猜：
                #  · gang_kai：只有「这张牌是杠后补牌」才算杠开（v33 的 tile_drawn.data.gang_replenish）
                #  · baotou  ：用**暗手**（不含副露）的摸前 13-3n 张判「任意摸都胡」，且要带上副露数
                #    旧实现用重建后的 14 张等效手牌 + 硬编码 melds=0 → 杠局的番型对拍全是假 DIFF。
                "gang_kai": bool(self.last_replenish[seat]),
                "baotou": self._is_baotou(seat),
            })
        for i in range(4):
            if self.hands[i] and any(c < 0 for c in self.hands[i]):
                self.bad("hand_neg", (round_no, i, t, tile))
                self.hands[i] = [max(0, c) for c in self.hands[i]]


def main():
    room = None
    p = os.path.join(ROOT, "data", "room.txt")
    if os.path.exists(p):
        room = io.open(p, encoding="utf-8").read().strip().split(":")[-1].strip()
    arch = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "data", "fetch_%s" % room)
    files = sorted(glob.glob(os.path.join(arch, "events_*.json")))
    op("=== 对局校验 %s（%d 个 batch 文件） ===" % (arch, len(files)))

    tot_rounds = tot_hu = 0
    fan_ok = fan_bad = api_ok = api_bad = 0
    all_viol = Counter()
    details = Counter()
    bad_samples = []
    for fp in files:
        d = json.load(open(fp, encoding="utf-8"))
        op("\n-- batch %s game_id=%s status=%s rounds=%s"
           % (d.get("batch"), d.get("game_id"), d.get("status"),
              json.dumps(d.get("rounds"), ensure_ascii=False)))
        for r in (d.get("rounds") or []):
            tot_rounds += 1
            if r.get("winner", -1) >= 0:
                tot_hu += 1

        groups = OrderedDict()
        for blk in d.get("blocks") or []:
            groups.setdefault(blk.get("round_no"), []).append(blk)
        for round_no, blks in groups.items():
            rp = Replay()
            for bi, blk in enumerate(blks):
                evs = blk.get("events") or []
                if bi == 0:
                    shs = blk.get("start_hands")
                    if not (isinstance(shs, list) and len(shs) >= 4
                            and all(isinstance(x, list) for x in shs)):
                        op("   [跳过] round=%s 无 start_hands（占位 block）" % round_no)
                        break
                    rp.init(shs)
                for ev in evs:
                    rp.feed(ev, round_no)
            all_viol.update(rp.viol)
            for k, item in rp.viol_samples:
                op("   [违规/%s] %s" % (k, item))
            for h in rp.hus:
                hand = h["hand"]
                n = sum(hand)
                if n != 14 or not h["drawn"]:
                    op("   [跳过] round=%s winner=%s 全手=%d 副露=%d 杠=%d 摸=%s"
                       % (h["round_no"], h["winner"], n, h["n_melds"], h["kongs"], h["drawn"]))
                    continue
                h13 = list(hand)
                h13[tile_from_str(h["drawn"])] -= 1
                # baotou / gang_kai 由 Replay 按事件判定（2026-09-21 修正，见 Replay.feed 的注释）
                baotou = h.get("baotou")
                if baotou is None:                      # 老归档兜底
                    baotou = any_draw_win(h13, h.get("n_melds", 0))
                gang_kai = h.get("gang_kai")
                if gang_kai is None:
                    gang_kai = max(0, h["kongs"]) > 0
                # 动作链拆分（2026-09-20）：服务端 chain = 飘 + 杠 的累计次数，两者都是 ×2。
                # 旧代码把整条 chain 当成 piao_count 传（当时真机 chain 恒为 0 所以看不出来），
                # 一旦出现财飘或扛链就会算错——这里按 kongs 拆出杠、其余算飘。
                piao_n = max(0, h["chain"] - h["kongs"])
                gang_n = max(0, h["kongs"])
                local = calc_fan(hand, gang_kai=gang_kai, piao_count=piao_n, baotou=baotou)
                srv = h["server_fan"]
                ok = (local == srv)
                fan_ok += ok
                fan_bad += (not ok)
                for det in (h["server_detail"] or []):
                    details[det] += 1
                h13s = [tile_to_str(i) for i in range(NUM_TILES) for _ in range(h13[i])]
                api = fan_calc(h13s, h["drawn"], h["chain"], piao_n)
                a_fan = api.get("fan")
                api_ok += (a_fan == srv)
                api_bad += (a_fan != srv)
                line = ("   round=%s winner=%s dealer=%s 手牌=%s 摸=%s chain=%d(飘%d/杠%d) baotou=%s | "
                        "服务器 x%s %s | calc_fan x%s %s | fan-calc x%s %s"
                        % (h["round_no"], h["winner"], h["dealer"], "".join(h13s), h["drawn"],
                           h["chain"], piao_n, gang_n, baotou, srv, h["server_detail"], local,
                           "OK" if ok else "**DIFF**", a_fan, "OK" if a_fan == srv else "**DIFF**"))
                op(line)
                if not ok or a_fan != srv:
                    bad_samples.append(line)
    op("\n==== 汇总 ====")
    op("局数=%d 有人胡=%d" % (tot_rounds, tot_hu))
    op("番型分布（服务器 detail）: %s" % dict(details))
    op("calc_fan vs 服务器 fan: OK=%d DIFF=%d" % (fan_ok, fan_bad))
    op("fan-calc端点 vs 服务器 fan: OK=%d DIFF=%d" % (api_ok, api_bad))
    op("违规计数: %s" % (dict(all_viol) or "无"))
    if bad_samples:
        op("\n!! 差异样本:")
        for l in bad_samples[:10]:
            op(l)
    OUT.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
