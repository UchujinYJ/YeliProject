from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles # ⬅️ 新增這行
import requests
import os

app = FastAPI()

# 🔥 如果你有圖片，這行會讓 Zeabur 讀取你 GitHub 裡的檔案
if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

HTML_PAGE = """
<!DOCTYPE html>
<html>
<head>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>小龍蝦手機監控</title>
    <style>
        body { 
            background: #000; 
            /* 這裡示範如何讀取 static 資料夾裡的背景圖 */
            background-image: url('/static/bg.png'); 
            background-size: cover;
            color: #eee; 
            font-family: monospace; 
            padding: 20px; 
        }
        /* ... 其他 CSS 保持不變 ... */
    </style>
</head>
<body>
    </body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
def home(): return HTML_PAGE

@app.post("/get_logs")
def get_logs(info: dict):
    # 這裡維持原樣，幫手機抓 Zeabur Log
    try:
        url = "https://gateway.zeabur.com/graphql"
        query = f'query {{ serviceRuntimeLogs(serviceID: "{info["id"]}", limit: 1) {{ content timestamp }} }}'
        res = requests.post(url, json={"query": query}, headers={"Authorization": f"Bearer {info['key']}"}).json()
        return {"logs": res["data"]["serviceRuntimeLogs"]}
    except: return {"logs": []}
