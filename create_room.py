"""创建测试房间并提取 4 个令牌（需先通过 netease-auth-login 登录）。

用法：
    python create_room.py                       # 默认 M=10 / 局数=1 / 底分=1
    python create_room.py --m 4 --r 3           # 指定 同时场数 M / 每场局数 Rounds
    python create_room.py --r 8 --ycb           # 8 局/场 + 有财必拷响

为什么需要这些参数：
- **Rounds≥2** 才会出现 v31 的「局间 5s 停顿（phase=settled）」与跨局连庄（流局庄家连庄），
  单局房测不到；策略迭代（财飘/弃胡/连庄）也需要多局房。
- `--ycb` 用于有财必拷响（YouCaiBiKao）专项 A/B。

实现说明（2026-09-18 改）：
- 直接调用门户 API `POST /portal/api/test-rooms`（页面会话 cookie），body 用**蛇形键**
  （`m/rounds/base_score/you_cai_bi_kao/peng_timeout_sec/chi_timeout_sec/discard_timeout_sec/timeout_min`），
  响应含 `room_id` 与 4 个 `tokens` —— 比抓 DOM 文本可靠（旧做法等 3s 抓 64-hex，实测会因渲染时序偶发失败）。
- 产物：data/room.txt、data/tokens.txt、data/room_config.txt。
"""

import argparse
import json
import sys

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, ".")

from playwright.sync_api import sync_playwright
from netease_auth_login import NeteaseAuthLogin

TARGET = "https://10.240.169.190:18080/portal/"
API = TARGET + "api/test-rooms"


def parse_args(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--m", type=int, default=10, help="同时场数上限 M（默认 10）")
    ap.add_argument("--r", type=int, default=1, help="每场局数 Rounds（≥2 才有局间停顿/连庄）")
    ap.add_argument("--base", type=int, default=1, help="底分")
    ap.add_argument("--ycb", action="store_true", help="有财必拷响")
    ap.add_argument("--peng", type=int, default=1, help="碰窗口秒")
    ap.add_argument("--chi", type=int, default=1, help="吃窗口秒")
    ap.add_argument("--discard", type=int, default=3, help="出牌思考秒")
    ap.add_argument("--timeout-min", type=int, default=30, help="开赛超时（分钟）")
    return ap.parse_args(argv[1:])


def main():
    args = parse_args(sys.argv)
    payload = {
        "m": args.m, "rounds": args.r, "base_score": args.base,
        "you_cai_bi_kao": bool(args.ycb),
        "peng_timeout_sec": args.peng, "chi_timeout_sec": args.chi,
        "discard_timeout_sec": args.discard, "timeout_min": args.timeout_min,
    }
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(ignore_https_errors=True)
        page = context.new_page()
        page.goto(TARGET, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(2000)
        page.click("a.btn-primary", timeout=10000)
        page.wait_for_url(lambda u: "login.netease.com" in u, timeout=30000)
        page.wait_for_timeout(2000)
        auth = NeteaseAuthLogin()
        result = auth.login(page=page, target_url=TARGET, use_token_api=False,
                            read_cookie=False, manual_input_on_failure=False)
        print("LOGIN:", result.success)
        page.wait_for_timeout(2500)
        page.locator('[data-nav="testrooms"]').first.click(timeout=15000)
        page.wait_for_timeout(1500)

        print("POST", API, json.dumps(payload, ensure_ascii=False))
        resp = page.request.post(API, data=json.dumps(payload),
                                 headers={"Content-Type": "application/json"})
        print("HTTP", resp.status)
        body = resp.text()
        if resp.status != 200:
            print("创建失败:", body[:500])
            browser.close()
            return 1
        d = json.loads(body)
        rid = d.get("room_id")
        toks = d.get("tokens") or []
        if not rid or len(toks) < 4:
            print("响应缺 room_id/tokens:", body[:500])
            browser.close()
            return 1
        with open("data/room.txt", "w", encoding="utf-8", newline="\n") as f:
            f.write("room: %s\n" % rid)
        with open("data/tokens.txt", "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(toks[:4]) + "\n")
        cfg = "M=%s · 局数=%s · 底分=%s · YCB=%s · 碰%s/吃%s/出牌%s · 开赛超时%s分" % (
            d.get("m"), d.get("rounds"), d.get("base_score"), d.get("you_cai_bi_kao"),
            d.get("peng_timeout_sec"), d.get("chi_timeout_sec"),
            d.get("discard_timeout_sec"), d.get("timeout_min"))
        with open("data/room_config.txt", "w", encoding="utf-8", newline="\n") as f:
            f.write(cfg + "\n")
        print("房规:", cfg)
        print("创建成功 room_id:", rid, "令牌数:", len(toks))
        for t in toks[:4]:
            print(t)
        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

