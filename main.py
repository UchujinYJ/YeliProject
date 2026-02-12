import os
import json
import time
import requests
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

app = FastAPI()
app.mount("/static", StaticFiles(directory="."), name="static")

# ============================
# Gemini 翻譯快取（防止瘋狂打 API）
# ============================
translate_cache = {}       # {log_hash: translated_text}
last_translate_time = 0    # 上次翻譯的時間戳
TRANSLATE_COOLDOWN = 60    # 至少間隔 60 秒才翻譯一次

def get_sys_config():
    return {
        "has_zeabur": bool(os.getenv("ZEABUR_API_TOKEN", "")),
        "has_gemini": bool(os.getenv("GEMINI_KEY", ""))
        # 不再傳 Key 到前端！
    }

# ============================
# Zeabur API
# ============================
ZEABUR_API_URL = "https://api.zeabur.com/graphql"

def get_zeabur_headers():
    token = os.getenv("ZEABUR_API_TOKEN", "")
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

def zeabur_exec(command_list):
    """在小龍蝦的容器裡遠端執行指令"""
    service_id = os.getenv("ZEABUR_SERVICE_ID", "")
    environment_id = os.getenv("ZEABUR_ENVIRONMENT_ID", "")
    query = {
        "query": """
            mutation ExecCmd($sid: ObjectID!, $eid: ObjectID!, $cmd: [String!]!) {
                executeCommand(serviceID: $sid, environmentID: $eid, command: $cmd) { exitCode output }
            }
        """,
        "variables": {"sid": service_id, "eid": environment_id, "cmd": command_list}
    }
    try:
        res = requests.post(ZEABUR_API_URL, json=query, headers=get_zeabur_headers(), timeout=10)
        data = res.json()
        if "errors" in data:
            return None
        return data.get("data", {}).get("executeCommand", {}).get("output", "")
    except:
        return None

def fetch_runtime_logs():
    project_id = os.getenv("ZEABUR_PROJECT_ID", "")
    service_id = os.getenv("ZEABUR_SERVICE_ID", "")
    environment_id = os.getenv("ZEABUR_ENVIRONMENT_ID", "")
    if not all([project_id, service_id, environment_id]):
        return {"logs": [], "error": "缺少必要環境變數"}
    query = {
        "query": """
            query RuntimeLogs($pid: ObjectID!, $sid: ObjectID!, $eid: ObjectID!) {
                runtimeLogs(projectID: $pid, serviceID: $sid, environmentID: $eid) { message timestamp }
            }
        """,
        "variables": {"pid": project_id, "sid": service_id, "eid": environment_id}
    }
    try:
        res = requests.post(ZEABUR_API_URL, json=query, headers=get_zeabur_headers(), timeout=10)
        data = res.json()
        if "errors" in data:
            return {"logs": [], "error": data["errors"][0].get("message", "GraphQL 錯誤")}
        logs = data.get("data", {}).get("runtimeLogs", [])
        return {"logs": [{"content": l["message"], "timestamp": l["timestamp"]} for l in logs]}
    except Exception as e:
        return {"logs": [], "error": f"連線錯誤: {str(e)}"}

def translate_with_gemini(text):
    """後端翻譯，帶快取和頻率限制"""
    global last_translate_time, translate_cache
    
    gk = os.getenv("GEMINI_KEY", "")
    if not gk:
        return ""
    
    # 快取檢查
    text_hash = hash(text[:200])
    if text_hash in translate_cache:
        return translate_cache[text_hash]
    
    # 頻率限制：至少間隔 TRANSLATE_COOLDOWN 秒
    now = time.time()
    if now - last_translate_time < TRANSLATE_COOLDOWN:
        return ""
    
    sp = os.getenv("SYSTEM_PROMPT", "你是一個傲嬌的監控秘書。")
    
    try:
        res = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={gk}",
            headers={"Content-Type": "application/json"},
            json={"contents": [{"parts": [{"text": f"{sp}\n\n用一句繁體中文白話翻譯這段 Log（不要超過 50 字）：\n{text[:300]}"}]}]},
            timeout=10
        )
        data = res.json()
        
        if "error" in data:
            return ""
        
        result = data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
        
        # 存入快取
        translate_cache[text_hash] = result
        last_translate_time = now
        
        # 快取最多存 50 筆
        if len(translate_cache) > 50:
            keys = list(translate_cache.keys())
            for k in keys[:25]:
                del translate_cache[k]
        
        return result
    except:
        return ""

