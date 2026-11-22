// Cloudflare Worker: tóm tắt tin bằng Gemini khi người đọc bấm "AI tóm tắt".
// Key Gemini chỉ nằm trong secret của Worker, trang web không bao giờ thấy.
// Chặn lạm dụng: chỉ nhận từ trang của mình (Origin), cần mã truy cập riêng (X-Access-Key),
// chỉ tóm tắt bài từ các báo trong danh sách, và giới hạn số lần mỗi ngày.

const SOURCES = [
  "vnexpress.net", "tuoitre.vn", "vietnamplus.vn", "bbc.co.uk", "bbc.com", "tinhte.vn",
  "gsmarena.com", "9to5mac.com", "9to5google.com", "macrumors.com", "thanhnien.vn",
  "reuters.com", "apnews.com", "bloomberg.com",
];

const SCHEMA = {
  type: "OBJECT",
  properties: {
    title: { type: "STRING", description: "Tiêu đề tiếng Việt 8–14 chữ, đủ ý, không bỏ lửng" },
    summary: { type: "STRING", description: "1 câu trọn vẹn ≤ 30 chữ" },
    developments: { type: "STRING", description: "Diễn biến chính, 1–2 câu" },
    context: { type: "STRING", description: "Bối cảnh, 1–2 câu" },
    why_it_matters: { type: "STRING", description: "Vì sao quan trọng / ảnh hưởng tới Việt Nam, 1–2 câu" },
  },
  required: ["title", "summary", "developments", "context", "why_it_matters"],
};

function json(body, status, cors) {
  return new Response(JSON.stringify(body), {
    status, headers: { "Content-Type": "application/json; charset=utf-8", ...cors },
  });
}

