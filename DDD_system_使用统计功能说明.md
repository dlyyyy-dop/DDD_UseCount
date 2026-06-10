# DDD数智通 · 使用统计功能说明

------

## 一、整体原理

### 统计了什么？

| 事件                  | 触发时机                                 |
| --------------------- | ---------------------------------------- |
| `page_view` 网页打开  | 每次用户打开网页时自动上报               |
| `pwa_install` PWA安装 | 用户将网页"安装到桌面"时上报             |
| `calc_click` 计算DDDs | 用户点击"✅ 计算DDDs及使用强度"按钮时上报 |

### 双环境自动路由

网页加载时，统计模块会检查当前访问地址，**自动判断是公网还是内网**，选择对应的上报渠道：

```
用户打开网页
      │
      ▼
 检查 location.hostname
      │
      ├─ 含 192.168. / 10. / 172.16. 等内网特征
      │        │
      │        ▼
      │   POST → 内网统计服务（stats_server.py）
      │        │
      │        ▼
      │   写入 stats_data.json（本地文件）
      │
      └─ 否（github.io 等公网域名）
               │
               ▼
          POST → Cloudflare
               │
               ▼
         写入 Cloudflare 的 KV
```

两套渠道**完全独立**，互不干扰。任何一侧的故障（网络不通、服务未启动等）都会静默失败，**不影响主功能的正常使用**。

------

## 二、公网发布

### 1、 Cloudflare Workers 源码 (无需外接任何数据库)

请在 Cloudflare Workers 控制台创建一个新项目，并将以下代码粘贴到 `index.js` 或 `worker.ts` 中。

JavaScript

```
export default {
  async fetch(request, env, ctx) {
    // 处理跨域请求 (CORS)
    const corsHeaders = {
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type",
    };

    if (request.method === "OPTIONS") {
      return new Response(null, { headers: corsHeaders });
    }

    const url = new URL(request.url);

    // 检查 KV 绑定是否存在
    if (!env.DDD_STATS_KV) {
      return new Response(JSON.stringify({ error: "KV 命名空间 'DDD_STATS_KV' 未绑定！" }), {
        status: 500,
        headers: { ...corsHeaders, "Content-Type": "application/json" }
      });
    }

    // ══ 路由1：上报统计数据 (POST /track) ══
    if (url.pathname === "/track" && request.method === "POST") {
      try {
        const body = await request.json();
        const { event, ua } = body;
        
        const validEvents = ["page_view", "pwa_install", "calc_click"];
        if (!validEvents.includes(event)) {
          return new Response(JSON.stringify({ error: "无效的事件名称" }), { status: 400, headers: corsHeaders });
        }

        // 1. 原子自增总计数
        // 由于 Workers 默认没有直接自增方法，我们在 KV 中读取后加 1 再写回
        const countKey = `count:${event}`;
        const currentCount = parseInt(await env.DDD_STATS_KV.get(countKey) || "0");
        await env.DDD_STATS_KV.put(countKey, (currentCount + 1).toString());

        // 2. 插入最新日志 (保存最近20条)
        const logListKey = "stats_logs";
        const logsRaw = await env.DDD_STATS_KV.get(logListKey) || "[]";
        let logs = JSON.parse(logsRaw);

        // 获取北京时间字符串
        const bjTime = new Date(new Date().getTime() + 8 * 3600000).toISOString()
          .replace("T", " ")
          .substring(0, 19);

        const eventLabels = {
          "page_view": "网页打开",
          "pwa_install": "PWA 安装",
          "calc_click": "计算DDDs"
        };

        const newLog = {
          event: event,
          label: eventLabels[event] || event,
          time: bjTime,
          ua: ua || "Unknown"
        };

        logs.unshift(newLog); // 插入到数组开头
        logs = logs.slice(0, 20); // 仅保留最近20条

        await env.DDD_STATS_KV.put(logListKey, JSON.stringify(logs));

        return new Response(JSON.stringify({ success: true }), {
          headers: { ...corsHeaders, "Content-Type": "application/json" }
        });
      } catch (err) {
        return new Response(JSON.stringify({ error: err.message }), { status: 500, headers: corsHeaders });
      }
    }

    // ══ 路由2：获取统计结果 (GET /api/stats) ══
    if (url.pathname === "/api/stats" && request.method === "GET") {
      try {
        const pv = parseInt(await env.DDD_STATS_KV.get("count:page_view") || "0");
        const inst = parseInt(await env.DDD_STATS_KV.get("count:pwa_install") || "0");
        const calc = parseInt(await env.DDD_STATS_KV.get("count:calc_click") || "0");
        
        const logsRaw = await env.DDD_STATS_KV.get("stats_logs") || "[]";
        const logs = JSON.parse(logsRaw);

        const result = {
          counts: {
            page_view: pv,
            pwa_install: inst,
            calc_click: calc
          },
          logs: logs
        };

        return new Response(JSON.stringify(result), {
          headers: { ...corsHeaders, "Content-Type": "application/json" }
        });
      } catch (err) {
        return new Response(JSON.stringify({ error: err.message }), { status: 500, headers: corsHeaders });
      }
    }

    // 404 页面
    return new Response("Not Found", { status: 404, headers: corsHeaders });
  }
};
```

