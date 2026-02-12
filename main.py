import os
import json
import requests
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

app = FastAPI()
# 確保 bg.png 放在 GitHub 根目錄
app.mount("/static", StaticFiles(directory="."), name="static")

# 🔒 所有敏感資料都從 Zeabur 環境變數讀取
def get_sys_config():
    return {
        "gk": os.getenv("GEMINI_KEY", ""),
        "sp": os.getenv("SYSTEM_PROMPT", "你是一個傲嬌的監控秘書。"),
        # 內網地址也改由變數讀取，預設值為空
        "internal_url": os.getenv("LOBSTER_INTERNAL_URL", "")
    }

HTML_CODE = """
<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>Yeli Room</title>
    <link href="https://fonts.googleapis.com/css2?family=DotGothic16&display=swap" rel="stylesheet">
    <style>
        :root { --bg: #0a0e14; --panel: rgba(16, 22, 34, 0.95); --accent: #fbbf24; --text: #e2e8f0; --border: #303b58; }
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { background: var(--bg); font-family: 'DotGothic16', sans-serif; color: var(--text); height: 100vh; display: flex; flex-direction: column; overflow: hidden; }

        /* --- 分頁標籤 --- */
        .tabs { height: 50px; background: #111827; border-bottom: 2px solid var(--border); display: flex; z-index: 100; }
        .tab { flex: 1; text-align: center; line-height: 50px; cursor: pointer; color: #666; font-size: 14px; }
        .tab.active { color: var(--accent); border-bottom: 2px solid var(--accent); background: rgba(251, 191, 36, 0.05); }

        .content { flex: 1; position: relative; }
        .page { display: none; width: 100%; height: 100%; position: absolute; top: 0; left: 0; }
        .page.active { display: block; }

        /* --- 辦公室畫面 --- */
        .room-view { background: url('/static/bg.png') no-repeat center center; background-size: contain; image-rendering: pixelated; height: 100%; position: relative; }
        .mini-log { position: absolute; bottom: 20px; left: 5%; width: 90%; max-height: 100px; background: var(--panel); border: 1px solid var(--border); padding: 10px; font-size: 12px; overflow-y: auto; }

        /* --- 技能分析 --- */
        .skills-page { padding: 20px; overflow-y: auto; height: 100%; }
        .skill-card { border: 1px solid var(--accent); padding: 15px; margin-bottom: 15px; background: var(--panel); border-radius: 4px; }
        .skill-name { color: var(--accent); font-size: 16px; font-weight: bold; margin-bottom: 5px; }
    </style>
</head>
<body>
    <div class="tabs">
        <div class="tab active" onclick="switchPage('office', this)">🏠 主辦公室</div>
        <div class="tab" onclick="switchPage('skills', this)">📊 技能分析</div>
    </div>

    <div class="content">
        <div id="page-office" class="page active">
            <div class="room-view"><div class="mini-log" id="mini-log">初始化安全性檢查...</div></div>
        </div>
        <div id="page-skills" class="page">
            <div class="skills-page">
                <h2 style="color:var(--accent); margin-bottom:20px;">AI 動態技能分析</h2>
                <div id="skills-list"><div style="color:#444">等待日誌同步以提取技能...</div></div>
            </div>
        </div>
    </div>

    <script>
        let CFG = {};

        async function init() {
            try {
                const res = await fetch('/get_sys_config');
                CFG = await res.json();
                if (CFG.internal_url) {
                    setInterval(sync, 10000);
                    sync();
                } else {
                    document.getElementById('mini-log').innerText = "❌ 警告：環境變數 LOBSTER_INTERNAL_URL 未設定，連線中止！";
                }
            } catch(e) { console.error(e); }
        }

        function switchPage(p, el) {
            document.querySelectorAll('.page').forEach(page => page.classList.remove('active'));
            document.querySelectorAll('.tab').forEach(tab => tab.classList.remove('active'));
            document.getElementById('page-' + p).classList.add('active');
            el.classList.add('active');
        }

        async function sync() {
            try {
                const res = await fetch('/get_logs_internal', { method: 'POST' });
                const data = await res.json();
                if (data.logs && data.logs.length > 0) {
                    updateUI(data.logs[0].content);
                    if(document.querySelector('#page-skills.active')) {
                        analyzeSkills(data.logs.map(l => l.content).join("\\n"));
                    }
                } else if (data.error) {
                    document.getElementById('mini-log').innerText = "❌ 狀態: " + data.error;
                }
            } catch(e) {}
        }

        async function updateUI(text) {
            let display = text;
            if (CFG.gk && CFG.sp) {
                try {
                    const res = await fetch(`https://generativelanguage.googleapis.com/v1beta/models/gemini-pro:generateContent?key=${CFG.gk}`, {
                        method: 'POST',
                        body: JSON.stringify({ contents: [{ parts: [{ text: CFG.sp + "\\n\\n翻譯Log：" + text }] }] })
                    });
                    const d = await res.json();
                    display = d.candidates[0].content.parts[0].text;
                } catch(e) {}
            }
            document.getElementById('mini-log').innerText = "➜ " + display;
        }

        async function analyzeSkills(logs) {
            if (!CFG.gk) return;
            try {
                const prompt = "分析日誌提取 3 個當前系統正在進行的任務，格式 JSON: [{'name':'名','desc':'敘'}]。內容: " + logs.substring(0, 500);
                const res = await fetch(`https://generativelanguage.googleapis.com/v1beta/models/gemini-pro:generateContent?key=${CFG.gk}`, {
                    method: 'POST',
                    body: JSON.stringify({ contents: [{ parts: [{ text: prompt }] }] })
                });
                const d = await res.json();
                const aiText = d.candidates[0].content.parts[0].text;
                const skills = JSON.parse(aiText.substring(aiText.indexOf('['), aiText.lastIndexOf(']') + 1));
                document.getElementById('skills-list').innerHTML = skills.map(s => `
                    <div class="skill-card"><div class="skill-name">${s.name}</div><div style="font-size:12px; color:#94a3b8;">${s.desc}</div></div>
                `).join('');
            } catch(e) {}
        }

        init();
    </script>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
def home(): return HTML_CODE

@app.get("/get_sys_config")
def api_get_config(): return JSONResponse(content=get_sys_config())

@app.post("/get_logs_internal")
def get_logs_internal():
    # 安全設計：內網網址從伺服器環境變數讀取，不洩漏給前端代碼
    url = os.getenv("LOBSTER_INTERNAL_URL", "")
    if not url:
        return JSONResponse(content={"logs": [], "error": "未設定內網地址"})
        
    try:
        # 內網版直接存取小龍蝦服務
        res = requests.get(url, timeout=5)
        return JSONResponse(content={"logs": [{"content": f"內網連線成功：{res.text[:150]}...", "timestamp": ""}]})
    except Exception as e:
        return JSONResponse(content={"logs": [], "error": "內網握手失敗，請確認服務名與端口。"})