function sameKey(a, b) {
  if (!a || !b || a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

function allowedUrl(raw) {
  try {
    const u = new URL(raw);
    if (u.protocol !== "https:") return null;
    const host = u.hostname.toLowerCase();
    return SOURCES.some((d) => host === d || host.endsWith("." + d)) ? u : null;
  } catch { return null; }
}

function articleText(html) {
  const pick = html.match(/<article[\s\S]*?<\/article>/i)?.[0] || html;
  const paras = [...pick.matchAll(/<p[^>]*>([\s\S]*?)<\/p>/gi)]
    .map((m) => m[1].replace(/<[^>]+>/g, " ").replace(/&nbsp;/g, " ").replace(/&amp;/g, "&")
      .replace(/&quot;/g, '"').replace(/&#39;|&apos;/g, "'").replace(/\s+/g, " ").trim())
    .filter((t) => t.length > 40);
  if (paras.join("").length > 300) return paras.join("\n").slice(0, 6000);
  // Diễn đàn kiểu Tinh tế viết bài bằng <div>/<br> chứ không dùng <p>: lấy khối nội dung bài, bỏ script/style
  const body = (html.match(/<div[^>]+class="[^"]*bbWrapper[^"]*"[^>]*>([\s\S]*?)<\/article>/i)?.[1] || pick)
    .replace(/<(script|style|noscript|nav|header|footer)[\s\S]*?<\/\1>/gi, " ")
    .replace(/<br\s*\/?>/gi, "\n").replace(/<[^>]+>/g, " ").replace(/&nbsp;/g, " ").replace(/&amp;/g, "&")
    .replace(/[ \t]+/g, " ").replace(/\n\s*\n+/g, "\n").trim();
  const desc = html.match(/<meta[^>]+(?:name|property)="(?:og:)?description"[^>]+content="([^"]*)"/i)?.[1] || "";
  return (desc + "\n" + body).slice(0, 6000);
}

async function underLimit(env) {
  if (!env.LIMITS) return true; // chưa gắn KV thì chỉ dựa vào mã truy cập
  const day = new Date().toISOString().slice(0, 10);
  const used = parseInt((await env.LIMITS.get(day)) || "0", 10);
  if (used >= parseInt(env.DAILY_LIMIT || "80", 10)) return false;
  await env.LIMITS.put(day, String(used + 1), { expirationTtl: 172800 });
  return true;
}

async function callGemini(env, prompt) {
  // key #2 trước: thực tế key #1 hay bị treo / hết lượt
  const keys = [env.GEMINI_API_KEY_2, env.GEMINI_API_KEY].filter(Boolean);
  const models = (env.GEMINI_MODELS || "gemini-3.8-flash").split(",").map((s) => s.trim()).filter(Boolean);
  let last = "no_key";
  for (const key of keys) {
    for (const model of models) {
      // Gemini 3.x: suy nghĩ mức thấp cho nhanh (bấm là cần có ngay); 2.x không hỗ trợ thinkingLevel
      const gen = { temperature: 0.3, responseMimeType: "application/json", responseSchema: SCHEMA };
      if (/gemini-3/.test(model)) gen.thinkingConfig = { thinkingLevel: "LOW" };
      const r = await fetch(`https://generativelanguage.googleapis.com/v1beta/models/${model}:generateContent`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "x-goog-api-key": key },
        body: JSON.stringify({ contents: [{ role: "user", parts: [{ text: prompt }] }], generationConfig: gen }),
        signal: AbortSignal.timeout(25000),
      }).catch(() => ({ ok: false, status: 504 }));
      if (r.ok) {
                const data = await r.json();
        const text = data?.candidates?.[0]?.content?.parts?.map((p) => p.text || "").join("") || "";
        try { return JSON.parse(text); } catch { last = "bad_json"; continue; }
      }
      last = String(r.status);
      let reason = "";
      try { reason = (await r.json())?.error?.message?.slice(0, 160) || ""; } catch { /* body không phải JSON */ }
      console.log(`gemini ${model} -> ${r.status} ${reason}`);
      if (r.status === 404) continue;                 // model không có -> thử model khác
      if ([401, 403, 429].includes(r.status)) break;  // key lỗi/hết lượt -> thử key khác
    }
  }
  throw new Error("gemini_" + last);
}

export default {
  async fetch(req, env) {
    const allowed = env.ALLOWED_ORIGIN || "https://vongocngu273.github.io";
    const cors = {
      "Access-Control-Allow-Origin": allowed,
      "Access-Control-Allow-Methods": "POST, OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type, X-Access-Key",
      "Access-Control-Max-Age": "86400",
      Vary: "Origin",
    };
    if (req.method === "OPTIONS") return new Response(null, { status: 204, headers: cors });
    const path = new URL(req.url).pathname;
    if (req.method !== "POST" || path !== "/summarize") return json({ error: "not_found" }, 404, cors);
    if ((req.headers.get("Origin") || "") !== allowed) return json({ error: "forbidden" }, 403, cors);
    if (!sameKey(req.headers.get("X-Access-Key") || "", env.ACCESS_KEY || "")) return json({ error: "unauthorized" }, 401, cors);

    let body;
    try { body = await req.json(); } catch { return json({ error: "bad_request" }, 400, cors); }
    const url = allowedUrl(String(body.url || ""));
    const title = String(body.title || "").slice(0, 300);
    const snippet = String(body.snippet || "").slice(0, 1200);
    const source = String(body.source || "").slice(0, 60);
    if (!url || !title) return json({ error: "bad_request" }, 400, cors);
    if (!(await underLimit(env))) return json({ error: "daily_limit" }, 429, cors);

    let text = "";
    try {
      const r = await fetch(url.toString(), {
        headers: { "User-Agent": "Mozilla/5.0 (compatible; ban-tin-ai/1.0)" },
        cf: { cacheTtl: 900, cacheEverything: true },
      });
      if (r.ok) text = articleText((await r.text()).slice(0, 600000));
    } catch { /* không đọc được bài thì tóm tắt từ tiêu đề + mô tả */ }

    const prompt = `Bạn là biên tập viên bản tin sáng cho độc giả Việt Nam. Tóm tắt bài báo sau bằng tiếng Việt chuẩn, trung lập, súc tích.
Chỉ dùng thông tin có trong tiêu đề, mô tả và nội dung bên dưới; không bịa chi tiết hay số liệu. Nếu bài tiếng Anh thì dịch sang tiếng Việt.
Nguồn: ${source}
Tiêu đề gốc: ${title}
Mô tả: ${snippet}
Nội dung bài (có thể thiếu):
${text || "(không lấy được nội dung, chỉ dựa vào tiêu đề và mô tả)"}`;

    try {
      const out = await callGemini(env, prompt);
      return json({ ...out, from_article: Boolean(text) }, 200, cors);
    } catch (e) {
      return json({ error: "ai_unavailable" }, 502, cors);
    }
  },

  // Hẹn giờ của Cloudflare (đúng giờ hơn lịch GitHub): gọi GitHub Actions chạy bản tin / làm mới.
  // Token GitHub (fine-grained, chỉ repo daily-briefing, quyền Actions) nằm trong secret GH_DISPATCH_TOKEN.
  async scheduled(event, env, ctx) {
    const job = CRON_JOBS[event.cron];
    if (!job) { console.log(`cron lạ: ${event.cron}`); return; }
    ctx.waitUntil(dispatch(env, job));
  },
};

const REPO = "vongocngu273/daily-briefing";
const CRON_JOBS = {
  "5 0 * * *": "daily-briefing.yml",        // 07:05 VN: bản tin sáng (job "check" chặn chạy trùng)
  "25,55 0-16,23 * * *": "trends.yml",      // 30 phút/lần 06:25–23:55 VN: tin nóng, giá, trend
};

async function dispatch(env, workflow) {
  if (!env.GH_DISPATCH_TOKEN) { console.log("thiếu GH_DISPATCH_TOKEN"); return; }
  const r = await fetch(`https://api.github.com/repos/${REPO}/actions/workflows/${workflow}/dispatches`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${env.GH_DISPATCH_TOKEN}`,
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      "User-Agent": "ban-tin-ai-cron",
    },
    body: JSON.stringify({ ref: "main", inputs: { auto: "true" } }),
  });
  console.log(`dispatch ${workflow} -> ${r.status}`);
}
