(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);

  const setupView = $("setupView");
  const workspace = $("workspace");
  const insightView = $("insightView");
  const stageTabCollect = $("stageTabCollect");
  const stageTabInsight = $("stageTabInsight");
  const stageTabOutreach = $("stageTabOutreach");
  const outreachView = $("outreachView");
  const btnBackSetup = $("btnBackSetup");

  const insightSourceList = $("insightSourceList");
  const insightSourceStatus = $("insightSourceStatus");
  const insightSourceSearch = $("insightSourceSearch");
  const insightSelectionSummary = $("insightSelectionSummary");
  const btnInsightRefreshSources = $("btnInsightRefreshSources");
  const btnInsightSelectVisible = $("btnInsightSelectVisible");
  const btnInsightClearSelection = $("btnInsightClearSelection");
  const insightRunName = $("insightRunName");
  const insightRunHistory = $("insightRunHistory");
  const insightBaseUrl = $("insightBaseUrl");
  const insightModelName = $("insightModelName");
  const insightApiKey = $("insightApiKey");
  const insightBudgetLimit = $("insightBudgetLimit");
  const btnInsightVerifyModel = $("btnInsightVerifyModel");
  const insightVerifyStatus = $("insightVerifyStatus");
  const btnInsightStartRun = $("btnInsightStartRun");
  const btnInsightRetryFailed = $("btnInsightRetryFailed");
  const btnInsightStopRun = $("btnInsightStopRun");
  const insightProgressWrap = $("insightProgressWrap");
  const insightProgressFill = $("insightProgressFill");
  const insightProgressLabel = $("insightProgressLabel");
  const insightCompletionSummary = $("insightCompletionSummary");
  const insightExportPlaceholder = $("insightExportPlaceholder");
  const insightRunStatus = $("insightRunStatus");
  const insightRunHint = $("insightRunHint");
  const insightRunId = $("insightRunId");
  const insightTotal = $("insightTotal");
  const insightCompleted = $("insightCompleted");
  const insightStatus = $("insightStatus");
  const insightElapsed = $("insightElapsed");
  const insightFailed = $("insightFailed");
  const insightErrorSummary = $("insightErrorSummary");
  const insightPromptTokens = $("insightPromptTokens");
  const insightCacheHitTokens = $("insightCacheHitTokens");
  const insightCompletionTokens = $("insightCompletionTokens");
  const insightCost = $("insightCost");
  const insightCostProjection = $("insightCostProjection");
  const insightOverview = $("insightOverview");
  const insightContradictions = $("insightContradictions");
  const insightDashboard = $("insightDashboard");
  const btnInsightClusterThemes = $("btnInsightClusterThemes");
  const insightThemesPanel = $("insightThemesPanel");
  const insightThemesStatus = $("insightThemesStatus");
  const insightResultsTable = $("insightResultsTable");
  const insightResultsPager = $("insightResultsPager");
  const insightResearchCard = $("insightResearchCard");
  const insightResearchReport = $("insightResearchReport");
  const insightFilterKeyword = $("insightFilterKeyword");
  const insightFilterIntent = $("insightFilterIntent");
  const insightFilterVideo = $("insightFilterVideo");
  const insightFilterFit = $("insightFilterFit");
  const insightFilterHypothesis = $("insightFilterHypothesis");
  const insightFilterStatus = $("insightFilterStatus");
  const btnInsightClearFilters = $("btnInsightClearFilters");

  const API_KEY_STORAGE = "vc_insight_api_key";

  const EVIDENCE_TYPE_LABELS = {
    problem: "问题",
    behavior: "行为",
    result: "结果",
    context: "背景",
    solution: "方案",
    barrier: "障碍",
    action_gap: "行动差距",
    engagement: "互动",
    opinion: "观点",
    quantitative: "量化",
  };

  const RECORD_STATUS_LABELS = {
    usable: "可用",
    off_topic: "跑题",
    machine_generated: "机器生成",
    spam: "垃圾",
    garbled: "乱码",
    unclear: "不清",
  };

  const EXPRESSION_LABELS = {
    question: "提问",
    help_request: "求助",
    complaint: "抱怨",
    result_feedback: "结果反馈",
    check_in: "打卡",
    praise: "赞赏",
    other: "其他",
  };

  const state = {
    selectedPaths: new Set(),
    currentRunId: null,
    groups: [],
    totalFiles: 0,
    totalComments: 0,
    searchQuery: "",
    expandedCategories: new Set(),
    expandedCreators: new Set(),
    useMock: false,
    currentRunUseMock: false,
    currentRunStatus: "",
    pollTimer: null,
    pollBusy: false,
    lastProgress: {},
    allResults: [],
    resultsPage: { page: 1, pageSize: 100, total: 0, items: [] },
    evidenceMode: false,
    evidencePage: { page: 1, pageSize: 50, total: 0, items: [] },
    themesDoc: null,
    filters: {
      keyword: "",
      intent: "",
      intent_valid: "",
      video: "",
      fit: "",
      hypothesis: "",
      signal: "",
      themeRecordIds: null,
    },
  };

  const POLL_INTERVAL_MS = 5000;
  const RUN_ID_STORAGE = "vc_insight_current_run_id";

  function getAnalysisLimit() {
    const checked = document.querySelector('input[name="insightAnalysisLimit"]:checked');
    return Number(checked?.value ?? 100);
  }

  function setAnalysisLimit(value) {
    const limit = value == null ? 100 : Number(value);
    const input = document.querySelector(`input[name="insightAnalysisLimit"][value="${limit}"]`);
    if (input) input.checked = true;
  }

  function getAnalyzeBody() {
    return { background: true, api_key: getApiKey() };
  }

  function requireApiKey() {
    if (!getApiKey()) {
      insightRunStatus.textContent = "请先填写 API Key";
      insightRunStatus.className = "inline-status error";
      return false;
    }
    return true;
  }

  function computeElapsedSeconds(progress, active) {
    if (!progress?.started_at) return null;
    const started = Date.parse(progress.started_at);
    if (Number.isNaN(started)) return null;
    if (!active && progress.updated_at) {
      const updated = Date.parse(progress.updated_at);
      if (!Number.isNaN(updated)) return Math.max(0, Math.floor((updated - started) / 1000));
    }
    return Math.max(0, Math.floor((Date.now() - started) / 1000));
  }

  function canContinueRun(progress) {
    if (!progress) return false;
    const total = progress.total_records || 0;
    const completed = progress.completed || 0;
    if (!total || completed >= total) return false;
    if (state.selectedPaths.size > 0) return false;
    return ["ready", "paused", "cancelled", "failed"].includes(progress.status);
  }

  function updateStartButtonLabel(progress, active) {
    if (!btnInsightStartRun) return;
    if (progress?.status === "cancelling") {
      btnInsightStartRun.textContent = "正在停止…";
      btnInsightStartRun.disabled = true;
      return;
    }
    if (active) {
      btnInsightStartRun.textContent = "分析中…";
      btnInsightStartRun.disabled = true;
      return;
    }
    btnInsightStartRun.disabled = false;
    btnInsightStartRun.textContent = canContinueRun(progress) ? "继续分析" : "开始分析";
  }

  function updateProgressBar(progress, active) {
    if (!insightProgressWrap || !insightProgressFill || !insightProgressLabel) return;
    const total = progress?.total_records || 0;
    const completed = progress?.completed || 0;
    const show = active || completed > 0;
    insightProgressWrap.hidden = !show;
    if (!show) return;
    const pct = total > 0 ? Math.min(100, Math.round((completed / total) * 100)) : 0;
    insightProgressFill.style.width = `${pct}%`;
    insightProgressLabel.textContent = `${completed.toLocaleString()} / ${total.toLocaleString()}（${pct}%）`;
  }

  function updateCompletionSummary(progress, config) {
    if (!insightCompletionSummary) return;
    const done = progress?.status === "completed";
    if (!done || !(progress?.completed > 0)) {
      insightCompletionSummary.hidden = true;
      insightCompletionSummary.innerHTML = "";
      return;
    }
    const elapsed = formatDuration(computeElapsedSeconds(progress, false));
    insightCompletionSummary.hidden = false;
    insightCompletionSummary.innerHTML = `<strong>分析完成</strong> · 共 ${progress.completed.toLocaleString()} 条 · 耗时 ${elapsed} · 实际费用 ${formatCost(actualCost(progress), config?.currency || "CNY")}`;
  }

  function updateExportLinks(runId, progress, summary) {
    const hasResults = (progress?.completed || 0) > 0;
    const paths = summary?.export_paths || {};
    if (!insightExportPlaceholder) return;
    if (!runId || !hasResults) {
      insightExportPlaceholder.hidden = false;
      insightExportPlaceholder.textContent =
        "完成至少一批评论分析后，将自动保存分析结果 CSV 与洞察报告至 CSV 同目录。调研对象 / 私信请到「找人聊聊」。";
      return;
    }
    const lines = [];
    if (paths.results_csv) lines.push(`· data/${paths.results_csv}`);
    if (paths.report_md) lines.push(`· data/${paths.report_md}`);
    const exportError = summary?.export_error;
    if (exportError) {
      insightExportPlaceholder.innerHTML = `<span class="inline-status error">自动导出失败：${escapeHtml(exportError)}</span>`;
    } else if (lines.length) {
      insightExportPlaceholder.innerHTML =
        `已自动保存（分析产物）：<br>${lines.map(escapeHtml).join("<br>")}<br><span class="hint">调研对象与私信请在「找人聊聊」生成与导出。</span>`;
    } else {
      insightExportPlaceholder.textContent = "分析结果将在本批完成后自动保存至 CSV 同目录。";
    }
    insightExportPlaceholder.hidden = false;
  }

  async function loadRunHistory() {
    try {
      const data = await apiFetch("/api/analysis/runs");
      const runs = data.runs || [];
      const current = state.currentRunId;
      if (!insightRunHistory) return;
      insightRunHistory.innerHTML =
        '<option value="">— 加载已有任务 —</option>' +
        runs
          .map((run) => {
            const label = `${run.name || run.run_id} · ${run.completed}/${run.total_records} · ${statusLabel(run.status)}`;
            const selected = run.run_id === current ? " selected" : "";
            return `<option value="${escapeHtml(run.run_id)}"${selected}>${escapeHtml(label)}</option>`;
          })
          .join("");
    } catch {
      /* ignore history load errors */
    }
  }

  async function selectRunFromHistory(runId) {
    if (!runId) return;
    state.selectedPaths.clear();
    state.currentRunId = runId;
    sessionStorage.setItem(RUN_ID_STORAGE, runId);
    stopPolling();
    const data = await refreshRunDisplay(runId);
    if (data?.config?.name && insightRunName) insightRunName.value = data.config.name;
    if (data?.config?.analysis_limit != null) setAnalysisLimit(data.config.analysis_limit);
    if (insightRunHistory && insightRunHistory.value !== runId) insightRunHistory.value = runId;
    renderSourceTree();
    const progress = state.lastProgress || {};
    if (progress.status === "failed" && (progress.failed || 0) > 0) {
      insightRunStatus.textContent = `任务加载完成：${progress.failed} 条失败，可点「重试失败项」或「继续分析」处理剩余评论`;
      insightRunStatus.className = "inline-status error";
    } else {
      insightRunStatus.textContent = "";
      insightRunStatus.className = "inline-status";
    }
    if (isActiveRunStatus(progress.status)) startPolling(runId);
  }

  function loadStoredApiKey() {
    if (!insightApiKey) return;
    const stored = sessionStorage.getItem(API_KEY_STORAGE);
    if (stored) insightApiKey.value = stored;
  }

  function persistApiKey() {
    if (!insightApiKey) return;
    const value = insightApiKey.value.trim();
    if (value) sessionStorage.setItem(API_KEY_STORAGE, value);
    else sessionStorage.removeItem(API_KEY_STORAGE);
  }

  function getModelSettings() {
    return {
      model_name: insightModelName?.value?.trim() || "deepseek-v4-flash",
      base_url: insightBaseUrl?.value?.trim() || "https://api.deepseek.com",
      budget_limit: Number(insightBudgetLimit?.value || 0),
    };
  }

  function getAnalysisEngine() {
    const el = document.getElementById("insightAnalysisEngine");
    const value = el?.value?.trim() || "evidence_items_v1";
    return value === "legacy_per_record" ? "legacy_per_record" : "evidence_items_v1";
  }

  function getApiKey() {
    persistApiKey();
    return insightApiKey?.value?.trim() || "";
  }

  function formatCost(value, currency = "CNY") {
    if (value == null || Number.isNaN(value)) return "—";
    return `${Number(value).toFixed(4)} ${currency}`;
  }

  function formatDuration(totalSeconds) {
    if (totalSeconds == null || totalSeconds <= 0) return "—";
    const hours = Math.floor(totalSeconds / 3600);
    const minutes = Math.floor((totalSeconds % 3600) / 60);
    const seconds = totalSeconds % 60;
    const parts = [];
    if (hours) parts.push(`${hours} 小时`);
    if (minutes) parts.push(`${minutes} 分钟`);
    if (!parts.length && seconds) parts.push(`${seconds} 秒`);
    return parts.join(" ") || "少于 1 分钟";
  }

  function formatRunLabel(runId, configName) {
    if (configName && configName !== runId) return `${configName}（${runId}）`;
    return runId || "—";
  }

  function statusLabel(status) {
    const labels = {
      ready: "就绪",
      running: "分析中",
      cancelling: "正在停止",
      cancelled: "已停止",
      paused: "已暂停",
      completed: "已完成",
      failed: "失败",
    };
    return labels[status] || status || "—";
  }

  function isActiveRunStatus(status) {
    return status === "running" || status === "cancelling";
  }

  function stopPolling() {
    if (state.pollTimer) {
      clearInterval(state.pollTimer);
      state.pollTimer = null;
    }
  }

  function startPolling(runId) {
    stopPolling();
    if (!runId) return;
    state.pollTimer = setInterval(() => {
      // Quiet poll: progress/summary only — never full /results
      pollRunProgress(runId, { quiet: true, shouldLoadResults: false }).catch(() => {});
    }, POLL_INTERVAL_MS);
  }

  function countSelectedComments() {
    let comments = 0;
    state.groups.forEach((group) => {
      group.creators.forEach((creator) => {
        creator.files.forEach((file) => {
          if (state.selectedPaths.has(file.path)) {
            comments += file.comment_count || 0;
          }
        });
      });
    });
    return comments;
  }

  async function verifyModelConnection() {
    if (!btnInsightVerifyModel) return;
    const apiKey = getApiKey();
    if (!apiKey) {
      insightVerifyStatus.textContent = "请先填写 API Key";
      insightVerifyStatus.className = "inline-status error";
      return;
    }
    btnInsightVerifyModel.disabled = true;
    insightVerifyStatus.textContent = "正在验证 API 连接…";
    insightVerifyStatus.className = "inline-status loading";
    try {
      const data = await apiFetch("/api/analysis/verify-model", {
        method: "POST",
        body: JSON.stringify({
          api_key: apiKey,
          model: getModelSettings(),
        }),
      });
      insightVerifyStatus.textContent = `${data.message}（${data.provider_label} / ${data.model_name}，intent=${data.primary_intent}，confidence=${data.confidence}）`;
      insightVerifyStatus.className = "inline-status success";
    } catch (err) {
      insightVerifyStatus.textContent = `验证失败：${err.message}`;
      insightVerifyStatus.className = "inline-status error";
    } finally {
      btnInsightVerifyModel.disabled = false;
    }
  }

  const CHEVRON_SVG =
    '<svg class="insight-icon-chevron" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true"><path fill-rule="evenodd" d="M7.21 14.77a.75.75 0 01.02-1.06L10.94 10 7.23 6.29a.75.75 0 111.06-1.06l4.25 4.25a.75.75 0 010 1.06l-4.25 4.25a.75.75 0 01-1.06 0z" clip-rule="evenodd"/></svg>';

  const INTENT_LABELS = {
    gratitude_recognition: "感谢与认可",
    check_in: "打卡",
    result_feedback: "结果反馈",
    question: "提问",
    difficulty_help_request: "困难求助",
    complaint: "不满",
    other_valid: "其他有效",
    invalid_or_unclear: "无效/不明",
  };

  const SIGNAL_LABELS = {
    gratitude: "表达感谢",
    saved_or_plan_to_try: "收藏或准备尝试",
    started_training: "已开始训练",
    continued_training: "持续训练",
    positive_result: "正向结果反馈",
    no_change: "无变化",
    negative_result: "负向结果反馈",
    applicability_question: "适用性提问",
    form_uncertainty: "动作形态不确定",
    cannot_complete: "无法完成动作",
    no_target_muscle_sensation: "目标肌群无感",
    physical_discomfort: "身体不适",
    injury_or_special_condition: "伤病或特殊情况",
    needs_substitution: "需要替换动作",
    needs_regression: "需要降阶",
    needs_progression: "需要进阶",
    needs_training_plan: "需要训练计划",
    pace_or_counting_problem: "节奏或计数问题",
    instruction_unclear: "讲解不清楚",
    equipment_or_space_constraint: "设备或空间限制",
    privacy_concern: "隐私顾虑",
    motivation_or_accountability: "需要督促或陪伴",
    asks_coach_reply: "希望博主回复",
    searched_other_content: "搜索其他内容",
    recorded_self_for_review: "录像自我回看",
    paid_professional_help: "付费专业帮助",
    skipped_exercise: "跳过动作",
    stopped_training: "停止训练",
    changed_training_plan: "改变训练计划",
    other_new_signal: "其他新信号",
  };

  const PRODUCT_FIT_LABELS = {
    high: "高",
    medium: "中",
    low: "低",
    unclear: "不明",
  };

  const SINGLE_VIDEO_LABELS = {
    video_sufficient: "视频本身足够",
    one_reply_sufficient: "一次回复即可",
    personalized_judgment_needed: "需个性化判断",
    realtime_observation_needed: "需实时观察",
    unclear: "信息不足",
  };

  const HYPOTHESIS_LABELS = {
    H1: "H1 训练过程/质量",
    H2: "H2 需实时反馈",
    H3: "H3 需 Agent 规划",
  };

  const HYPOTHESIS_RELATION_LABELS = {
    supports: "支持",
    weakens: "削弱",
    insufficient: "证据不足",
    irrelevant: "无关",
  };

  const THEME_RELATION_LABELS = {
    supports_existing: "支持已有假设的新证据",
    extends_existing: "扩展已有假设的新发现",
    weakens_existing: "削弱已有假设的新发现",
    unrelated_notable: "与已有假设无关但值得注意",
  };

  const THEME_RELATION_ORDER = [
    "supports_existing",
    "extends_existing",
    "weakens_existing",
    "unrelated_notable",
  ];

  function labelSignal(signal) {
    return SIGNAL_LABELS[signal] || signal;
  }

  async function apiFetch(path, options = {}) {
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

  function setStage(stage) {
    const isCollect = stage === "collect";
    const isInsight = stage === "insight";
    const isOutreach = stage === "outreach";
    stageTabCollect?.classList.toggle("active", isCollect);
    stageTabInsight?.classList.toggle("active", isInsight);
    stageTabOutreach?.classList.toggle("active", isOutreach);
    if (setupView) setupView.hidden = !isCollect;
    if (insightView) insightView.hidden = !isInsight;
    if (outreachView) outreachView.hidden = !isOutreach;
    if (workspace) workspace.hidden = true;
    if (btnBackSetup) btnBackSetup.hidden = true;
    if (isInsight) refreshSources();
    // 第三板块自行激活；洞察不驱动其内部状态
    window.dispatchEvent(new CustomEvent("vc:stage-change", { detail: { stage } }));
  }

  function escapeHtml(text) {
    return String(text || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  function formatSize(bytes) {
    if (!bytes) return "0 B";
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }

  function matchesSearch(file, query) {
    if (!query) return true;
    const haystack = [file.category, file.creator, file.video_label, file.folder, file.name]
      .join(" ")
      .toLowerCase();
    return haystack.includes(query);
  }

  function creatorKey(category, creator) {
    return `${category}/${creator}`;
  }

  function ensureExpandedDefaults(groups) {
    groups.forEach((group) => state.expandedCategories.add(group.category));
    if (state.searchQuery.trim()) {
      groups.forEach((group) => {
        group.creators.forEach((creator) => {
          state.expandedCreators.add(creatorKey(group.category, creator.creator));
        });
      });
    }
  }

  function toggleCategory(category) {
    if (state.expandedCategories.has(category)) state.expandedCategories.delete(category);
    else state.expandedCategories.add(category);
    renderSourceTree();
  }

  function toggleCreator(key) {
    if (state.expandedCreators.has(key)) state.expandedCreators.delete(key);
    else state.expandedCreators.add(key);
    renderSourceTree();
  }

  function updateSelectionSummary() {
    if (!insightSelectionSummary) return;
    const count = state.selectedPaths.size;
    if (!count) {
      insightSelectionSummary.innerHTML = '<span class="insight-selection-pill muted">未选择文件</span>';
      return;
    }
    let comments = 0;
    state.groups.forEach((group) => {
      group.creators.forEach((creator) => {
        creator.files.forEach((file) => {
          if (state.selectedPaths.has(file.path)) {
            comments += file.comment_count || 0;
          }
        });
      });
    });
    insightSelectionSummary.innerHTML = `
      <span class="insight-selection-pill active">已选 <strong>${count}</strong> 个文件</span>
      <span class="insight-selection-pill active">约 <strong>${comments.toLocaleString()}</strong> 条评论</span>
    `;
  }

  function togglePath(path, checked) {
    if (checked) state.selectedPaths.add(path);
    else state.selectedPaths.delete(path);
    updateSelectionSummary();
  }

  function renderSourceTree() {
    if (!insightSourceList) return;
    const query = state.searchQuery.trim().toLowerCase();
    insightSourceList.innerHTML = "";

    let visibleCount = 0;
    const tree = document.createElement("div");
    tree.className = "insight-tree";

    state.groups.forEach((group) => {
      const visibleCreators = group.creators
        .map((creator) => ({
          ...creator,
          files: creator.files.filter((file) => matchesSearch(file, query)),
        }))
        .filter((creator) => creator.files.length);

      if (!visibleCreators.length) return;

      const catComments = visibleCreators.reduce((sum, c) => sum + (c.comment_count || 0), 0);
      const categoryOpen = state.expandedCategories.has(group.category) || Boolean(query);

      const section = document.createElement("section");
      section.className = "insight-tree-section";

      const sectionHead = document.createElement("button");
      sectionHead.type = "button";
      sectionHead.className = "insight-tree-section-head";
      sectionHead.setAttribute("aria-expanded", String(categoryOpen));
      sectionHead.innerHTML = `
        <span class="insight-tree-section-chevron ${categoryOpen ? "open" : ""}">${CHEVRON_SVG}</span>
        <span class="insight-tree-section-title">${escapeHtml(group.category)}</span>
        <span class="insight-tree-section-meta">${visibleCreators.length} 位博主 · ${catComments.toLocaleString()} 条评论</span>
      `;
      sectionHead.addEventListener("click", () => toggleCategory(group.category));
      section.appendChild(sectionHead);

      if (!categoryOpen) {
        tree.appendChild(section);
        return;
      }

      const sectionBody = document.createElement("div");
      sectionBody.className = "insight-tree-section-body";

      visibleCreators.forEach((creator) => {
        visibleCount += creator.files.length;
        const key = creatorKey(group.category, creator.creator);
        const creatorOpen = state.expandedCreators.has(key) || Boolean(query);

        const creatorBlock = document.createElement("div");
        creatorBlock.className = "insight-tree-creator";

        const creatorHead = document.createElement("div");
        creatorHead.className = "insight-tree-creator-head";

        const expandBtn = document.createElement("button");
        expandBtn.type = "button";
        expandBtn.className = "insight-tree-expand";
        expandBtn.setAttribute("aria-label", creatorOpen ? "收起视频列表" : "展开视频列表");
        expandBtn.setAttribute("aria-expanded", String(creatorOpen));
        expandBtn.innerHTML = `<span class="insight-tree-expand-icon ${creatorOpen ? "open" : ""}">${CHEVRON_SVG}</span>`;
        expandBtn.addEventListener("click", () => toggleCreator(key));

        const creatorCheckbox = document.createElement("input");
        creatorCheckbox.type = "checkbox";
        creatorCheckbox.className = "insight-tree-check";
        creatorCheckbox.checked = creator.files.every((file) => state.selectedPaths.has(file.path));
        creatorCheckbox.addEventListener("change", (event) => {
          creator.files.forEach((file) => togglePath(file.path, event.target.checked));
          renderSourceTree();
        });

        const creatorName = document.createElement("span");
        creatorName.className = "insight-tree-creator-name";
        creatorName.textContent = creator.creator;
        creatorName.title = creator.creator;

        const creatorMeta = document.createElement("span");
        creatorMeta.className = "insight-tree-creator-meta";
        creatorMeta.textContent = `${creator.files.length} 个视频 · ${(creator.comment_count || 0).toLocaleString()} 条`;

        creatorHead.append(expandBtn, creatorCheckbox, creatorName, creatorMeta);
        creatorBlock.appendChild(creatorHead);

        if (creatorOpen) {
          const filesWrap = document.createElement("div");
          filesWrap.className = "insight-tree-files";

          creator.files.forEach((file) => {
            const row = document.createElement("label");
            row.className = "insight-tree-file";
            const checked = state.selectedPaths.has(file.path);
            row.innerHTML = `
              <span class="insight-tree-file-spacer"></span>
              <input type="checkbox" class="insight-tree-check" ${checked ? "checked" : ""} />
              <span class="insight-tree-file-main">
                <span class="insight-tree-file-title" title="${escapeHtml(file.video_label)}">${escapeHtml(file.video_label)}</span>
                <span class="insight-tree-file-sub">${escapeHtml(file.creator_type_hint || "未知")} · ${formatSize(file.size)}</span>
              </span>
              <span class="insight-tree-file-count">${(file.comment_count || 0).toLocaleString()} 条</span>
            `;
            row.querySelector('input[type="checkbox"]').addEventListener("change", (event) => {
              togglePath(file.path, event.target.checked);
            });
            filesWrap.appendChild(row);
          });

          creatorBlock.appendChild(filesWrap);
        }

        sectionBody.appendChild(creatorBlock);
      });

      section.appendChild(sectionBody);
      tree.appendChild(section);
    });

    if (!visibleCount) {
      insightSourceList.innerHTML =
        '<div class="empty-state"><strong>没有匹配的文件</strong><span>试试换个关键词，或点击刷新列表</span></div>';
    } else {
      insightSourceList.appendChild(tree);
    }
    updateSelectionSummary();
  }

  async function refreshSources() {
    if (!insightSourceList) return;
    insightSourceStatus.textContent = "加载并统计评论数中…";
    insightSourceStatus.className = "inline-status loading";
    try {
      const data = await apiFetch("/api/analysis/sources?grouped=true");
      state.groups = data.groups || [];
      state.totalFiles = data.total_files || 0;
      state.totalComments = data.total_comments || 0;
      ensureExpandedDefaults(state.groups);
      if (!state.groups.length) {
        insightSourceList.innerHTML =
          '<div class="empty-state"><strong>暂无可分析文件</strong><span>请先在「数据采集」中抓取评论</span></div>';
        insightSourceStatus.textContent = "";
        return;
      }
      renderSourceTree();
      insightSourceStatus.textContent = `共 ${state.totalFiles} 个文件，约 ${state.totalComments.toLocaleString()} 条评论`;
      insightSourceStatus.className = "inline-status success";
    } catch (err) {
      insightSourceStatus.textContent = `加载失败：${err.message}`;
      insightSourceStatus.className = "inline-status error";
    }
  }

  function selectVisibleFiles() {
    const query = state.searchQuery.trim().toLowerCase();
    state.groups.forEach((group) => {
      group.creators.forEach((creator) => {
        creator.files.forEach((file) => {
          if (matchesSearch(file, query)) state.selectedPaths.add(file.path);
        });
      });
    });
    renderSourceTree();
  }

  function clearSelection() {
    state.selectedPaths.clear();
    renderSourceTree();
  }

  function actualCost(progress) {
    if (!progress) return null;
    return progress.actual_cost ?? progress.estimated_cost;
  }

  function formatCostProjection(progress, config) {
    const completed = progress?.completed || 0;
    const total = progress?.total_records || 0;
    const cost = actualCost(progress);
    if (!completed || cost == null || !total) return "—";
    const perItem = cost / completed;
    const projected = perItem * total;
    const currency = config?.currency || "CNY";
    return `约 ${perItem.toFixed(4)} ${currency}/条 · 全量约 ${projected.toFixed(0)} ${currency}`;
  }

  function renderErrorSummary(progress) {
    if (!insightErrorSummary) return;
    const summary = Array.isArray(progress.error_summary) ? progress.error_summary : [];
    if (!summary.length) {
      const fallback = progress.last_error || "";
      insightErrorSummary.textContent = fallback || "—";
      insightErrorSummary.title = fallback;
      return;
    }
    insightErrorSummary.innerHTML = summary
      .map(
        (item) =>
          `<div class="insight-error-line"><span class="insight-error-count">${item.count}×</span> ${escapeHtml(
            item.message || ""
          )}</div>`
      )
      .join("");
    insightErrorSummary.title = summary.map((item) => `${item.count}× ${item.message || ""}`).join("\n");
  }

  function updateRunMetrics(data) {
    const progress = data.progress || {};
    const config = data.config || {};
    state.lastProgress = progress;
    state.currentRunStatus = progress.status || "";
    insightRunId.textContent = formatRunLabel(data.config?.run_id || state.currentRunId, config.name);
    insightRunId.title = config.run_id || state.currentRunId || "";
    insightTotal.textContent = String(progress.total_records ?? "—");
    insightCompleted.textContent = String(progress.completed ?? "—");
    insightStatus.textContent = statusLabel(progress.status);
    const active = isActiveRunStatus(progress.status) || Boolean(data.is_running);
    insightElapsed.textContent = formatDuration(computeElapsedSeconds(progress, active));
    insightFailed.textContent = progress.failed != null ? String(progress.failed) : "—";
    renderErrorSummary(progress);
    insightPromptTokens.textContent = progress.prompt_tokens != null ? progress.prompt_tokens.toLocaleString() : "—";
    if (insightCacheHitTokens) {
      const cacheHits = progress.prompt_cache_hit_tokens;
      insightCacheHitTokens.textContent =
        cacheHits != null && progress.prompt_tokens
          ? `${cacheHits.toLocaleString()} (${Math.round((cacheHits / progress.prompt_tokens) * 100)}%)`
          : cacheHits != null
            ? String(cacheHits)
            : "—";
    }
    insightCompletionTokens.textContent =
      progress.completion_tokens != null ? progress.completion_tokens.toLocaleString() : "—";
    insightCost.textContent = formatCost(actualCost(progress), config.currency || "CNY");
    if (insightRunHint) {
      const budgetPaused =
        progress.status === "paused" && (progress.last_error || "").includes("预算上限");
      insightRunHint.hidden = !active && !budgetPaused;
      if (budgetPaused) {
        insightRunHint.innerHTML =
          "当前任务因达到预算上限暂停。请提高预算上限后点击「继续分析」，已完成结果不会重复调用和计费。";
      } else if (!insightRunHint.hidden) {
        insightRunHint.textContent = "分析在后台运行，进度每 5 秒自动刷新；可随时点击「停止分析」。";
      }
    }
    if (insightCostProjection) {
      insightCostProjection.textContent = formatCostProjection(progress, config);
      insightCostProjection.title = config.model_name
        ? `模型：${config.model_name}${config.model_display ? `（${config.model_display}）` : ""}`
        : "";
    }

    const hasFailed = (progress.failed_record_ids || []).length > 0 || (progress.failed || 0) > 0;
    updateStartButtonLabel(progress, active);
    btnInsightRetryFailed.disabled = !hasFailed || active || !state.currentRunId;
    btnInsightStopRun.disabled = !active;
    updateProgressBar(progress, active);
    updateCompletionSummary(progress, config);
    updateExportLinks(state.currentRunId, progress, data.summary || {});
    if (config.analysis_limit != null) setAnalysisLimit(config.analysis_limit);
  }

  async function pollRunProgress(runId, options = {}) {
    const { quiet = false, shouldLoadResults = false } = options;
    if (state.pollBusy) return null;
    state.pollBusy = true;
    try {
      const data = await apiFetch(`/api/analysis/runs/${encodeURIComponent(runId)}`);
      updateRunMetrics(data);
      renderSummary(data.summary || {});
      if (data.document_warnings && Object.keys(data.document_warnings).length) {
        const warnText = Object.values(data.document_warnings).join("；");
        if (insightRunStatus && !isActiveRunStatus(data.progress?.status)) {
          insightRunStatus.textContent = `注意：${warnText}`;
          insightRunStatus.className = "inline-status error";
        }
      }
      if (shouldLoadResults) await loadResultsLight(runId);
      const progress = data.progress || {};
      if (!isActiveRunStatus(progress.status) && !data.is_running) {
        stopPolling();
        // One-shot refresh of paginated results + themes after run settles
        await loadResultsLight(runId);
        await loadRunHistory();
      }
      return data;
    } catch (err) {
      if (!quiet) throw err;
      return null;
    } finally {
      state.pollBusy = false;
    }
  }

  async function refreshRunDisplay(runId) {
    await pollRunProgress(runId, { quiet: false, shouldLoadResults: true });
  }

  function renderSummary(summary) {
    renderInsightDashboard(summary);
    if (summary?.total_analyzed) populateFilterSelects(summary);
  }

  function metricCard(label, value, filterKey, filterValue) {
    const clickable = filterKey ? ` data-filter-key="${filterKey}" data-filter-value="${escapeHtml(filterValue)}"` : "";
    return `<button type="button" class="insight-metric-card"${clickable}><span class="insight-metric-value">${value}</span><span class="insight-metric-label">${escapeHtml(label)}</span></button>`;
  }

  function renderOverview(summary) {
    if (!insightOverview) return;
    if (!summary?.total_analyzed) {
      insightOverview.innerHTML = '<p class="hint">暂无统计，请先运行分析。</p>';
      return;
    }
    insightOverview.innerHTML = `
      <div class="insight-metric-grid">
        ${metricCard("已分析", summary.total_analyzed)}
        ${metricCard("有效评论", summary.valid_comments, "intent_valid", "1")}
        ${metricCard("独立用户", summary.unique_users)}
        ${metricCard("已训练用户", summary.trained_users)}
        ${metricCard("感谢信号", summary.gratitude_signal_count, "signal", "gratitude")}
        ${metricCard("打卡", summary.check_in_count, "intent", "check_in")}
        ${metricCard("结果反馈", summary.result_feedback_count, "intent", "result_feedback")}
        ${metricCard("提问", summary.question_count, "intent", "question")}
        ${metricCard("具体困难", summary.difficulty_count, "intent", "difficulty_help_request")}
        ${metricCard("需个性化判断", summary.personalized_needed_count, "video", "personalized_judgment_needed")}
        ${metricCard("需实时观察", summary.realtime_needed_count, "video", "realtime_observation_needed")}
        ${metricCard("高产品适配", summary.product_fit_high_count, "fit", "high")}
        ${metricCard("匹配调研对象", summary.research_matched_user_count ?? summary.high_priority_user_count ?? 0)}
        ${metricCard("可定位主页", summary.contactable_homepage_count)}
      </div>`;
  }

  function renderThemes(themesDoc) {
    if (!insightThemesPanel) return;
    const themes = themesDoc?.themes || [];
    if (!themes.length) {
      const rawCount = themesDoc?.raw_signal_count || 0;
      insightThemesPanel.innerHTML = rawCount
        ? `<p class="hint">已收集 ${rawCount} 条原始新信号，但未形成主题。请检查分析结果或重新生成。</p>`
        : '<p class="hint">暂无开放主题。请先生成开放主题，或确认分析结果中包含 new_signals。</p>';
      return;
    }
    const grouped = {};
    themes.forEach((theme) => {
      const key = theme.relation_to_existing_hypotheses || "extends_existing";
      if (!grouped[key]) grouped[key] = [];
      grouped[key].push(theme);
    });
    const sections = THEME_RELATION_ORDER.filter((key) => grouped[key]?.length)
      .map((key) => {
        const cards = grouped[key]
          .map((theme) => {
            const stats = theme.stats || {};
            const quotes = (theme.representative_quotes || [])
              .map((q) => `<li>${escapeHtml(q)}</li>`)
              .join("");
            return `<article class="insight-theme-card">
              <header>
                <strong>${escapeHtml(theme.theme_name)}</strong>
                <span class="insight-theme-type">${escapeHtml(theme.theme_type || "—")}</span>
              </header>
              <p class="hint">${escapeHtml(theme.definition || "")}</p>
              <div class="insight-theme-meta">
                <span>${stats.comment_count || 0} 条评论</span>
                <span>${stats.unique_user_count || 0} 独立用户</span>
                <span>${stats.source_file_count || 0} 个来源文件</span>
                <span>${stats.video_count || 0} 个视频</span>
                <span>置信 ${theme.confidence != null ? Math.round(theme.confidence * 100) : "—"}%</span>
              </div>
              ${theme.implication ? `<p>${escapeHtml(theme.implication)}</p>` : ""}
              ${quotes ? `<ul>${quotes}</ul>` : ""}
              <button type="button" class="btn ghost sm insight-theme-view-btn" data-theme-id="${escapeHtml(theme.theme_id)}">查看相关评论</button>
            </article>`;
          })
          .join("");
        return `<section class="insight-theme-group"><h4>${escapeHtml(THEME_RELATION_LABELS[key] || key)}</h4>${cards}</section>`;
      })
      .join("");
    const meta = themesDoc?.created_at
      ? `<p class="hint">共 ${themes.length} 个主题 · ${themesDoc.raw_signal_count || 0} 条原始信号 · 归并费用 ${formatCost(themesDoc.cost, themesDoc.currency || "CNY")}</p>`
      : "";
    insightThemesPanel.innerHTML = meta + sections;
  }

  function applyThemeFilter(themeId) {
    const theme = (state.themesDoc?.themes || []).find((item) => item.theme_id === themeId);
    if (!theme) return;
    state.filters.themeRecordIds = new Set(theme.record_ids || []);
    syncFilterControls();
    loadResultsPage(1);
    if (insightFilterStatus) {
      insightFilterStatus.textContent = `主题「${theme.theme_name}」相关 ${(theme.record_ids || []).length} 条`;
    }
    insightResultsTable?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  async function clusterThemes() {
    if (!state.currentRunId) {
      insightThemesStatus.textContent = "请先选择或创建一个分析任务";
      insightThemesStatus.className = "inline-status error";
      return;
    }
    if (!requireApiKey()) return;
    btnInsightClusterThemes.disabled = true;
    insightThemesStatus.textContent = "正在归并开放主题…";
    insightThemesStatus.className = "inline-status loading";
    try {
      const doc = await apiFetch(`/api/analysis/runs/${encodeURIComponent(state.currentRunId)}/themes/cluster`, {
        method: "POST",
        body: JSON.stringify({ api_key: getApiKey(), use_mock: false }),
      });
      state.themesDoc = doc;
      renderThemes(doc);
      insightThemesStatus.textContent = `完成：${(doc.themes || []).length} 个主题，费用 ${formatCost(doc.cost, doc.currency || "CNY")}`;
      insightThemesStatus.className = "inline-status success";
    } catch (err) {
      insightThemesStatus.textContent = `归并失败：${err.message}`;
      insightThemesStatus.className = "inline-status error";
    } finally {
      btnInsightClusterThemes.disabled = false;
    }
  }

  function buildResultsQueryParams(page) {
    const f = state.filters;
    const params = new URLSearchParams();
    params.set("page", String(page || state.resultsPage.page || 1));
    params.set("page_size", String(state.resultsPage.pageSize || 100));
    if (f.keyword) params.set("keyword", f.keyword);
    if (f.intent) params.set("primary_intent", f.intent);
    if (f.intent_valid === "1") params.set("intent_valid", "true");
    if (f.signal) params.set("signal", f.signal);
    if (f.video) params.set("single_video_relation", f.video);
    if (f.fit) params.set("product_fit", f.fit);
    if (f.hypothesis) {
      const [hid, rel] = f.hypothesis.split(":");
      if (hid) params.set("hypothesis_id", hid);
      if (rel) params.set("hypothesis_relation", rel);
    }
    if (f.themeRecordIds?.size) params.set("record_ids", Array.from(f.themeRecordIds).join(","));
    return params;
  }

  function renderPager(container, pageState, onPage) {
    if (!container) return;
    const totalPages = Math.max(1, Math.ceil((pageState.total || 0) / (pageState.pageSize || 1)));
    if ((pageState.total || 0) <= (pageState.pageSize || 100)) {
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

  async function loadResultsPage(page = 1) {
    if (!state.currentRunId) return;
    if (state.evidenceMode) {
      await loadEvidencePage(page);
      return;
    }
    state.resultsPage.page = page;
    const params = buildResultsQueryParams(page);
    const data = await apiFetch(
      `/api/analysis/runs/${encodeURIComponent(state.currentRunId)}/results/items?${params.toString()}`
    );
    state.resultsPage = {
      page: data.page || page,
      pageSize: data.page_size || state.resultsPage.pageSize,
      total: data.total || 0,
      items: data.items || [],
    };
    renderResultsTable();
  }

  async function loadEvidencePage(page = 1) {
    if (!state.currentRunId) return;
    const params = new URLSearchParams();
    params.set("page", String(page));
    params.set("page_size", String(state.evidencePage.pageSize || 50));
    if (state.filters.keyword) params.set("keyword", state.filters.keyword);
    const data = await apiFetch(
      `/api/analysis/runs/${encodeURIComponent(state.currentRunId)}/evidence/items?${params.toString()}`
    );
    state.evidencePage = {
      page: data.page || page,
      pageSize: data.page_size || 50,
      total: data.total || 0,
      items: data.items || [],
    };
    renderEvidenceTable();
  }

  function renderEvidenceItems(items) {
    if (!items || !items.length) return '<span class="hint">无证据项</span>';
    return `<div class="evidence-item-list">${items
      .map((it) => {
        const typeLabel = EVIDENCE_TYPE_LABELS[it.type] || it.type || "—";
        const subtype = it.subtype ? ` · ${escapeHtml(it.subtype)}` : "";
        const scope = it.speaker_scope || "—";
        const cert = it.certainty || "—";
        return `<div class="evidence-item-card">
          <div class="evidence-item-meta"><strong>${escapeHtml(typeLabel)}</strong>${subtype}
            <span class="hint">主体 ${escapeHtml(scope)} · ${escapeHtml(cert)}</span></div>
          <div>${escapeHtml(it.text || "")}</div>
          <blockquote class="evidence-quote">${escapeHtml(it.evidence_quote || "")}</blockquote>
        </div>`;
      })
      .join("")}</div>`;
  }

  function renderEvidenceTable() {
    if (!insightResultsTable) return;
    const rows = state.evidencePage.items || [];
    if (!state.evidencePage.total && !rows.length) {
      insightResultsTable.innerHTML = '<p class="hint center">尚无证据分析结果</p>';
      if (insightFilterStatus) insightFilterStatus.textContent = "";
      if (insightResultsPager) {
        insightResultsPager.hidden = true;
        insightResultsPager.innerHTML = "";
      }
      return;
    }
    if (insightFilterStatus) {
      insightFilterStatus.textContent = `证据路径 · 显示 ${rows.length} 条 · 共 ${state.evidencePage.total.toLocaleString()} 条`;
    }
    if (!rows.length) {
      insightResultsTable.innerHTML = '<p class="hint center">无符合筛选条件的评论</p>';
      renderPager(insightResultsPager, state.evidencePage, loadEvidencePage);
      return;
    }
    const thead = `<tr>
      <th>原评论</th><th>状态</th><th>主表达</th><th>证据强度</th><th>证据项</th><th>缓存</th>
    </tr>`;
    const tbody = rows
      .map((row) => {
        const source = row.source || {};
        const card = row.card || {};
        const status = RECORD_STATUS_LABELS[card.record_status] || card.record_status || "—";
        const expr = EXPRESSION_LABELS[card.primary_expression] || card.primary_expression || "—";
        return `<tr>
          <td class="insight-col-comment" title="${escapeHtml(source.comment_text || "")}">${escapeHtml((source.comment_text || "").slice(0, 80))}</td>
          <td>${escapeHtml(status)}</td>
          <td>${escapeHtml(expr)}</td>
          <td>${escapeHtml(card.evidence_level || "—")}</td>
          <td>${renderEvidenceItems(card.evidence_items || [])}</td>
          <td>${row.from_cache || card.reused_from_record_id ? "命中" : "—"}</td>
        </tr>`;
      })
      .join("");
    insightResultsTable.innerHTML = `<table class="preview-table insight-detail-table"><thead>${thead}</thead><tbody>${tbody}</tbody></table>`;
    renderPager(insightResultsPager, state.evidencePage, loadEvidencePage);
  }

  async function loadResearchReport(runId) {
    if (!insightResearchCard || !insightResearchReport) return;
    try {
      const data = await apiFetch(`/api/analysis/runs/${encodeURIComponent(runId)}/research-report`);
      if (!data?.has_report) {
        insightResearchCard.hidden = true;
        insightResearchReport.innerHTML = "";
        return;
      }
      insightResearchCard.hidden = false;
      const md = data.markdown || "";
      // Lightweight markdown → HTML: headings + paragraphs (no JSON dump)
      const html = md
        .split(/\n{2,}/)
        .map((block) => {
          const line = block.trim();
          if (!line) return "";
          if (line.startsWith("### ")) return `<h4>${escapeHtml(line.slice(4))}</h4>`;
          if (line.startsWith("## ")) return `<h3>${escapeHtml(line.slice(3))}</h3>`;
          if (line.startsWith("# ")) return `<h2>${escapeHtml(line.slice(2))}</h2>`;
          if (line.startsWith("- ")) {
            const items = line
              .split("\n")
              .map((l) => l.replace(/^- /, "").trim())
              .filter(Boolean)
              .map((l) => `<li>${escapeHtml(l)}</li>`)
              .join("");
            return `<ul>${items}</ul>`;
          }
          return `<p>${escapeHtml(line).replace(/\n/g, "<br>")}</p>`;
        })
        .join("");
      insightResearchReport.innerHTML = html || '<p class="hint">报告为空</p>';
    } catch (_err) {
      insightResearchCard.hidden = true;
    }
  }

  async function loadResultsLight(runId) {
    // Themes + paged results — prefer evidence_items path when artifacts exist
    const themes = await apiFetch(`/api/analysis/runs/${encodeURIComponent(runId)}/themes`).catch(() => null);
    if (themes) {
      state.themesDoc = themes;
      renderThemes(state.themesDoc);
    }
    await loadResearchReport(runId);
    try {
      const ev = await apiFetch(
        `/api/analysis/runs/${encodeURIComponent(runId)}/evidence/items?page=1&page_size=1`
      );
      if ((ev?.total || 0) > 0) {
        state.evidenceMode = true;
        await loadEvidencePage(1);
        return;
      }
    } catch (_err) {
      /* fall through to legacy */
    }
    state.evidenceMode = false;
    await loadResultsPage(1);
  }

  function renderContradictions(summary) {
    if (!insightContradictions) return;
    const items = summary?.contradictions || [];
    if (!items.length) {
      insightContradictions.hidden = true;
      insightContradictions.innerHTML = "";
      return;
    }
    insightContradictions.hidden = false;
    insightContradictions.innerHTML = `
      <section class="insight-contradictions-section">
        <h4>与预期不一致的发现</h4>
        ${items
          .map(
            (item) => `
          <article class="insight-contradiction-card${item.importance === "important" ? " important" : ""}">
            <header><strong>${escapeHtml(HYPOTHESIS_LABELS[item.hypothesis_id] || item.hypothesis_id)}</strong>${item.importance === "important" ? '<span class="insight-importance-badge">重要反例</span>' : ""} · 削弱 ${item.weaken_count} 条 / 支持 ${item.support_count} 条</header>
            <p>${escapeHtml(item.caution_note || "")}</p>
            <ul>${(item.representative_quotes || []).map((q) => `<li>${escapeHtml(q)}</li>`).join("") || "<li>—</li>"}</ul>
            <button type="button" class="btn ghost sm insight-filter-link" data-filter-key="hypothesis" data-filter-value="${escapeHtml(item.hypothesis_id)}:weakens">查看削弱评论</button>
          </article>`
          )
          .join("")}
      </section>`;
  }

  function renderInsightDashboard(summary) {
    renderOverview(summary);
    renderContradictions(summary);
    if (!insightDashboard) return;
    if (!summary?.total_analyzed) {
      insightDashboard.innerHTML = "";
      return;
    }

    const intents = summary.primary_intent_percentages || {};
    const intentHtml = Object.entries(intents)
      .map(([key, pct]) => {
        const count = summary.primary_intent_counts?.[key] || 0;
        return `<li><button type="button" class="insight-filter-link" data-filter-key="intent" data-filter-value="${escapeHtml(key)}">${escapeHtml(INTENT_LABELS[key] || key)}：${count}（${pct}%）</button></li>`;
      })
      .join("");

    const signals = summary.signal_coverage || {};
    const signalHtml = Object.entries(signals)
      .map(([key, info]) => {
        return `<li><button type="button" class="insight-filter-link" data-filter-key="signal" data-filter-value="${escapeHtml(key)}">${escapeHtml(labelSignal(key))}：${info.count} 条（覆盖率 ${info.coverage_pct}%）</button></li>`;
      })
      .join("");

    const hypothesisHtml = ["H1", "H2", "H3"]
      .map((hid) => {
        const detail = summary.hypothesis_details?.[hid] || {};
        const counts = detail.counts || {};
        const supportQuotes = (detail.support_quotes || []).map((q) => `<li class="quote">${escapeHtml(q)}</li>`).join("");
        const weakenQuotes = (detail.weaken_quotes || []).map((q) => `<li class="quote">${escapeHtml(q)}</li>`).join("");
        return `
          <div class="insight-summary-card insight-hypothesis-card">
            <h4>${escapeHtml(HYPOTHESIS_LABELS[hid] || hid)}</h4>
            <p class="hint">${escapeHtml(detail.label || "")}</p>
            <div class="insight-hypothesis-counts">
              ${["supports", "weakens", "insufficient", "irrelevant"]
                .map(
                  (rel) =>
                    `<button type="button" class="insight-chip insight-filter-link" data-filter-key="hypothesis" data-filter-value="${hid}:${rel}">${HYPOTHESIS_RELATION_LABELS[rel]} ${counts[rel] || 0}</button>`
                )
                .join("")}
            </div>
            <div class="insight-quote-columns">
              <div><strong>支持性原话</strong><ul>${supportQuotes || "<li>—</li>"}</ul></div>
              <div><strong>削弱性原话</strong><ul>${weakenQuotes || "<li>—</li>"}</ul></div>
            </div>
            <p class="hint">原话按与假设相关度筛选展示；计数仍含全部标注。若个别不准，请点上方标签进明细核对。</p>
          </div>`;
      })
      .join("");

    const videoStats = summary.single_video_stats || {};
    const videoHtml = Object.entries(SINGLE_VIDEO_LABELS)
      .map(([key, label]) => {
        const info = videoStats[key] || { count: 0, coverage_pct: 0 };
        return `<li><button type="button" class="insight-filter-link" data-filter-key="video" data-filter-value="${escapeHtml(key)}">${escapeHtml(label)}：${info.count}（${info.coverage_pct}%）</button></li>`;
      })
      .join("");

    insightDashboard.innerHTML = `
      <p class="hint insight-coverage-note">信息信号为覆盖率统计，同一评论可含多个标签，覆盖率之和可能超过 100%。</p>
      <div class="insight-summary-grid">
        <div class="insight-summary-card"><h4>主要沟通目的</h4><ul>${intentHtml || "<li>—</li>"}</ul></div>
        <div class="insight-summary-card"><h4>信息信号覆盖率</h4><ul class="insight-signal-list">${signalHtml || "<li>—</li>"}</ul></div>
        <div class="insight-summary-card"><h4>单向视频关系</h4><ul>${videoHtml || "<li>—</li>"}</ul></div>
      </div>
      <div class="insight-hypothesis-grid">${hypothesisHtml}</div>`;
  }

  function populateFilterSelects(summary) {
    if (!summary?.total_analyzed) return;
    if (insightFilterIntent) {
      insightFilterIntent.innerHTML =
        '<option value="">全部目的</option>' +
        Object.keys(summary.primary_intent_counts || {})
          .map((k) => `<option value="${escapeHtml(k)}">${escapeHtml(INTENT_LABELS[k] || k)}</option>`)
          .join("");
    }
    if (insightFilterVideo) {
      insightFilterVideo.innerHTML =
        '<option value="">全部视频关系</option>' +
        Object.entries(SINGLE_VIDEO_LABELS)
          .map(([k, label]) => `<option value="${k}">${escapeHtml(label)}</option>`)
          .join("");
    }
    if (insightFilterFit) {
      insightFilterFit.innerHTML =
        '<option value="">全部适配度</option>' +
        Object.entries(PRODUCT_FIT_LABELS)
          .map(([k, label]) => `<option value="${k}">${escapeHtml(label)}</option>`)
          .join("");
    }
    if (insightFilterHypothesis) {
      const opts = ['<option value="">全部假设关系</option>'];
      ["H1", "H2", "H3"].forEach((hid) => {
        ["supports", "weakens", "insufficient", "irrelevant"].forEach((rel) => {
          opts.push(`<option value="${hid}:${rel}">${HYPOTHESIS_LABELS[hid]} · ${HYPOTHESIS_RELATION_LABELS[rel]}</option>`);
        });
      });
      insightFilterHypothesis.innerHTML = opts.join("");
    }
  }

  function setFilter(key, value) {
    if (key === "intent_valid") {
      state.filters.intent_valid = value;
      state.filters.intent = "";
    } else if (key === "intent") {
      state.filters.intent = value;
      state.filters.intent_valid = "";
    } else if (key === "signal") state.filters.signal = value;
    else if (key === "video") state.filters.video = value;
    else if (key === "fit") state.filters.fit = value;
    else if (key === "hypothesis") state.filters.hypothesis = value;
    syncFilterControls();
    loadResultsPage(1);
  }

  function syncFilterControls() {
    if (insightFilterIntent) insightFilterIntent.value = state.filters.intent;
    if (insightFilterVideo) insightFilterVideo.value = state.filters.video;
    if (insightFilterFit) insightFilterFit.value = state.filters.fit;
    if (insightFilterHypothesis) insightFilterHypothesis.value = state.filters.hypothesis;
    if (insightFilterKeyword) insightFilterKeyword.value = state.filters.keyword;
  }

  function clearFilters() {
    state.filters = {
      keyword: "",
      intent: "",
      intent_valid: "",
      video: "",
      fit: "",
      hypothesis: "",
      signal: "",
      themeRecordIds: null,
    };
    syncFilterControls();
    loadResultsPage(1);
  }

  function rowMatchesFilters(row) {
    const source = row.source || {};
    const analysis = row.analysis || {};
    const f = state.filters;
    if (f.keyword) {
      const hay = [source.comment_text, source.video_title, source.username].join(" ").toLowerCase();
      if (!hay.includes(f.keyword.toLowerCase())) return false;
    }
    if (f.intent && analysis.primary_intent !== f.intent) return false;
    if (f.intent_valid === "1" && analysis.primary_intent === "invalid_or_unclear") return false;
    if (f.video && analysis.single_video_relation !== f.video) return false;
    if (f.fit && analysis.product_fit !== f.fit) return false;
    if (f.signal && !(analysis.signals || []).includes(f.signal)) return false;
    if (f.hypothesis) {
      const [hid, rel] = f.hypothesis.split(":");
      const matched = (analysis.hypothesis_relations || []).some(
        (item) => item.hypothesis_id === hid && item.relation === rel
      );
      if (!matched) return false;
    }
    if (f.themeRecordIds && f.themeRecordIds.size) {
      const rid = row.record_id || analysis.record_id;
      if (!f.themeRecordIds.has(rid)) return false;
    }
    return true;
  }

  function formatHypothesisRelations(relations) {
    return (relations || [])
      .map((r) => `${r.hypothesis_id}:${HYPOTHESIS_RELATION_LABELS[r.relation] || r.relation}`)
      .join("；");
  }

  function formatNewSignals(signals) {
    return (signals || []).map((s) => s.text || s.type).join("；");
  }

  function renderResultsTable() {
    if (!insightResultsTable) return;
    const rows = state.resultsPage.items || [];
    if (!state.resultsPage.total && !rows.length) {
      insightResultsTable.innerHTML = '<p class="hint center">尚无分析结果</p>';
      if (insightFilterStatus) insightFilterStatus.textContent = "";
      if (insightResultsPager) {
        insightResultsPager.hidden = true;
        insightResultsPager.innerHTML = "";
      }
      return;
    }
    if (insightFilterStatus) {
      insightFilterStatus.textContent = `显示 ${rows.length} 条 · 共 ${state.resultsPage.total.toLocaleString()} 条匹配`;
    }
    if (!rows.length) {
      insightResultsTable.innerHTML = '<p class="hint center">无符合筛选条件的评论</p>';
      renderPager(insightResultsPager, state.resultsPage, loadResultsPage);
      return;
    }
    const thead = `<tr>
      <th>评论</th><th>用户</th><th>平台</th><th>视频</th><th>目的</th><th>信号</th>
      <th>训练证据</th><th>具体问题</th><th>视频关系</th><th>假设</th><th>新发现</th><th>适配</th><th>置信度</th>
    </tr>`;
    const tbody = rows
      .map((row) => {
        const source = row.source || {};
        const analysis = row.analysis || {};
        const userCell = source.user_homepage_url
          ? `<a href="${escapeHtml(source.user_homepage_url)}" target="_blank" rel="noopener">${escapeHtml(source.username || source.user_id || "—")}</a>`
          : escapeHtml(source.username || source.user_id || "—");
        return `<tr>
          <td class="insight-col-comment" title="${escapeHtml(source.comment_text)}">${escapeHtml((source.comment_text || "").slice(0, 60))}</td>
          <td>${userCell}</td>
          <td>${escapeHtml(source.platform || "—")}</td>
          <td title="${escapeHtml(source.video_title)}">${escapeHtml((source.video_title || "—").slice(0, 24))}</td>
          <td>${escapeHtml(INTENT_LABELS[analysis.primary_intent] || analysis.primary_intent || "—")}</td>
          <td>${escapeHtml((analysis.signals || []).map(labelSignal).join("，"))}</td>
          <td>${escapeHtml(analysis.actual_training_evidence || "—")}</td>
          <td>${escapeHtml((analysis.specific_problems || []).join("；") || "—")}</td>
          <td>${escapeHtml(SINGLE_VIDEO_LABELS[analysis.single_video_relation] || analysis.single_video_relation || "—")}</td>
          <td>${escapeHtml(formatHypothesisRelations(analysis.hypothesis_relations))}</td>
          <td>${escapeHtml(formatNewSignals(analysis.new_signals))}</td>
          <td>${escapeHtml(PRODUCT_FIT_LABELS[analysis.product_fit] || analysis.product_fit || "—")}</td>
          <td>${analysis.confidence != null ? `${Math.round(analysis.confidence * 100)}%` : "—"}</td>
        </tr>`;
      })
      .join("");
    insightResultsTable.innerHTML = `<table class="preview-table insight-detail-table"><thead>${thead}</thead><tbody>${tbody}</tbody></table>`;
    renderPager(insightResultsPager, state.resultsPage, loadResultsPage);
  }

  async function loadResults(runId) {
    // Prefer light path; keep as alias for call sites that still expect loadResults
    await loadResultsLight(runId);
  }

  async function createRun() {
    const paths = Array.from(state.selectedPaths);
    if (!paths.length) {
      insightRunStatus.textContent = "请至少选择一个评论文件";
      insightRunStatus.className = "inline-status error";
      return null;
    }
    insightRunStatus.textContent = "准备任务中…";
    insightRunStatus.className = "inline-status loading";
    const created = await apiFetch("/api/analysis/runs", {
      method: "POST",
      body: JSON.stringify({
        name: insightRunName?.value || "评论洞察任务",
        file_paths: paths,
        use_mock: false,
        analysis_limit: getAnalysisLimit(),
        analysis_version: getAnalysisEngine(),
        model: getModelSettings(),
      }),
    });
    state.currentRunId = created.run_id;
    sessionStorage.setItem(RUN_ID_STORAGE, created.run_id);
    await refreshRunDisplay(created.run_id);
    await loadRunHistory();
    if (insightRunHistory) insightRunHistory.value = created.run_id;
    return created;
  }

  async function runAnalysisJob(runId) {
    const result = await apiFetch(`/api/analysis/runs/${encodeURIComponent(runId)}/analyze`, {
      method: "POST",
      body: JSON.stringify(getAnalyzeBody()),
    });
    startPolling(runId);
    insightRunStatus.textContent = result.message || "分析已在后台运行";
    insightRunStatus.className = "inline-status loading";
    return result;
  }

  async function startAnalysis() {
    if (!requireApiKey()) return;
    const progress = state.lastProgress || {};
    const active = isActiveRunStatus(progress.status);
    if (active) return;

    const historyRunId = insightRunHistory?.value?.trim();
    if (historyRunId && historyRunId !== state.currentRunId) {
      await selectRunFromHistory(historyRunId);
    }

    btnInsightStartRun.disabled = true;
    try {
      const latestProgress = state.lastProgress || {};
      if (state.currentRunId && canContinueRun(latestProgress)) {
        insightRunStatus.textContent = "继续分析中…";
        insightRunStatus.className = "inline-status loading";
        await runAnalysisJob(state.currentRunId);
        return;
      }

      const paths = Array.from(state.selectedPaths);
      if (!paths.length) {
        insightRunStatus.textContent = "请至少选择一个评论文件，或从历史任务加载已有结果";
        insightRunStatus.className = "inline-status error";
        return;
      }

      const created = await createRun();
      if (!created) return;
      insightRunStatus.textContent = `已创建任务（${created.total_records} 条），正在启动分析…`;
      await runAnalysisJob(created.run_id);
    } catch (err) {
      insightRunStatus.textContent = `失败：${err.message}`;
      insightRunStatus.className = "inline-status error";
    } finally {
      updateStartButtonLabel(state.lastProgress || {}, isActiveRunStatus(state.currentRunStatus));
    }
  }

  async function retryFailed() {
    if (!state.currentRunId) return;
    if (!requireApiKey()) return;
    btnInsightRetryFailed.disabled = true;
    insightRunStatus.textContent = "重试失败项中…";
    insightRunStatus.className = "inline-status loading";
    try {
      await apiFetch(`/api/analysis/runs/${encodeURIComponent(state.currentRunId)}/retry-failed`, {
        method: "POST",
        body: JSON.stringify(getAnalyzeBody()),
      });
      startPolling(state.currentRunId);
      insightRunStatus.textContent = "失败项重试已在后台运行";
      insightRunStatus.className = "inline-status loading";
    } catch (err) {
      insightRunStatus.textContent = `重试失败：${err.message}`;
      insightRunStatus.className = "inline-status error";
    } finally {
      btnInsightRetryFailed.disabled = false;
    }
  }

  async function stopAnalyze() {
    if (!state.currentRunId) return;
    btnInsightStopRun.disabled = true;
    insightRunStatus.textContent = "正在请求停止分析…";
    insightRunStatus.className = "inline-status loading";
    try {
      const result = await apiFetch(`/api/analysis/runs/${encodeURIComponent(state.currentRunId)}/cancel`, {
        method: "POST",
        body: JSON.stringify({}),
      });
      const nextStatus = result.status || "cancelling";
      state.currentRunStatus = nextStatus;
      if (state.lastProgress) {
        state.lastProgress = { ...state.lastProgress, status: nextStatus };
      }
      updateStartButtonLabel(state.lastProgress || { status: nextStatus }, true);
      if (insightStatus) insightStatus.textContent = statusLabel(nextStatus);
      insightRunStatus.textContent =
        nextStatus === "cancelled"
          ? result.message || "分析已停止"
          : "已请求停止，等待当前条完成…";
      insightRunStatus.className = nextStatus === "cancelled" ? "inline-status success" : "inline-status loading";
      // Keep polling until backend leaves cancelling/running — do not stopPolling() here.
      startPolling(state.currentRunId);
      await pollRunProgress(state.currentRunId, { quiet: false, shouldLoadResults: true });
      if (!isActiveRunStatus(state.currentRunStatus)) {
        insightRunStatus.textContent = "分析已停止";
        insightRunStatus.className = "inline-status success";
      }
    } catch (err) {
      insightRunStatus.textContent = `停止失败：${err.message}`;
      insightRunStatus.className = "inline-status error";
      btnInsightStopRun.disabled = !isActiveRunStatus(state.currentRunStatus);
    }
  }

  stageTabCollect?.addEventListener("click", () => setStage("collect"));
  stageTabInsight?.addEventListener("click", () => setStage("insight"));
  stageTabOutreach?.addEventListener("click", () => setStage("outreach"));
  btnInsightRefreshSources?.addEventListener("click", refreshSources);
  btnInsightSelectVisible?.addEventListener("click", selectVisibleFiles);
  btnInsightClearSelection?.addEventListener("click", clearSelection);
  btnInsightVerifyModel?.addEventListener("click", verifyModelConnection);
  btnInsightStartRun?.addEventListener("click", startAnalysis);
  btnInsightClusterThemes?.addEventListener("click", clusterThemes);
  insightRunHistory?.addEventListener("change", (event) => {
    const runId = event.target.value;
    if (runId) selectRunFromHistory(runId);
  });
  insightApiKey?.addEventListener("change", persistApiKey);
  insightSourceSearch?.addEventListener("input", (event) => {
    state.searchQuery = event.target.value || "";
    renderSourceTree();
  });

  document.addEventListener("click", (event) => {
    const themeBtn = event.target.closest(".insight-theme-view-btn");
    if (themeBtn && insightView?.contains(themeBtn)) {
      applyThemeFilter(themeBtn.getAttribute("data-theme-id"));
      return;
    }
    const btn = event.target.closest("[data-filter-key]");
    if (!btn || !insightView?.contains(btn)) return;
    const key = btn.getAttribute("data-filter-key");
    const value = btn.getAttribute("data-filter-value");
    if (key && value != null) setFilter(key, value);
  });

  insightFilterKeyword?.addEventListener("input", (e) => {
    state.filters.keyword = e.target.value || "";
    clearTimeout(state.filterDebounceTimer);
    state.filterDebounceTimer = setTimeout(() => loadResultsPage(1), 300);
  });
  insightFilterIntent?.addEventListener("change", (e) => {
    state.filters.intent = e.target.value;
    loadResultsPage(1);
  });
  insightFilterVideo?.addEventListener("change", (e) => {
    state.filters.video = e.target.value;
    loadResultsPage(1);
  });
  insightFilterFit?.addEventListener("change", (e) => {
    state.filters.fit = e.target.value;
    loadResultsPage(1);
  });
  insightFilterHypothesis?.addEventListener("change", (e) => {
    state.filters.hypothesis = e.target.value;
    loadResultsPage(1);
  });
  btnInsightClearFilters?.addEventListener("click", clearFilters);

  btnInsightRetryFailed?.addEventListener("click", retryFailed);
  btnInsightStopRun?.addEventListener("click", stopAnalyze);

  loadStoredApiKey();
  loadRunHistory();
  const savedRunId = sessionStorage.getItem(RUN_ID_STORAGE);
  if (savedRunId) {
    state.currentRunId = savedRunId;
    pollRunProgress(savedRunId, { quiet: true, shouldLoadResults: true }).catch(() => {});
  }

  window.VCBridge = {
    apiFetch,
    escapeHtml,
    formatCost,
    getApiKey,
    getCurrentRunId: () => state.currentRunId,
    RUN_ID_STORAGE,
    API_KEY_STORAGE,
  };
  window.vcInsight = { setStage, refreshSources };
})();
