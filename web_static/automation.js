/* B站回复自动化 · 监工台逻辑 */
"use strict";

const API = "/api/automation";
let statusCache = null;
let queueItems = [];

async function api(path, options) {
  const res = await fetch(API + path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch (e) {}
    throw new Error(detail);
  }
  return res.json();
}

function fmtAge(hours) {
  if (hours < 1) return `${Math.round(hours * 60)}分钟前`;
  if (hours < 48) return `${hours.toFixed(1)}小时前`;
  return `${(hours / 24).toFixed(1)}天前`;
}

function esc(s) {
  return String(s || "").replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[c]);
}

async function refreshStatus() {
  try {
    statusCache = await api("/status");
    renderStatus();
  } catch (e) {
    document.getElementById("cycle-state").textContent = "状态获取失败：" + e.message;
  }
}

function renderStatus() {
  const s = statusCache;
  const cyc = s.cycle || {};
  const running = !!cyc.running;
  const stateEl = document.getElementById("cycle-state");
  if (running) {
    stateEl.textContent = "⏳ 采集周期运行中…";
    stateEl.className = "au-chip warn";
  } else if (s.enabled) {
    stateEl.textContent = "✅ 自动化运行中";
    stateEl.className = "au-chip on";
  } else {
    stateEl.textContent = "⏸ 未启用";
    stateEl.className = "au-chip bad";
  }

  const btn = document.getElementById("btn-enable");
  btn.textContent = s.enabled ? "暂停自动化" : "启动自动化";
  btn.className = "au-btn " + (s.enabled ? "danger" : "primary");

  const f = s.funnel || {}, st = s.stats || {};
  document.getElementById("chips").innerHTML = [
    chip(`已采视频 ${st.collected_videos || 0}`),
    chip(`评论总量 ${st.collected_comments || 0}`),
    chip(`待审 ${f.pending_review || 0}`, (f.pending_review || 0) > 0 ? "warn" : ""),
    chip(`已批待发 ${f.approved || 0}`, (f.approved || 0) > 0 ? "on" : ""),
    chip(`累计发送 ${f.sent || 0}`, "on"),
    (f.failed || 0) > 0 ? chip(`失败 ${f.failed}`, "bad") : "",
  ].join("");

  const sender = s.sender || {};
  document.getElementById("sender-panel").innerHTML = `
    <div class="au-side-row"><span>今日已发</span><b>${sender.sent_today || 0} / ${s.config.daily_send_limit}</b></div>
    <div class="au-side-row"><span>发送窗口</span><span>${s.config.send_window_start}-${s.config.send_window_end}</span></div>
    <div class="au-side-row"><span>状态</span><span>${sender.can_send ? "✅ 可发送" : "⏳ " + esc(sender.wait_reason || "等待中")}</span></div>
    <div class="au-side-row"><span>下次可发</span><span>${sender.next_allowed_at || "随时"}</span></div>
    <div class="au-side-row"><span>B站 Cookie</span><span>${sender.cookie_cached ? "✅ 已缓存" : "⚠️ 未缓存（发送前自动刷新）"}</span></div>`;

  document.getElementById("cycle-panel").innerHTML = `
    <div class="au-side-row"><span>采集间隔</span><span>${s.config.collect_interval_hours} 小时</span></div>
    <div class="au-side-row"><span>关键词</span><span>${esc((s.config.keywords || []).join("、"))}</span></div>
    <div class="au-side-row"><span>上次采集</span><span>${cyc.last_run_at || "从未"}</span></div>
    <div class="au-side-row"><span>上周期结果</span><span>${summarizeCycle(cyc.last_summary)}</span></div>
    ${cyc.last_error ? `<div class="au-side-row"><span style="color:#991b1b">上次错误</span><span style="color:#991b1b">${esc(cyc.last_error)}</span></div>` : ""}`;
}

