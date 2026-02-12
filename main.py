import os
import json
import requests
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

app = FastAPI()
# 確保 bg.png 放在 GitHub 根目錄
app.mount("/static", StaticFiles(directory="."), name="static")

def get_sys_config():
    """回傳前端需要的設定（不含敏感資訊）"""
    return {
        "gk": os.getenv("GEMINI_KEY", ""),
        "sp": os.getenv("SYSTEM_PROMPT", "你是一個傲嬌的監控秘書。"),
        "has_zeabur": bool(os.getenv("ZEABUR_API_TOKEN", ""))
    }

# ============================
# Zeabur API 設定
# ============================
ZEABUR_API_URL = "https://api.zeabur.com/graphql"

def get_zeabur_headers():
    """取得 Zeabur API 的認證 Header"""
    token = os.getenv("ZEABUR_API_TOKEN", "")
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

def fetch_runtime_logs():
    """從 Zeabur 官方 API 拿小龍蝦的 Runtime Logs"""
    project_id = os.getenv("ZEABUR_PROJECT_ID", "")
    service_id = os.getenv("ZEABUR_SERVICE_ID", "")
    environment_id = os.getenv("ZEABUR_ENVIRONMENT_ID", "")
    
    if not all([project_id, service_id, environment_id]):
        return {"logs": [], "error": "缺少 ZEABUR_PROJECT_ID / ZEABUR_SERVICE_ID / ZEABUR_ENVIRONMENT_ID"}
    
    # Zeabur 官方 GraphQL 查詢格式
    query = {
        "query": """
            query RuntimeLogs($projectId: ObjectID!, $serviceId: ObjectID!, $environmentId: ObjectID!) {
                runtimeLogs(projectID: $projectId, serviceID: $serviceId, environmentID: $environmentId) {
                    message
                    timestamp
                }
            }
        """,
        "variables": {
            "projectId": project_id,
            "serviceId": service_id,
            "environmentId": environment_id
        }
    }
    
    try:
        res = requests.post(
            ZEABUR_API_URL,
            json=query,
            headers=get_zeabur_headers(),
            timeout=10
        )
        data = res.json()
        
        # 檢查 GraphQL 錯誤
        if "errors" in data:
            return {"logs": [], "error": data["errors"][0].get("message", "GraphQL 錯誤")}
        
        logs = data.get("data", {}).get("runtimeLogs", [])
        # 轉換格式，讓前端能用
        formatted = [{"content": log["message"], "timestamp": log["timestamp"]} for log in logs]
        return {"logs": formatted}
        
    except Exception as e:
        return {"logs": [], "error": f"連線錯誤: {str(e)}"}

