@echo off
chcp 65001 > nul
cd /d "%~dp0"
echo ==================================================
echo    유튜브 영상 자동 제작 도구 - 설치
echo ==================================================
echo.

set "PY="
py -3.11 --version >nul 2>&1 && set "PY=py -3.11"
if not defined PY python --version >nul 2>&1 && set "PY=python"
if not defined PY goto :no_python

echo 사용할 파이썬:
%PY% --version
echo.

if exist ".venv\Scripts\python.exe" goto :install_packages
echo [1/3] 가상환경을 만드는 중...
%PY% -m venv .venv
if errorlevel 1 goto :fail

:install_packages
echo [2/3] 필요한 프로그램을 설치하는 중... 몇 분 걸릴 수 있어요.
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :fail

echo [3/3] 설정 파일 준비...
if not exist ".env" copy ".env.example" ".env" >nul
echo.

where ffmpeg >nul 2>&1
if errorlevel 1 echo [참고] ffmpeg가 설치되어 있지 않아요. 내장 ffmpeg로도 동작하지만, README의 ffmpeg 설치를 권장해요.

echo.
echo ==================================================
echo    설치 완료!
echo    1. .env 파일을 메모장으로 열어 API 키를 넣으세요.
echo    2. run.bat 을 더블클릭하면 프로그램이 열려요.
echo ==================================================
pause
exit /b 0

:no_python
echo [오류] 파이썬을 찾지 못했어요.
echo README.md 의 "1단계: 파이썬 설치" 를 먼저 해 주세요.
echo 설치할 때 "Add python.exe to PATH" 체크를 꼭 켜야 해요.
pause
exit /b 1

:fail
echo.
echo [오류] 설치 중 문제가 생겼어요. 위의 빨간 글씨를 캡처해서 질문해 주세요.
echo 인터넷 연결을 확인하고 install.bat 을 다시 실행해 보세요.
pause
exit /b 1