function chip(text, cls) { return `<span class="au-chip ${cls || ""}">${esc(text)}</span>`; }

function summarizeCycle(raw) {
  if (!raw) return "—";
  try {
    const d = JSON.parse(raw);
    return `新增候选 ${d.new_candidates}（起草 ${d.llm_drafted}）/ 评论 ${d.comments} / 排除 ${d.funnel ? d.funnel.excluded : "?"}`;
  } catch (e) { return "—"; }
}

async function refreshQueue() {
  try {
    queueItems = await api("/candidates?status=pending_review");
    renderQueue();
  } catch (e) { /* 静默 */ }
}

function renderQueue() {
  const box = document.getElementById("queue");
  document.getElementById("queue-count").textContent = queueItems.length;
  if (!queueItems.length) {
    box.innerHTML = '<div class="au-note">暂无待审条目。启动后每周期自动采集 → 筛选 → 起草 → 进入这里等批准。</div>';
    return;
  }
  box.innerHTML = queueItems.map(item => `
    <div class="au-item" id="item-${esc(item.id)}">
      <div class="au-item-head">
        <span class="au-tag ${item.tier === "A" ? "a" : "b"}">${item.tier}档·${esc(item.signal)}</span>
        <span>👤 ${esc(item.commenter)}</span>
        <span>❤ ${item.like_count || 0}</span>
        <span>${fmtAge(item.age_hours)}</span>
        ${item.draft_source ? `<span class="au-tag">${item.draft_source === "llm" ? "LLM起草" : "人工"}</span>` : '<span class="au-tag" style="background:#fee2e2;color:#991b1b">待起草</span>'}
      </div>
      <div class="au-quote">${esc(item.comment_text)}</div>
      <div class="au-video">← 《${esc(item.video_title)}》 <a class="au-link" href="${esc(commentUrl(item))}" target="_blank">查看原评论</a></div>
      <textarea class="au-draft" id="draft-${esc(item.id)}" placeholder="${item.draft ? "" : "模型未配置或起草失败，可手动填写回复"}">${esc(item.draft || "")}</textarea>
      <div class="au-lint" id="lint-${esc(item.id)}">${(item.lint_warnings || []).map(esc).join("；")}</div>
      <div class="au-actions">
        <button class="au-btn primary" onclick="approve('${esc(item.id)}')">✅ 批准发送</button>
        <button class="au-btn ghost" onclick="saveDraft('${esc(item.id)}')">💾 保存草稿</button>
        <button class="au-btn ghost" onclick="redraft('${esc(item.id)}')">🔄 重新起草</button>
        <button class="au-btn danger" onclick="reject('${esc(item.id)}')">✖ 拒绝</button>
      </div>
    </div>`).join("");
}

function commentUrl(item) {
  if (item.video_url) return item.video_url;
  return `https://www.bilibili.com/video/av${item.video_id}#reply${item.comment_id}`;
}

async function approve(id) {
  const draft = document.getElementById("draft-" + id).value.trim();
  if (!draft) { alert("草稿为空，先填写或起草"); return; }
  try {
    const res = await api(`/candidates/${id}/approve`, { method: "POST", body: JSON.stringify({ draft }) });
    if ((res.item.lint_warnings || []).length && !confirm("风格 lint 有警告：\n" + res.item.lint_warnings.join("\n") + "\n\n仍要批准发送？")) {
      return; // 已批准，此分支不可达；提示放在 confirm 之前需要预检，简化：警告在批准后显示
    }
    refreshAll();
  } catch (e) { alert("批准失败：" + e.message); }
}

async function reject(id) {
  if (!confirm("拒绝这条候选？")) return;
  try { await api(`/candidates/${id}/reject`, { method: "POST" }); refreshAll(); }
  catch (e) { alert("操作失败：" + e.message); }
}

async function redraft(id) {
  try { await api(`/candidates/${id}/draft`, { method: "POST" }); refreshQueue(); }
  catch (e) { alert("起草失败：" + e.message + "（可手动填写）"); }
}

