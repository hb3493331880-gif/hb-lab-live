@echo off
chcp 65001 >nul
cd /d "C:\Users\MACHENIKE\Doubao\chats\2026-11-18\new-chat-7\hb-lab-live"
set PYTHONIOENCODING=utf-8
if not exist raw mkdir raw
"E:\python\python.exe" scripts\local_cycle.py >> raw\cycle_out.log 2>&1
