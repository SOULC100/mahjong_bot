@echo off
chcp 936 >nul 2>&1 <nul
setlocal
cd /d "%~dp0"

echo ==========================================
echo    mahjong_bot  快速提交
echo ==========================================
echo.

rem ---------- 0. 检查仓库 ----------
git rev-parse --is-inside-work-tree >nul 2>&1 <nul
if errorlevel 1 (
    echo [错误] 当前目录不是 git 仓库。
    echo        请确认 commit.bat 放在仓库根目录下。
    echo.
    pause
    exit /b 1
)

rem ---------- 1. 显示改动 ----------
echo [1/4] 当前改动：
echo.
git status --short <nul
echo.

rem 用临时文件判断有无改动。
rem 注意：git 子进程会占用标准输入，必须加 ^<nul，否则下面的 set /p 读不到你输入的内容。
set "STTMP=%TEMP%\mahjong_bot_status.tmp"
git status --porcelain > "%STTMP%" 2>nul <nul
set HASCHANGE=
for /f "usebackq delims=" %%i in ("%STTMP%") do set HASCHANGE=1
del "%STTMP%" >nul 2>&1
if not defined HASCHANGE (
    echo 没有需要提交的改动，无需提交。
    echo.
    pause
    exit /b 0
)

rem ---------- 2. 取提交说明 ----------
if not "%~1"=="" (
    set "MSG=%~1"
) else (
    set "MSG="
    set /p "MSG=[2/4] 请输入提交说明（直接回车＝取消）: "
)

if not defined MSG (
    echo.
    echo [取消] 没有输入提交说明，未做任何改动。
    echo.
    pause
    exit /b 0
)

rem ---------- 3. 暂存 + 提交 ----------
echo.
echo [3/4] 暂存并提交...
echo.
git add -A
if errorlevel 1 goto FAIL

rem 安全网：凭据文件绝不允许进仓库
git diff --cached --name-only | findstr /i /c:"tokens.txt" /c:"xuanwu_token.txt" /c:"portal_session.json" >nul
if not errorlevel 1 (
    echo.
    echo [危险] 检测到凭据文件进入了暂存区，已中止提交！
    echo        请检查 .gitignore 是否被改动过。
    git reset >nul
    echo.
    pause
    exit /b 1
)

git commit -m "%MSG%"
if errorlevel 1 goto FAIL

rem ---------- 4. 推送 ----------
echo.
echo [4/4] 推送到 GitHub...
echo.
git push
if errorlevel 1 (
    echo.
    echo [提示] 提交已经在本地完成了，只是推送失败。
    echo        网络或 SSH 恢复后，单独执行一次 git push 即可。
    echo.
    pause
    exit /b 1
)

echo.
echo ==========================================
echo   完成！已提交并推送到 GitHub
echo ==========================================
git log --oneline -1
echo.
pause
exit /b 0

:FAIL
echo.
echo [错误] 操作失败，请查看上面的报错信息。
echo.
pause
exit /b 1