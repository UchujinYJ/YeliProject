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
# Gemini 翻譯快取
# ============================
translate_cache = {}
last_translate_time = 0
TRANSLATE_COOLDOWN = 60

def get_sys_config():
    return {
        "has_zeabur": bool(os.getenv("ZEABUR_API_TOKEN", "")),
        "has_gemini": bool(os.getenv("GEMINI_KEY", ""))
    }

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

def translate_with_gemini(text):
    global last_translate_time, translate_cache
    gk = os.getenv("GEMINI_KEY", "")
    if not gk:
        return ""
    text_hash = hash(text[:200])
    if text_hash in translate_cache:
        return translate_cache[text_hash]
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
        translate_cache[text_hash] = result
        last_translate_time = now
        if len(translate_cache) > 50:
            keys = list(translate_cache.keys())
            for k in keys[:25]:
                del translate_cache[k]
        return result
    except:
        return ""

def fetch_lobster_status():
    ws = "/home/node/.openclaw/workspace"
    result = {"core_files": [], "memory_files": [], "scripts": [], "skills": [],
              "memory_index": "", "identity": "", "mem_summaries": [], "soul": ""}
    ls_output = zeabur_exec(["ls", "-1", ws])
    if not ls_output:
        return {"error": "無法連線到小龍蝦"}
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

@app.get("/health")
def health(): return {"status": "ok"}

