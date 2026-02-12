import os
import json
import requests
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

app = FastAPI()
# 修正圖片格式：確保讀取 bg.png
app.mount("/static", StaticFiles(directory="."), name="static")

def get_config():
    return {
        "zk": os.getenv("ZEABUR_KEY", ""),
        "zi": os.getenv("LOBSTER_ID", ""),
        "gk": os.getenv("GEMINI_KEY", ""),
        "sp": os.getenv("SYSTEM_PROMPT", "你是一個傲嬌的監控秘書。")
    }

# ▼▼▼▼▼ 重點檢查區域：這裡面包含了所有的網頁設計和邏輯，絕對不能少！ ▼▼▼▼▼
HTML_CODE = """
<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>LOBSTER OS - 全功能監控</title>
    <link href="https://fonts.googleapis.com/css2?family=DotGothic16&display=swap" rel="stylesheet">
    <style>
        :root { --bg: #0a0e14; --panel: rgba(16, 22, 34, 0.95); --accent: #fbbf24; --text: #e2e8f0; --border: #303b58; }
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { background: var(--bg); font-family: 'DotGothic16', sans-serif; color: var(--text); height: 100vh; display: flex; flex-direction: column; overflow: hidden; }

        /* --- 分頁標籤樣式 --- */
        .tabs { height: 50px; background: #111827; border-bottom: 2px solid var(--border); display: flex; z-index: 100; }
        .tab { flex: 1; text-align: center; line-height: 50px; cursor: pointer; color: #666; font-size: 14px; }
        .tab.active { color: var(--accent); border-bottom: 2px solid var(--accent); background: rgba(251, 191, 36, 0.05); }

        .content { flex: 1; position: relative; }
        .page { display: none; width: 100%; height: 100%; position: absolute; top: 0; left: 0; }
        .page.active { display: block; }

        /* --- 辦公室畫面 (bg.png) --- */
        .room-view { 
            background: url('/static/bg.png') no-repeat center center; 
            background-size: contain; image-rendering: pixelated; height: 100%; position: relative;
        }
        .mini-log { 
            position: absolute; bottom: 20px; left: 5%; width: 90%; max-height: 100px;
            background: var(--panel); border: 1px solid var(--border); padding: 10px; font-size: 12px; overflow-y: auto;
        }

        /* --- 技能分析頁面 --- */
        .skills-page { padding: 20px; overflow-y: auto; height: 100%; }
        .skill-card { border: 1px solid var(--accent); padding: 15px; margin-bottom: 15px; background: var(--panel); border-radius: 4px; }
        .skill-name { color: var(--accent); font-size: 16px; font-weight: bold; margin-bottom: 5px; }
        .skill-desc { color: #aaa; font-size: 12px; }
    </style>
</head>
<body>
    <div class="tabs">
        <div class="tab active" onclick="switchPage('office', this)">🏠 主辦公室</div>
        <div class="tab" onclick="switchPage('skills', this)">📊 技能分析</div>
    </div>

    <div class="content">
        <div id="page-office" class="page active">
            <div class="room-view"><div class="mini-log" id="mini-log">等待日誌同步...</div></div>
        </div>
        <div id="page-skills" class="page">
            <div class="skills-page">
                <h3 style="color:var(--accent); margin-bottom:20px;">AI 動態技能分析</h3>
                <div id="skills-list"><div style="color:#444">分析中...</div></div>
            </div>
        </div>
    </div>

    <script>
        let CFG = {};
        // 分頁切換邏輯
        function switchPage(p, el) {
            document.querySelectorAll('.page').forEach(page => page.classList.remove('active'));
            document.querySelectorAll('.tab').forEach(tab => tab.classList.remove('active'));
            document.getElementById('page-' + p).classList.add('active');
            el.classList.add('active');
        }

        // 初始化：抓取環境變數
        async function init() {
            const res = await fetch('/get_sys_config');
            CFG = await res.json();
            if (CFG.zk && CFG.zi) { setInterval(sync, 10000); sync(); }
            else { document.getElementById('mini-log').innerText = "❌ 變數未設定！請檢查 Zeabur 環境變數。"; }
        }

        // 同步日誌
        async function sync() {
            try {
                const res = await fetch('/get_logs_internal', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ key: CFG.zk, id: CFG.zi })
                });
                const data = await res.json();
                if (data.logs && data.logs.length > 0) {
                    updateUI(data.logs[0].content);
                    // 只有在技能頁面啟用時才進行分析，節省 Token
                    if(document.querySelector('#page-skills.active')) {
                        analyzeSkills(data.logs.map(l=>l.content).join("\\n"));
                    }
                } else if (data.error) {
                    document.getElementById('mini-log').innerText = "❌ 連線失敗: " + data.error;
                }
            } catch(e) {}
        }

        // 更新主畫面的小日誌窗
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

        // Gemini 技能分析邏輯
        async function analyzeSkills(logs) {
            if (!CFG.gk) return;
            try {
                const prompt = "分析 Log 提取 3 個任務，以 JSON 回傳: [{'name':'名','desc':'敘'}]。內容: " + logs.substring(0, 500);
                const res = await fetch(`https://generativelanguage.googleapis.com/v1beta/models/gemini-pro:generateContent?key=${CFG.gk}`, {
                    method: 'POST',
                    body: JSON.stringify({ contents: [{ parts: [{ text: prompt }] }] })
                });
                const d = await res.json();
                const aiText = d.candidates[0].content.parts[0].text;
                const skills = JSON.parse(aiText.substring(aiText.indexOf('['), aiText.lastIndexOf(']') + 1));
                document.getElementById('skills-list').innerHTML = skills.map(s => `
                    <div class="skill-card"><div class="skill-name">${s.name}</div><div class="skill-desc">${s.desc}</div></div>
                `).join('');
            } catch(e) {}
        }
        init();
    </script>
</body>
</html>
"""
# ▲▲▲▲▲ 如果上面這一大段不見了，那才是真的變少了！ ▲▲▲▲▲

@app.get("/", response_class=HTMLResponse)
def home(): return HTML_CODE

@app.get("/get_sys_config")
def api_config(): return JSONResponse(content=get_config())

@app.post("/get_logs_internal")
def get_logs_internal(info: dict):
    # 針對 Errno 111 增加 User-Agent 偽裝，嘗試繞過網關限制
    url = "https://gateway.zeabur.com/graphql"
    query = f'query {{ serviceRuntimeLogs(serviceID: "{info["id"]}", limit: 20) {{ content timestamp }} }}'
    headers = {
        "Authorization": f"Bearer {info['key']}",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    try:
        res = requests.post(url, json={"query": query}, headers=headers, timeout=10)
        res.raise_for_status()
        return JSONResponse(content=res.json().get("data", {}))
    except Exception as e:
        # 如果還是連線被拒，這裡會回傳具體錯誤
        return JSONResponse(content={"logs": [], "error": f"連線被拒絕 (Errno 111)。請確認 Zeabur 專用伺服器的網路設定是否允許外部 API 呼叫，或嘗試重新產生 API Key。"})