def analyze_tasks_with_gemini(logs_text):
    """後端分析任務"""
    gk = os.getenv("GEMINI_KEY", "")
    if not gk:
        return []
    
    try:
        prompt = '分析以下 AI Agent 日誌，提取最多 3 個任務。只回 JSON：[{"name":"名","desc":"述","status":"running/done/error"}]\n\n' + logs_text
        res = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={gk}",
            headers={"Content-Type": "application/json"},
            json={"contents": [{"parts": [{"text": prompt}]}]},
            timeout=15
        )
        data = res.json()
        if "error" in data:
            return []
        
        ai_text = data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "[]")
        json_str = ai_text[ai_text.index("["):ai_text.rindex("]") + 1]
        return json.loads(json_str)
    except:
        return []

def fetch_lobster_status():
    """讀取小龍蝦的真實狀態"""
    ws = "/home/node/.openclaw/workspace"
    result = {"core_files": [], "memory_files": [], "scripts": [], "skills": [],
              "memory_index": "", "identity": "", "mem_summaries": []}

    ls_output = zeabur_exec(["ls", "-1", ws])
    if not ls_output:
        return {"error": "無法連線到小龍蝦"}

    for f in ls_output.strip().split("\n"):
        f = f.strip()
        if not f:
            continue
        if f in ["SOUL.md","AGENTS.md","IDENTITY.md","USER.md","TOOLS.md","BOOTSTRAP.md","HEARTBEAT.md","MEMORY.md"]:
            result["core_files"].append(f)
        elif f.startswith("mem-") and f.endswith(".md"):
            result["memory_files"].append(f)
        elif f.endswith(".py"):
            result["scripts"].append(f)

    mem = zeabur_exec(["cat", f"{ws}/MEMORY.md"])
    if mem:
        result["memory_index"] = mem[:2000]

    ident = zeabur_exec(["cat", f"{ws}/IDENTITY.md"])
    if ident:
        result["identity"] = ident[:500]

    skills_out = zeabur_exec(["ls", "-1", f"{ws}/skills/"])
    if skills_out and skills_out.strip():
        result["skills"] = [s.strip() for s in skills_out.strip().split("\n") if s.strip()]

    for mf in result["memory_files"]:
        content = zeabur_exec(["head", "-10", f"{ws}/{mf}"])
        if content:
            result["mem_summaries"].append({"file": mf, "preview": content.strip()})

    return result

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
        :root { --bg: #0a0e14; --panel: rgba(16, 22, 34, 0.95); --accent: #fbbf24; --text: #e2e8f0; --border: #303b58; --green: #22c55e; --red: #ef4444; --blue: #3b82f6; --purple: #a855f7; }
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
        .section-title { color: var(--accent); font-size: 16px; margin: 20px 0 10px 0; }
        .section-title:first-child { margin-top: 0; }
        .card { border: 1px solid var(--border); padding: 12px; margin-bottom: 10px; background: var(--panel); border-radius: 4px; }
        .card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; }
        .card-name { font-size: 14px; font-weight: bold; }
        .card-badge { font-size: 10px; padding: 2px 8px; border-radius: 10px; }
        .badge-core { background: rgba(251,191,36,0.2); color: var(--accent); }
        .badge-mem { background: rgba(59,130,246,0.2); color: var(--blue); }
        .badge-script { background: rgba(34,197,94,0.2); color: var(--green); }
        .badge-task { background: rgba(168,85,247,0.2); color: var(--purple); }
        .card-preview { font-size: 11px; color: #64748b; white-space: pre-wrap; max-height: 80px; overflow: hidden; }
        .file-grid { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 15px; }
        .file-chip { font-size: 11px; padding: 4px 10px; border-radius: 12px; border: 1px solid var(--border); background: rgba(255,255,255,0.03); }
        .status-bar { position: fixed; top: 0; left: 0; right: 0; height: 24px; background: #111827; color: #666; font-size: 11px; line-height: 24px; padding: 0 10px; z-index: 200; display: flex; justify-content: space-between; }
        .status-dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 6px; }
        .status-dot.ok { background: #22c55e; }
        .status-dot.err { background: #ef4444; }
        .tabs { margin-top: 24px; }
        .loading { color: #666; text-align: center; padding: 40px; }
        .loading::after { content: ''; animation: dots 1.5s infinite; }
        @keyframes dots { 0%{content:'.'} 33%{content:'..'} 66%{content:'...'} }
    </style>
</head>
<body>
    <div class="status-bar">
        <span><span class="status-dot" id="status-dot"></span><span id="status-text">連線中...</span></span>
        <span id="last-update">--:--:--</span>
    </div>
    <div class="tabs">
        <div class="tab active" onclick="switchPage('office', this)">🏠 主辦公室</div>
        <div class="tab" onclick="switchPage('skills', this)">📊 技能面板</div>
    </div>
    <div class="content">
        <div id="page-office" class="page active">
            <div class="room-view">
                <div class="mini-log" id="mini-log">初始化連線...</div>
            </div>
        </div>
        <div id="page-skills" class="page">
            <div class="skills-page" id="skills-page">
                <div class="loading">載入小龍蝦狀態中</div>
            </div>
        </div>
    </div>
    <script>
        let CFG = {};
        let lastLogs = [];

        function switchPage(p, el) {
            document.querySelectorAll('.page').forEach(x => x.classList.remove('active'));
            document.querySelectorAll('.tab').forEach(x => x.classList.remove('active'));
            document.getElementById('page-' + p).classList.add('active');
            el.classList.add('active');
            if (p === 'skills') loadSkillsPage();
        }

        function setStatus(ok, text) {
            document.getElementById('status-dot').className = 'status-dot ' + (ok ? 'ok' : 'err');
            document.getElementById('status-text').innerText = text;
            if (ok) document.getElementById('last-update').innerText = new Date().toLocaleTimeString('zh-TW', {hour12: false});
        }

        async function init() {
            const res = await fetch('/get_sys_config');
            CFG = await res.json();
            if (CFG.has_zeabur) { setStatus(true, '已連線'); sync(); setInterval(sync, 30000); }
            else { setStatus(false, '未設定'); document.getElementById('mini-log').innerText = "❌ 缺少環境變數"; }
        }

        async function sync() {
            try {
                const res = await fetch('/get_logs', { method: 'POST' });
                const data = await res.json();
                if (data.logs && data.logs.length > 0) {
                    lastLogs = data.logs;
                    setStatus(true, '已連線 (' + data.logs.length + ' 筆)');
                    renderLogs(data);
                } else if (data.error) {
                    setStatus(false, data.error);
                    document.getElementById('mini-log').innerText = "❌ " + data.error;
                } else {
                    setStatus(true, '暫無日誌');
                    document.getElementById('mini-log').innerText = "🦞 安靜中...";
                }
            } catch(e) { setStatus(false, '連線失敗'); }
        }

        function renderLogs(data) {
            const el = document.getElementById('mini-log');
            const recent = data.logs.slice(-10);
            const translated = data.translated || '';
            el.innerHTML = recent.map((log, i) => {
                const t = log.timestamp ? new Date(log.timestamp).toLocaleTimeString('zh-TW',{hour12:false}) : '--:--:--';
                const last = i === recent.length - 1;
                return '<div class="log-entry"><span class="log-time">'+t+'</span><span class="log-msg">'+esc(log.content.substring(0,200))+'</span>'+(last&&translated?'<span class="log-translated">🦞 '+esc(translated)+'</span>':'')+'</div>';
            }).join('');
            el.scrollTop = el.scrollHeight;
        }

        async function loadSkillsPage() {
            const page = document.getElementById('skills-page');
            page.innerHTML = '<div class="loading">載入小龍蝦狀態中</div>';

            const res = await fetch('/get_status', { method: 'POST' });
            const st = await res.json();

            if (st.error) { page.innerHTML = '<div style="color:var(--red)">❌ '+esc(st.error)+'</div>'; return; }

            let h = '';

            if (st.identity) {
                h += '<div class="section-title">🦞 身份</div>';
                h += '<div class="card"><div class="card-preview">'+esc(st.identity)+'</div></div>';
            }

            h += '<div class="section-title">📁 核心檔案</div><div class="file-grid">';
            (st.core_files||[]).forEach(f => h += '<span class="file-chip">'+esc(f)+'</span>');
            h += '</div>';

            h += '<div class="section-title">🧠 記憶系統</div>';
            if (st.memory_index) {
                h += '<div class="card"><div class="card-header"><span class="card-name">MEMORY.md（索引）</span><span class="card-badge badge-core">INDEX</span></div>';
                h += '<div class="card-preview">'+esc(st.memory_index.substring(0,500))+'</div></div>';
            }
            (st.mem_summaries||[]).forEach(m => {
                h += '<div class="card"><div class="card-header"><span class="card-name">'+esc(m.file)+'</span><span class="card-badge badge-mem">MEMORY</span></div>';
                h += '<div class="card-preview">'+esc(m.preview)+'</div></div>';
            });

            if (st.scripts && st.scripts.length > 0) {
                h += '<div class="section-title">🐍 Python 腳本</div><div class="file-grid">';
                st.scripts.forEach(s => h += '<span class="file-chip">'+esc(s)+'</span>');
                h += '</div>';
            }

            h += '<div class="section-title">⚡ 已安裝技能</div>';
            if (st.skills && st.skills.length > 0) {
                h += '<div class="file-grid">';
                st.skills.forEach(s => h += '<span class="file-chip">'+esc(s)+'</span>');
                h += '</div>';
            } else {
                h += '<div class="card" style="color:#64748b;">目前沒有安裝任何 skill</div>';
            }

            // AI 任務分析
            h += '<div class="section-title">🤖 即時任務分析</div><div id="ai-tasks"><div class="loading">分析中</div></div>';
            page.innerHTML = h;

            if (CFG.has_gemini && lastLogs.length > 0) {
                const taskRes = await fetch('/analyze_tasks', { method: 'POST',
                    headers: {'Content-Type':'application/json'},
                    body: JSON.stringify({logs: lastLogs.slice(-30).map(l=>l.content).join("\\n").substring(0,1500)})
                });
                const tasks = await taskRes.json();
                const el = document.getElementById('ai-tasks');
                if (tasks.length === 0) { el.innerHTML = '<div class="card" style="color:#64748b;">目前沒有偵測到任務</div>'; return; }
                el.innerHTML = tasks.map(t => {
                    const icon = t.status==='running'?'🟢':t.status==='error'?'🔴':'✅';
                    return '<div class="card"><div class="card-header"><span class="card-name">'+icon+' '+esc(t.name)+'</span><span class="card-badge badge-task">'+esc(t.status||'?')+'</span></div><div class="card-preview">'+esc(t.desc)+'</div></div>';
                }).join('');
            } else {
                const el = document.getElementById('ai-tasks');
                if (el) el.innerHTML = '<div class="card" style="color:#64748b;">需要 Gemini Key 和日誌</div>';
            }
        }

        function esc(t) { const d=document.createElement('div'); d.textContent=t; return d.innerHTML; }

        init();
    </script>
</body>
</html>
"""

# ============================
# API 路由
# ============================
@app.get("/", response_class=HTMLResponse)
def home(): return HTML_CODE

@app.get("/get_sys_config")
def api_get_config(): return JSONResponse(content=get_sys_config())

@app.post("/get_logs")
def get_logs():
    """拿 Log + 後端翻譯最新一筆（帶快取和頻率限制）"""
    result = fetch_runtime_logs()
    if result.get("logs"):
        last_msg = result["logs"][-1]["content"]
        translated = translate_with_gemini(last_msg)
        result["translated"] = translated
    return JSONResponse(content=result)

@app.post("/get_status")
def get_status():
    return JSONResponse(content=fetch_lobster_status())

@app.post("/analyze_tasks")
async def analyze_tasks_endpoint(request: dict):
    """後端呼叫 Gemini 分析任務"""
    logs_text = request.get("logs", "")
    if not logs_text:
        return JSONResponse(content=[])
    tasks = analyze_tasks_with_gemini(logs_text)
    return JSONResponse(content=tasks)

@app.get("/health")
def health(): return {"status": "ok"}
