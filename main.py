import os
import json
import requests
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

app = FastAPI()
# 修正：支援讀取 bg.png
app.mount("/static", StaticFiles(directory="."), name="static")

# 從 Zeabur 環境變數抓取 (這部分在伺服器端執行)
def get_sys_config():
    return {
        "zk": os.getenv("ZEABUR_KEY", ""),
        "zi": os.getenv("LOBSTER_ID", ""),
        "gk": os.getenv("GEMINI_KEY", ""),
        "sp": os.getenv("SYSTEM_PROMPT", "你是一個傲嬌的監控秘書。")
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
        * { margin: 0; padding: 0; box-sizing: border-box; -webkit-tap-highlight-color: transparent; }
        body { background: var(--bg); font-family: 'DotGothic16', sans-serif; color: var(--text); height: 100vh; display: flex; flex-direction: column; overflow: hidden; }

        /* --- 頂部導航 (分頁標籤) --- */
        .tab-bar { 
            height: 50px; background: #111827; border-bottom: 2px solid var(--border); 
            display: flex; justify-content: space-around; align-items: center; z-index: 100;
        }
        .tab { 
            flex: 1; text-align: center; line-height: 50px; font-size: 14px; color: #666; cursor: pointer; border-bottom: 2px solid transparent; 
        }
        .tab.active { color: var(--accent); border-bottom: 2px solid var(--accent); background: rgba(251, 191, 36, 0.05); }

        /* --- 內容區域 --- */
        .content-wrapper { flex: 1; position: relative; }
        .page { display: none; width: 100%; height: 100%; position: absolute; top: 0; left: 0; }
        .page.active { display: block; }

        /* 頁面 1: 辦公室 (主畫面) */
        .room-view { 
            background: url('/static/bg.png') no-repeat center center; /* 修正為 png */
            background-size: contain; image-rendering: pixelated; height: 100%; position: relative;
        }
        .mini-log { 
            position: absolute; bottom: 20px; left: 5%; width: 90%; max-height: 120px;
            background: var(--panel); border: 1px solid var(--border); padding: 10px; font-size: 12px; overflow-y: auto;
        }

        /* 頁面 2: 技能列表 */
        .skills-page { background: var(--bg); padding: 20px; overflow-y: auto; }
        .skill-card { 
            border: 1px solid var(--accent); padding: 15px; margin-bottom: 15px; background: var(--panel);
            box-shadow: 4px 4px 0px var(--border);
        }
        .skill-name { color: var(--accent); font-size: 16px; margin-bottom: 5px; }
        .skill-desc { font-size: 12px; color: #94a3b8; line-height: 1.4; }

        .loading-overlay { 
            position: fixed; top:0; left:0; width:100%; height:100%; background:var(--bg); 
            z-index: 999; display: flex; justify-content: center; align-items: center; 
        }

        @keyframes blink { 50% { opacity: 0.3; } }
        .status-dot { width: 8px; height: 8px; background: #34d399; border-radius: 50%; display: inline-block; margin-right: 5px; animation: blink 1s infinite; }
    </style>
</head>
<body>

    <div id="loader" class="loading-overlay">系統同步中...</div>

    <div class="tab-bar">
        <div class="tab active" onclick="showPage('office', this)">主辦公室</div>
        <div class="tab" onclick="showPage('skills', this)">技能分析</div>
    </div>

    <div class="content-wrapper">
        <div id="page-office" class="page active">
            <div class="room-view">
                <div class="mini-log" id="mini-log">等待日誌同步...</div>
            </div>
        </div>

        <div id="page-skills" class="page">
            <div class="skills-page">
                <h2 style="color:var(--accent); margin-bottom:20px;">AI 動態技能偵測</h2>
                <div id="skills-list">
                    <div style="color:#444;">正在從 Log 中提煉技能數據...</div>
                </div>
            </div>
        </div>
    </div>

    <script>
        let CONFIG = {};

        // 1. 初始化：從後端安全取得環境變數
        async function init() {
            try {
                const res = await fetch('/get_sys_config');
                CONFIG = await res.json();
                document.getElementById('loader').style.display = 'none';
                
                if (CONFIG.zk && CONFIG.zi) {
                    setInterval(sync, 8000);
                    sync();
                } else {
                    alert("請在 Zeabur 環境變數中設定 ZEABUR_KEY 與 LOBSTER_ID！");
                }
            } catch(e) { console.error("初始化失敗", e); }
        }

        // 2. 分頁切換
        function showPage(pageId, tabEl) {
            document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
            document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
            document.getElementById('page-' + pageId).classList.add('active');
            tabEl.classList.add('active');
        }

        // 3. 數據同步
        async function sync() {
            try {
                const res = await fetch('/get_logs_internal', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ key: CONFIG.zk, id: CONFIG.zi })
                });
                const data = await res.json();
                
                if (data.logs && data.logs.length > 0) {
                    const latestLog = data.logs[0].content;
                    updateMiniLog(latestLog);
                    
                    // 分析技能 (只在進入技能頁或 Log 變動時觸發)
                    analyzeSkills(data.logs.map(l => l.content).join("\\n"));
                }
            } catch(e) {}
        }

        async function updateMiniLog(text) {
            let display = text;
            if (CONFIG.gk && CONFIG.sp) {
                try {
                    const res = await fetch(`https://generativelanguage.googleapis.com/v1beta/models/gemini-pro:generateContent?key=${CONFIG.gk}`, {
                        method: 'POST',
                        body: JSON.stringify({ contents: [{ parts: [{ text: CONFIG.sp + "\\n\\n翻譯此 Log：" + text }] }] })
                    });
                    const d = await res.json();
                    display = d.candidates[0].content.parts[0].text;
                } catch(e) {}
            }
            document.getElementById('mini-log').innerHTML = `<span class="status-dot"></span> ➜ ${{display}}`;
        }

        async function analyzeSkills(logs) {
            if (!CONFIG.gk) return;
            try {
                const prompt = `分析以下小龍蝦 AI 系統的日誌，提取出目前正在運作的 3 個主要技能或狀態。以 JSON 格式回傳：[{"name":"技能名","desc":"描述"}]。\\nLog內容：\\n${logs.substring(0, 1000)}`;
                const res = await fetch(`https://generativelanguage.googleapis.com/v1beta/models/gemini-pro:generateContent?key=${CONFIG.gk}`, {
                    method: 'POST',
                    body: JSON.stringify({ contents: [{ parts: [{ text: prompt }] }] })
                });
                const d = await res.json();
                const aiText = d.candidates[0].content.parts[0].text;
                const skills = JSON.parse(aiText.substring(aiText.indexOf('['), aiText.lastIndexOf(']') + 1));
                
                document.getElementById('skills-list').innerHTML = skills.map(s => `
                    <div class="skill-card">
                        <div class="skill-name">${s.name}</div>
                        <div class="skill-desc">${s.desc}</div>
                    </div>
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
def api_get_config():
    # 這是關鍵：把環境變數傳給前端，前端才讀得到設定
    return JSONResponse(content=get_sys_config())

@app.post("/get_logs_internal")
def get_logs_internal(info: dict):
    # 這是代理路徑，幫前端去問 Zeabur 伺服器
    url = "https://gateway.zeabur.com/graphql"
    query = f'query {{ serviceRuntimeLogs(serviceID: "{info["id"]}", limit: 20) {{ content timestamp }} }}'
    res = requests.post(url, json={"query": query}, headers={"Authorization": f"Bearer {info['key']}"}).json()
    return JSONResponse(content=res["data"])
