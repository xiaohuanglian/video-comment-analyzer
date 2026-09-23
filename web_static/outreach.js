/**
 * 评论区回复（第三板块）— 独立模块。
 * 只消费前两板块产出的分析任务；不驱动评论洞察流程。
 */
(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);

  const outreachView = $("outreachView");
  const outreachRunHistory = $("outreachRunHistory");
  const outreachResearchTargets = $("outreachResearchTargets");
  const outreachRunStatus = $("outreachRunStatus");
  const outreachTargetsStatus = $("outreachTargetsStatus");
  const btnOutreachSaveTargets = $("btnOutreachSaveTargets");
  const outreachApiKey = $("outreachApiKey");
  const btnOutreachBuildCandidates = $("btnOutreachBuildCandidates");
  const btnOutreachGenerate = $("btnOutreachGenerate");
  const btnOutreachExportCandidates = $("btnOutreachExportCandidates");
  const btnOutreachExportOutreach = $("btnOutreachExportOutreach");
  const outreachExportHint = $("outreachExportHint");
  const outreachCandidateFilterResearch = $("outreachCandidateFilterResearch");
  const outreachCandidateFilterPriority = $("outreachCandidateFilterPriority");
  const outreachCandidateFilterContactability = $("outreachCandidateFilterContactability");
  const outreachCandidateFilterStatus = $("outreachCandidateFilterStatus");
  const outreachCandidateSelectAll = $("outreachCandidateSelectAll");
  const outreachTemplate = $("outreachTemplate");
  const outreachCandidatesStatus = $("outreachCandidatesStatus");
  const outreachCandidatesPanel = $("outreachCandidatesPanel");
  const outreachCandidatesPager = $("outreachCandidatesPager");
  const outreachIntervalSeconds = $("outreachIntervalSeconds");
  const outreachJitterSeconds = $("outreachJitterSeconds");
  const outreachDailyLimit = $("outreachDailyLimit");
  const outreachWindowStart = $("outreachWindowStart");
  const outreachWindowEnd = $("outreachWindowEnd");
  const btnOutreachStartReply = $("btnOutreachStartReply");
  const btnOutreachStopReply = $("btnOutreachStopReply");
  const outreachReplyStatus = $("outreachReplyStatus");

  const RUN_ID_STORAGE = "vc_outreach_current_run_id";
  const SHARED_RUN_HINT = "vc_insight_current_run_id";
  const API_KEY_STORAGE = "vc_insight_api_key";

  const state = {
    currentRunId: null,
    candidatesDoc: null,
    outreachDoc: null,
    defaultOutreachTemplate: "",
    candidatesPage: { page: 1, pageSize: 50, total: 0, items: [] },
    selectedCandidateKeys: new Set(),
    candidateFilters: {
      priority: "",
      contactability: "",
      contact_status: "",
      research_matched: "",
    },
    replyRunning: false,
    replyPollTimer: null,
  };

  const REVIEW_STATUS_LABELS = { draft: "待审核", approved: "已通过", rejected: "不回复" };
  const SEND_STATUS_LABELS = {
    pending: "待发送",
    queued: "已入队",
    sending: "发送中",
    sent: "已发送",
    failed: "发送失败",
    skipped: "已跳过",
  };

  const PRODUCT_FIT_LABELS = { high: "高", medium: "中", low: "低", unclear: "不明" };
  const PRIORITY_LABELS = { high: "高优先", medium: "中优先", low: "低优先" };
  const CONTACTABILITY_LABELS = { high: "可定位主页", medium: "有评论链接", low: "难以联系" };
  const CONTACT_STATUS_LABELS = {
    not_contacted: "未联系",
    preparing: "准备中",
    contacted: "已联系",
    replied: "已回复",
    interview_agreed: "已深度互动",
    declined: "已拒绝",
    no_reply: "无回复",
    interview_completed: "已跟进",
  };

  async function apiFetch(path, options = {}) {
    if (window.VCBridge?.apiFetch) return window.VCBridge.apiFetch(path, options);
    const res = await fetch(path, {
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
      ...options,
    });
    if (!res.ok) {
      let detail = res.statusText;
      try {
        const body = await res.json();
        detail = body.detail || body.message || detail;
      } catch (_) {}
      throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
    }
    return res.json();
  }

  function escapeHtml(text) {
    if (window.VCBridge?.escapeHtml) return window.VCBridge.escapeHtml(text);
    return String(text || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  function formatCost(value, currency = "CNY") {
    if (window.VCBridge?.formatCost) return window.VCBridge.formatCost(value, currency);
    if (value == null || Number.isNaN(value)) return "—";
    return `${Number(value).toFixed(4)} ${currency}`;
  }

  function statusLabel(status) {
    return (
      {
        ready: "待开始",
        running: "分析中",
        paused: "可继续",
        completed: "已完成",
        failed: "失败",
        cancelled: "已取消",
      }[status] || status || "—"
    );
  }

  function formatRunLabel(runId, configName) {
    return configName && configName !== runId ? `${configName}（${runId}）` : runId;
  }

  function getApiKey() {
    const local = outreachApiKey?.value?.trim() || "";
    if (local) {
      sessionStorage.setItem(API_KEY_STORAGE, local);
      return local;
    }
    return sessionStorage.getItem(API_KEY_STORAGE) || "";
  }

  function loadStoredApiKey() {
    if (!outreachApiKey) return;
    const stored = sessionStorage.getItem(API_KEY_STORAGE);
    if (stored && !outreachApiKey.value) outreachApiKey.value = stored;
  }

  function updateExportLinks(runId) {
    const hasCandidates = (state.candidatesDoc?.candidates || []).length > 0;
    const hasOutreach = (state.outreachDoc?.entries || []).length > 0;
    if (btnOutreachExportCandidates) {
      btnOutreachExportCandidates.hidden = !runId || !hasCandidates;
      if (runId && hasCandidates) {
        btnOutreachExportCandidates.href = `/api/analysis/runs/${encodeURIComponent(runId)}/export/candidates.csv`;
        btnOutreachExportCandidates.download = `${runId}_candidates.csv`;
      }
    }
    if (btnOutreachExportOutreach) {
      btnOutreachExportOutreach.hidden = !runId || !hasOutreach;
      if (runId && hasOutreach) {
        btnOutreachExportOutreach.href = `/api/analysis/runs/${encodeURIComponent(runId)}/export/outreach.csv`;
        btnOutreachExportOutreach.download = `${runId}_outreach.csv`;
      }
    }
    const paths = state.exportPaths || {};
    if (outreachExportHint) {
      const lines = [];
      if (paths.candidates_csv) lines.push(`· data/${paths.candidates_csv}`);
      if (paths.outreach_csv) lines.push(`· data/${paths.outreach_csv}`);
      if (lines.length) {
        outreachExportHint.hidden = false;
        outreachExportHint.innerHTML = `已自动保存：<br>${lines.map(escapeHtml).join("<br>")}`;
      } else {
        outreachExportHint.hidden = true;
        outreachExportHint.textContent = "";
      }
    }
  }

  async function loadRunHistory() {
    try {
      const data = await apiFetch("/api/analysis/runs");
      const runs = data.runs || [];
      const current = state.currentRunId;
      if (!outreachRunHistory) return;
      outreachRunHistory.innerHTML =
        '<option value="">— 选择已有分析任务 —</option>' +
        runs
          .map((run) => {
            const label = `${run.name || run.run_id} · ${run.completed}/${run.total_records} · ${statusLabel(run.status)}`;
            const selected = run.run_id === current ? " selected" : "";
            return `<option value="${escapeHtml(run.run_id)}"${selected}>${escapeHtml(label)}</option>`;
          })
          .join("");
    } catch {
      /* ignore */
    }
  }

  async function activate() {
    loadStoredApiKey();
    await loadRunHistory();
    const preferred =
      state.currentRunId ||
      sessionStorage.getItem(RUN_ID_STORAGE) ||
      sessionStorage.getItem(SHARED_RUN_HINT) ||
      "";
    if (preferred && outreachRunHistory) {
      outreachRunHistory.value = preferred;
      if (outreachRunHistory.value === preferred) {
        await selectRun(preferred);
      } else if (outreachRunStatus) {
        outreachRunStatus.textContent = "请从下拉列表选择一个已完成分析的任务";
        outreachRunStatus.className = "inline-status";
      }
    }
  }

  async function selectRun(runId) {
    if (!runId) return;
    state.currentRunId = runId;
    sessionStorage.setItem(RUN_ID_STORAGE, runId);
    if (outreachRunStatus) {
      outreachRunStatus.textContent = "加载任务中…";
      outreachRunStatus.className = "inline-status loading";
    }
    try {
      const data = await apiFetch(`/api/analysis/runs/${encodeURIComponent(runId)}`);
      const completed = data.progress?.completed || 0;
      if (completed <= 0) {
        outreachRunStatus.textContent = "该任务尚无分析结果，请先在「评论洞察」完成分析";
        outreachRunStatus.className = "inline-status error";
        state.candidatesDoc = null;
        state.outreachDoc = null;
        renderCandidatesPanel();
        return;
      }
      const targets = (data.config?.research_targets || []).join("、");
      if (outreachResearchTargets) outreachResearchTargets.value = targets;
      state.exportPaths = data.export_paths || data.summary?.export_paths || {};
      state.candidatesDoc = null;
      state.outreachDoc = null;
      await loadOutreachData(runId, data);
      outreachRunStatus.textContent = `已关联：${formatRunLabel(runId, data.config?.name)} · 已分析 ${completed} 条`;
      outreachRunStatus.className = "inline-status success";
    } catch (err) {
      outreachRunStatus.textContent = `加载失败：${err.message}`;
      outreachRunStatus.className = "inline-status error";
    }
  }

  async function loadOutreachData(runId, runMeta) {
    const [candidates, outreach] = await Promise.all([
      apiFetch(`/api/analysis/runs/${encodeURIComponent(runId)}/candidates`),
      apiFetch(`/api/analysis/runs/${encodeURIComponent(runId)}/outreach`),
    ]);
    state.candidatesDoc = candidates || null;
    state.outreachDoc = outreach || null;
    applyReplyControl(outreach?.reply_control);
    state.defaultOutreachTemplate = runMeta?.default_outreach_template || "";
    if (outreachTemplate && !outreachTemplate.value.trim() && state.defaultOutreachTemplate) {
      outreachTemplate.value = state.defaultOutreachTemplate;
    }
    updateExportLinks(runId);
    await loadCandidatesPage(1);
    try {
      const status = await apiFetch(`/api/analysis/runs/${encodeURIComponent(runId)}/outreach/reply/status`);
      renderReplyStatus(status);
      if (status.is_running) startReplyPolling();
    } catch (_) {
      /* status is best-effort */
    }
  }

  async function saveTargets() {
    if (!state.currentRunId) {
      outreachTargetsStatus.textContent = "请先选择分析任务";
      outreachTargetsStatus.className = "inline-status error";
      return;
    }
    const text = outreachResearchTargets?.value?.trim() || "";
    outreachTargetsStatus.textContent = "保存中…";
    outreachTargetsStatus.className = "inline-status loading";
    try {
      await apiFetch(`/api/analysis/runs/${encodeURIComponent(state.currentRunId)}/config`, {
        method: "PATCH",
        body: JSON.stringify({ research_targets: text }),
      });
      let msg = "目标人群已保存。请点击「筛选值得回复的用户」重新匹配，否则列表仍是旧目标。";
      if (state.candidatesDoc?.candidates?.length) {
        msg += `（当前列表 ${state.candidatesDoc.candidates.length} 人可能已过期）`;
      }
      outreachTargetsStatus.textContent = msg;
      outreachTargetsStatus.className = "inline-status success";
    } catch (err) {
      outreachTargetsStatus.textContent = `保存失败：${err.message}`;
      outreachTargetsStatus.className = "inline-status error";
    }
  }

  function getOutreachEntry(userKey) {
    return (state.outreachDoc?.entries || []).find((entry) => entry.user_key === userKey);
  }

  function buildCandidatesQueryParams(page) {
    const f = state.candidateFilters;
    const params = new URLSearchParams();
    params.set("page", String(page || state.candidatesPage.page || 1));
    params.set("page_size", String(state.candidatesPage.pageSize || 50));
    if (f.priority) params.set("priority", f.priority);
    if (f.contactability) params.set("contactability", f.contactability);
    if (f.contact_status) params.set("contact_status", f.contact_status);
    if (f.research_matched) params.set("research_matched", f.research_matched);
    return params;
  }

  function renderPager(container, pageState, onPage) {
    if (!container) return;
    const totalPages = Math.max(1, Math.ceil((pageState.total || 0) / (pageState.pageSize || 1)));
    if ((pageState.total || 0) <= (pageState.pageSize || 50)) {
      container.hidden = true;
      container.innerHTML = "";
      return;
    }
    container.hidden = false;
    container.innerHTML = `
      <button type="button" class="btn ghost sm" data-page="${pageState.page - 1}" ${pageState.page <= 1 ? "disabled" : ""}>上一页</button>
      <span class="hint">第 ${pageState.page} / ${totalPages} 页 · 共 ${pageState.total.toLocaleString()} 条</span>
      <button type="button" class="btn ghost sm" data-page="${pageState.page + 1}" ${pageState.page >= totalPages ? "disabled" : ""}>下一页</button>`;
    container.querySelectorAll("[data-page]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const next = Number(btn.getAttribute("data-page"));
        if (next >= 1 && next <= totalPages) onPage(next);
      });
    });
  }

  async function loadCandidatesPage(page = 1) {
    if (!state.currentRunId) return;
    if (!(state.candidatesDoc?.total_candidates || state.candidatesDoc?.candidates?.length)) {
      renderCandidatesPanel();
      return;
    }
    state.candidatesPage.page = page;
    const params = buildCandidatesQueryParams(page);
    const data = await apiFetch(
      `/api/analysis/runs/${encodeURIComponent(state.currentRunId)}/candidates/items?${params.toString()}`
    );
    state.candidatesPage = {
      page: data.page || page,
      pageSize: data.page_size || state.candidatesPage.pageSize,
      total: data.total || 0,
      items: data.items || [],
    };
    renderCandidatesPanel();
  }

  function renderCandidatesPanel() {
    if (!outreachCandidatesPanel) return;
    const allCount = state.candidatesDoc?.total_candidates || state.candidatesDoc?.candidates?.length || 0;
    const visible = state.candidatesPage.items || [];
    if (!allCount) {
      outreachCandidatesPanel.innerHTML =
        '<p class="hint">暂无值得回复的用户。请先在「评论洞察」完成分析，再点击「筛选值得回复的用户」。</p>';
      if (outreachCandidateSelectAll) outreachCandidateSelectAll.checked = false;
      if (outreachCandidatesPager) {
        outreachCandidatesPager.hidden = true;
        outreachCandidatesPager.innerHTML = "";
      }
      return;
    }

    const meta = state.candidatesDoc?.generated_at
      ? `<p class="hint">共 ${allCount} 位用户 · 当前页 ${visible.length} 位 · 已选 ${state.selectedCandidateKeys.size} 位</p>`
      : "";
    if (!visible.length) {
      outreachCandidatesPanel.innerHTML = meta + '<p class="hint center">无符合筛选条件的用户</p>';
      renderPager(outreachCandidatesPager, state.candidatesPage, loadCandidatesPage);
      return;
    }

    const cards = visible
      .map((candidate) => {
        const checked = state.selectedCandidateKeys.has(candidate.user_key);
        const outreach = getOutreachEntry(candidate.user_key);
        const draft = outreach?.edited_content || outreach?.generated_draft || "";
        const userLabel = candidate.username || candidate.user_key;
        const homepageLink = candidate.homepage_url
          ? `<button type="button" class="btn ghost sm outreach-link-btn" data-href="${escapeHtml(candidate.homepage_url)}">打开主页</button>`
          : "";
        const commentLink = candidate.comment_urls?.[0]
          ? `<button type="button" class="btn ghost sm outreach-link-btn" data-href="${escapeHtml(candidate.comment_urls[0])}">查看评论</button>`
          : "";
        const researchBadges = (candidate.research_target_matches || [])
          .map((tag) => `<span class="insight-tag insight-research-tag">${escapeHtml(tag)}</span>`)
          .join("");
        const quotes = (candidate.representative_quotes || [])
          .map((q) => `<li>${escapeHtml(q)}</li>`)
          .join("");
        const problems = (candidate.specific_problems || []).join("；") || "—";
        const statusOptions = Object.entries(CONTACT_STATUS_LABELS)
          .map(
            ([value, label]) =>
              `<option value="${value}"${value === candidate.contact_status ? " selected" : ""}>${label}</option>`
          )
          .join("");
        return `<article class="insight-candidate-card" data-user-key="${escapeHtml(candidate.user_key)}">
          <header class="insight-candidate-head">
            <label class="insight-candidate-check">
              <input type="checkbox" class="outreach-candidate-select" data-user-key="${escapeHtml(candidate.user_key)}" ${checked ? "checked" : ""} />
              <strong class="insight-candidate-name">${escapeHtml(userLabel)}</strong>
            </label>
            <div class="insight-candidate-badges">
              ${researchBadges}
              <span class="insight-priority-badge priority-${escapeHtml(candidate.priority)}">${escapeHtml(PRIORITY_LABELS[candidate.priority] || candidate.priority)} · ${candidate.candidate_score} 分</span>
              <span class="insight-contactability-badge contactability-${escapeHtml(candidate.contactability)}">${escapeHtml(CONTACTABILITY_LABELS[candidate.contactability] || candidate.contactability)}</span>
            </div>
          </header>
          <p class="insight-candidate-reason">${escapeHtml(candidate.contact_reason || "—")}</p>
          ${
            (candidate.score_breakdown || []).length
              ? `<details class="insight-score-details"><summary>评分参考（非付费意愿）</summary><p class="hint insight-score-breakdown">${escapeHtml(candidate.score_breakdown.join(" · "))}</p></details>`
              : ""
          }
          <div class="insight-candidate-meta">
            <span>平台 ${escapeHtml(candidate.platform || "—")}</span>
            <span>评论 ${candidate.record_ids?.length || 0} 条</span>
            <span>适配 ${escapeHtml(PRODUCT_FIT_LABELS[candidate.product_fit] || candidate.product_fit || "—")}</span>
            ${candidate.help_seeking ? '<span class="insight-tag">主动求助</span>' : ""}
          </div>
          <p class="hint insight-candidate-problems">具体问题：${escapeHtml(problems)}</p>
          ${quotes ? `<ul class="insight-candidate-quotes">${quotes}</ul>` : ""}
          <div class="insight-candidate-links">${homepageLink} ${commentLink}</div>
          <div class="insight-candidate-status-row">
            <label>联系状态
              <select class="outreach-candidate-status" data-user-key="${escapeHtml(candidate.user_key)}">${statusOptions}</select>
            </label>
            <label class="insight-candidate-note-field">备注
              <input type="text" class="outreach-candidate-note" data-user-key="${escapeHtml(candidate.user_key)}" value="${escapeHtml(candidate.product_manager_note || "")}" placeholder="产品经理备注…" />
            </label>
          </div>
          ${
            draft
              ? (() => {
                  const review = outreach?.review_status || "draft";
                  const send = outreach?.send_status || "pending";
                  const reviewLabel = REVIEW_STATUS_LABELS[review] || review;
                  const sendLabel = SEND_STATUS_LABELS[send] || send;
                  const errorHint =
                    send === "failed" && outreach?.send_error
                      ? `<span class="hint insight-send-error">发送失败：${escapeHtml(outreach.send_error)}</span>`
                      : "";
                  return `<div class="insight-outreach-block">
              <label>回复内容（可编辑；<strong>审核通过</strong>后才会进入发送队列）
                <textarea class="outreach-draft" data-user-key="${escapeHtml(candidate.user_key)}" rows="4">${escapeHtml(draft)}</textarea>
              </label>
              <div class="insight-outreach-actions">
                <button type="button" class="btn ${review === "approved" ? "primary" : "secondary"} sm outreach-review-btn" data-user-key="${escapeHtml(candidate.user_key)}" data-review="approved">${review === "approved" ? "已通过 ✓" : "审核通过"}</button>
                <button type="button" class="btn ghost sm outreach-review-btn" data-user-key="${escapeHtml(candidate.user_key)}" data-review="rejected">不回复</button>
                <button type="button" class="btn ghost sm outreach-draft-copy" data-user-key="${escapeHtml(candidate.user_key)}">复制</button>
                <span class="hint">审核：${escapeHtml(reviewLabel)} · 发送：${escapeHtml(sendLabel)}${outreach?.sent_at ? ` （${escapeHtml(outreach.sent_at)}）` : ""}${outreach?.cost ? ` · 费用 ${formatCost(outreach.cost, outreach.currency || "CNY")}` : ""}</span>
              </div>
              ${errorHint}
            </div>`;
                })()
              : ""
          }
        </article>`;
      })
      .join("");
    outreachCandidatesPanel.innerHTML = meta + `<div class="insight-candidate-list">${cards}</div>`;
    renderPager(outreachCandidatesPager, state.candidatesPage, loadCandidatesPage);

    if (outreachCandidateSelectAll) {
      const allVisibleSelected =
        visible.length > 0 && visible.every((c) => state.selectedCandidateKeys.has(c.user_key));
      outreachCandidateSelectAll.checked = allVisibleSelected;
    }
  }

  async function buildCandidates() {
    if (!state.currentRunId) {
      outreachCandidatesStatus.textContent = "请先选择分析任务";
      outreachCandidatesStatus.className = "inline-status error";
      return;
    }
    btnOutreachBuildCandidates.disabled = true;
    outreachCandidatesStatus.textContent = "正在筛选值得回复的用户…";
    outreachCandidatesStatus.className = "inline-status loading";
    try {
      const doc = await apiFetch(`/api/analysis/runs/${encodeURIComponent(state.currentRunId)}/candidates/build`, {
        method: "POST",
        body: JSON.stringify({}),
      });
      state.candidatesDoc = doc;
      state.exportPaths = { ...(state.exportPaths || {}), ...(doc.export_paths || {}) };
      state.selectedCandidateKeys.clear();
      await loadCandidatesPage(1);
      updateExportLinks(state.currentRunId);
      const highCount = (doc.candidates || []).filter((c) => c.priority === "high").length;
      outreachCandidatesStatus.textContent = `完成：${doc.total_candidates || 0} 位用户，其中 ${highCount} 位高优先`;
      outreachCandidatesStatus.className = "inline-status success";
    } catch (err) {
      outreachCandidatesStatus.textContent = `生成失败：${err.message}`;
      outreachCandidatesStatus.className = "inline-status error";
    } finally {
      btnOutreachBuildCandidates.disabled = false;
    }
  }

  async function generateOutreach() {
    if (!state.currentRunId) {
      outreachCandidatesStatus.textContent = "请先选择分析任务";
      outreachCandidatesStatus.className = "inline-status error";
      return;
    }
    const keys = Array.from(state.selectedCandidateKeys);
    if (!keys.length) {
      outreachCandidatesStatus.textContent = "请先勾选要生成回复的用户";
      outreachCandidatesStatus.className = "inline-status error";
      return;
    }
    const apiKey = getApiKey();
    if (!apiKey) {
      outreachCandidatesStatus.textContent = "请填写 API Key（本板块或「评论洞察」均可）";
      outreachCandidatesStatus.className = "inline-status error";
      return;
    }
    btnOutreachGenerate.disabled = true;
    outreachCandidatesStatus.textContent = `正在为 ${keys.length} 位用户按各自意图生成回复草稿…`;
    outreachCandidatesStatus.className = "inline-status loading";
    try {
      const doc = await apiFetch(`/api/analysis/runs/${encodeURIComponent(state.currentRunId)}/outreach/generate`, {
        method: "POST",
        body: JSON.stringify({
          user_keys: keys,
          base_template: outreachTemplate?.value?.trim() || state.defaultOutreachTemplate || "",
          api_key: apiKey,
          use_mock: false,
        }),
      });
      state.outreachDoc = doc;
      state.exportPaths = { ...(state.exportPaths || {}), ...(doc.export_paths || {}) };
      const candidates = await apiFetch(`/api/analysis/runs/${encodeURIComponent(state.currentRunId)}/candidates`);
      state.candidatesDoc = candidates;
      await loadCandidatesPage(state.candidatesPage.page || 1);
      updateExportLinks(state.currentRunId);
      outreachCandidatesStatus.textContent = `完成：已为 ${keys.length} 位用户生成回复内容，请逐条审核「通过 / 不回复」后再开始受控回复`;
      outreachCandidatesStatus.className = "inline-status success";
    } catch (err) {
      outreachCandidatesStatus.textContent = `生成失败：${err.message}`;
      outreachCandidatesStatus.className = "inline-status error";
    } finally {
      btnOutreachGenerate.disabled = false;
    }
  }

  async function saveCandidateNote(userKey, note) {
    if (!state.currentRunId || !userKey) return;
    try {
      await apiFetch(`/api/analysis/runs/${encodeURIComponent(state.currentRunId)}/candidates/${encodeURIComponent(userKey)}`, {
        method: "PATCH",
        body: JSON.stringify({ product_manager_note: note }),
      });
      const candidate = (state.candidatesDoc?.candidates || []).find((c) => c.user_key === userKey);
      if (candidate) candidate.product_manager_note = note;
    } catch (err) {
      outreachCandidatesStatus.textContent = `保存备注失败：${err.message}`;
      outreachCandidatesStatus.className = "inline-status error";
    }
  }

  async function saveCandidateStatus(userKey, status) {
    if (!state.currentRunId || !userKey) return;
    try {
      await apiFetch(`/api/analysis/runs/${encodeURIComponent(state.currentRunId)}/candidates/${encodeURIComponent(userKey)}`, {
        method: "PATCH",
        body: JSON.stringify({ contact_status: status }),
      });
      const candidate = (state.candidatesDoc?.candidates || []).find((c) => c.user_key === userKey);
      if (candidate) candidate.contact_status = status;
    } catch (err) {
      outreachCandidatesStatus.textContent = `更新状态失败：${err.message}`;
      outreachCandidatesStatus.className = "inline-status error";
    }
  }

  async function saveOutreachDraft(userKey, content) {
    if (!state.currentRunId || !userKey) return;
    try {
      await apiFetch(`/api/analysis/runs/${encodeURIComponent(state.currentRunId)}/outreach/${encodeURIComponent(userKey)}`, {
        method: "PATCH",
        body: JSON.stringify({ edited_content: content }),
      });
      const entry = getOutreachEntry(userKey);
      if (entry) entry.edited_content = content;
    } catch (err) {
      outreachCandidatesStatus.textContent = `保存草稿失败：${err.message}`;
      outreachCandidatesStatus.className = "inline-status error";
    }
  }

  function copyOutreachDraft(userKey) {
    const entry = getOutreachEntry(userKey);
    const textarea = outreachCandidatesPanel?.querySelector(`.outreach-draft[data-user-key="${CSS.escape(userKey)}"]`);
    const text = textarea?.value || entry?.edited_content || entry?.generated_draft || "";
    if (!text) return;
    navigator.clipboard.writeText(text).then(
      () => {
        outreachCandidatesStatus.textContent = "已复制到剪贴板";
        outreachCandidatesStatus.className = "inline-status success";
      },
      () => {
        outreachCandidatesStatus.textContent = "复制失败，请手动选择文本";
        outreachCandidatesStatus.className = "inline-status error";
      }
    );
  }

  async function reviewOutreach(userKey, status) {
    if (!state.currentRunId || !userKey) return;
    const textarea = outreachCandidatesPanel?.querySelector(`.outreach-draft[data-user-key="${CSS.escape(userKey)}"]`);
    const body = { review_status: status };
    if (textarea) body.edited_content = textarea.value;
    try {
      const entry = await apiFetch(
        `/api/analysis/runs/${encodeURIComponent(state.currentRunId)}/outreach/${encodeURIComponent(userKey)}`,
        { method: "PATCH", body: JSON.stringify(body) }
      );
      const existing = getOutreachEntry(userKey);
      if (existing) Object.assign(existing, entry);
      const labels = { approved: "已通过，待发送", rejected: "已标记为不回复" };
      outreachCandidatesStatus.textContent = labels[status] || "已更新";
      outreachCandidatesStatus.className = "inline-status success";
      renderCandidatesPanel();
    } catch (err) {
      outreachCandidatesStatus.textContent = `审核失败：${err.message}`;
      outreachCandidatesStatus.className = "inline-status error";
    }
  }

  async function refreshOutreachDoc() {
    if (!state.currentRunId) return;
    state.outreachDoc = await apiFetch(
      `/api/analysis/runs/${encodeURIComponent(state.currentRunId)}/outreach`
    );
  }

  function getReplyControlInput() {
    return {
      interval_seconds: Number(outreachIntervalSeconds?.value || 90),
      jitter_seconds: Number(outreachJitterSeconds?.value || 20),
      daily_limit: Number(outreachDailyLimit?.value || 30),
      time_window_start: outreachWindowStart?.value || "09:00",
      time_window_end: outreachWindowEnd?.value || "22:00",
    };
  }

  function applyReplyControl(control) {
    if (!control) return;
    if (outreachIntervalSeconds && control.interval_seconds != null) outreachIntervalSeconds.value = control.interval_seconds;
    if (outreachJitterSeconds && control.jitter_seconds != null) outreachJitterSeconds.value = control.jitter_seconds;
    if (outreachDailyLimit && control.daily_limit != null) outreachDailyLimit.value = control.daily_limit;
    if (outreachWindowStart && control.time_window_start) outreachWindowStart.value = control.time_window_start;
    if (outreachWindowEnd && control.time_window_end) outreachWindowEnd.value = control.time_window_end;
  }

  function renderReplyStatus(data) {
    state.replyRunning = Boolean(data?.is_running);
    if (btnOutreachStartReply) btnOutreachStartReply.disabled = state.replyRunning;
    if (btnOutreachStopReply) btnOutreachStopReply.disabled = !state.replyRunning;
    if (!outreachReplyStatus) return;
    const counts = data?.send_status_counts || {};
    const summary = Object.entries(SEND_STATUS_LABELS)
      .filter(([key]) => counts[key])
      .map(([key, label]) => `${label} ${counts[key]}`)
      .join(" · ");
    const parts = [data?.reply_message || "—"];
    if (data?.replies_sent_today != null) parts.push(`今日已发 ${data.replies_sent_today}`);
    if (summary) parts.push(summary);
    outreachReplyStatus.textContent = parts.join(" ｜ ");
    outreachReplyStatus.className = `inline-status ${data?.is_running ? "loading" : ""}`.trim();
  }

  async function pollReplyStatus() {
    if (!state.currentRunId) return;
    try {
      const data = await apiFetch(
        `/api/analysis/runs/${encodeURIComponent(state.currentRunId)}/outreach/reply/status`
      );
      renderReplyStatus(data);
      await refreshOutreachDoc();
      renderCandidatesPanel();
      if (!data.is_running) stopReplyPolling();
    } catch (err) {
      if (outreachReplyStatus) {
        outreachReplyStatus.textContent = `获取回复状态失败：${err.message}`;
        outreachReplyStatus.className = "inline-status error";
      }
      stopReplyPolling();
    }
  }

  function startReplyPolling() {
    if (state.replyPollTimer) return;
    state.replyPollTimer = setInterval(pollReplyStatus, 5000);
    pollReplyStatus();
  }

  function stopReplyPolling() {
    if (state.replyPollTimer) {
      clearInterval(state.replyPollTimer);
      state.replyPollTimer = null;
    }
  }

  async function startReplyRun() {
    if (!state.currentRunId) {
      outreachReplyStatus.textContent = "请先选择分析任务";
      outreachReplyStatus.className = "inline-status error";
      return;
    }
    const approved = (state.outreachDoc?.entries || []).filter(
      (e) => e.review_status === "approved" && (e.edited_content || e.generated_draft || "").trim()
    );
    if (!approved.length) {
      outreachReplyStatus.textContent = "没有已审核通过的回复；请先在上方对每条内容点击「审核通过」";
      outreachReplyStatus.className = "inline-status error";
      return;
    }
    const control = getReplyControlInput();
    if (!window.confirm(`将按受控节奏发送 ${approved.length} 条已审核回复：\n最小间隔 ${control.interval_seconds}s，每日上限 ${control.daily_limit} 条，允许时段 ${control.time_window_start}–${control.time_window_end}。\n确定开始吗？`)) {
      return;
    }
    btnOutreachStartReply.disabled = true;
    outreachReplyStatus.textContent = "正在启动受控回复…";
    outreachReplyStatus.className = "inline-status loading";
    try {
      const doc = await apiFetch(
        `/api/analysis/runs/${encodeURIComponent(state.currentRunId)}/outreach/reply/start`,
        { method: "POST", body: JSON.stringify(control) }
      );
      state.outreachDoc = doc;
      applyReplyControl(doc.reply_control);
      renderCandidatesPanel();
      startReplyPolling();
    } catch (err) {
      outreachReplyStatus.textContent = `启动失败：${err.message}`;
      outreachReplyStatus.className = "inline-status error";
      btnOutreachStartReply.disabled = false;
    }
  }

  async function stopReplyRun() {
    if (!state.currentRunId) return;
    btnOutreachStopReply.disabled = true;
    try {
      const doc = await apiFetch(
        `/api/analysis/runs/${encodeURIComponent(state.currentRunId)}/outreach/reply/stop`,
        { method: "POST", body: JSON.stringify({}) }
      );
      state.outreachDoc = doc;
      await pollReplyStatus();
    } catch (err) {
      outreachReplyStatus.textContent = `停止失败：${err.message}`;
      outreachReplyStatus.className = "inline-status error";
    }
  }

  function toggleCandidateSelection(userKey, checked) {
    if (!userKey) return;
    if (checked) state.selectedCandidateKeys.add(userKey);
    else state.selectedCandidateKeys.delete(userKey);
    renderCandidatesPanel();
  }

  function toggleAllVisibleCandidates(checked) {
    (state.candidatesPage.items || []).forEach((candidate) => {
      if (checked) state.selectedCandidateKeys.add(candidate.user_key);
      else state.selectedCandidateKeys.delete(candidate.user_key);
    });
    renderCandidatesPanel();
  }

  // —— 事件 ——
  outreachRunHistory?.addEventListener("change", (event) => {
    const runId = event.target.value;
    if (runId) selectRun(runId);
  });
  btnOutreachSaveTargets?.addEventListener("click", saveTargets);
  btnOutreachBuildCandidates?.addEventListener("click", buildCandidates);
  btnOutreachGenerate?.addEventListener("click", generateOutreach);
  btnOutreachStartReply?.addEventListener("click", startReplyRun);
  btnOutreachStopReply?.addEventListener("click", stopReplyRun);
  outreachApiKey?.addEventListener("change", () => {
    const v = outreachApiKey.value.trim();
    if (v) sessionStorage.setItem(API_KEY_STORAGE, v);
  });
  outreachCandidateFilterResearch?.addEventListener("change", (e) => {
    state.candidateFilters.research_matched = e.target.value;
    loadCandidatesPage(1);
  });
  outreachCandidateFilterPriority?.addEventListener("change", (e) => {
    state.candidateFilters.priority = e.target.value;
    loadCandidatesPage(1);
  });
  outreachCandidateFilterContactability?.addEventListener("change", (e) => {
    state.candidateFilters.contactability = e.target.value;
    loadCandidatesPage(1);
  });
  outreachCandidateFilterStatus?.addEventListener("change", (e) => {
    state.candidateFilters.contact_status = e.target.value;
    loadCandidatesPage(1);
  });
  outreachCandidateSelectAll?.addEventListener("change", (e) => {
    toggleAllVisibleCandidates(e.target.checked);
  });

  document.addEventListener("click", (event) => {
    if (!outreachView || outreachView.hidden) return;
    const copyBtn = event.target.closest(".outreach-draft-copy");
    if (copyBtn && outreachView.contains(copyBtn)) {
      copyOutreachDraft(copyBtn.getAttribute("data-user-key"));
      return;
    }
    const reviewBtn = event.target.closest(".outreach-review-btn");
    if (reviewBtn && outreachView.contains(reviewBtn)) {
      reviewOutreach(reviewBtn.getAttribute("data-user-key"), reviewBtn.getAttribute("data-review"));
      return;
    }
    const linkBtn = event.target.closest(".outreach-link-btn");
    if (linkBtn && outreachView.contains(linkBtn)) {
      const href = linkBtn.getAttribute("data-href");
      if (href) window.open(href, "_blank", "noopener");
    }
  });

  outreachCandidatesPanel?.addEventListener("change", (event) => {
    const selectInput = event.target.closest(".outreach-candidate-select");
    if (selectInput) {
      toggleCandidateSelection(selectInput.getAttribute("data-user-key"), selectInput.checked);
      return;
    }
    const statusSelect = event.target.closest(".outreach-candidate-status");
    if (statusSelect) {
      saveCandidateStatus(statusSelect.getAttribute("data-user-key"), statusSelect.value);
    }
  });

  outreachCandidatesPanel?.addEventListener(
    "blur",
    (event) => {
      const noteInput = event.target.closest(".outreach-candidate-note");
      if (noteInput) {
        saveCandidateNote(noteInput.getAttribute("data-user-key"), noteInput.value);
        return;
      }
      const draftInput = event.target.closest(".outreach-draft");
      if (draftInput) {
        saveOutreachDraft(draftInput.getAttribute("data-user-key"), draftInput.value);
      }
    },
    true
  );

  // 第二板块切到本板块时激活；不反向驱动洞察
  window.addEventListener("vc:stage-change", (event) => {
    if (event.detail?.stage === "outreach") activate();
  });

  window.VCOutreach = { activate, selectRun };

  loadStoredApiKey();
})();
