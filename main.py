from fastapi import FastAPI
from fastapi.responses import HTMLResponse
import requests

app = FastAPI()

# 這是手機會看到的畫面
HTML_PAGE = """
<!DOCTYPE html>
<html>
<head>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>小龍蝦手機監控</title>
    <style>
        body { background: #111; color: #eee; font-family: monospace; padding: 20px; }
        .box { background: #222; border: 1px solid #444; padding: 15px; border-radius: 8px; margin-bottom: 15px; }
        input, textarea, button { width: 100%; box-sizing: border-box; margin-top: 5px; padding: 10px; background: #000; color: #fff; border: 1px solid #555; }
        button { background: #10b981; color: #000; font-weight: bold; cursor: pointer; margin-top: 15px; }
        .log-area { height: 200px; overflow-y: auto; background: #000; padding: 10px; border: 1px solid #555; font-size: 13px; }
        .ai-text { color: #fbbf24; margin-top: 2px; }
    </style>
</head>
<body>
    <h2 style="color: #10b981;">📱 小龍蝦手機監控台</h2>
    
    <div class="box">
        <h3>1. 填寫鑰匙 (手機會自動記住)</h3>
        <input type="password" id="zKey" placeholder="Zeabur API Key (ey...)">
        <input type="text" id="zId" placeholder="Service ID (service-...)">
        <input type="password" id="gKey" placeholder="Gemini API Key">
        <button onclick="saveAndStart()">💾 儲存並開始監控</button>
    </div>

    <div class="box">
        <h3 style="display:flex; justify-content:space-between;">
            即時動態 <span id="status" style="color:#888; font-size:14px;">等待中...</span>
        </h3>
        <div class="log-area" id="logs"></div>
    </div>

    <script>
        document.getElementById('zKey').value = localStorage.getItem('ZK') || '';
        document.getElementById('zId').value = localStorage.getItem('ZI') || '';
        document.getElementById('gKey').value = localStorage.getItem('GK') || '';
        let lastTime = "";

        function saveAndStart() {
            localStorage.setItem('ZK', document.getElementById('zKey').value);
            localStorage.setItem('ZI', document.getElementById('zId').value);
            localStorage.setItem('GK', document.getElementById('gKey').value);
            document.getElementById('status').innerText = "連線中...";
            document.getElementById('status').style.color = "#10b981";
            setInterval(fetchData, 4000); // 每4秒抓一次
            fetchData();
        }

        async function fetchData() {
            try {
                // 叫秘書去抓資料
                const res = await fetch('/get_logs', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ key: localStorage.getItem('ZK'), id: localStorage.getItem('ZI') })
                });
                const data = await res.json();
                
                if (data.logs && data.logs.length > 0) {
                    const log = data.logs[0];
                    if (log.timestamp !== lastTime) {
                        lastTime = log.timestamp;
                        showLog(log.content, "翻譯中...");
                        translate(log.content);
                    }
                }
            } catch (e) { document.getElementById('status').innerText = "連線失敗"; document.getElementById('status').style.color = "red"; }
        }

        async function translate(text) {
            const gKey = localStorage.getItem('GK');
            if(!gKey) return;
            try {
                const res = await fetch(`https://generativelanguage.googleapis.com/v1beta/models/gemini-pro:generateContent?key=${gKey}`, {
                    method: 'POST', headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ contents: [{ parts: [{ text: "你是慵懶駭客少女，請把這句Log翻譯成傲嬌吐槽(白話文)：" + text }] }] })
                });
                const data = await res.json();
                if(data.candidates) {
                    document.getElementById('logs').firstElementChild.querySelector('.ai-text').innerText = "➜ " + data.candidates[0].content.parts[0].text;
                }
            } catch(e) {}
        }

        function showLog(raw, ai) {
            const div = document.createElement('div');
            div.style.borderBottom = "1px solid #333";
            div.style.paddingBottom = "5px";
            div.style.marginBottom = "5px";
            div.innerHTML = `<div style="color:#666; font-size:11px;">${raw}</div><div class="ai-text">➜ ${ai}</div>`;
            document.getElementById('logs').prepend(div);
        }
    </script>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
def home():
    return HTML_PAGE

@app.post("/get_logs")
def get_logs(info: dict):
    # 秘書代勞去抓 Zeabur 資料
    try:
        url = "https://gateway.zeabur.com/graphql"
        query = f'query {{ serviceRuntimeLogs(serviceID: "{info["id"]}", limit: 1) {{ content timestamp }} }}'
        headers = {"Authorization": f"Bearer {info['key']}"}
        res = requests.post(url, json={"query": query}, headers=headers).json()
        return {"logs": res["data"]["serviceRuntimeLogs"]}
    except:
        return {"logs": []}
