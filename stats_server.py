#!/usr/bin/env python3
"""
DDD数智通 - 内网统计服务
================================
依赖：Python 3.6+，无需安装任何第三方库

启动方式：
    python3 stats_server.py

默认监听：0.0.0.0:8765
数据文件：stats_data.json（与本脚本同目录）
查看统计：浏览器打开 http://内网IP:8765/report
"""

import json
import os
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime
from urllib.parse import urlparse

# ── 配置 ────────────────────────────────────────
PORT      = 8765
DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'stats_data.json')
# ── 配置结束 ─────────────────────────────────────

EVENT_LABELS = {
    'page_view'  : '网页打开',
    'pwa_install': 'PWA安装',
    'calc_click' : '计算DDDs及使用强度',
}


def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {'counts': {k: 0 for k in EVENT_LABELS}, 'logs': []}


def save_data(data):
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


class StatsHandler(BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        # 简化日志输出
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {args[0]} {args[1]}")

    def send_cors(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'POST, GET, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')

    def do_OPTIONS(self):
        # 处理预检请求（浏览器跨域会先发 OPTIONS）
        self.send_response(204)
        self.send_cors()
        self.end_headers()

    def do_POST(self):
        path = urlparse(self.path).path
        if path != '/track':
            self.send_response(404)
            self.end_headers()
            return

        length = int(self.headers.get('Content-Length', 0))
        body   = self.rfile.read(length)

        try:
            payload = json.loads(body)
            event   = payload.get('event', '')
            ua      = payload.get('ua', '')
            time_   = payload.get('time', datetime.now().isoformat())

            if event not in EVENT_LABELS:
                self.send_response(400)
                self.send_cors()
                self.end_headers()
                self.wfile.write(b'{"error":"unknown event"}')
                return

            data = load_data()
            data['counts'][event] = data['counts'].get(event, 0) + 1
            data['logs'].append({
                'event': event,
                'time' : time_,
                'ua'   : ua[:120],
            })
            # 只保留最近 2000 条日志，避免文件过大
            if len(data['logs']) > 2000:
                data['logs'] = data['logs'][-2000:]
            save_data(data)

            label = EVENT_LABELS[event]
            print(f"  ✅ 记录：{label}（累计 {data['counts'][event]} 次）")

            self.send_response(200)
            self.send_cors()
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'ok': True, 'count': data['counts'][event]}).encode())

        except Exception as e:
            print(f"  ❌ 错误：{e}")
            self.send_response(500)
            self.send_cors()
            self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path

        if path == '/report':
            self._serve_report()
        elif path == '/api/stats':
            self._serve_json()
        else:
            self.send_response(302)
            self.send_header('Location', '/report')
            self.end_headers()

    def _serve_json(self):
        data = load_data()
        self.send_response(200)
        self.send_cors()
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))

    def _serve_report(self):
        data   = load_data()
        counts = data.get('counts', {})
        logs   = data.get('logs', [])

        # 最近20条日志（倒序）
        recent = logs[-20:][::-1]
        rows   = ''
        for log in recent:
            t     = log.get('time', '')[:19].replace('T', ' ')
            label = EVENT_LABELS.get(log['event'], log['event'])
            ua    = log.get('ua', '')[:60]
            rows += f'<tr><td>{t}</td><td>{label}</td><td class="ua">{ua}</td></tr>\n'

        html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>DDD数智通 · 使用统计</title>
<style>
  body{{font-family:"PingFang SC","Microsoft YaHei",sans-serif;
       background:#f0f5fa;color:#1a2533;margin:0;padding:20px;}}
  h1{{font-size:18px;color:#0d2137;margin-bottom:20px;}}
  .cards{{display:flex;gap:16px;flex-wrap:wrap;margin-bottom:28px;}}
  .card{{background:#fff;border-radius:12px;padding:20px 28px;
         box-shadow:0 2px 12px rgba(13,33,55,.1);min-width:160px;text-align:center;}}
  .card .num{{font-size:42px;font-weight:900;color:#f39c12;line-height:1;}}
  .card .lbl{{font-size:13px;color:#7f8c9a;margin-top:6px;}}
  table{{width:100%;border-collapse:collapse;background:#fff;
         border-radius:12px;overflow:hidden;
         box-shadow:0 2px 12px rgba(13,33,55,.1);}}
  th{{background:#0d2137;color:#fff;padding:10px 14px;
      font-size:13px;text-align:left;}}
  td{{padding:9px 14px;font-size:12px;border-bottom:1px solid #eef2f7;}}
  tr:last-child td{{border:none;}}
  .ua{{color:#7f8c9a;font-size:11px;}}
  .refresh{{font-size:12px;color:#7f8c9a;margin-bottom:12px;}}
  a{{color:#2e86c1;text-decoration:none;}}
</style>
</head>
<body>
<h1>🏥 DDD数智通 · 使用统计看板</h1>
<div class="cards">
  <div class="card">
    <div class="num">{counts.get("page_view", 0)}</div>
    <div class="lbl">网页打开次数</div>
  </div>
  <div class="card">
    <div class="num">{counts.get("pwa_install", 0)}</div>
    <div class="lbl">PWA安装次数</div>
  </div>
  <div class="card">
    <div class="num">{counts.get("calc_click", 0)}</div>
    <div class="lbl">计算DDDs次数</div>
  </div>
</div>
<p class="refresh">最近20条记录 · <a href="/report">刷新</a> · 数据文件：{DATA_FILE}</p>
<table>
  <thead><tr><th>时间</th><th>事件</th><th>客户端</th></tr></thead>
  <tbody>{rows if rows else '<tr><td colspan="3" style="text-align:center;color:#aaa;">暂无数据</td></tr>'}</tbody>
</table>
</body>
</html>'''

        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write(html.encode('utf-8'))


if __name__ == '__main__':
    server = HTTPServer(('0.0.0.0', PORT), StatsHandler)
    print(f'╔══════════════════════════════════════╗')
    print(f'║   DDD数智通 统计服务已启动             ║')
    print(f'╠══════════════════════════════════════╣')
    print(f'║  接收地址: http://0.0.0.0:{PORT}/track  ║')
    print(f'║  查看报告: http://localhost:{PORT}/report ║')
    print(f'║  数据文件: stats_data.json             ║')
    print(f'║  Ctrl+C 停止服务                      ║')
    print(f'╚══════════════════════════════════════╝')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\n服务已停止。')
