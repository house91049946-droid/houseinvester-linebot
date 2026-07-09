#!/bin/bash
# 啟動腳本 - 自動換 port 避免衝突
cd "/Users/chtsaimac/Library/CloudStorage/SynologyDrive-自己/my-cursor- houseinvester"

# 殺掉所有舊的 Flask 和 ngrok on 4040
pkill -f "python -m app.main" 2>/dev/null
kill $(lsof -ti:4040) 2>/dev/null
sleep 1

# 啟動 ngrok（如果還沒跑在 4444）
if ! pgrep -f "ngrok http 4444" > /dev/null; then
    ngrok http 4444 --log stdout &
    sleep 2
fi

# 啟動 Flask
PORT=4444 python -m app.main
