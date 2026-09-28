@echo off
REM ── 自动匹配赛果收集器：常驻看门狗 ─────────────────────────────────────────
REM 作用：每 60s 检查一次收集器常驻是否在跑，不在就用 ensure 拉起（幂等 PID 锁）。
REM 为什么需要它：ensure 拉起的常驻在父 shell 退出后会被回收（2026-09-23 实测），
REM               所以"下次触发自由匹配时自动收集"要靠一个**活得住的宿主**来保证。
REM 用法：双击本文件 / 或挂计划任务（登录时启动）：
REM   schtasks /Create /TN MahjongAutoCollect /SC ONLOGON /RL LIMITED ^
REM     /TR "H:\L22Trunk\mahjong_bot\collect_watch.bat"
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
echo [%date% %time%] 看门狗启动：每 60s 确保收集器常驻（Ctrl-C 停）
:loop
python collect_auto.py ensure --interval 300
timeout /t 60 /nobreak >nul
goto loop
