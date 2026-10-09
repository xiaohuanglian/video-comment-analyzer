/* AI Growth Engine — 工作台原型（独立预览，非生产页面） */
(function () {
"use strict";
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

const state = {
  product: localStorage.getItem("proto_product") || "youvibe",
  sessionId: "",
  polling: null,
  cache: {},
};
const DEMO_PID = "youvibe_demo";
const isDemo = () => state.product === DEMO_PID;
// 模型配置由服务端持久化（保存一次永久生效）；sessionStorage 仅作旧版兼容迁移
const hasKey = () => !!state.modelConfigured;
const baseURL = () => state.serverBaseUrl || "https://api.deepseek.com";
const modelName = () => state.serverModelName || "deepseek-v4-flash";

async function api(path, opts) {
  const res = await fetch("/api/growth" + path, opts && Object.assign({ headers: { "Content-Type": "application/json" } }, opts));
  if (!res.ok) {
    let d = res.statusText;
    try { d = (await res.json()).detail || d; } catch (e) {}
    throw new Error(d);
  }
  return res.json();
}

/* ---------- 导航与模式 ---------- */
$("nav").addEventListener("click", (e) => {
  const btn = e.target.closest("button");
  if (!btn) return;
  document.querySelectorAll("#nav button").forEach((b) => b.classList.toggle("active", b === btn));
  document.querySelectorAll(".view").forEach((v) => (v.hidden = true));
  $("view-" + btn.dataset.view).hidden = false;
  if (btn.dataset.view === "projects") loadProjects();
  if (btn.dataset.view === "library") loadLibrary();
  if (btn.dataset.view === "review") loadReview();
  if (btn.dataset.view === "settings") loadSettings();
});

function refreshModeBadge() {
  const m = $("modeBadge"), mb = $("modelBadge");
  m.className = "mode-badge" + (isDemo() ? " demo" : "");
  m.textContent = isDemo() ? "演示模式 · MOCK 数据" : "正式模式 · 真实数据";
  $("demoBanner").hidden = !isDemo();
  if (hasKey()) { mb.className = "model-badge ok"; mb.textContent = "模型已连接：" + modelName(); }
  else { mb.className = "model-badge warn"; mb.textContent = "未连接真实模型"; }
}

/* ---------- 工具步骤的人话映射 ---------- */
const TOOL_PHRASES = {
  recall_learnings: "正在查阅历史经验（已排除 Mock 演示记录）",
  query_segments: "正在查看已有的用户研究报告",
  create_segment_report: "正在写用户研究报告",
  crawl_bilibili_comments: "正在采集 B 站评论（已授权，受频率控制）",
  list_analysis_runs: "正在查看可用的评论分析数据",
  get_run_summary: "正在了解分析任务详情",
  get_run_top_needs: "正在统计高频用户需求",
  import_signals_from_run: "正在把评论分析结果转为用户信号",
  query_signals: "正在分析用户需求信号",
  query_assets: "正在检索内部素材库",
  upsert_asset: "正在登记素材",
  match_assets_to_needs: "正在匹配需求与可用素材（含授权检查）",
  create_opportunity: "正在形成增长机会判断",
  create_content_brief: "正在起草内容任务书",
  create_experiment: "正在登记增长实验",
  record_publish_results: "正在登记发布结果",
  compute_experiment_metrics: "正在汇总实验指标",
  review_experiments: "正在汇总实验事实（传播/导流分层）",
  record_learning: "正在写入经验记录",
  crawl_external: "请求外部数据采集（需任务授权）",
  send_external_reply: "请求对外发送（已被权限拒绝）",
};

/* ---------- 首页：今天 3 件事 ---------- */
async function loadToday() {
  const pid = state.product;
  const list = $("todayList");
  try {
    const [briefs, opps, exps, exp, product] = await Promise.all([
      api(`/products/${pid}/briefs`), api(`/products/${pid}/opportunities`),
      api(`/products/${pid}/experiments`), api(`/products/${pid}/export`),
      api("/products").then((d) => d.products.find((p) => p.product_id === pid)),
    ]);
    const items = [];
    const drafts = briefs.briefs.filter((b) => b.status === "draft");
    if (drafts.length) items.push({ text: `有 ${drafts.length} 份任务书等待你批准——批准后才能建实验发布`, act: `view-library` });
    const openOpps = opps.opportunities.filter((o) => o.status === "open");
    if (openOpps.length) items.push({ text: `${openOpps.length} 个增长机会待你决策（采纳或拒绝并说明理由）` });
    const running = exps.experiments.filter((e) => e.status === "running");
    const obsExpIds = new Set((exp.observations || []).map((o) => o.experiment_id));
    const noData = running.filter((e) => !obsExpIds.has(e.experiment_id));
    if (noData.length) items.push({ text: `${noData.length} 个进行中的实验还没回填表现数据，无法复盘` });
    const blockers = [];
    if (!(exp.assets || []).length) blockers.push("没有任何已登记素材——AI 无法引用真实素材做内容策划，请先导入团队素材");
    else if (!(exp.assets || []).some((a) => ["owned", "licensed"].includes(a.license_status))) blockers.push("素材均未确认授权——禁止对外使用，需人工核对授权");
    if (!(exp.signals || []).length) blockers.push("没有用户需求信号——先导入评论分析结果或录入真实反馈");
    if (product && product.attribution_capability === "none") blockers.push("站内转化不可验证——建议先用可追踪链接，否则无法评估内容是否拉新");
    blockers.slice(0, 3 - items.length).forEach((b) => items.push({ text: b, blocker: true }));
    if (!items.length) items.push({ text: "当前没有待处理事项。可以提出新的增长目标。", blocker: false });
    list.innerHTML = items.slice(0, 3).map((it, i) =>
      `<div class="today-item ${it.blocker ? "blocker" : ""}"><span class="no">${i + 1}</span><span>${it.blocker ? "⛔ " : ""}${esc(it.text)}</span></div>`
    ).join("");
  } catch (e) {
    list.innerHTML = `<div class="today-item blocker"><span class="no">!</span><span>无法读取数据：${esc(e.message)}</span></div>`;
  }
}

/* ---------- 运行 Agent ---------- */
$("goalInput").addEventListener("input", () => {});
document.querySelectorAll(".chip").forEach((c) =>
  c.addEventListener("click", () => { $("goalInput").value = c.dataset.goal; $("goalInput").focus(); }));

$("runBtn").addEventListener("click", async () => {
  const goal = $("goalInput").value.trim();
  if (!goal) { alert("请先输入增长目标"); return; }
  if (!isDemo() && !hasKey()) {
    alert("正式模式需要连接真实模型（设置与调试 → 模型连接）。\n本原型不会用 Mock 代替真实 AI 处理正式数据。\n如只想体验流程，请切换到 YouVibe（DEMO）产品。");
    return;
  }
  $("runBtn").disabled = true; $("stopBtn").disabled = false;
  $("workPanel").hidden = false; $("resultPanel").hidden = true;
  $("workSteps").innerHTML = ""; $("workDebug").textContent = "";
  setStatus("running", "AI 正在工作…");
  try {
    const r = await api("/agent/run_async", { method: "POST", body: JSON.stringify({
      product_id: state.product, goal,
      use_mock: isDemo() || !hasKey(), api_key: "",  // 凭据由服务端持久化，请求无需携带
    })});
    state.sessionId = r.session_id;
    state.polling = setInterval(poll, 1300);
  } catch (e) {
    setStatus("error", "启动失败：" + e.message);
    $("runBtn").disabled = false; $("stopBtn").disabled = true;
  }
});

$("stopBtn").addEventListener("click", () => {
  if (state.sessionId) api(`/agent/sessions/${state.sessionId}/stop?product_id=${state.product}`, { method: "POST" }).catch(() => {});
});

function setStatus(kind, text) {
  $("workStatus").className = "status-dot " + kind;
  $("workMeta").textContent = text;
}

async function poll() {
  try {
    const s = await api(`/agent/sessions/${state.sessionId}?product_id=${state.product}`);
    renderSteps(s);
    setStatus(s.status === "running" ? "running" : (s.status === "done" ? "done" : "error"),
      `${s.status} · 第 ${s.iterations} 轮 · 成本 ¥${(s.cost_cny || 0).toFixed(4)} · ${isDemo() || s.config.use_mock ? "MOCK 模型" : modelName()}`);
    if (["done", "error", "stopped", "budget_exceeded"].includes(s.status)) {
      clearInterval(state.polling); state.polling = null;
      $("runBtn").disabled = false; $("stopBtn").disabled = true;
      await renderResult(s);
      await loadToday();
    }
  } catch (e) { /* 忽略瞬时错误 */ }
}

function renderSteps(session) {
  const seen = new Set([...$("workSteps").children].map((li) => li.dataset.key));
  const toolMsgs = (session.messages || []).filter((m) => m.role === "tool");
  toolMsgs.forEach((m, i) => {
    const key = m.name + i;
    if (seen.has(key)) return;
    let payload = {};
    try { payload = JSON.parse(m.content || "{}"); } catch (e) {}
    const phrase = TOOL_PHRASES[m.name] || m.name;
    const cls = payload.status === "denied" ? "denied" : (payload.status === "error" ? "err" : "");
    let suffix = " ✓";
    if (payload.status === "denied") {
      suffix = (payload.error || "").includes("安全上限")
        ? "（⚠ 触发安全上限：AI 停止重复查询，改用已拿到的信息继续——防浪费机制，不是故障）"
        : "（被权限边界拒绝：" + (payload.error || "").slice(0, 50) + "）";
    } else if (payload.status === "error") {
      suffix = (payload.error || "").includes("ValidationError")
        ? "（第一次写报告格式有误，AI 会自动纠正重试）"
        : "（失败：" + (payload.error || "").slice(0, 50) + "）";
    }
    $("workSteps").insertAdjacentHTML("beforeend",
      `<li class="${cls}" data-key="${key}"><span class="t">步骤${i + 1}</span><span>${esc(phrase)}${esc(suffix)}</span></li>`);
    $("workDebug").textContent += `\n[${m.name}] ${(m.content || "").slice(0, 300)}\n`;
  });
}

/* ---------- 结果卡片 ---------- */
async function renderResult(session) {
  $("resultPanel").hidden = false;
  const mock = session.config.use_mock || !hasKey() || isDemo();
  $("resultSummary").innerHTML =
    (mock ? '<span class="mock-stamp">MOCK · 演示结果，非真实 AI 推理</span>' : `<span class="mock-stamp" style="background:#dcfce7;color:var(--ok)">${esc(modelName())}</span>`) +
    "<br>" + esc(session.final_answer || ("已退出：" + (session.stop_reason || "")));
  let createdIds = [];
  try {
    const sum = await api(`/agent/sessions/${session.session_id}/summary?product_id=${state.product}`);
    createdIds = sum.created_records || [];
    renderGaps(sum.data_gaps || []);
  } catch (e) {}
  const pid = state.product;
  const [opps, briefs, segments] = await Promise.all([
    api(`/products/${pid}/opportunities`), api(`/products/${pid}/briefs`),
    api(`/products/${pid}/segments`),
  ]);
  // 只展示【本次任务】产出的卡片（修复“历史重复对象混排”问题的原型实现）
  const myOpps = opps.opportunities.filter((o) => createdIds.includes(o.opportunity_id) || true);
  const sessionOpps = createdIds.length ? opps.opportunities.filter((o) => createdIds.includes(o.opportunity_id)) : [];
  const sessionBriefs = createdIds.length ? briefs.briefs.filter((b) => createdIds.includes(b.brief_id)) : [];
  const sessionSegs = (segments.reports || []).filter((r) => r.created_by_session === session.session_id);
  const cards = $("resultCards");
  cards.innerHTML = "";
  const shownOpps = sessionOpps.length ? sessionOpps : [];
  const shownBriefs = sessionBriefs.length ? sessionBriefs : [];
  if (!shownOpps.length && !shownBriefs.length && !sessionSegs.length) {
    cards.innerHTML = `<div class="muted">本次任务没有产生新的机会或任务书（可能因证据不足被 AI 拒绝，或对象在此前任务已存在）。</div>`;
    return;
  }
  cards.insertAdjacentHTML("beforeend", '<div class="rcards" id="rcards"></div>');
  const wrap = $("rcards");
  sessionSegs.forEach((r) => wrap.insertAdjacentHTML("beforeend", segmentCard(r)));
  shownOpps.forEach((o) => wrap.insertAdjacentHTML("beforeend", oppCard(o)));
  shownBriefs.forEach((b) => wrap.insertAdjacentHTML("beforeend", briefCard(b)));
}

function segmentCard(r) {
  const certTag = { evidenced: "ok", inferred: "warn", unverified: "bad" };
  const certLabel = { evidenced: "有证据", inferred: "推断", unverified: "未验证" };
  const segs = (r.segments || []).map((s) => `<div class="hidden-row">
    <span class="tag ${certTag[s.certainty] || ""} certainty">${certLabel[s.certainty] || esc(s.certainty)}</span>
    <b>${esc(s.name)}</b>
    <div class="muted">需求：${esc((s.core_needs || []).join("；") || "-")} ｜ 平台：${esc((s.platforms || []).join(",") || "-")}</div>
    <div class="muted">产品匹配：${esc(s.product_fit)}（${esc(s.product_fit_reason || "-")}）</div>
    <div class="muted">触达：${esc((s.reach_methods || []).join("；") || "-")}${(s.hypothesized_channels || []).length ? " ｜ 推测渠道：" + esc(s.hypothesized_channels.join(",")) : ""}</div>
    <div class="muted">证据 ${((s.evidence_refs || []).length)} 条</div>
  </div>`).join("");
  return `<div class="rcard seg-card" style="grid-column:1/-1">
    <div class="tags"><span class="tag">潜在用户研究报告</span><span class="tag warn">初步画像，非已确认目标用户</span></div>
    <h4>用户群体（${(r.segments || []).length}）</h4>
    ${segs}
    <div class="row-block"><b>数据边界：</b>${esc(r.data_limitations || "-")}</div>
    ${(r.not_recommended || []).length ? `<div class="row-block"><b>不建议当作目标：</b>${esc(r.not_recommended.join("；"))}</div>` : ""}
  </div>`;
}

$("followupBtn").addEventListener("click", async () => {
  const msg = $("followupInput").value.trim();
  if (!msg || !state.sessionId) return;
  if (!isDemo() && !hasKey()) { alert("正式模式需先连接真实模型"); return; }
  $("followupBtn").disabled = true;
  try {
    const r = await api(`/agent/sessions/${state.sessionId}/followup?product_id=${state.product}`, {
      method: "POST", body: JSON.stringify({
        message: msg, use_mock: isDemo() || !hasKey(), api_key: "",
      }),
    });
    $("followupInput").value = "";
    state.sessionId = r.session_id;
    $("workPanel").hidden = false;
    setStatus("running", "AI 正在继续这个任务…");
    state.polling = setInterval(poll, 1300);
  } catch (e) { alert("追问失败：" + e.message); }
  $("followupBtn").disabled = false;
});

function renderGaps(gaps) {
  if (!gaps.length) return;
  $("resultSummary").innerHTML += `<div style="margin-top:8px" class="muted">⚠ 当前数据缺口：<br>${gaps.map(esc).join("<br>")}</div>`;
}

function oppCard(o) {
  const kindTag = o.opportunity_kind === "demand_first"
    ? '<span class="tag warn">待制作（无现成素材）</span>' : '<span class="tag ok">有素材可承接</span>';
  const vTag = o.verdict === "recommend" ? "ok" : (o.verdict === "reject" ? "bad" : "warn");
  return `<div class="rcard" data-opp="${esc(o.opportunity_id)}">
    <div class="tags">${kindTag}<span class="tag ${vTag}">${esc(o.verdict)}</span><span class="tag">${esc(o.uncertainty_level)}</span></div>
    <h4>${esc(o.problem || "(未命名机会)")}</h4>
    <div class="row-block"><b>为什么：</b>${esc(o.verdict_rationale || "-")}</div>
    ${o.production_need ? `<div class="row-block"><b>需要制作：</b>${esc(o.production_need)}</div>` : ""}
    ${(o.usable_assets || []).length ? `<div class="row-block"><b>可用素材：</b>${esc(o.usable_assets.join(", "))}</div>` : ""}
    <div class="row-block"><b>建议行动：</b>${esc(o.recommended_action || "-")}</div>
    ${(o.metrics_to_verify || []).length ? `<div class="row-block"><b>验证指标：</b>${esc(o.metrics_to_verify.join(", "))}</div>` : ""}
    <div class="ops">
      <button class="accept" onclick="protoOpp('${esc(o.opportunity_id)}','accepted')">采纳</button>
      <button class="reject" onclick="protoOpp('${esc(o.opportunity_id)}','rejected')">拒绝并说明</button>
    </div>
  </div>`;
}

function briefCard(b) {
  const sTag = b.status === "approved" ? "ok" : (b.status === "rejected" ? "bad" : "warn");
  return `<div class="rcard" data-brief="${esc(b.brief_id)}">
    <div class="tags"><span class="tag ${sTag}">任务书 · ${esc(b.status)}</span><span class="tag">优先级 P${b.priority || "-"}</span></div>
    <h4>${esc(b.title)}</h4>
    <div class="meta">面向：${esc(b.audience)} ｜ 素材：${esc((b.asset_ids || []).join(", "))} ｜ 渠道：${esc((b.channels || []).join(", "))}</div>
    <div class="row-block"><b>开头钩子：</b>${esc(b.hook)}</div>
    <div class="row-block"><b>到站理由：</b>${esc(b.visit_reason)}</div>
    <div class="row-block"><b>验证指标：</b>${esc((b.validation_metrics || []).join(", "))}</div>
    <div class="row-block"><b>推荐理由：</b>${esc(b.rationale)}</div>
    <div class="ops">
      ${b.status === "draft" ? `<button class="accept" onclick="protoBrief('${esc(b.brief_id)}','approve')">批准（可建实验）</button>
      <button class="reject" onclick="protoBrief('${esc(b.brief_id)}','reject')">拒绝</button>` : `<span class="muted">${b.status === "approved" ? "已批准，可登记实验" : "已拒绝"}</span>`}
    </div>
  </div>`;
}

window.protoOpp = async (id, action) => {
  if (action === "rejected") {
    const reason = prompt("拒绝的原因（会写入经验，供 AI 下次参考）:");
    if (!reason) return;
    await api(`/products/${state.product}/learnings`, { method: "POST", body: JSON.stringify({
      learning_id: "fb_" + Date.now(), product_id: state.product,
      what_tested: "人工拒绝增长机会 " + id, outcome: "rejected",
      human_feedback: { verdict: "rejected", reason },
    })});
  }
  const cur = await api(`/products/${state.product}/opportunities`);
  const opp = cur.opportunities.find((o) => o.opportunity_id === id);
  if (opp) {
    opp.status = action;
    await api(`/products/${state.product}/opportunities`, { method: "POST", body: JSON.stringify(opp) });
  }
  document.querySelector(`[data-opp="${id}"] .ops`).innerHTML = `<span class="muted">已${action === "accepted" ? "采纳" : "拒绝并记录"}</span>`;
  loadToday();
};

window.protoBrief = async (id, action) => {
  const note = action === "reject" ? (prompt("拒绝原因：") || "") : "";
  if (action === "reject" && note === "") return;
  await api(`/products/${state.product}/briefs/${id}/review`, { method: "POST", body: JSON.stringify({ action, note }) });
  const el = document.querySelector(`[data-brief="${id}"]`);
  if (el) el.querySelector(".ops").innerHTML = `<span class="muted">${action === "approve" ? "已批准，可登记实验" : "已拒绝"}</span>`;
  loadToday();
};

/* ---------- 增长项目 ---------- */
async function loadProjects() {
  const pid = state.product;
  const el = $("projectList");
  el.innerHTML = '<div class="muted">加载中…</div>';
  try {
    const [sessions, opps, briefs, exps] = await Promise.all([
      api(`/agent/sessions?product_id=${pid}`), api(`/products/${pid}/opportunities`),
      api(`/products/${pid}/briefs`), api(`/products/${pid}/experiments`),
    ]);
    const stageOf = (s) => s.status === "running" ? "研究中" : s.status;
    el.innerHTML = "";
    if (!sessions.sessions.length) { el.innerHTML = '<div class="muted">还没有任务。回到工作台提出第一个增长目标。</div>'; return; }
    sessions.sessions.slice().reverse().forEach((s) => {
      el.insertAdjacentHTML("beforeend", `<div class="card" style="margin-bottom:10px">
        <div class="tags"><span class="tag">${esc(stageOf(s))}</span><span class="tag">${s.config.use_mock ? "MOCK" : "真实模型"}</span>
        <span class="tag">${new Date(s.created_at).toLocaleString()}</span></div>
        <h4 style="margin:6px 0 4px;font-size:14px">${esc(s.config.goal)}</h4>
        <div class="muted">第 ${s.iterations} 轮 · 成本 ¥${(s.cost_cny || 0).toFixed(4)} · ${esc(s.stop_reason || s.final_answer.slice(0, 60))}</div>
      </div>`);
    });
    const stats = `<div class="muted" style="margin-top:10px">累计：机会 ${opps.opportunities.length} · 任务书 ${briefs.briefs.length} · 实验 ${exps.experiments.length}</div>`;
    el.insertAdjacentHTML("beforeend", stats);
  } catch (e) { el.innerHTML = `<div class="muted">${esc(e.message)}</div>`; }
}

/* ---------- 素材与知识 ---------- */
async function loadLibrary() {
  const pid = state.product;
  try {
    const [assets, signals, learns, batches] = await Promise.all([
      api(`/products/${pid}/assets`), api(`/products/${pid}/signals?limit=5`),
      api(`/products/${pid}/learnings`), api(`/products/${pid}/import_batches`),
    ]);
    $("assetCount").textContent = `${assets.assets.length} 份`;
    $("assetList").innerHTML = assets.assets.length ? assets.assets.map((a) => {
      const tag = a.license_status === "unknown" ? "bad" : "ok";
      return `<div class="hidden-row"><span class="tag ${tag}">${esc(a.license_status)}</span> ${esc(a.title)} <span class="muted">${esc((a.topics || []).join("/"))}</span></div>`;
    }).join("") : '<div class="muted">暂无素材。团队可用上方入口导入 CSV/JSON。</div>';
    const realLearns = learns.learnings.filter((l) => l.data_nature !== "mock");
    const mockLearns = learns.learnings.length - realLearns.length;
    $("signalStats").innerHTML = `<div class="hidden-row">需求信号：<b>${signals.signals.length}</b> 条（仅显示前 ${Math.min(5, signals.signals.length)} 条）</div>` +
      signals.signals.map((s) => `<div class="hidden-row muted">· ${esc(s.need_or_problem.slice(0, 60))} <span class="tag">${esc(s.dataset_ref || s.source_platform)}</span></div>`).join("") +
      (batches.batches.length ? `<div class="hidden-row muted">数据批次：${batches.batches.map((b) => `${esc(b.source)}（${b.count}条·${b.data_nature}）`).join("；")}</div>` : "");
    $("learningList").innerHTML = `<h3 style="margin-top:10px">已验证经验 <span class="count">${realLearns.length} 条（另有 ${mockLearns} 条 Mock 记录已隔离）</span></h3>` +
      (realLearns.length ? realLearns.map((l) => `<div class="hidden-row"><b>${esc(l.what_tested)}</b><div class="muted">${esc(l.outcome)}（${esc(l.evidence_strength)}）</div></div>`).join("")
        : '<div class="muted">暂无真实经验。复盘后自动写入。</div>');
  } catch (e) { $("assetList").innerHTML = `<div class="muted">${esc(e.message)}</div>`; }
}

$("afAddBtn").addEventListener("click", async () => {
  const title = $("afTitle").value.trim();
  if (!title) { alert("请先填素材标题"); return; }
  const asset = {
    asset_id: "a_" + Date.now().toString(36),
    title,
    license_status: $("afLicense").value,
    asset_type: $("afType").value,
    topics: $("afTopics").value.split(/[,，]/).map((s) => s.trim()).filter(Boolean),
    uri: $("afUri").value.trim(),
    landing_page: $("afLanding").value.trim(),
    source_label: "web_form",
  };
  try {
    const r = await api(`/products/${state.product}/assets/import`, { method: "POST", body: JSON.stringify({ assets: [asset] }) });
    alert(`已登记：${title}（${asset.license_status === "unknown" ? "授权未确认，对外使用前需核对" : "可用于内容策划"}）`);
    ["afTitle", "afTopics", "afUri", "afLanding"].forEach((id) => ($(id).value = ""));
    loadLibrary(); loadToday();
  } catch (e) { alert("登记失败：" + e.message); }
});

$("importAssetBtn").addEventListener("click", async () => {
  const text = $("assetImport").value.trim();
  if (!text) return;
  const body = text.startsWith("[") ? { assets: JSON.parse(text) } : { csv_text: text };
  try {
    const r = await api(`/products/${state.product}/assets/import`, { method: "POST", body: JSON.stringify(body) });
    alert(`导入完成：新增 ${r.created}，更新 ${r.updated}`);
    loadLibrary(); loadToday();
  } catch (e) { alert("导入失败：" + e.message); }
});

/* ---------- 增长复盘 ---------- */
async function loadReview() {
  const pid = state.product;
  const el = $("expList");
  try {
    const exp = await api(`/products/${pid}/export`);
    const product = await api("/products").then((d) => d.products.find((p) => p.product_id === pid));
    const warn = $("attrWarning");
    if (product && product.attribution_capability === "none") {
      warn.hidden = false;
      warn.textContent = "⚠ 当前产品站内转化不可验证（attribution=none）：以下只有站外表现时有数据，任何「拉新/注册」结论都不可得出。";
    } else warn.hidden = true;
    if (!exp.experiments.length) {
      el.innerHTML = '<div class="card muted">还没有实验数据。<br>路径：工作台规划内容 → 批准任务书 → 建实验 → 人工发布 → 回填表现。此处不展示虚构图表。</div>';
      return;
    }
    el.innerHTML = exp.experiments.map((e) => {
      const obs = (exp.observations || []).filter((o) => o.experiment_id === e.experiment_id);
      const names = [...new Set(obs.map((o) => o.name))];
      const rows = names.map((n) => {
        const o = obs.find((x) => x.name === n);
        const val = o && o.value != null ? o.value.toLocaleString() : '<span class="unknown">Unknown</span>';
        return `<tr><td>${esc(n)}</td><td>${esc(o ? o.metric_kind : "-")}</td><td>${val}</td><td class="muted">${esc(o ? o.channel : "")}</td></tr>`;
      }).join("");
      return `<div class="card" style="margin-bottom:10px">
        <div class="tags"><span class="tag">${esc(e.status)}</span></div>
        <h4 style="margin:6px 0 4px;font-size:14px">${esc(e.goal || e.experiment_id)}</h4>
        <div class="muted">假设：${esc(e.hypothesis || "-")} ｜ 已发布 ${e.publish_records.length} 条 ｜ 归因限制：${esc(e.attribution_limits || "-")}</div>
        ${obs.length ? `<table class="metrics"><tr><th>指标</th><th>类型</th><th>数值</th><th>渠道</th></tr>${rows}</table>` : '<div class="muted" style="margin-top:6px">还没有回填表现数据。</div>'}
      </div>`;
    }).join("");
  } catch (e) { el.innerHTML = `<div class="muted">${esc(e.message)}</div>`; }
}

/* ---------- 设置与调试 ---------- */
async function loadSettings() {
  let st = { configured: false };
  try {
    st = await api("/settings/model");
    state.modelConfigured = st.configured;
    state.serverBaseUrl = st.base_url || "";
    state.serverModelName = st.model_name || "";
  } catch (e) {}
  const connected = !!st.configured;
  $("modelState").innerHTML = connected
    ? `<div class="model-badge ok" style="margin-bottom:8px">已保存并生效：${esc(st.model_name)} @ ${esc(st.base_url)}（Key: ${esc(st.api_key_masked)}，仅存服务端本地，不会提交 Git）</div>`
    : `<div class="model-badge warn" style="margin-bottom:8px">未配置真实模型。正式模式下 AI 功能不可用（不会用 Mock 冒充）。</div>`;
  $("keyInput").value = "";
  $("keyInput").placeholder = connected ? "已保存（输入新 Key 可替换，留空则保留）" : "API Key（保存到服务端本地文件）";
  $("baseInput").value = st.base_url || "";
  $("modelInput").value = st.model_name || "";
  try {
    const exp = await api(`/products/${state.product}/export`);
    $("dataStats").innerHTML = ["signals", "assets", "opportunities", "briefs", "experiments", "observations", "learnings"]
      .map((k) => `<div class="hidden-row">${k}：<b>${(exp[k] || []).length}</b></div>`).join("");
    const audit = await api(`/products/${state.product}/audit?limit=50`);
    $("auditLog").textContent = audit.audit.map((a) => `[${(a.created_at || "").slice(0, 19)}] ${a.action} → ${a.status} ${a.detail || ""}`).join("\n") || "无";
  } catch (e) { $("dataStats").innerHTML = esc(e.message); }
}

$("saveKeyBtn").addEventListener("click", async () => {
  try {
    const st = await api("/settings/model", { method: "POST", body: JSON.stringify({
      base_url: $("baseInput").value.trim(),
      model_name: $("modelInput").value.trim(),
      api_key: $("keyInput").value.trim(),  // 留空保留已存 Key
    })});
    state.modelConfigured = st.configured;
    state.serverBaseUrl = st.base_url;
    state.serverModelName = st.model_name;
    $("keyTestResult").textContent = st.configured ? "已保存（永久生效，无需再输入）" : "已保存（提示：还未填 API Key）";
    refreshModeBadge(); loadSettings();
  } catch (e) { $("keyTestResult").textContent = "保存失败：" + e.message; }
});

$("testKeyBtn").addEventListener("click", async () => {
  $("keyTestResult").textContent = "正在通过服务端测试连接（最小请求）…";
  try {
    const r = await api("/settings/model/test", { method: "POST", body: JSON.stringify({
      base_url: $("baseInput").value.trim(),
      model_name: $("modelInput").value.trim(),
      api_key: $("keyInput").value.trim(),
    })});
    $("keyTestResult").textContent = r.ok
      ? `连接成功（${r.latency_s}s）：模型回「${r.model_reply}」@ ${r.base_url}`
      : "连接失败：" + (r.error || "未知错误");
  } catch (e) { $("keyTestResult").textContent = "连接失败：" + e.message; }
});

/* ---------- 初始化 ---------- */
async function init() {
  // 旧版 sessionStorage 迁移到服务端持久化（一次性）
  try {
    const legacyKey = sessionStorage.getItem("llm_api_key");
    if (legacyKey) {
      const st0 = await api("/settings/model");
      if (!st0.configured) {
        await api("/settings/model", { method: "POST", body: JSON.stringify({
          base_url: sessionStorage.getItem("llm_base_url") || "",
          model_name: sessionStorage.getItem("llm_model") || "",
          api_key: legacyKey,
        })});
      }
      sessionStorage.removeItem("llm_api_key");
      sessionStorage.removeItem("llm_base_url");
      sessionStorage.removeItem("llm_model");
    }
    const st = await api("/settings/model");
    state.modelConfigured = st.configured;
    state.serverBaseUrl = st.base_url || "";
    state.serverModelName = st.model_name || "";
  } catch (e) {}
  const d = await api("/products");
  const sel = $("productSel");
  sel.innerHTML = d.products.map((p) =>
    `<option value="${esc(p.product_id)}">${esc(p.name)}${p.product_id === DEMO_PID ? "（演示）" : ""}</option>`).join("");
  sel.value = state.product;
  if (sel.value !== state.product) { state.product = sel.value; }
  sel.addEventListener("change", () => {
    state.product = sel.value;
    localStorage.setItem("proto_product", state.product);
    refreshModeBadge(); loadToday();
  });
  refreshModeBadge();
  await loadToday();
}
init().catch((e) => { $("todayList").innerHTML = `<div class="today-item blocker">初始化失败：${esc(e.message)}（请确认 Web 服务已启动）</div>`; });
})();
