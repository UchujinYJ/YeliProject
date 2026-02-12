import os
import json
import time
import requests
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

app = FastAPI()
app.mount("/static", StaticFiles(directory="."), name="static")

# ============================
# Gemini 翻譯
# ============================
translate_cache = {}
last_translate_time = 0
TRANSLATE_COOLDOWN = 30

def get_sys_config():
    return {
        "has_zeabur": bool(os.getenv("ZEABUR_API_TOKEN", "")),
        "has_gemini": bool(os.getenv("GEMINI_KEY", ""))
    }

def call_gemini(prompt, max_len=500):
    global last_translate_time
    gk = os.getenv("GEMINI_KEY", "")
    if not gk:
        return ""
    now = time.time()
    if now - last_translate_time < TRANSLATE_COOLDOWN:
        return ""
    try:
        res = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={gk}",
            headers={"Content-Type": "application/json"},
            json={"contents": [{"parts": [{"text": prompt}]}]},
            timeout=15
        )
        data = res.json()
        if "error" in data:
            return ""
        result = data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
        last_translate_time = now
        return result[:max_len] if result else ""
    except:
        return ""

def translate_with_gemini(text):
    global translate_cache
    text_hash = hash(text[:200])
    if text_hash in translate_cache:
        return translate_cache[text_hash]
    sp = os.getenv("SYSTEM_PROMPT", "你是一個傲嬌的監控秘書。")
    result = call_gemini(f"{sp}\n\n用一句繁體中文白話翻譯這段 Log（不要超過 50 字）：\n{text[:300]}")
    if result:
        translate_cache[text_hash] = result
        if len(translate_cache) > 100:
            keys = list(translate_cache.keys())
            for k in keys[:50]:
                del translate_cache[k]
    return result

# ============================
# Zeabur API
# ============================
ZEABUR_API_URL = "https://api.zeabur.com/graphql"

def get_zeabur_headers():
    token = os.getenv("ZEABUR_API_TOKEN", "")
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

def zeabur_exec(command_list):
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
        formatted = [{"content": l["message"], "timestamp": l["timestamp"]} for l in logs]
        formatted.reverse()
        return {"logs": formatted}
    except Exception as e:
        return {"logs": [], "error": f"連線錯誤: {str(e)}"}

def fetch_lobster_status():
    ws = "/home/node/.openclaw/workspace"
    result = {"core_files": [], "memory_files": [], "scripts": [], "skills": [],
              "memory_index": "", "identity": "", "mem_summaries": [], "soul": ""}
    ls_output = zeabur_exec(["ls", "-1", ws])
    if not ls_output:
        return {"error": "無法連線到夜璃"}
    for f in ls_output.strip().split("\n"):
        f = f.strip()
        if not f: continue
        if f in ["SOUL.md","AGENTS.md","IDENTITY.md","USER.md","TOOLS.md","BOOTSTRAP.md","HEARTBEAT.md","MEMORY.md"]:
            result["core_files"].append(f)
        elif f.startswith("mem-") and f.endswith(".md"):
            result["memory_files"].append(f)
        elif f.endswith(".py"):
            result["scripts"].append(f)
    mem = zeabur_exec(["cat", f"{ws}/MEMORY.md"])
    if mem: result["memory_index"] = mem[:3000]
    ident = zeabur_exec(["cat", f"{ws}/IDENTITY.md"])
    if ident: result["identity"] = ident[:500]
    soul = zeabur_exec(["cat", f"{ws}/SOUL.md"])
    if soul: result["soul"] = soul[:2000]
    skills_out = zeabur_exec(["ls", "-1", f"{ws}/skills/"])
    if skills_out and skills_out.strip():
        result["skills"] = [s.strip() for s in skills_out.strip().split("\n") if s.strip()]
    for mf in result["memory_files"]:
        content = zeabur_exec(["cat", f"{ws}/{mf}"])
        if content:
            result["mem_summaries"].append({"file": mf, "content": content[:2000]})
    return result

# ============================
# API 路由
# ============================
@app.get("/", response_class=HTMLResponse)
def home(): return HTML_CODE

@app.get("/get_sys_config")
def api_get_config(): return JSONResponse(content=get_sys_config())

