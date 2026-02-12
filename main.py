import os
import json
import requests
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

app = FastAPI()
# 確保 bg.png 放在 GitHub 根目錄，這裡會將其掛載到 /static/bg.png
app.mount("/static", StaticFiles(directory="."), name="static")

def get_config():
    return {
        "zk": os.getenv("ZEABUR_KEY", ""),
        "zi": os.getenv("LOBSTER_ID", ""),
        "gk": os.getenv("GEMINI_KEY", ""),
        "sp": os.getenv("SYSTEM_PROMPT", "你是一個傲嬌的監控秘書，負責監督小龍蝦。")
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
        body { 
            background: var(--bg); font-family: 'DotGothic16', sans-serif; 
            color: var(--text); height: 100vh; display: flex; flex-direction: column; overflow: hidden; 
        }

        /* --- 頂部標籤導航 --- */
        .tabs { 
            height: 60px; background: #111827; border-bottom: 2px solid var(--border); 
            display: flex; justify-content: space-around; align-items: center; z-index: 1000;
        }
        .tab { 
            flex: 1; text-align: center; line-height: 60px; cursor: pointer; color: #666; 
            font-size: 16px; border-bottom: 3px solid transparent; transition: 0.3s;
        }
        .tab.active { 
            color: var(--accent); border-bottom: 3px solid var(--accent); 
            background: rgba(251, 191, 36, 0.05); font-weight: bold;
        }

        /* --- 內容區域 --- */
        .content { flex: 1; position: relative; }
        .page { display: none; width: 100%; height: 100%; position: absolute; top: 0; left: 0; }
        .page.active { display: block; }

        /* --- 分頁 1: 主辦公室 --- */
        .room-bg { 
            background: url('/static/bg.png') no-repeat center center; 
            background-size: contain; image-rendering: pixelated; 
            height: 100%; width: 100%; position: relative;
        }
        .mini-log { 
            position: absolute; bottom: 30px; left: 5%; width: 90%; max-height: 120px;
            background: var(--panel); border: 1px solid var(--border); padding: 15px; 
            font-size: 14px; overflow-y: auto; box-shadow: 0 10px 30px rgba(0,0,0,0.8);
        }

        /* --- 分頁 2: 技能分析 --- */
        .skills-page { padding: 30px; height: 100%; overflow-y: auto; background: var(--bg); }
        .skill-card { 
            border: 1px solid var(--accent); padding: 20px; margin-bottom: 20px; 
            background: var(--panel); border-radius: 4px; position: relative;
        }
        .skill-name { color: var(--accent); font-size: 18px; font-weight: bold; margin-bottom: 8px; }
        .skill-desc { font-size: 14px; color: #94a3b8; line-height: 1.6; }

        /* 狀態指示燈 */
        .status-dot { 
            width: 10px; height: 10px; background: #34d399; border-radius: 50%; 
            display: inline-block; margin-right: 8px; animation: pulse 1.5s infinite; 
        }
        @keyframes pulse { 50% { opacity: 0.3; } }
    </style>
</head>
<body>

    <div class="tabs">
        <div class="tab active" onclick="switchPage('office', this)">🏠 主辦公室</div>
        <div class="tab" onclick="switchPage('skills', this)">📊 技能分析</div>
    </div>

    <div class="content">
        <div id="page-office" class="page active">
            <div class="room-bg">
                <div class="mini-log" id="log-display">系統啟動中...</div>
            </div>
        </div>

        <div id="page-skills" class="page">
            <div class="skills-page">
                <h2 style="color:var(--accent); margin-bottom:25px;">小龍蝦技能狀態偵測</h2>
                <div id="skills-list">
                    <div style="color:#555">正在分析 Log 中的數據特徵...</div>
                </div>
            </div>
        </div>
    </div>

    <script>
        let CFG = {};

        // 切換分頁
        function switchPage(pageId, el) {
            document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
            document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
            document.getElementById('page-' + pageId).classList.add('active');
            el.classList.add('active');
        }

        // 初始化
        async function init() {
            try {
                const res = await fetch('/get_sys_config');
                CFG = await res.json();
                if (CFG.zk && CFG.zi) {
                    setInterval(sync, 10000); // 10秒同步一次，省點錢
                    sync();
                } else {
                    document.getElementById('log-display').innerText = "❌ 變數未設定！請去 Zeabur 環境變數檢查。";
                }
            } catch(e) { console.error(e); }
        }

        async function sync() {
            try {
                const res = await fetch('/get_logs_internal', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ key: CFG.zk, id: CFG.zi })
                });
                const data = await res.json();
                
                if (data.logs && data.logs.length > 0) {
                    processLog(data.logs[0].content);
                    // 只有在技能頁面時才分析，省 Token
                    if(document.getElementById('page-skills').classList.contains('active')) {
                        analyzeSkills(data.logs.map(l => l.content).join("\\n"));
                    }
                } else if (data.error) {
                    document.getElementById('log-display').innerText = "❌ 錯誤: " + data.error;
                }
            } catch(e) {}
        }

        async function processLog(text) {
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
            document.getElementById('log-display').innerHTML = `<span class="status-dot"></span> ➜ ${{display}}`;
        }

        async function analyzeSkills(logs) {
            if (!CFG.gk) return;
            try {
                const prompt = "你是系統分析員。分析以下小龍蝦日誌，列出 3 個核心任務或狀態。以 JSON 陣列回傳：[ {\\"name\\": \\"名稱\\", \\"desc\\": \\"描述\\"} ]。日誌內容：" + logs.substring(0, 1000);
                const res = await fetch(`https://generativelanguage.googleapis.com/v1beta/models/gemini-pro:generateContent?key=${CFG.gk}`, {
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
    return JSONResponse(content=get_config())

@app.post("/get_logs_internal")
def get_logs_internal(info: dict):
    # 針對 Errno 111 增加重試與錯誤攔截
    url = "https://gateway.zeabur.com/graphql"
    query = f'query {{ serviceRuntimeLogs(serviceID: "{info["id"]}", limit: 20) {{ content timestamp }} }}'
    headers = {
        "Authorization": f"Bearer {info['key']}",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    try:
        res = requests.post(url, json={"query": query}, headers=headers, timeout=5)
        res.raise_for_status()
        return JSONResponse(content=res.json().get("data", {}))
    except requests.exceptions.ConnectionError:
        return JSONResponse(content={"logs": [], "error": "連線拒絕！請檢查 Zeabur 帳戶狀態或 Service ID 是否正確。"})
    except Exception as e:
        return JSONResponse(content={"logs": [], "error": str(e)})
