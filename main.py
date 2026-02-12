from fastapi import FastAPI
from fastapi.responses import HTMLResponse
import requests

app = FastAPI()

# 強制顯示版 - 排除所有圖片與黑底干擾
HTML_CODE = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>DEBUG MODE - 監控台</title>
    <style>
        body { background: white; color: black; font-family: sans-serif; padding: 20px; }
        .debug-card { border: 2px solid red; padding: 20px; margin-bottom: 20px; }
        input { width: 100%; padding: 10px; margin: 10px 0; border: 1px solid #ccc; }
        button { width: 100%; padding: 15px; background: blue; color: white; font-weight: bold; }
        #log-area { background: #eee; padding: 10px; height: 200px; overflow-y: auto; border: 1px solid #000; }
    </style>
</head>
<body>
    <h1 style="color: red;">🚨 如果你看到這行字，代表連線成功！</h1>
    <div class="debug-card">
        <h3>請填入鑰匙測試：</h3>
        <input type="password" id="zk" placeholder="Zeabur API Key">
        <input type="text" id="zi" placeholder="小龍蝦 Service ID">
        <button onclick="testStart()">點我開始測試連線</button>
    </div>
    <div id="status">連線狀態：等待測試...</div>
    <div id="log-area"></div>

    <script>
        function testStart() {
            const zk = document.getElementById('zk').value;
            const zi = document.getElementById('zi').value;
            localStorage.setItem('ZK', zk);
            localStorage.setItem('ZI', zi);
            document.getElementById('status').innerText = "正在抓取 Log...";
            setInterval(fetchData, 4000);
        }

        async function fetchData() {
            try {
                const res = await fetch('/get_logs', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ key: localStorage.getItem('ZK'), id: localStorage.getItem('ZI') })
                });
                const data = await res.json();
                if (data.logs) {
                    const div = document.createElement('div');
                    div.innerText = new Date().toLocaleTimeString() + " - " + data.logs[0].content;
                    document.getElementById('log-area').prepend(div);
                }
            } catch (e) {
                document.getElementById('status').innerText = "連線失敗：" + e;
            }
        }
    </script>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
def home():
    return HTML_CODE

@app.post("/get_logs")
def get_logs(info: dict):
    # 這部分是幫你跨過 Zeabur API 的牆
    try:
        url = "https://gateway.zeabur.com/graphql"
        query = f'query {{ serviceRuntimeLogs(serviceID: "{info["id"]}", limit: 1) {{ content timestamp }} }}'
        res = requests.post(url, json={"query": query}, headers={"Authorization": f"Bearer {info['key']}"}).json()
        return {"logs": res["data"]["serviceRuntimeLogs"]}
    except Exception as e:
        return {"error": str(e)}