# ============================
# 前端 HTML
# ============================
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
        .tabs { height: 50px; background: #111827; border-bottom: 2px solid var(--border); display: flex; z-index: 100; }
        .tab { flex: 1; text-align: center; line-height: 50px; cursor: pointer; color: #666; font-size: 14px; }
        .tab.active { color: var(--accent); border-bottom: 2px solid var(--accent); background: rgba(251, 191, 36, 0.05); }
        .content { flex: 1; position: relative; }
        .page { display: none; width: 100%; height: 100%; position: absolute; top: 0; left: 0; }
        .page.active { display: block; }
        .room-view { background: url('/static/bg.png') no-repeat center center; background-size: contain; image-rendering: pixelated; height: 100%; position: relative; }
        .mini-log { position: absolute; bottom: 20px; left: 5%; width: 90%; max-height: 150px; background: var(--panel); border: 1px solid var(--border); padding: 10px; font-size: 12px; overflow-y: auto; border-radius: 4px; }
        .log-entry { margin-bottom: 4px; line-height: 1.4; }
        .log-time { color: #fbbf24; margin-right: 8px; }
        .log-msg { color: #e2e8f0; }
        .log-translated { color: #94a3b8; font-style: italic; display: block; margin-left: 80px; margin-top: 2px; }
        .skills-page { padding: 20px; overflow-y: auto; height: 100%; }
        .skill-card { border: 1px solid var(--accent); padding: 15px; margin-bottom: 15px; background: var(--panel); border-radius: 4px; }
        .skill-name { color: var(--accent); font-size: 16px; font-weight: bold; margin-bottom: 5px; }
        .status-bar { position: fixed; top: 0; left: 0; right: 0; height: 24px; background: #111827; color: #666; font-size: 11px; line-height: 24px; padding: 0 10px; z-index: 200; display: flex; justify-content: space-between; }
        .status-dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 6px; }
        .status-dot.ok { background: #22c55e; }
        .status-dot.err { background: #ef4444; }
        .tabs { margin-top: 24px; }
    </style>
</head>
<body>
    <div class="status-bar">
        <span><span class="status-dot" id="status-dot"></span><span id="status-text">連線中...</span></span>
        <span id="last-update">--:--:--</span>
    </div>
    <div class="tabs">
        <div class="tab active" onclick="switchPage('office', this)">🏠 主辦公室</div>
        <div class="tab" onclick="switchPage('skills', this)">📊 技能分析</div>
    </div>
    <div class="content">
        <div id="page-office" class="page active">
            <div class="room-view">
                <div class="mini-log" id="mini-log">初始化連線...</div>
            </div>
        </div>
        <div id="page-skills" class="page">
            <div class="skills-page">
                <h2 style="color:var(--accent); margin-bottom:20px;">AI 動態技能分析</h2>
                <div id="skills-list"><div style="color:#444">等待日誌中...</div></div>
            </div>
        </div>
    </div>
    <script>
        let CFG = {};
        let lastLogs = [];
        
        function switchPage(p, el) {
            document.querySelectorAll('.page').forEach(page => page.classList.remove('active'));
            document.querySelectorAll('.tab').forEach(tab => tab.classList.remove('active'));
            document.getElementById('page-' + p).classList.add('active');
            el.classList.add('active');
            if (p === 'skills' && lastLogs.length > 0) analyzeSkills(lastLogs);
        }
        
        function setStatus(ok, text) {
            const dot = document.getElementById('status-dot');
            dot.className = 'status-dot ' + (ok ? 'ok' : 'err');
            document.getElementById('status-text').innerText = text;
            if (ok) {
                const now = new Date();
                document.getElementById('last-update').innerText = 
                    now.toLocaleTimeString('zh-TW', {hour12: false});
            }
        }
        
        async function init() {
            const res = await fetch('/get_sys_config');
            CFG = await res.json();
            if (CFG.has_zeabur) {
                setStatus(true, '已連線 Zeabur API');
                sync();
                setInterval(sync, 15000);  // 每 15 秒更新一次
            } else {
                setStatus(false, '未設定 Zeabur API Token');
                document.getElementById('mini-log').innerText = "❌ 請設定環境變數：ZEABUR_API_TOKEN, ZEABUR_PROJECT_ID, ZEABUR_SERVICE_ID, ZEABUR_ENVIRONMENT_ID";
            }
        }
        
        async function sync() {
            try {
                const res = await fetch('/get_logs', { method: 'POST' });
                const data = await res.json();
                if (data.logs && data.logs.length > 0) {
                    lastLogs = data.logs;
                    setStatus(true, '已連線 (' + data.logs.length + ' 筆日誌)');
                    renderLogs(data.logs);
                } else if (data.error) {
                    setStatus(false, data.error);
                    document.getElementById('mini-log').innerText = "❌ " + data.error;
                } else {
                    setStatus(true, '暫無日誌');
                    document.getElementById('mini-log').innerText = "🦞 小龍蝦安靜中...目前沒有新日誌";
                }
            } catch(e) {
                setStatus(false, '連線失敗');
            }
        }
        
        async function renderLogs(logs) {
            const logEl = document.getElementById('mini-log');
            // 取最新 10 筆
            const recent = logs.slice(-10);
            
            // 如果有 Gemini Key，翻譯最新的一筆
            let translated = '';
            if (CFG.gk && recent.length > 0) {
                translated = await translateLog(recent[recent.length - 1].content);
            }
            
            let html = recent.map((log, i) => {
                const time = log.timestamp ? new Date(log.timestamp).toLocaleTimeString('zh-TW', {hour12: false}) : '--:--:--';
                const isLast = i === recent.length - 1;
                return `<div class="log-entry">
                    <span class="log-time">${time}</span>
                    <span class="log-msg">${escapeHtml(log.content.substring(0, 200))}</span>
                    ${isLast && translated ? '<span class="log-translated">🦞 ' + escapeHtml(translated) + '</span>' : ''}
                </div>`;
            }).join('');
            
            logEl.innerHTML = html;
            logEl.scrollTop = logEl.scrollHeight;
        }
        
        async function translateLog(text) {
            if (!CFG.gk) return '';
            try {
                const res = await fetch(
                    'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key=' + CFG.gk,
                    {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            contents: [{ parts: [{ text: CFG.sp + "\\n\\n用一句繁體中文白話翻譯這段 Log（不要超過 50 字）：\\n" + text.substring(0, 300) }] }]
                        })
                    }
                );
                const d = await res.json();
                return d.candidates?.[0]?.content?.parts?.[0]?.text || '';
            } catch(e) { return ''; }
        }
        
        async function analyzeSkills(logs) {
            if (!CFG.gk) return;
            try {
                const logsText = logs.slice(-20).map(l => l.content).join("\\n").substring(0, 1000);
                const prompt = '分析以下 AI Agent 的日誌，提取最多 3 個正在執行的任務。用 JSON 格式回覆，只要 JSON 不要其他文字：[{"name":"任務名稱","desc":"簡短描述"}]\\n\\n日誌：\\n' + logsText;
                const res = await fetch(
                    'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key=' + CFG.gk,
                    {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ contents: [{ parts: [{ text: prompt }] }] })
                    }
                );
                const d = await res.json();
                const aiText = d.candidates?.[0]?.content?.parts?.[0]?.text || '[]';
                const jsonStr = aiText.substring(aiText.indexOf('['), aiText.lastIndexOf(']') + 1);
                const skills = JSON.parse(jsonStr);
                document.getElementById('skills-list').innerHTML = skills.map(s => `
                    <div class="skill-card">
                        <div class="skill-name">${escapeHtml(s.name)}</div>
                        <div style="font-size:12px; color:#94a3b8;">${escapeHtml(s.desc)}</div>
                    </div>
                `).join('') || '<div style="color:#444">沒有分析到任務</div>';
            } catch(e) {
                document.getElementById('skills-list').innerHTML = '<div style="color:#ef4444">分析失敗: ' + e.message + '</div>';
            }
        }
        
        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }
        
        init();
    </script>
</body>
</html>
"""

# ============================
# API 路由
# ============================
@app.get("/", response_class=HTMLResponse)
def home():
    return HTML_CODE

@app.get("/get_sys_config")
def api_get_config():
    return JSONResponse(content=get_sys_config())

@app.post("/get_logs")
def get_logs():
    """從 Zeabur 官方 API 拿 Runtime Logs"""
    return JSONResponse(content=fetch_runtime_logs())

@app.get("/health")
def health():
    """健康檢查"""
    return {"status": "ok"}