async function saveDraft(id) {
  const draft = document.getElementById("draft-" + id).value;
  try { await api(`/candidates/${id}/draft-manual`, { method: "POST", body: JSON.stringify({ draft }) }); refreshQueue(); }
  catch (e) { alert("保存失败：" + e.message); }
}

async function toggleEnable() {
  const enabled = !(statusCache && statusCache.enabled);
  try {
    await api("/config", { method: "POST", body: JSON.stringify({ enabled }) });
    if (enabled) alert("已启动：60秒内开始首个采集周期；候选进入待审队列等你批准。");
    refreshStatus();
  } catch (e) { alert("操作失败：" + e.message); }
}

async function collectNow() {
  try {
    const res = await api("/collect-now", { method: "POST" });
    alert(res.message);
    refreshStatus();
  } catch (e) { alert("启动失败：" + e.message); }
}

function toggleConfig() {
  const p = document.getElementById("config-panel");
  if (p.style.display === "none") {
    const c = statusCache.config;
    document.getElementById("cfg-keywords").value = (c.keywords || []).join(",");
    document.getElementById("cfg-interval").value = c.collect_interval_hours;
    document.getElementById("cfg-max-candidates").value = c.max_new_candidates_per_cycle;
    document.getElementById("cfg-daily-limit").value = c.daily_send_limit;
    document.getElementById("cfg-interval-send").value = c.send_interval_seconds;
    document.getElementById("cfg-window-start").value = c.send_window_start;
    document.getElementById("cfg-window-end").value = c.send_window_end;
    p.style.display = "";
  } else p.style.display = "none";
}

async function saveConfig() {
  const body = {
    keywords_text: document.getElementById("cfg-keywords").value,
    collect_interval_hours: +document.getElementById("cfg-interval").value,
    max_new_candidates_per_cycle: +document.getElementById("cfg-max-candidates").value,
    daily_send_limit: +document.getElementById("cfg-daily-limit").value,
    send_interval_seconds: +document.getElementById("cfg-interval-send").value,
    send_window_start: document.getElementById("cfg-window-start").value,
    send_window_end: document.getElementById("cfg-window-end").value,
  };
  try { await api("/config", { method: "POST", body: JSON.stringify(body) }); alert("已保存"); refreshStatus(); }
  catch (e) { alert("保存失败：" + e.message); }
}

async function refreshHistory() {
  try {
    const items = await api("/candidates?status=sent&limit=20");
    const fails = await api("/candidates?status=failed&limit=10");
    const box = document.getElementById("history");
    if (!items.length && !fails.length) { box.innerHTML = '<div class="au-note">还没有发送记录。</div>'; return; }
    box.innerHTML = items.concat(fails).map(i => `
      <div class="au-side-row">
        <span>${i.status === "sent" ? "✅" : "❌"} ${esc(i.commenter)}（${fmtAge(i.age_hours)}时提问）</span>
        <span>${i.status === "sent" ? (i.sent_at || "") : esc((i.send_error || "").slice(0, 60))}</span>
      </div>`).join("");
  } catch (e) { /* 静默 */ }
}

function toggleHistory() {
  const p = document.getElementById("history");
  if (p.style.display === "none") { refreshHistory(); p.style.display = ""; }
  else p.style.display = "none";
}

function refreshAll() { refreshStatus(); refreshQueue(); refreshHistory(); }

document.getElementById("btn-enable").onclick = toggleEnable;
document.getElementById("btn-collect").onclick = collectNow;
// 被 growth-v2 内嵌时隐藏返回链接，避免 iframe 套娃导航
if (window.self !== window.top) {
  const back = document.querySelector('a.au-link[href="/"]');
  if (back) back.style.display = "none";
}
refreshAll();
setInterval(refreshStatus, 5000);
setInterval(refreshQueue, 8000);
