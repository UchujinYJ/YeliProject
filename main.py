import os
import requests
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

app = FastAPI()
app.mount("/static", StaticFiles(directory="."), name="static")

# 從 Zeabur 環境變數抓取鑰匙
Z_KEY = os.getenv("ZEABUR_KEY", "")
L_ID = os.getenv("LOBSTER_ID", "")
G_KEY = os.getenv("GEMINI_KEY", "")
S_PROMPT = os.getenv("SYSTEM_PROMPT", "你是一個傲嬌的監控秘書。")

HTML_CODE = f"""
<!DOCTYPE html>
<html>
<head>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Yeli Room</title>
    <link href="https://fonts.googleapis.com/css2?family=DotGothic16&display=swap" rel="stylesheet">
    <style>
        :root {{ --bg: #0a0e14; --panel: rgba(16, 22, 34, 0.9); --accent: #fbbf24; --text: #e2e8f0; --border: #303b58; }}
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ background: var(--bg); font-family: 'DotGothic16', sans-serif; color: var(--text); height: 100vh; overflow: hidden; display: flex; flex-direction: column; }}
        .header {{ height: 45px; background: #111827; border-bottom: 1px solid var(--border); display: flex; justify-content: space-between; align-items: center; padding: 0 20px; }}
        .main-stage {{ flex: 1; display: flex; position: relative; }}
        .room-view {{ flex: 1; background: url('/static/bg.jpg') no-repeat center center; background-size: contain; image-rendering: pixelated; position: relative; }}
        .log-window {{ position: absolute; bottom: 20px; left: 20px; width: 420px; height: 320px; background: var(--panel); border: 1px solid var(--border); padding: 15px; backdrop-filter: blur(10px); }}
        .log-list {{ height: 100%; overflow-y: auto; font-size: 13px; line-height: 1.6; }}
        .side-panel {{ width: 320px; background: var(--panel); border-left: 1px solid var(--border); padding: 20px; display: flex; flex-direction: column; }}
        .skill-card {{ border: 1px solid var(--accent); padding: 12px; margin-bottom: 12px; background: rgba(0,0,0,0.6); position: relative; }}
        .skill-card::before {{ content: "ACTIVE"; position: absolute; top: -8px; right: 5px; background: var(--accent); color: #000; font-size: 9px; padding: 0 4px; }}
        .loading {{ color: #555; font-size: 12px; text-align: center; margin-top: 20px; }}
    </style>
</head>
<body>
    <div class="header">
        <div style="color:var(--accent); display:flex; align-items:center; gap:10px;">
            <div style="width:10px; height:10px; background:#34d399; border-radius:50%;"></div>
            LOBSTER OS | 全自動 AI 監控中
        </div>
        <div id="cost-info" style="color:#fb7185; font-size:12px;">每日 Token 消耗預警...</div>
    </div>
    <div class="main-stage">
        <div class="room-view">
            <div class="log-window">
                <div id="log-list" class="log-list">正在讀取夜璃運行日誌...</div>
            </div>
        </div>
        <div class="side-panel">
            <h3 style="color:var(--accent); margin-bottom:15px; border-bottom: 1px solid var(--border); padding-bottom: 10px;">
                🤖 動態技能分析
            </h3>
            <div id="skills-container">
                <div class="loading">正在分析 Log 以提取技能...</div>
            </div>
        </div>
    </div>

    <script>
        const CONFIG = {{ zk: "{Z_KEY}", zi: "{L_ID}", gk: "{G_KEY}", sp: "{S_PROMPT}" }};
        let lastFullLog = "";

        window.onload = () => {{
            if(CONFIG.zk && CONFIG.zi) {{
                setInterval(sync, 8000); // 每8秒同步一次
                sync();
            }}
        }};

        async function sync() {{
            try {{
                // 1. 抓取最近的 Log (一次抓 20 條來分析)
                const res = await fetch('/get_logs_batch', {{
                    method: 'POST',
                    headers: {{'Content-Type': 'application/json'}},
                    body: JSON.stringify({{ key: CONFIG.zk, id: CONFIG.zi }})
                }});
                const data = await res.json();
                
                if(data.logs && data.logs.length > 0) {{
                    const latestContent = data.logs[0].content;
                    const allLogsText = data.logs.map(l => l.content).join("\\n");
                    
                    // 2. 如果 Log 有更新，執行翻譯與技能分析
                    if(latestContent !== lastFullLog) {{
                        lastFullLog = latestContent;
                        updateLogUI(latestContent);
                        analyzeSkills(allLogsText);
                    }}
                }}
            }} catch(e) {{}}
        }}

        // 使用 Gemini 分析 Log 中的技能
        async function analyzeSkills(logs) {{
            if(!CONFIG.gk) return;
            try {{
                const prompt = `你是一個系統分析員。請根據以下的小龍蝦系統 Log，列出目前系統展現出的 3 個「核心技能」或「處理中任務」。
                格式必須是 JSON 陣列：[ {{"name": "技能名", "desc": "簡短描述"}} ]。
                請參考他最近正在處理的：Token 費用、thought_signature 報錯、記憶總結系統。
                Log內容：\\n${{logs.substring(0, 1000)}}`;

                const res = await fetch(`https://generativelanguage.googleapis.com/v1beta/models/gemini-pro:generateContent?key=${{CONFIG.gk}}`, {{
                    method: 'POST',
                    body: JSON.stringify({{ contents: [{{ parts: [{{ text: prompt }}] }}] }})
                }});
                const result = await res.json();
                const aiResponse = result.candidates[0].content.parts[0].text;
                
                // 提取 JSON 並渲染
                const skills = JSON.parse(aiResponse.substring(aiResponse.indexOf('['), aiResponse.lastIndexOf(']') + 1));
                renderSkills(skills);
            }} catch(e) {{ console.error("技能分析失敗", e); }}
        }}

        function renderSkills(skills) {{
            const container = document.getElementById('skills-container');
            container.innerHTML = skills.map(s => `
                <div class="skill-card">
                    <div style="font-size:14px; color:#fff; font-weight:bold;">${{s.name}}</div>
                    <div style="font-size:11px; color:#94a3b8; margin-top:5px;">${{s.desc}}</div>
                </div>
            `).join('');
        }}

        async function updateLogUI(text) {{
            let display = text;
            if(CONFIG.gk && CONFIG.sp) {{
                try {{
                    const res = await fetch(`https://generativelanguage.googleapis.com/v1beta/models/gemini-pro:generateContent?key=${{CONFIG.gk}}`, {{
                        method: 'POST',
                        body: JSON.stringify({{ contents: [{{ parts: [{{ text: CONFIG.sp + "\\\\n\\\\n翻譯Log: " + text }}] }}] }})
                    }});
                    const data = await res.json();
                    display = data.candidates[0].content.parts[0].text;
                }} catch(e) {{}}
            }}
            const list = document.getElementById('log-list');
            const div = document.createElement('div');
            div.className = "log-item";
            div.innerHTML = `<span style="color:#fbbf24;">➜</span> ${{display}}`;
            list.prepend(div);
            if(list.children.length > 10) list.lastElementChild.remove();
        }}
    </script>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
def home(): return HTML_CODE

@app.post("/get_logs_batch")
def get_logs_batch(info: dict):
    # 改為一次抓取 20 條，方便 AI 分析當前狀態
    url = "https://gateway.zeabur.com/graphql"
    query = f'query {{ serviceRuntimeLogs(serviceID: "{info["id"]}", limit: 20) {{ content timestamp }} }}'
    res = requests.post(url, json={"query": query}, headers={"Authorization": f"Bearer {info['key']}"}).json()
    return {"logs": res["data"]["serviceRuntimeLogs"]}
