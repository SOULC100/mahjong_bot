"""创建测试房间并提取 4 个令牌（需先通过 netease-auth-login 登录）。"""

import json
import re
import sys

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, ".")

from playwright.sync_api import sync_playwright
from netease_auth_login import NeteaseAuthLogin

TARGET = "https://10.240.169.190:18080/portal/"


def main():
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
        page.wait_for_timeout(3000)

        # 进入测试房间
        page.locator('[data-nav="testrooms"]').first.click(timeout=15000)
        page.wait_for_timeout(2000)
        # 若有活跃房间，点「重新生成令牌」；否则点「创建」
        try:
            btn = page.locator("button", has_text="重新生成令牌").first
            if btn.count() > 0 and btn.is_visible():
                btn.click(timeout=5000)
                page.wait_for_timeout(2500)
                print("点了重新生成令牌")
            else:
                page.locator("button", has_text="创建").first.click(timeout=10000)
                page.wait_for_timeout(3000)
                print("点了创建")
        except Exception:
            page.locator("button", has_text="创建").first.click(timeout=10000)
            page.wait_for_timeout(3000)
            print("点了创建(回退)")

        # 令牌以 64 位 hex 显示在页面上（仅显示一次），从 body 提取
        body = page.inner_text("body")
        tokens = re.findall(r"\b[0-9a-f]{64}\b", body)
        if len(tokens) < 4:
            with open("data/debug_body.txt", "w", encoding="utf-8") as f:
                f.write(body)
            print("提取令牌失败，body 已写到 data/debug_body.txt")
            return 1
        # 房间 id 从 body 里匹配 t_xxx
        room_id = None
        m = re.search(r"\b(t_[0-9a-f]{12})\b", body)
        room_id = m.group(1) if m else "unknown"
        with open("data/room.txt", "w", encoding="utf-8", newline="\n") as f:
            f.write("room: %s\n" % room_id)
        with open("data/tokens.txt", "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(tokens[:4]) + "\n")
        print("创建成功 room_id:", room_id, "令牌数:", len(tokens))
        for t in tokens[:4]:
            print(t)
        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