@app.post("/get_logs")
def get_logs():
    result = fetch_runtime_logs()
    if result.get("logs"):
        last_msg = result["logs"][-1]["content"]
        translated = translate_with_gemini(last_msg)
        result["translated"] = translated
    return JSONResponse(content=result)

@app.post("/get_status")
def get_status(): return JSONResponse(content=fetch_lobster_status())

@app.post("/translate")
async def translate_content(request: Request):
    """按需翻譯單一內容"""
    body = await request.json()
    text = body.get("text", "")
    if not text:
        return JSONResponse(content={"translated": ""})
    cache_key = hash(text[:300])
    if cache_key in translate_cache:
        return JSONResponse(content={"translated": translate_cache[cache_key]})
    prompt = f"將以下 AI Agent 的系統檔案內容翻譯成繁體中文。保留 Markdown 格式和結構。只輸出翻譯結果，不要加任何解釋：\n\n{text[:1500]}"
    result = call_gemini(prompt, max_len=2000)
    if result:
        translate_cache[cache_key] = result
    return JSONResponse(content={"translated": result})

@app.get("/health")
def health(): return {"status": "ok"}

# ============================
# 前端 HTML
# ============================
HTML_CODE = r"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no">
<title>Yeli Room</title>
<link href="https://fonts.googleapis.com/css2?family=DotGothic16&family=Noto+Sans+TC:wght@300;400;700&display=swap" rel="stylesheet">
<script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
<style>
:root{--bg:#080c12;--panel:rgba(12,18,30,.95);--accent:#fbbf24;--text:#c8d6e5;--border:#1e2a42;--green:#22c55e;--red:#ef4444;--blue:#60a5fa;--purple:#a78bfa;--cyan:#22d3ee;--orange:#fb923c;--pink:#f472b6}
*{margin:0;padding:0;box-sizing:border-box}
body{background:var(--bg);font-family:'Noto Sans TC','DotGothic16',sans-serif;color:var(--text);height:100vh;display:flex;flex-direction:column;overflow:hidden}
.sbar{height:28px;background:linear-gradient(90deg,#0d1117,#161b22);color:#8b949e;font-size:11px;line-height:28px;padding:0 12px;z-index:200;display:flex;justify-content:space-between;border-bottom:1px solid #21262d;font-family:'DotGothic16',monospace}
.sdot{display:inline-block;width:7px;height:7px;border-radius:50%;margin-right:6px;animation:pulse 2s infinite}
.sdot.ok{background:var(--green);box-shadow:0 0 6px var(--green)}.sdot.err{background:var(--red);box-shadow:0 0 6px var(--red);animation:none}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.5}}
.tabs{height:44px;background:#0d1117;border-bottom:1px solid #21262d;display:flex}
.tab{flex:1;text-align:center;line-height:44px;cursor:pointer;color:#484f58;font-size:13px;transition:all .2s;position:relative;letter-spacing:.5px}
.tab:hover{color:#c9d1d9;background:rgba(255,255,255,.02)}.tab.active{color:var(--accent);background:rgba(251,191,36,.04)}
.tab.active::after{content:'';position:absolute;bottom:0;left:20%;right:20%;height:2px;background:var(--accent);border-radius:2px 2px 0 0}
.content{flex:1;position:relative;overflow:hidden}
.page{display:none;width:100%;height:100%;position:absolute;top:0;left:0}.page.active{display:flex}
.room-view{background:url('/static/bg.png') no-repeat center center;background-size:contain;background-color:#080c12;image-rendering:pixelated;width:100%;height:100%;position:relative}
.mlog{position:absolute;bottom:16px;left:3%;width:94%;max-height:160px;background:rgba(8,12,18,.92);border:1px solid #1e2a42;padding:10px 12px;font-size:11px;overflow-y:auto;border-radius:6px;backdrop-filter:blur(8px);font-family:'DotGothic16',monospace}
.le{margin-bottom:3px;line-height:1.5}.lt{color:var(--accent);margin-right:8px;opacity:.7}.lm{color:#8b949e}.ltr{color:var(--cyan);font-style:italic;display:block;margin-left:70px;margin-top:1px;font-size:11px}
/* RPG */
.rpg{width:100%;height:100%;display:flex;flex-direction:column;background:radial-gradient(ellipse at 50% 0%,rgba(251,191,36,.03) 0%,transparent 60%),var(--bg);overflow:hidden}
.rpg-h{padding:16px 20px 0;flex-shrink:0}.rpg-t{font-family:'DotGothic16',monospace;font-size:18px;color:var(--accent);text-shadow:0 0 20px rgba(251,191,36,.3)}
.rpg-sub{font-size:11px;color:#484f58;margin-top:4px}
.rpg-st{display:flex;gap:16px;margin-top:12px;padding-bottom:12px;border-bottom:1px solid #1a1f2e}
.stb{text-align:center;min-width:55px}.stv{font-size:20px;font-weight:700;font-family:'DotGothic16',monospace}.stl{font-size:9px;color:#484f58;text-transform:uppercase;letter-spacing:1px}
.rpg-tree{flex:1;overflow-y:auto;padding:16px 20px 20px}
.scat{margin-bottom:20px}.cath{display:flex;align-items:center;gap:8px;margin-bottom:10px}
.catI{width:28px;height:28px;border-radius:6px;display:flex;align-items:center;justify-content:center;font-size:14px}
.catN{font-size:13px;font-weight:700}.catC{font-size:10px;color:#484f58;margin-left:auto}
.sn{display:flex;align-items:center;gap:10px;padding:10px 12px;margin-bottom:6px;border-radius:8px;border:1px solid transparent;background:rgba(255,255,255,.015);transition:all .2s;cursor:pointer}
.sn:hover{background:rgba(255,255,255,.04);border-color:#1e2a42}.sn.act{border-color:var(--accent);background:rgba(251,191,36,.04)}
.sorb{width:36px;height:36px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:16px;flex-shrink:0;position:relative}
.sorb::after{content:'';position:absolute;inset:-2px;border-radius:50%;border:1.5px solid rgba(255,255,255,.1)}
.sinf{flex:1;min-width:0}.snam{font-size:12px;font-weight:700;margin-bottom:2px}
.sdsc{font-size:10px;color:#484f58;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.slv{font-family:'DotGothic16',monospace;font-size:10px;color:#484f58;flex-shrink:0}.slv span{color:var(--accent)}
.sdet{display:none;margin:0 0 10px 58px;padding:10px 14px;background:rgba(255,255,255,.02);border-radius:6px;border-left:2px solid var(--accent);font-size:11px;color:#8b949e;white-space:pre-wrap;max-height:240px;overflow-y:auto;line-height:1.6}
.sdet.open{display:block}
.conn{width:24px;height:20px;margin-left:18px;border-left:1px dashed #1e2a42}
/* MEMORY 3D */
.mp{width:100%;height:100%;display:flex;background:var(--bg);overflow:hidden}
.mcw{flex:1;position:relative}
.msb{width:300px;background:#0d1117;border-left:1px solid #21262d;overflow-y:auto;flex-shrink:0;display:none}.msb.open{display:block}
.msbh{padding:14px 16px;border-bottom:1px solid #21262d;display:flex;justify-content:space-between;align-items:center}
.msbt{font-size:14px;font-weight:700;color:var(--accent)}.msbc{cursor:pointer;color:#484f58;font-size:18px}
.msbb{padding:12px 16px;font-size:11px;color:#8b949e;white-space:pre-wrap;line-height:1.7}
.mleg{position:absolute;bottom:12px;left:12px;background:rgba(13,17,23,.9);border:1px solid #21262d;border-radius:6px;padding:8px 12px;font-size:10px;z-index:10}
.mli{display:flex;align-items:center;gap:6px;margin-bottom:3px}.mld{width:8px;height:8px;border-radius:50%}
.mhint{position:absolute;top:12px;left:50%;transform:translateX(-50%);color:#484f58;font-size:11px;pointer-events:none;font-family:'DotGothic16',monospace;z-index:10}
.loading{color:#484f58;text-align:center;padding:40px;font-family:'DotGothic16',monospace}
.loading::after{content:'';animation:dots 1.5s infinite}@keyframes dots{0%{content:'.'}33%{content:'..'}66%{content:'...'}}
::-webkit-scrollbar{width:4px}::-webkit-scrollbar-track{background:transparent}::-webkit-scrollbar-thumb{background:#1e2a42;border-radius:2px}
</style>
</head>
<body>
<div class="sbar"><span><span class="sdot" id="sdot"></span><span id="stxt">連線中...</span></span><span id="lupd">--:--:--</span></div>
<div class="tabs">
<div class="tab active" onclick="sw('office',this)">OFFICE</div>
<div class="tab" onclick="sw('skills',this)">SKILLS</div>
<div class="tab" onclick="sw('memory',this)">MEMORY</div>
</div>
<div class="content">
<div id="p-office" class="page active" style="display:block"><div class="room-view"><div class="mlog" id="mlog">初始化連線...</div></div></div>
<div id="p-skills" class="page"><div class="rpg" id="rpg"><div class="loading">載入中</div></div></div>
<div id="p-memory" class="page"><div class="mp"><div class="mcw" id="mcw"><div id="labels-wrap" style="position:absolute;top:0;left:0;width:100%;height:100%;pointer-events:none;overflow:hidden;z-index:5"></div><div class="mhint" id="mhint">拖曳旋轉 · 滾輪縮放 · 點擊節點查看詳情</div><div class="mleg" id="mleg"></div></div><div class="msb" id="msb"><div class="msbh"><span class="msbt" id="msbt">--</span><span class="msbc" onclick="csb()">✕</span></div><div class="msbb" id="msbb"></div></div></div></div>
</div>
<script>
let CFG={},LL=[],SD=null;

function sw(p,el){
document.querySelectorAll('.page').forEach(x=>{x.classList.remove('active');x.style.display='none'});
document.querySelectorAll('.tab').forEach(x=>x.classList.remove('active'));
const pg=document.getElementById('p-'+p);pg.classList.add('active');pg.style.display=p==='office'?'block':'flex';
el.classList.add('active');
if(p==='skills')lsp();if(p==='memory')lmp();
}
function ss(ok,t){document.getElementById('sdot').className='sdot '+(ok?'ok':'err');document.getElementById('stxt').innerText=t;if(ok)document.getElementById('lupd').innerText=new Date().toLocaleTimeString('zh-TW',{hour12:false})}

async function init(){const r=await fetch('/get_sys_config');CFG=await r.json();if(CFG.has_zeabur){ss(true,'已連線');sync();setInterval(sync,30000)}else{ss(false,'未設定');document.getElementById('mlog').innerText="❌ 缺少環境變數"}}

async function sync(){try{const r=await fetch('/get_logs',{method:'POST'});const d=await r.json();if(d.logs&&d.logs.length>0){LL=d.logs;ss(true,'已連線 ('+d.logs.length+' 筆)');rl(d)}else if(d.error){ss(false,d.error);document.getElementById('mlog').innerText="❌ "+d.error}else{ss(true,'暫無日誌');document.getElementById('mlog').innerText="🌙 安靜中..."}}catch(e){ss(false,'連線失敗')}}

function rl(d){const el=document.getElementById('mlog');const rc=d.logs.slice(-10);const tr=d.translated||'';
el.innerHTML=rc.map((l,i)=>{const t=l.timestamp?new Date(l.timestamp).toLocaleTimeString('zh-TW',{hour12:false}):'--:--:--';const la=i===rc.length-1;
return'<div class="le"><span class="lt">'+t+'</span><span class="lm">'+E(l.content.substring(0,200))+'</span>'+(la&&tr?'<span class="ltr">🌙 '+E(tr)+'</span>':'')+'</div>'}).join('');el.scrollTop=el.scrollHeight}

// ========== SKILLS ==========
async function lsp(){
const pg=document.getElementById('rpg');
if(!SD){pg.innerHTML='<div class="loading">讀取夜璃資料中</div>';const r=await fetch('/get_status',{method:'POST'});SD=await r.json()}
if(SD.error){pg.innerHTML='<div style="color:var(--red);padding:20px">❌ '+E(SD.error)+'</div>';return}
const s=SD,cc=(s.core_files||[]).length,mc=(s.memory_files||[]).length,sc=(s.scripts||[]).length,kc=(s.skills||[]).length,tt=cc+mc+sc+kc;
let h='<div class="rpg-h"><div class="rpg-t">⚔️ 夜璃 — 能力面板</div><div class="rpg-sub">'+E(s.identity||'AI Agent on OpenClaw')+'</div><div class="rpg-st">'+sb(tt,'TOTAL')+sb(cc,'核心')+sb(mc,'記憶')+sb(sc,'腳本')+sb(kc,'技能')+'</div></div><div class="rpg-tree">';
h+=sC('💛','var(--accent)','核心系統',s.core_files||[],'core',s);
h+=sC('🧠','var(--blue)','記憶模組',s.memory_files||[],'memory',s);
h+=sC('🐍','var(--green)','Python 腳本',s.scripts||[],'script',s);
h+=sC('⚡','var(--purple)','已安裝技能',s.skills||[],'skill',s);
h+='</div>';pg.innerHTML=h;
pg.querySelectorAll('.sn').forEach(n=>{n.addEventListener('click',()=>{const d=n.nextElementSibling;if(d&&d.classList.contains('sdet')){n.classList.toggle('act');d.classList.toggle('open')}})})
}
function sb(v,l){return'<div class="stb"><div class="stv" style="color:'+(v>0?'var(--accent)':'#484f58')+'">'+v+'</div><div class="stl">'+l+'</div></div>'}
function sC(ico,col,name,files,type,s){
if(type==='skill'&&!files.length)return'<div class="scat"><div class="cath"><div class="catI" style="background:rgba(168,139,250,.1)">'+ico+'</div><div class="catN" style="color:'+col+'">'+name+'</div><div class="catC">0</div></div><div class="sn" style="opacity:.4;cursor:default"><div class="sorb" style="background:rgba(255,255,255,.03)">🔒</div><div class="sinf"><div class="snam" style="color:#484f58">尚未安裝技能</div><div class="sdsc">Skills 資料夾目前為空</div></div></div></div>';
let h='<div class="scat"><div class="cath"><div class="catI" style="background:'+col+'15">'+ico+'</div><div class="catN" style="color:'+col+'">'+name+'</div><div class="catC">'+files.length+'</div></div>';
files.forEach((f,i)=>{
const det=gD(f,type,s),lv=gL(f,type),oc=gOC(type),fi=gFI(f,type),uid='det_'+type+'_'+i;
h+='<div class="sn"><div class="sorb" style="background:'+oc+'">'+fi+'</div><div class="sinf"><div class="snam">'+E(f)+'</div><div class="sdsc">'+E(gFD(f,type))+'</div></div><div class="slv">Lv.<span>'+lv+'</span></div></div>';
h+='<div class="sdet" id="'+uid+'">'+E(det)+'</div>';
if(i<files.length-1)h+='<div class="conn"></div>'});
return h+'</div>'}
function gD(f,t,s){if(t==='core'){if(f==='MEMORY.md'&&s.memory_index)return s.memory_index.substring(0,800);if(f==='IDENTITY.md'&&s.identity)return s.identity;if(f==='SOUL.md'&&s.soul)return s.soul.substring(0,800)}if(t==='memory'){const m=(s.mem_summaries||[]).find(x=>x.file===f);if(m)return m.content.substring(0,800)}return'（無預覽資料）'}
function gL(f,t){if(t==='core')return{'SOUL.md':5,'AGENTS.md':4,'IDENTITY.md':3,'MEMORY.md':5,'USER.md':2,'TOOLS.md':3,'BOOTSTRAP.md':2,'HEARTBEAT.md':1}[f]||1;if(t==='memory')return 3;if(t==='script')return 2;return 1}
function gOC(t){return{core:'rgba(251,191,36,.15)',memory:'rgba(96,165,250,.15)',script:'rgba(34,197,94,.15)',skill:'rgba(167,139,250,.15)'}[t]}
function gFI(f,t){if(t==='core')return{'SOUL.md':'🔥','AGENTS.md':'🤖','IDENTITY.md':'🦞','MEMORY.md':'📋','USER.md':'👤','TOOLS.md':'🔧','BOOTSTRAP.md':'🚀','HEARTBEAT.md':'💓'}[f]||'📄';if(t==='memory')return'💾';if(t==='script')return'⚙️';return'⚡'}
function gFD(f,t){if(t==='core')return{'SOUL.md':'核心人格與行為準則','AGENTS.md':'多代理協作框架','IDENTITY.md':'身份定義','MEMORY.md':'記憶索引系統','USER.md':'使用者偏好','TOOLS.md':'可用工具列表','BOOTSTRAP.md':'啟動流程','HEARTBEAT.md':'心跳配置'}[f]||'';
if(t==='memory')return{'mem-crypto.md':'加密貨幣追蹤','mem-daily.md':'每日紀錄','mem-decisions.md':'決策記錄','mem-lessons.md':'學習經驗','mem-prefs.md':'偏好設定','mem-quest.md':'任務追蹤','mem-settings.md':'系統設定'}[f]||'記憶檔案';
if(t==='script')return{'crypto_check.py':'加密貨幣價格監控','bounty_hunter.py':'賞金獵人系統','check_profit.py':'損益計算','jailbreak_pip.py':'套件安裝工具'}[f]||'Python 腳本';return''}

// ========== 3D MEMORY GRAPH ==========
let scene,camera,renderer,nodeGroup,edgeGroup,raycaster,mouse,nodeDataMap={},controls;
let isRotating=false,prevMouse={x:0,y:0},autoRotate=true;
let labelEls=[];

async function lmp(){
if(!SD){const r=await fetch('/get_status',{method:'POST'});SD=await r.json()}
if(SD.error)return;
const wrap=document.getElementById('mcw');
// 避免重複初始化
if(renderer){nodeGroup.clear();edgeGroup.clear();labelEls.forEach(l=>l.lbl.remove());labelEls=[];buildNodes3D(SD);return}
init3D(SD);
document.getElementById('mleg').innerHTML=[{c:'#fbbf24',l:'中心'},{c:'#ef4444',l:'核心'},{c:'#60a5fa',l:'記憶'},{c:'#22c55e',l:'腳本'}].map(x=>'<div class="mli"><div class="mld" style="background:'+x.c+'"></div>'+x.l+'</div>').join('')}

function init3D(s){
const wrap=document.getElementById('mcw');
const W=wrap.clientWidth,H=wrap.clientHeight;

scene=new THREE.Scene();
camera=new THREE.PerspectiveCamera(60,W/H,1,2000);
camera.position.set(0,0,400);

renderer=new THREE.WebGLRenderer({antialias:true,alpha:true});
renderer.setSize(W,H);renderer.setPixelRatio(devicePixelRatio);
renderer.setClearColor(0x080c12,1);
wrap.insertBefore(renderer.domElement,wrap.firstChild);

// Lights
scene.add(new THREE.AmbientLight(0x404050,0.6));
const pl=new THREE.PointLight(0xfbbf24,1,600);pl.position.set(0,0,200);scene.add(pl);

raycaster=new THREE.Raycaster();mouse=new THREE.Vector2();
nodeGroup=new THREE.Group();edgeGroup=new THREE.Group();
scene.add(edgeGroup);scene.add(nodeGroup);

buildNodes3D(s);
setupInteraction3D(wrap);
animate3D();
window.addEventListener('resize',()=>{
const w2=wrap.clientWidth,h2=wrap.clientHeight;
camera.aspect=w2/h2;camera.updateProjectionMatrix();renderer.setSize(w2,h2)});
}

function makeNode3D(id,label,pos,radius,color,content){
const geo=new THREE.SphereGeometry(radius,24,24);
const mat=new THREE.MeshPhongMaterial({color:new THREE.Color(color),emissive:new THREE.Color(color),emissiveIntensity:0.3,transparent:true,opacity:0.85});
const mesh=new THREE.Mesh(geo,mat);
mesh.position.copy(pos);
mesh.userData={id,label,content,color,radius};
nodeDataMap[id]={mesh,label,content,color};
nodeGroup.add(mesh);

// 光暈
const glowGeo=new THREE.SphereGeometry(radius*1.6,16,16);
const glowMat=new THREE.MeshBasicMaterial({color:new THREE.Color(color),transparent:true,opacity:0.08});
const glow=new THREE.Mesh(glowGeo,glowMat);
glow.position.copy(pos);
nodeGroup.add(glow);

// HTML label
const lbl=document.createElement('div');
lbl.style.cssText='position:absolute;color:#c8d6e5;font-size:10px;font-family:"Noto Sans TC",sans-serif;white-space:nowrap;text-shadow:0 0 4px #000,0 0 8px #000;transform:translate(-50%,0);pointer-events:none';
lbl.innerText=label;
document.getElementById('labels-wrap').appendChild(lbl);
labelEls.push({mesh,lbl,offset:radius+6});

return mesh;
}

function buildNodes3D(s){
// Center
makeNode3D('core','🌙 夜璃',new THREE.Vector3(0,0,0),20,'#fbbf24',s.identity||'AI Agent');

// Core ring (horizontal circle)
const cf=s.core_files||[];
const ccm={'SOUL.md':'#ef4444','AGENTS.md':'#f97316','IDENTITY.md':'#fbbf24','MEMORY.md':'#22d3ee','USER.md':'#a78bfa','TOOLS.md':'#22c55e','BOOTSTRAP.md':'#6366f1','HEARTBEAT.md':'#f472b6'};
cf.forEach((f,i)=>{
const a=(i/cf.length)*Math.PI*2;
const p=new THREE.Vector3(Math.cos(a)*90,Math.sin(a)*90,(Math.random()-0.5)*30);
const n=makeNode3D('c_'+f,f.replace('.md',''),p,10,ccm[f]||'#60a5fa',gD(f,'core',s));
addEdge3D(new THREE.Vector3(0,0,0),p,ccm[f]||'#60a5fa');
});

// Memory ring (tilted)
const mf=s.memory_files||[];
const mcm={'mem-crypto.md':'#fb923c','mem-daily.md':'#60a5fa','mem-decisions.md':'#a78bfa','mem-lessons.md':'#22c55e','mem-prefs.md':'#f472b6','mem-quest.md':'#fbbf24','mem-settings.md':'#6366f1'};
mf.forEach((f,i)=>{
const a=(i/mf.length)*Math.PI*2;
const p=new THREE.Vector3(Math.cos(a)*160,Math.sin(a)*100+40,(Math.sin(a*2))*60);
const mc=(s.mem_summaries||[]).find(x=>x.file===f);
makeNode3D('m_'+f,f.replace('mem-','').replace('.md',''),p,8,mcm[f]||'#60a5fa',mc?mc.content.substring(0,800):'');
// Connect to MEMORY.md
const memNode=nodeDataMap['c_MEMORY.md'];
if(memNode)addEdge3D(memNode.mesh.position,p,mcm[f]||'#60a5fa');
});

// Scripts (outer)
const sc=s.scripts||[];
sc.forEach((f,i)=>{
const a=(i/sc.length)*Math.PI*2+Math.PI/4;
const p=new THREE.Vector3(Math.cos(a)*200,(Math.sin(a)*80)-60,(Math.cos(a*1.5))*80);
makeNode3D('s_'+f,f.replace('.py',''),p,7,'#22c55e',f);
const toolNode=nodeDataMap['c_TOOLS.md'];
if(toolNode)addEdge3D(toolNode.mesh.position,p,'#22c55e');
});
}

function addEdge3D(from,to,color){
const pts=[from.clone(),to.clone()];
const geo=new THREE.BufferGeometry().setFromPoints(pts);
const mat=new THREE.LineBasicMaterial({color:new THREE.Color(color),transparent:true,opacity:0.2});
edgeGroup.add(new THREE.Line(geo,mat));
}

function setupInteraction3D(wrap){
const cv=renderer.domElement;
let dragDist=0,mouseDownPos={x:0,y:0};

cv.addEventListener('mousedown',e=>{isRotating=true;autoRotate=false;dragDist=0;mouseDownPos={x:e.clientX,y:e.clientY};prevMouse={x:e.clientX,y:e.clientY}});
cv.addEventListener('mousemove',e=>{if(!isRotating)return;const dx=e.clientX-prevMouse.x,dy=e.clientY-prevMouse.y;
dragDist+=Math.abs(dx)+Math.abs(dy);
nodeGroup.rotation.y+=dx*0.005;nodeGroup.rotation.x+=dy*0.005;edgeGroup.rotation.y+=dx*0.005;edgeGroup.rotation.x+=dy*0.005;
prevMouse={x:e.clientX,y:e.clientY}});
cv.addEventListener('mouseup',e=>{
isRotating=false;
if(dragDist<5){handleNodeClick(e.clientX,e.clientY,cv)}
});
cv.addEventListener('mouseleave',()=>isRotating=false);
cv.addEventListener('wheel',e=>{e.preventDefault();camera.position.z+=e.deltaY*0.5;camera.position.z=Math.max(100,Math.min(800,camera.position.z))},{passive:false});

// Touch
let touchStart=null,touchDragDist=0;
cv.addEventListener('touchstart',e=>{if(e.touches.length===1){isRotating=true;autoRotate=false;touchDragDist=0;touchStart=Date.now();prevMouse={x:e.touches[0].clientX,y:e.touches[0].clientY}}});
cv.addEventListener('touchmove',e=>{e.preventDefault();if(isRotating&&e.touches.length===1){const dx=e.touches[0].clientX-prevMouse.x,dy=e.touches[0].clientY-prevMouse.y;
touchDragDist+=Math.abs(dx)+Math.abs(dy);
nodeGroup.rotation.y+=dx*0.005;nodeGroup.rotation.x+=dy*0.005;edgeGroup.rotation.y+=dx*0.005;edgeGroup.rotation.x+=dy*0.005;
prevMouse={x:e.touches[0].clientX,y:e.touches[0].clientY}}},{passive:false});
cv.addEventListener('touchend',e=>{isRotating=false;
if(touchDragDist<10&&e.changedTouches.length===1){const t=e.changedTouches[0];handleNodeClick(t.clientX,t.clientY,cv)}});
}

function handleNodeClick(cx,cy,cv){
const rect=cv.getBoundingClientRect();
mouse.x=((cx-rect.left)/rect.width)*2-1;
mouse.y=-((cy-rect.top)/rect.height)*2+1;
raycaster.setFromCamera(mouse,camera);
const hits=raycaster.intersectObjects(nodeGroup.children);
const hit=hits.find(h=>h.object.userData&&h.object.userData.id);
if(hit){
const d=hit.object.userData;
document.getElementById('msbt').innerText=d.label;
const body=document.getElementById('msbb');
const hasContent=d.content&&d.content.trim();
body.innerHTML=(hasContent?'<div class="det-raw" style="margin-bottom:12px">'+E(d.content)+'</div>':'<div style="color:#484f58">（無內容）</div>')+(hasContent&&CFG.has_gemini?'<div onclick="trSb(this)" style="display:inline-block;padding:5px 14px;background:rgba(251,191,36,.12);color:#fbbf24;border:1px solid rgba(251,191,36,.3);border-radius:5px;font-size:11px;cursor:pointer;margin-top:4px">🌐 翻譯成中文</div>':'');
document.getElementById('msb').classList.add('open');
document.getElementById('mhint').style.display='none';
nodeGroup.children.forEach(c=>{if(c.material&&c.material.emissiveIntensity!==undefined)c.material.emissiveIntensity=c===hit.object?0.8:0.3});
}}

let trCache={};
async function trSb(btn){
if(btn.classList.contains('done'))return;
btn.innerText='⏳ 翻譯中...';btn.style.opacity='0.5';btn.classList.add('done');
const raw=document.querySelector('#msbb .det-raw');
if(!raw)return;
const text=raw.innerText;
const key=text.substring(0,200);
if(trCache[key]){raw.innerText=trCache[key];btn.innerText='✅ 已翻譯';return}
try{const r=await fetch('/translate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text:text})});
const d=await r.json();
if(d.translated){trCache[key]=d.translated;raw.innerText=d.translated;btn.innerText='✅ 已翻譯'}
else{btn.innerText='⏳ 冷卻中，稍後再試';btn.style.opacity='1';btn.classList.remove('done')}
}catch(e){btn.innerText='❌ 失敗';btn.style.opacity='1';btn.classList.remove('done')}}

function animate3D(){
requestAnimationFrame(animate3D);
if(autoRotate){nodeGroup.rotation.y+=0.002;edgeGroup.rotation.y+=0.002}
renderer.render(scene,camera);
// 更新 HTML 標籤位置
const W=renderer.domElement.clientWidth,H=renderer.domElement.clientHeight;
labelEls.forEach(({mesh,lbl,offset})=>{
const wp=new THREE.Vector3();
mesh.getWorldPosition(wp);
const v=wp.clone().project(camera);
const x=(v.x*0.5+0.5)*W;
const y=(-v.y*0.5+0.5)*H;
if(v.z>1){lbl.style.display='none';return}
lbl.style.display='';
lbl.style.left=x+'px';lbl.style.top=(y+offset*0.8)+'px';
lbl.style.opacity=v.z<0.99?'1':'0.3';
});
}

function csb(){document.getElementById('msb').classList.remove('open');
nodeGroup.children.forEach(c=>{if(c.material&&c.material.emissiveIntensity!==undefined)c.material.emissiveIntensity=0.3})}
function E(t){const d=document.createElement('div');d.textContent=t;return d.innerHTML}

init();
</script>
</body>
</html>"""
