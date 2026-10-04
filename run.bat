@echo off
chcp 65001 > nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" goto :not_installed

echo ==================================================
echo    유튜브 영상 자동 제작 도구를 시작합니다.
echo    잠시 후 인터넷 창이 자동으로 열려요.
echo    주소: http://localhost:8501
echo    프로그램을 끄려면 이 검은 창을 닫으세요.
echo ==================================================
start "" cmd /c "timeout /t 4 /nobreak >nul & start http://localhost:8501"
".venv\Scripts\python.exe" -m streamlit run app.py
pause
exit /b 0

:not_installed
echo [안내] 아직 설치가 안 되어 있어요. install.bat 을 먼저 더블클릭해 주세요.
pause
exit /b 1
