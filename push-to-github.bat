@echo off
chcp 65001 >nul
title Push dafeiyu to GitHub
cd /d "%~dp0"

echo ==========================================================
echo   Folder : %CD%
echo   Remote : see below
echo ==========================================================
echo.
git remote -v
echo.
echo ---- Commits waiting to be pushed ----
git log --oneline origin/main..HEAD 2>nul
echo.
echo ---- Pushing (a browser window may open for GitHub login) ----
echo.
set GIT_TERMINAL_PROMPT=1
git push -u origin main
if errorlevel 1 goto failed

echo.
echo ================= SUCCESS =================
echo Code is now on GitHub.
goto end

:failed
echo.
echo ================= FAILED ==================
echo 1) Login cancelled, or not logged in.
echo    Run this again and choose "Sign in with your browser".
echo.
echo 2) 403 Permission denied.
echo    The origin repo is not under your account.
echo    Create an empty repo on your account, then run:
echo      git remote set-url origin https://github.com/YOUR_NAME/dafeiyu.git
echo      git push -u origin main
echo.
echo 3) Connection reset or timeout.
echo    Turn on your proxy and set it for git, then retry:
echo      git config --global http.proxy http://127.0.0.1:7890

:end
echo.
pause
