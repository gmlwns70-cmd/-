@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo 처음 실행이라 설치 중이에요. 몇 분 걸려요...
  python -m venv .venv
  if errorlevel 1 goto nopython
)
call .venv\Scripts\activate
python -m pip install -q -r requirements.txt
if not exist .env copy .env.example .env >nul
echo 브라우저에 대시보드가 열려요. 이 검은 창은 닫지 마세요.
python -m streamlit run app.py
pause
exit /b 0
:nopython
echo 파이썬이 설치되어 있지 않아요. README 1단계를 먼저 해 주세요.
pause
