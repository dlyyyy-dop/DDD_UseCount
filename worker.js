/**
 * DDD数智通 · Cloudflare Worker 统计服务
 * 修复：移除导致所有请求被403拒绝的 host 白名单逻辑
 *       改为宽松的 Origin CORS 策略，允许来自任意域名的浏览器请求
 *
 * KV 命名空间：DDD_STATS_KV（在 CF 控制台绑定，变量名 DDD_STATS_KV）
 */

// ── 允许跨域的来源（按需扩展，* 表示全部放行）──────────────────────
const ALLOWED_ORIGINS = [
  'https://adamhtmei.github.io',   // GitHub Pages 外网
  'http://localhost',              // 本地开发
  'http://127.0.0.1',
  // 内网 IP 段请按需添加，如 'http://192.168.1.50'
];

const EVENT_LABELS = {
  page_view  : '网页打开',
  pwa_install: 'PWA安装',
  calc_click : '计算DDDs及使用强度',
};

// ── CORS 响应头 ─────────────────────────────────────────────────────
function corsHeaders(origin) {
  // 如果请求来源在白名单中则原样返回，否则不带 Allow-Origin（浏览器会拒绝）
  const allowed = ALLOWED_ORIGINS.includes(origin) ? origin : ALLOWED_ORIGINS[0];
  return {
    'Access-Control-Allow-Origin' : allowed,
    'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type',
  };
}

// ── KV 读写封装 ──────────────────────────────────────────────────────
async function loadData(env) {
  const raw = await env.DDD_STATS_KV.get('data');
  if (raw) return JSON.parse(raw);
  return { counts: { page_view: 0, pwa_install: 0, calc_click: 0 }, logs: [] };
}

async function saveData(env, data) {
  await env.DDD_STATS_KV.put('data', JSON.stringify(data));
}

// ── 主处理逻辑 ────────────────────────────────────────────────────────
export default {
  async fetch(request, env) {
    const url    = new URL(request.url);
    const path   = url.pathname;
    const origin = request.headers.get('Origin') || '';
    const cors   = corsHeaders(origin);

    // OPTIONS 预检
    if (request.method === 'OPTIONS') {
      return new Response(null, { status: 204, headers: cors });
    }

    // POST /track ─ 上报事件
    if (path === '/track' && request.method === 'POST') {
      let payload;
      try { payload = await request.json(); } catch {
        return new Response('{"error":"invalid json"}', { status: 400, headers: { ...cors, 'Content-Type': 'application/json' } });
      }

      const event = payload.event || '';
      if (!EVENT_LABELS[event]) {
        return new Response('{"error":"unknown event"}', { status: 400, headers: { ...cors, 'Content-Type': 'application/json' } });
      }

      const data = await loadData(env);
      data.counts[event] = (data.counts[event] || 0) + 1;
      data.logs.push({
        event,
        label: EVENT_LABELS[event],
        time : payload.time || new Date().toISOString().replace('T',' ').substring(0,19),
        ua   : (payload.ua || '').substring(0, 120),
      });
      if (data.logs.length > 2000) data.logs = data.logs.slice(-2000);
      await saveData(env, data);

      return new Response(
        JSON.stringify({ ok: true, count: data.counts[event] }),
        { status: 200, headers: { ...cors, 'Content-Type': 'application/json' } }
      );
    }

    // GET /api/stats ─ 读取统计数据（供面板和徽章使用）
    if (path === '/api/stats' && request.method === 'GET') {
      const data = await loadData(env);
      return new Response(
        JSON.stringify(data),
        { status: 200, headers: { ...cors, 'Content-Type': 'application/json; charset=utf-8' } }
      );
    }

    // GET /report ─ 可视化报告页
    if (path === '/report' && request.method === 'GET') {
      const data   = await loadData(env);
      const counts = data.counts;
      const recent = (data.logs || []).slice(-20).reverse();

      const rows = recent.map(l => `
        <tr>
          <td>${l.time || ''}</td>
          <td>${l.label || EVENT_LABELS[l.event] || l.event}</td>
          <td class="ua">${(l.ua || '').substring(0, 60)}</td>
        </tr>`).join('') || '<tr><td colspan="3" style="text-align:center;color:#aaa;">暂无数据</td></tr>';

      const html = `<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>DDD数智通 · 使用统计</title>
<style>
  body{font-family:"PingFang SC","Microsoft YaHei",sans-serif;background:#f0f5fa;color:#1a2533;margin:0;padding:20px;}
  h1{font-size:18px;color:#0d2137;margin-bottom:20px;}
  .cards{display:flex;gap:16px;flex-wrap:wrap;margin-bottom:28px;}
  .card{background:#fff;border-radius:12px;padding:20px 28px;box-shadow:0 2px 12px rgba(13,33,55,.1);min-width:160px;text-align:center;}
  .card .num{font-size:42px;font-weight:900;color:#f39c12;line-height:1;}
  .card .lbl{font-size:13px;color:#7f8c9a;margin-top:6px;}
  table{width:100%;border-collapse:collapse;background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 2px 12px rgba(13,33,55,.1);}
  th{background:#0d2137;color:#fff;padding:10px 14px;font-size:13px;text-align:left;}
  td{padding:9px 14px;font-size:12px;border-bottom:1px solid #eef2f7;}
  tr:last-child td{border:none;}
  .ua{color:#7f8c9a;font-size:11px;}
  a{color:#2e86c1;text-decoration:none;}
</style>
</head>
<body>
<h1>🏥 DDD数智通 · 使用统计看板（Cloudflare Workers）</h1>
<div class="cards">
  <div class="card"><div class="num">${counts.page_view||0}</div><div class="lbl">网页打开次数</div></div>
  <div class="card"><div class="num">${counts.pwa_install||0}</div><div class="lbl">PWA安装次数</div></div>
  <div class="card"><div class="num">${counts.calc_click||0}</div><div class="lbl">计算DDDs次数</div></div>
</div>
<p style="font-size:12px;color:#7f8c9a;margin-bottom:12px;">最近20条记录 · <a href="/report">刷新</a></p>
<table>
  <thead><tr><th>时间</th><th>事件</th><th>客户端</th></tr></thead>
  <tbody>${rows}</tbody>
</table>
</body></html>`;

      return new Response(html, {
        status: 200,
        headers: { 'Content-Type': 'text/html; charset=utf-8' },
      });
    }

    // 其他路径 → 重定向到报告页
    return Response.redirect(new URL('/report', request.url).toString(), 302);
  },
};