# ============================
# 前端 HTML (raw string)
# ============================
HTML_CODE = r"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no">
<title>Yeli Room</title>
<link href="https://fonts.googleapis.com/css2?family=DotGothic16&family=Noto+Sans+TC:wght@300;400;700&display=swap" rel="stylesheet">
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
.sdet{display:none;margin:0 0 10px 58px;padding:10px 14px;background:rgba(255,255,255,.02);border-radius:6px;border-left:2px solid var(--accent);font-size:11px;color:#8b949e;white-space:pre-wrap;max-height:200px;overflow-y:auto;line-height:1.6}
.sdet.open{display:block}.conn{width:24px;height:20px;margin-left:18px;border-left:1px dashed #1e2a42}
.mp{width:100%;height:100%;display:flex;background:var(--bg);overflow:hidden}
.mcw{flex:1;position:relative}.mcw canvas{width:100%;height:100%}
.msb{width:280px;background:#0d1117;border-left:1px solid #21262d;overflow-y:auto;flex-shrink:0;display:none}.msb.open{display:block}
.msbh{padding:14px 16px;border-bottom:1px solid #21262d;display:flex;justify-content:space-between;align-items:center}
.msbt{font-size:14px;font-weight:700;color:var(--accent)}.msbc{cursor:pointer;color:#484f58;font-size:18px}
.msbb{padding:12px 16px;font-size:11px;color:#8b949e;white-space:pre-wrap;line-height:1.7}
.mleg{position:absolute;bottom:12px;left:12px;background:rgba(13,17,23,.9);border:1px solid #21262d;border-radius:6px;padding:8px 12px;font-size:10px}
.mli{display:flex;align-items:center;gap:6px;margin-bottom:3px}.mld{width:8px;height:8px;border-radius:50%}
.mhint{position:absolute;top:12px;left:50%;transform:translateX(-50%);color:#484f58;font-size:11px;pointer-events:none;font-family:'DotGothic16',monospace}
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
<div id="p-memory" class="page"><div class="mp"><div class="mcw"><canvas id="mc"></canvas><div class="mhint" id="mhint">點擊節點查看記憶詳情</div><div class="mleg" id="mleg"></div></div><div class="msb" id="msb"><div class="msbh"><span class="msbt" id="msbt">--</span><span class="msbc" onclick="csb()">✕</span></div><div class="msbb" id="msbb"></div></div></div></div>
</div>
<script>
let CFG={},LL=[],SD=null,MN=[],ME=[],SN=null,cX=0,cY=0,zm=1,dr=false,ds={x:0,y:0},cs={x:0,y:0};

function sw(p,el){
document.querySelectorAll('.page').forEach(x=>{x.classList.remove('active');x.style.display='none'});
document.querySelectorAll('.tab').forEach(x=>x.classList.remove('active'));
const pg=document.getElementById('p-'+p);pg.classList.add('active');pg.style.display=p==='office'?'block':'flex';
el.classList.add('active');
if(p==='skills')lsp();if(p==='memory')lmp();
}
function ss(ok,t){document.getElementById('sdot').className='sdot '+(ok?'ok':'err');document.getElementById('stxt').innerText=t;if(ok)document.getElementById('lupd').innerText=new Date().toLocaleTimeString('zh-TW',{hour12:false})}

async function init(){
const r=await fetch('/get_sys_config');CFG=await r.json();
if(CFG.has_zeabur){ss(true,'已連線');sync();setInterval(sync,30000)}
else{ss(false,'未設定');document.getElementById('mlog').innerText="❌ 缺少環境變數"}
}

async function sync(){
try{const r=await fetch('/get_logs',{method:'POST'});const d=await r.json();
if(d.logs&&d.logs.length>0){LL=d.logs;ss(true,'已連線 ('+d.logs.length+' 筆)');rl(d)}
else if(d.error){ss(false,d.error);document.getElementById('mlog').innerText="❌ "+d.error}
else{ss(true,'暫無日誌');document.getElementById('mlog').innerText="🦞 安靜中..."}
}catch(e){ss(false,'連線失敗')}}

function rl(d){const el=document.getElementById('mlog');const rc=d.logs.slice(-10);const tr=d.translated||'';
el.innerHTML=rc.map((l,i)=>{const t=l.timestamp?new Date(l.timestamp).toLocaleTimeString('zh-TW',{hour12:false}):'--:--:--';const la=i===rc.length-1;
return'<div class="le"><span class="lt">'+t+'</span><span class="lm">'+E(l.content.substring(0,200))+'</span>'+(la&&tr?'<span class="ltr">🦞 '+E(tr)+'</span>':'')+'</div>'}).join('');el.scrollTop=el.scrollHeight}

// ========== SKILLS PAGE ==========
async function lsp(){
const pg=document.getElementById('rpg');
if(!SD){pg.innerHTML='<div class="loading">讀取小龍蝦資料中</div>';const r=await fetch('/get_status',{method:'POST'});SD=await r.json()}
if(SD.error){pg.innerHTML='<div style="color:var(--red);padding:20px">❌ '+E(SD.error)+'</div>';return}
const s=SD,cc=(s.core_files||[]).length,mc=(s.memory_files||[]).length,sc=(s.scripts||[]).length,kc=(s.skills||[]).length,tt=cc+mc+sc+kc;
let h='<div class="rpg-h"><div class="rpg-t">⚔️ 小龍蝦 — 能力面板</div><div class="rpg-sub">'+E(s.identity||'AI Agent on OpenClaw')+'</div><div class="rpg-st">'+sb(tt,'TOTAL')+sb(cc,'核心')+sb(mc,'記憶')+sb(sc,'腳本')+sb(kc,'技能')+'</div></div><div class="rpg-tree">';
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
const det=gD(f,type,s),lv=gL(f,type),oc=gOC(type),fi=gFI(f,type);
h+='<div class="sn"><div class="sorb" style="background:'+oc+'">'+fi+'</div><div class="sinf"><div class="snam">'+E(f)+'</div><div class="sdsc">'+E(gFD(f,type))+'</div></div><div class="slv">Lv.<span>'+lv+'</span></div></div>';
h+='<div class="sdet">'+E(det)+'</div>';
if(i<files.length-1)h+='<div class="conn"></div>'});
return h+'</div>'}
function gD(f,t,s){
if(t==='core'){if(f==='MEMORY.md'&&s.memory_index)return s.memory_index.substring(0,800);if(f==='IDENTITY.md'&&s.identity)return s.identity;if(f==='SOUL.md'&&s.soul)return s.soul.substring(0,800)}
if(t==='memory'){const m=(s.mem_summaries||[]).find(x=>x.file===f);if(m)return m.content.substring(0,800)}
return'點擊展開（無預覽資料）'}
function gL(f,t){if(t==='core')return{'SOUL.md':5,'AGENTS.md':4,'IDENTITY.md':3,'MEMORY.md':5,'USER.md':2,'TOOLS.md':3,'BOOTSTRAP.md':2,'HEARTBEAT.md':1}[f]||1;if(t==='memory')return 3;if(t==='script')return 2;return 1}
function gOC(t){return{core:'rgba(251,191,36,.15)',memory:'rgba(96,165,250,.15)',script:'rgba(34,197,94,.15)',skill:'rgba(167,139,250,.15)'}[t]}
function gFI(f,t){if(t==='core')return{'SOUL.md':'🔥','AGENTS.md':'🤖','IDENTITY.md':'🦞','MEMORY.md':'📋','USER.md':'👤','TOOLS.md':'🔧','BOOTSTRAP.md':'🚀','HEARTBEAT.md':'💓'}[f]||'📄';if(t==='memory')return'💾';if(t==='script')return'⚙️';return'⚡'}
function gFD(f,t){if(t==='core')return{'SOUL.md':'核心人格與行為準則','AGENTS.md':'多代理協作框架','IDENTITY.md':'身份定義','MEMORY.md':'記憶索引系統','USER.md':'使用者偏好','TOOLS.md':'可用工具列表','BOOTSTRAP.md':'啟動流程','HEARTBEAT.md':'心跳配置'}[f]||'';
if(t==='memory')return{'mem-crypto.md':'加密貨幣追蹤','mem-daily.md':'每日紀錄','mem-decisions.md':'決策記錄','mem-lessons.md':'學習經驗','mem-prefs.md':'偏好設定','mem-quest.md':'任務追蹤','mem-settings.md':'系統設定'}[f]||'記憶檔案';
if(t==='script')return{'crypto_check.py':'加密貨幣價格監控','bounty_hunter.py':'賞金獵人系統','check_profit.py':'損益計算','jailbreak_pip.py':'套件安裝工具'}[f]||'Python 腳本';return''}

// ========== MEMORY GRAPH ==========
async function lmp(){
if(!SD){const r=await fetch('/get_status',{method:'POST'});SD=await r.json()}
if(SD.error)return;bg(SD);dg()}

function bg(s){
MN=[];ME=[];const cx=0,cy=0;
MN.push({id:'core',label:'🦞 小龍蝦',x:cx,y:cy,r:30,color:'#fbbf24',type:'center',content:s.identity||'AI Agent'});
const cf=s.core_files||[],ccm={'SOUL.md':'#ef4444','AGENTS.md':'#f97316','IDENTITY.md':'#fbbf24','MEMORY.md':'#22d3ee','USER.md':'#a78bfa','TOOLS.md':'#22c55e','BOOTSTRAP.md':'#6366f1','HEARTBEAT.md':'#f472b6'};
cf.forEach((f,i)=>{const a=(i/cf.length)*Math.PI*2-Math.PI/2,d=120;MN.push({id:'c_'+f,label:f.replace('.md',''),x:cx+Math.cos(a)*d,y:cy+Math.sin(a)*d,r:16,color:ccm[f]||'#60a5fa',type:'core',content:gD(f,'core',s)});ME.push({from:'core',to:'c_'+f})});
const mf=s.memory_files||[],mcm={'mem-crypto.md':'#fb923c','mem-daily.md':'#60a5fa','mem-decisions.md':'#a78bfa','mem-lessons.md':'#22c55e','mem-prefs.md':'#f472b6','mem-quest.md':'#fbbf24','mem-settings.md':'#6366f1'};
mf.forEach((f,i)=>{const a=(i/mf.length)*Math.PI*2+Math.PI/6,d=220;const mc=(s.mem_summaries||[]).find(x=>x.file===f);MN.push({id:'m_'+f,label:f.replace('mem-','').replace('.md',''),x:cx+Math.cos(a)*d,y:cy+Math.sin(a)*d,r:13,color:mcm[f]||'#60a5fa',type:'memory',content:mc?mc.content.substring(0,800):''});ME.push({from:'c_MEMORY.md',to:'m_'+f})});
const sc=s.scripts||[];
sc.forEach((f,i)=>{const a=(i/sc.length)*Math.PI*2+Math.PI/3,d=300;MN.push({id:'s_'+f,label:f.replace('.py',''),x:cx+Math.cos(a)*d,y:cy+Math.sin(a)*d,r:11,color:'#22c55e',type:'script',content:f});ME.push({from:'c_TOOLS.md',to:'s_'+f})});
document.getElementById('mleg').innerHTML=[{c:'#fbbf24',l:'中心'},{c:'#ef4444',l:'核心'},{c:'#60a5fa',l:'記憶'},{c:'#22c55e',l:'腳本'}].map(x=>'<div class="mli"><div class="mld" style="background:'+x.c+'"></div>'+x.l+'</div>').join('')}

function dg(){
const cv=document.getElementById('mc'),wp=cv.parentElement;
cv.width=wp.clientWidth*devicePixelRatio;cv.height=wp.clientHeight*devicePixelRatio;
cv.style.width=wp.clientWidth+'px';cv.style.height=wp.clientHeight+'px';
const c=cv.getContext('2d');c.setTransform(devicePixelRatio,0,0,devicePixelRatio,0,0);
const W=wp.clientWidth,H=wp.clientHeight,ox=W/2+cX,oy=H/2+cY;
c.clearRect(0,0,W,H);
ME.forEach(e=>{const a=MN.find(n=>n.id===e.from),b=MN.find(n=>n.id===e.to);if(!a||!b)return;c.beginPath();c.moveTo(ox+a.x*zm,oy+a.y*zm);c.lineTo(ox+b.x*zm,oy+b.y*zm);c.strokeStyle='rgba(30,42,66,.6)';c.lineWidth=1;c.stroke()});
MN.forEach(n=>{const nx=ox+n.x*zm,ny=oy+n.y*zm,nr=n.r*zm;
const g=c.createRadialGradient(nx,ny,nr*.3,nx,ny,nr*2);g.addColorStop(0,n.color+'30');g.addColorStop(1,'transparent');c.fillStyle=g;c.beginPath();c.arc(nx,ny,nr*2,0,Math.PI*2);c.fill();
c.beginPath();c.arc(nx,ny,nr,0,Math.PI*2);c.fillStyle=n===SN?n.color:n.color+'40';c.fill();c.strokeStyle=n===SN?'#fff':n.color+'80';c.lineWidth=n===SN?2:1;c.stroke();
c.fillStyle='#c8d6e5';c.font=Math.max(9,11*zm)+'px "Noto Sans TC",sans-serif';c.textAlign='center';c.fillText(n.label,nx,ny+nr+14*zm)})}

function sce(){
const cv=document.getElementById('mc');
cv.addEventListener('mousedown',e=>{dr=true;ds={x:e.clientX,y:e.clientY};cs={x:cX,y:cY}});
cv.addEventListener('mousemove',e=>{if(!dr)return;cX=cs.x+(e.clientX-ds.x);cY=cs.y+(e.clientY-ds.y);dg()});
cv.addEventListener('mouseup',()=>dr=false);cv.addEventListener('mouseleave',()=>dr=false);
cv.addEventListener('wheel',e=>{e.preventDefault();zm*=e.deltaY>0?.9:1.1;zm=Math.max(.3,Math.min(3,zm));dg()},{passive:false});
cv.addEventListener('click',e=>{const r=cv.getBoundingClientRect(),mx=e.clientX-r.left,my=e.clientY-r.top,W=r.width,H=r.height,ox=W/2+cX,oy=H/2+cY;let found=null;
MN.forEach(n=>{const nx=ox+n.x*zm,ny=oy+n.y*zm,nr=n.r*zm;if(Math.sqrt((mx-nx)**2+(my-ny)**2)<nr+5)found=n});
if(found){SN=found;document.getElementById('msbt').innerText=found.label;document.getElementById('msbb').innerText=found.content||'（無內容）';document.getElementById('msb').classList.add('open');document.getElementById('mhint').style.display='none'}
else{SN=null;document.getElementById('msb').classList.remove('open')}dg()});
let lt=null;
cv.addEventListener('touchstart',e=>{if(e.touches.length===1){dr=true;ds={x:e.touches[0].clientX,y:e.touches[0].clientY};cs={x:cX,y:cY}}});
cv.addEventListener('touchmove',e=>{e.preventDefault();if(dr&&e.touches.length===1){cX=cs.x+(e.touches[0].clientX-ds.x);cY=cs.y+(e.touches[0].clientY-ds.y);dg()}},{passive:false});
cv.addEventListener('touchend',e=>{dr=false});
window.addEventListener('resize',()=>{if(MN.length)dg()})}

function csb(){document.getElementById('msb').classList.remove('open');SN=null;dg()}
function E(t){const d=document.createElement('div');d.textContent=t;return d.innerHTML}

sce();init();
</script>
</body>
</html>"""
