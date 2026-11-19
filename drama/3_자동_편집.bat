@echo off
chcp 65001 > nul
cd /d "%~dp0"
echo ==================================================
echo    3단계: 가장 최근 드라마 자동 편집
echo    (뉴테이크 영상을 clips\EP01\cut01.mp4 처럼 넣은 뒤 실행)
echo ==================================================
python main.py edit
echo.
pause
