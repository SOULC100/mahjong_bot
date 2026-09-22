"""牌编码口径回归测试：**协议字母 ↔ 花色** 必须按平台口径（2026-09-22 定案）。

背景：本仓 `tiles.py` 早期注释把 t/b 的花色写反了（写「1t=筒、1b=条」，实际相反），
导致复盘/文档里把 `9t` 说成「九筒」（其实是**九条**）。判据与线上行为不受影响
（本规则番型与花色无关，索引顺序是内部约定、协议串收发一致），但**面向人的文字会误导**。

平台口径的证据（服务端门户自己的渲染代码，抓自 `GET /portal/tiles.js`）：
1. `tileSVG()`：`suit === "b"` → `<circle>`（圆点，筒）；否则 → `<rect rx="1.3">`（竹条，条）；
   `suit === "w"` → 「萬」字。`TILE_COLOR = { w, b, t }` 三色。
2. `TILE_RECT` 贴图取片：`"1b": [0, 0, …]` 落在底图**行0**、`"1t": [0, 305, …]` 落在**行2**，
   而注释写明「行0=筒 行1=万 行2=条」。
3. 门户番型计算器：`FC_ALL_TILES` 由 `["w","b","t"]` 顺序生成，`slice(9,18)` 标「筒子」、
   `slice(18,27)` 标「条子」。

跑法：python tests/test_tile_coding.py
"""

import os
import sys

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from mahjong.tiles import (tile_from_str, tile_to_str, tile_name, suit,    # noqa: E402
                           is_number, LAIZI_INDEX, NUM_TILES)

ok = True


def ck(name, got, want):
    global ok
    good = got == want
    ok = ok and good
    print("[%s] %s: got=%r want=%r" % ("OK  " if good else "FAIL", name, got, want))


# ---- 1. 协议字母 → 花色（平台口径：w=万、t=条、b=筒）----
ck("1t 是条（九条 = 9t）", tile_name(tile_from_str("9t")), "9条")
ck("1b 是筒（九筒 = 9b）", tile_name(tile_from_str("9b")), "9筒")
ck("1w 是万", tile_name(tile_from_str("1w")), "1万")
ck("round-trip 9t", tile_to_str(tile_from_str("9t")), "9t")
ck("round-trip 9b", tile_to_str(tile_from_str("9b")), "9b")

# ---- 2. 内部索引区间（保持本仓既有顺序，改动会波及全仓）----
ck("索引 9~17 = 协议 t（条）", [tile_to_str(t) for t in (9, 17)], ["1t", "9t"])
ck("索引 18~26 = 协议 b（筒）", [tile_to_str(t) for t in (18, 26)], ["1b", "9b"])
ck("suit(9) = 1（条）", suit(9), 1)
ck("suit(18) = 2（筒）", suit(18), 2)
ck("字牌区间 27~33 不变", [tile_to_str(t) for t in (27, 33)], ["东", "白"])
ck("财神 = 白 = 33", LAIZI_INDEX, 33)

# ---- 3. 花色名与协议字母必须自洽（防再次写反）----
bad = []
for t in range(NUM_TILES):
    s = tile_to_str(t)
    nm = tile_name(t)
    if t < 9 and not (s.endswith("w") and nm.endswith("万")):
        bad.append((s, nm))
    elif 9 <= t < 18 and not (s.endswith("t") and nm.endswith("条")):
        bad.append((s, nm))
    elif 18 <= t < 27 and not (s.endswith("b") and nm.endswith("筒")):
        bad.append((s, nm))
ck("全 34 张的「协议字母 ↔ 花色名」自洽", bad, [])

# ---- 4. 顺子只在同花色内（与花色命名无关，但锁住索引顺序未被误改）----
ck("9t 与 1b 不同花色（不能组顺子）", suit(tile_from_str("9t")) == suit(tile_from_str("1b")), False)
ck("数牌判定：白不是数牌", is_number(LAIZI_INDEX), False)

print("\n" + ("ALL PASS" if ok else "SOME FAILED"))
sys.exit(0 if ok else 1)