### 2、 Cloudflare 部署步骤（新手几分钟即可搞定）

1. 登录到 [Cloudflare Dashboard](https://dash.cloudflare.com/)。

2. 在左侧菜单中点击 **Workers & Pages (Workers 和页面)** -> 点击 **Create (创建)** -> **Create Worker (创建 Worker)**。

3. 给项目起个名字（例如 `ddd-stats-api`），点击 **Deploy (部署)**。

4. 部署后点击 **Edit Code (编辑代码)**，将上方的 JavaScript 源码全部替换进去，然后点击右上角的 **Save and Deploy (保存并部署)**。

5. **绑定 KV 存储（关键步骤）：**

   - 第一步：新建一个 KV 空间（Namespace）
     1. **在新标签页中打开 Cloudflare**（或者直接点击左侧最外层的返回箭头，回到 Cloudflare 的大首页）。
     2. 在 Cloudflare 左侧最外层的主菜单中，找到 **Storage & Databases (存储与数据库)** -> 点击 **KV**。
     3. 进入 KV 页面后，点击右上角的 **Create a namespace (创建命名空间)** 按钮。
     4. 在弹出的输入框中输入名字：`ddd_kv_data`
     5. 点击 **Add (添加/保存)**。
   - 第二步：回到当前的 Worker 页面进行绑定
     1. 完成第一步后，切回 Worker 变量配置页面。
     2. **刷新一下网页**（让网页刷新读取到你刚刚新建的 KV 空间）。
     3. 重新点击 **Add binding (添加绑定)**：
        - **Variable name (变量名称)** 照常输入：`DDD_STATS_KV`（注意必须全大写）
        - **KV namespace (KV 命名空间)**：再次点击这个下拉框，你就会发现刚刚创建的 `ddd_kv_data` 已经躺在里面了，直接选中它。
     4. 点击最下方的 **Save (保存)** 按钮。

6. 回到 Worker 的 **Summary (概述)** 页，你会看到一个类似 `https://ddd-stats-api.<你的用户名>.workers.dev` 的 **Routes (路由)** 地址。**复制这个地址**，这就是你的统计后端！

   目前创建的是：[https://ddd-stats-api.adamhtmei.workers.dev](https://ddd-stats-api.adamhtmei.workers.dev/)

## 三、内网发布

### 部署统计服务

将 `stats_server.py` 放到内网服务器任意目录，执行：

```bash
python3 stats_server.py
```

无需安装任何第三方库，**Python 3.6+ 即可运行**。

启动成功后终端输出：

```
╔══════════════════════════════════════╗
║   DDD数智通 统计服务已启动             ║
╠══════════════════════════════════════╣
║  接收地址: http://0.0.0.0:8765/track  ║
║  查看报告: http://localhost:8765/report ║
║  数据文件: stats_data.json             ║
╚══════════════════════════════════════╝
```

### 填写配置

在 `DDD_system.html` 的 CONFIG 区域，填写内网服务器地址：

```javascript
const INTRANET_API = 'http://192.168.1.100:8765/track'; // 替换为实际内网IP

// 内网环境判断特征（默认已覆盖常见内网IP段，一般无需修改）
const INTRANET_HINTS = ['192.168.', '10.', '172.16.', 'localhost', '127.0.'];
```

> 如果内网使用域名访问（如 `ddd.hospital.local`），在 `INTRANET_HINTS` 中添加该域名关键词即可：
>
> ```javascript
> const INTRANET_HINTS = ['192.168.', '10.', '172.16.', 'hospital.local'];
> ```

### 查看内网统计结果

**浏览器打开统计看板：**

```
http://内网服务器IP:8765/report
```

页面显示三项累计数字 + 最近20条访问记录：

```
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│     128      │  │      17      │  │      89      │
│  网页打开次数  │  │  PWA安装次数  │  │  计算DDDs次数 │
└──────────────┘  └──────────────┘  └──────────────┘

时间                 事件              客户端
2025-06-10 14:32    计算DDDs及使用强度  Mozilla/5.0 (Windows...
2025-06-10 14:31    网页打开           Mozilla/5.0 (iPhone...
...
```

**或直接查看 JSON 原始数据：**

```
http://内网服务器IP:8765/api/stats
```

返回：

```json
{
  "counts": {
    "page_view": 128,
    "pwa_install": 17,
    "calc_click": 89
  },
  "logs": [...]
}
```

**或直接查看数据文件：**

```bash
cat stats_data.json
```

### 设置开机自启（Linux 推荐）

```bash
sudo nano /etc/systemd/system/ddd-stats.service
[Unit]
Description=DDD数智通统计服务
After=network.target

[Service]
ExecStart=/usr/bin/python3 /your/path/stats_server.py
WorkingDirectory=/your/path/
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
sudo systemctl daemon-reload
sudo systemctl enable ddd-stats   # 开机自启
sudo systemctl start ddd-stats    # 立即启动
sudo systemctl status ddd-stats   # 查看状态
```

------

## 四、文件清单

| 文件              | 作用                           | 部署位置                      |
| ----------------- | ------------------------------ | ----------------------------- |
| `DDD_system.html` | 主网页，含统计上报逻辑         | GitHub 仓库 / 内网 Web 服务器 |
| `stats_server.py` | 内网统计接收服务               | 内网服务器（仅内网需要）      |
| `stats_data.json` | 内网统计数据文件（自动生成）   | 与 `stats_server.py` 同目录   |
| `manifest.json`   | PWA 配置                       | 与 `DDD_system.html` 同目录   |
| `sw.js`           | Service Worker（PWA 离线缓存） | 与 `DDD_system.html` 同目录   |
| `icons `(图标)    | 各平台显示的图标               | 与 `DDD_system.html` 同目录   |

------

## 五、常见问题

**Q：公网和内网的数据是分开统计的吗？** 是的，完全独立。公网数据在 Cloudflare的KV，内网数据在 `stats_data.json`，不会合并。

**Q：统计失败会影响主功能吗？** 不会。所有上报请求都是异步发出、静默失败（`.catch(() => {})`），即使服务器宕机或网络不通，网页功能完全不受影响。

**Q：内网 stats_server.py 没启动时，内网用户访问会报错吗？** 不会。fetch 请求失败会被静默捕获，用户不会看到任何错误提示。

**Q：如何修改统计服务的端口？** 打开 `stats_server.py`，修改顶部的 `PORT = 8765` 为其他端口，同时更新 `DDD_system.html` 中 `INTRANET_API` 的端口号。

## 六、用户使用方法

#### ①顶栏徽章

顶栏右侧原来的"WHO DDD 标准"换成了一个三格计数徽章，页面加载约 1.5 秒后静默拉取数据填入：



```
👁 128  |  📲 17  |  🧮 89
```

点击徽章弹出详情面板。

------

#### ②统计详情面板（底部上滑）

点击徽章后从底部滑出，包含：

- **环境标签**：自动显示"📡 内网统计服务"或"🌐 Cloudflare Workers 统计"
- **三张数据卡**：大号数字 + 图标 + 标签，对应三项统计
- **最近访问记录列表**：彩色圆点区分事件类型（蓝=打开、绿=安装、橙=计算），右侧显示时间
- **刷新按钮**：手动重新拉取最新数据

点击面板外区域或右上角 ✕ 关闭。