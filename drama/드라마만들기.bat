@echo off
chcp 65001 > nul
cd /d "%~dp0"
set "PY=python"
if exist "..\.venv\Scripts\python.exe" set "PY=..\.venv\Scripts\python.exe"
echo ==================================================
echo    숏폼 로맨스 드라마 대본 + 컷 프롬프트 생성기
echo ==================================================
set /p IDEA=한 줄 아이디어를 입력하고 Enter: 
set /p EPS=회차 수 (그냥 Enter = 3): 
if "%EPS%"=="" set "EPS=3"
"%PY%" main.py --idea "%IDEA%" --episodes %EPS%
echo.
echo 결과는 output 폴더에 있어요.
pause
