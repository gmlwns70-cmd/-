#!/bin/bash
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  echo "처음 실행이라 설치 중이에요. 몇 분 걸려요..."
  python3 -m venv .venv || { echo "파이썬이 설치되어 있지 않아요. README 1단계를 먼저 해 주세요."; read; exit 1; }
fi
source .venv/bin/activate
python -m pip install -q -r requirements.txt
[ -f .env ] || cp .env.example .env
echo "브라우저에 대시보드가 열려요. 이 창은 닫지 마세요."
python -m streamlit run app.py
