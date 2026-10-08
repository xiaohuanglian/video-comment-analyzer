/* AI Growth Engine 最小工作台 */
(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const state = { product: "", sessionId: "", polling: null };

  async function api(path, opts) {
    const res = await fetch("/api/growth" + path, opts && Object.assign({
      headers: { "Content-Type": "application/json" },
    }, opts));
    if (!res.ok) {
      let detail = res.statusText;
      try { detail = (await res.json()).detail || detail; } catch (e) { /* ignore */ }
      throw new Error(detail);
    }
    return res.json();
  }

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  }

  async function loadProducts() {
    const data = await api("/products");
    const sel = $("gProduct");
    sel.innerHTML = data.products.map((p) =>
      `<option value="${esc(p.product_id)}">${esc(p.name)}</option>`).join("");
    const saved = localStorage.getItem("growth_product");
    state.product = saved || "youvibe_demo";
    sel.value = state.product;
    if (sel.value !== state.product) { state.product = sel.value; }
    await api("/products/seed", { method: "POST" }).catch(() => {});
  }

  async function refreshAll() {
    if (!state.product) return;
    const pid = state.product;
    try {
      const [opps, briefs, assets, exps, learns, audit] = await Promise.all([
        api(`/products/${pid}/opportunities`),
        api(`/products/${pid}/briefs`),
        api(`/products/${pid}/assets`),
        api(`/products/${pid}/experiments`),
        api(`/products/${pid}/learnings`),
        api(`/products/${pid}/audit?limit=40`),
      ]);
      renderOpps(opps.opportunities);
      renderBriefs(briefs.briefs);
      renderAssets(assets.assets);
      renderExps(exps.experiments);
      renderLearnings(learns.learnings);
      renderLog(audit.audit);
    } catch (e) { console.warn(e); }
  }

  function renderOpps(list) {
    $("gOppCount").textContent = list.length ? `${list.length} 条` : "";
    $("gOpps").innerHTML = list.length ? "" : '<span class="g-muted">暂无，运行 AI 助手后生成</span>';
    list.slice().reverse().forEach((o) => {
      const tag = o.verdict === "recommend" ? "ok" : (o.verdict === "reject" ? "bad" : "warn");
      $("gOpps").insertAdjacentHTML("beforeend", `<div class="g-item">
        <span class="g-tag ${tag}">${esc(o.verdict)}</span>
        <strong>${esc(o.problem || o.target_segment)}</strong>
        <div class="g-muted">${esc(o.verdict_rationale || "")}</div>
        <div class="g-muted">行动：${esc(o.recommended_action || "-")} ｜ 不确定性：${esc(o.uncertainty_level)}</div>
      </div>`);
    });
  }

  function renderBriefs(list) {
    $("gBriefCount").textContent = list.length ? `${list.length} 份` : "";
    $("gBriefs").innerHTML = list.length ? "" : '<span class="g-muted">暂无</span>';
    list.slice().reverse().forEach((b) => {
      const tag = b.status === "approved" ? "ok" : (b.status === "rejected" ? "bad" : "warn");
      const actions = b.status === "draft"
        ? `<button class="g-btn ghost" onclick="growthReview('${esc(b.brief_id)}','approve')">批准</button>
           <button class="g-btn ghost" style="color:#991b1b" onclick="growthReview('${esc(b.brief_id)}','reject')">拒绝</button>`
        : "";
      $("gBriefs").insertAdjacentHTML("beforeend", `<div class="g-item">
        <span class="g-tag ${tag}">${esc(b.status)}</span> <strong>P${b.priority || "-"} ${esc(b.title)}</strong>
        <div class="g-muted">用户：${esc(b.audience)} ｜ 问题：${esc(b.problem)}</div>
        <div class="g-muted">素材：${esc((b.asset_ids || []).join(", ") || "-")} ｜ 渠道：${esc((b.channels || []).join(", "))}</div>
        <div class="g-muted">钩子：${esc(b.hook)}</div>
        <div class="g-muted">到站理由：${esc(b.visit_reason)} ｜ 验证指标：${esc((b.validation_metrics || []).join(", "))}</div>
        <details><summary>推荐理由与证据</summary><pre>${esc(b.rationale)}\n证据：${esc((b.evidence_refs || []).join("\\n"))}</pre></details>
        ${actions}
      </div>`);
    });
  }

  window.growthReview = async function (briefId, action) {
    const note = action === "reject" ? (prompt("拒绝原因（会记录供 AI 后续参考）：") || "") : "";
    if (action === "reject" && note === null) return;
    await api(`/products/${state.product}/briefs/${encodeURIComponent(briefId)}/review`, {
      method: "POST", body: JSON.stringify({ action, note }),
    });
    await refreshAll();
  };

  function renderAssets(list) {
    $("gAssetCount").textContent = list.length ? `${list.length} 份` : "";
    $("gAssets").innerHTML = list.length ? "" : '<span class="g-muted">暂无</span>';
    list.forEach((a) => {
      const tag = a.license_status === "unknown" ? "bad" : "ok";
      $("gAssets").insertAdjacentHTML("beforeend", `<div class="g-item">
        <span class="g-tag ${tag}">${esc(a.license_status)}</span> ${esc(a.title)}
        <span class="g-muted">${esc((a.topics || []).join("/"))}</span>
      </div>`);
    });
  }

  function renderExps(list) {
    $("gExpCount").textContent = list.length ? `${list.length} 个` : "";
    $("gExps").innerHTML = list.length ? "" : '<span class="g-muted">暂无</span>';
    list.slice().reverse().forEach((e) => {
      $("gExps").insertAdjacentHTML("beforeend", `<div class="g-item">
        <span class="g-tag">${esc(e.status)}</span> <strong>${esc(e.goal || e.experiment_id)}</strong>
        <div class="g-muted">假设：${esc(e.hypothesis || "-")}</div>
        <div class="g-muted">ID：${esc(e.experiment_id)} ｜ 已发布 ${e.publish_records.length} 条 ｜ 渠道：${esc((e.channels || []).join(","))}</div>
        ${e.attribution_limits ? `<div class="g-muted">归因限制：${esc(e.attribution_limits)}</div>` : ""}
      </div>`);
    });
  }

  function renderLearnings(list) {
    $("gLearnCount").textContent = list.length ? `${list.length} 条` : "";
    $("gLearnings").innerHTML = list.length ? "" : '<span class="g-muted">暂无</span>';
    list.slice().reverse().forEach((l) => {
      $("gLearnings").insertAdjacentHTML("beforeend", `<div class="g-item">
        <strong>${esc(l.what_tested)}</strong>
        <div class="g-muted">结果：${esc(l.outcome)}（证据强度：${esc(l.evidence_strength)}）</div>
        ${(l.next_adjustments || []).length ? `<div class="g-muted">下轮调整：${esc(l.next_adjustments.join("；"))}</div>` : ""}
        ${l.human_feedback ? `<div class="g-muted">人工反馈：${esc(l.human_feedback.verdict)} — ${esc(l.human_feedback.reason || "")}</div>` : ""}
      </div>`);
    });
  }

  function renderLog(list) {
    $("gLog").innerHTML = list.slice().reverse().map((a) =>
      `<div>[${esc((a.created_at || "").slice(11, 19))}] ${esc(a.action)} → ${a.status === "ok" ? "✓" : (a.status === "denied" ? "✗拒绝" : "✗错误")} ${esc(a.detail || "")}</div>`
    ).join("") || '<div class="g-muted">无</div>';
  }

  async function pollSession() {
    if (!state.sessionId) return;
    try {
      const s = await api(`/agent/sessions/${encodeURIComponent(state.sessionId)}?product_id=${encodeURIComponent(state.product)}`);
      $("gSessionMeta").textContent = `状态 ${s.status} · 第 ${s.iterations} 轮 · 成本 ¥${(s.cost_cny || 0).toFixed(4)}`;
      if (s.final_answer) $("gAnswer").textContent = s.final_answer;
      if (["done", "error", "stopped", "budget_exceeded"].includes(s.status)) {
        clearInterval(state.polling); state.polling = null;
        $("gRun").disabled = false; $("gStop").disabled = true;
        if (s.status !== "done" && !s.final_answer) {
          $("gAnswer").textContent = `已安全退出：${s.stop_reason}（中间成果已保存）`;
        }
        await refreshAll();
      }
    } catch (e) { console.warn(e); }
  }

  $("gRun").addEventListener("click", async () => {
    const goal = $("gGoal").value.trim();
    if (!goal) { alert("请输入增长目标"); return; }
    const apiKey = sessionStorage.getItem("llm_api_key") || "";
    $("gRun").disabled = true; $("gStop").disabled = false;
    $("gAnswer").textContent = "AI 正在工作…（可在审计日志查看工具调用）";
    try {
      const r = await api("/agent/run_async", {
        method: "POST",
        body: JSON.stringify({
          product_id: state.product, goal,
          use_mock: !apiKey, api_key: apiKey,
          base_url: sessionStorage.getItem("llm_base_url") || "",
          model_name: sessionStorage.getItem("llm_model") || "",
        }),
      });
      state.sessionId = r.session_id;
      state.polling = setInterval(pollSession, 1200);
    } catch (e) {
      $("gAnswer").textContent = "启动失败：" + e.message;
      $("gRun").disabled = false; $("gStop").disabled = true;
    }
  });

  $("gStop").addEventListener("click", async () => {
    if (state.sessionId) {
      await api(`/agent/sessions/${encodeURIComponent(state.sessionId)}/stop?product_id=${encodeURIComponent(state.product)}`, { method: "POST" }).catch(() => {});
    }
  });

  $("gSeedDemo").addEventListener("click", async () => {
    const r = await api("/demo/seed", { method: "POST" });
    alert(`演示数据已就绪：素材 +${r.assets}，信号 +${r.signals}，历史指标 +${r.historical_observations}（全部 DEMO 标记，幂等）`);
    $("gProduct").value = "youvibe_demo";
    state.product = "youvibe_demo";
    localStorage.setItem("growth_product", state.product);
    await refreshAll();
  });

  $("gImportAssets").addEventListener("click", async () => {
    const text = $("gAssetImport").value.trim();
    if (!text) return;
    const body = text.startsWith("[") ? { assets: JSON.parse(text) } : { csv_text: text };
    const r = await api(`/products/${state.product}/assets/import`, { method: "POST", body: JSON.stringify(body) });
    alert(`导入完成：新增 ${r.created}，更新 ${r.updated}`);
    $("gAssetImport").value = "";
    await refreshAll();
  });

  $("gRecordPub").addEventListener("click", async () => {
    const metrics = {};
    if ($("gPubViews").value.trim()) metrics.views = Number($("gPubViews").value);
    if ($("gPubVisits").value.trim()) metrics.valid_visits = Number($("gPubVisits").value);
    const r = await api(`/products/${state.product}/tools/record_publish`, { method: "POST", body: JSON.stringify({
      experiment_id: $("gPubExp").value.trim(), channel: $("gPubChannel").value.trim(),
      url: $("gPubUrl").value.trim(), published_at: $("gPubDate").value.trim(), metrics,
    }) }).catch((e) => ({ error: e.message }));
    if (r.error) { alert("登记失败：" + r.error); return; }
    alert(`已登记 ${r.metrics_recorded} 条指标${r.unknown_metrics.length ? "；Unknown: " + r.unknown_metrics.join(",") : ""}`);
    await refreshAll();
  });

  $("gProduct").addEventListener("change", async (e) => {
    state.product = e.target.value;
    localStorage.setItem("growth_product", state.product);
    await refreshAll();
  });

  (async function init() {
    await loadProducts();
    await refreshAll();
  })();
})();
