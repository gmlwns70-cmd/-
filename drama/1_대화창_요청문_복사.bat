@echo off
chcp 65001 > nul
cd /d "%~dp0"
echo ==================================================
echo    1단계: Claude 대화창용 요청문 만들기
echo ==================================================
set /p IDEA=한 줄 아이디어 (그냥 Enter = 대화창에서 직접 적기): 
set /p EPS=회차 수 (그냥 Enter = 1): 
if "%EPS%"=="" set "EPS=1"
if "%IDEA%"=="" (
  python main.py chat-prompt --episodes %EPS%
) else (
  python main.py chat-prompt --idea "%IDEA%" --episodes %EPS%
)
echo.
pause
