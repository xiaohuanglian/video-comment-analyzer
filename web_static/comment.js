(function () {
  "use strict";

  const API = "";
  const wsProtocol = location.protocol === "https:" ? "wss:" : "ws:";
  const wsHost = `${wsProtocol}//${location.host}`;

  const $ = (id) => document.getElementById(id);

  const setupView = $("setupView");
  const workspace = $("workspace");
  const envChip = $("envChip");
  const setupStatus = $("setupStatus");
  const platformGrid = $("platformGrid");
  const videoInput = $("videoInput");
  const saveFormat = $("saveFormat");
  const saveDataPath = $("saveDataPath");
  const savePathPreviewTree = $("savePathPreviewTree");
  const enableSubComments = $("enableSubComments");
  const creatorInput = $("creatorInput");
  const creatorTopN = $("creatorTopN");
  const btnRankCreator = $("btnRankCreator");
  const btnCancelRank = $("btnCancelRank");
  const creatorRankWrap = $("creatorRankWrap");
  const creatorRankSummary = $("creatorRankSummary");
  const creatorRankList = $("creatorRankList");
  const creatorRankStatus = $("creatorRankStatus");
  const creatorRankEmpty = $("creatorRankEmpty");
  const rankPlatformChip = $("rankPlatformChip");
  const creatorInputLabel = $("creatorInputLabel");
  const tabCreator = $("tabCreator");
  const tabDirect = $("tabDirect");
  const creatorSourcePanel = $("creatorSourcePanel");
  const directSourcePanel = $("directSourcePanel");
  const directInputHelp = $("directInputHelp");
  const selectedContentCard = $("selectedContentCard");
  const selectedContentLabel = $("selectedContentLabel");
  const selectedContentTitle = $("selectedContentTitle");
  const selectedContentMeta = $("selectedContentMeta");
  const selectedContentList = $("selectedContentList");
  const btnClearSelection = $("btnClearSelection");
  const launchSummaryTitle = $("launchSummaryTitle");
  const btnStart = $("btnStart");
  const btnBackSetup = $("btnBackSetup");
  const btnStop = $("btnStop");
  const btnClearLogs = $("btnClearLogs");
  const btnCopyLogs = $("btnCopyLogs");
  const btnRefreshFiles = $("btnRefreshFiles");
  const btnDownload = $("btnDownload");
  const logConsole = $("logConsole");
  const statusBadge = $("statusBadge");
  const statusPlatform = $("statusPlatform");
  const statusMode = $("statusMode");
  const statusStarted = $("statusStarted");
  const statusProgress = $("statusProgress");
  const taskResultBanner = $("taskResultBanner");
  const statusProgressBar = $("statusProgressBar");
  const fileList = $("fileList");
  const previewMeta = $("previewMeta");
  const previewPath = $("previewPath");
  const previewContent = $("previewContent");
  const previewTableWrap = $("previewTableWrap");

  let platforms = [];
  let logsWs = null;
  let statusWs = null;
  let selectedFilePath = null;
  let progressPollTimer = null;
  let reconnectTimer = null;
  let reconnectAttempt = 0;
  let previewAbortController = null;
  let lastResultRefreshKey = null;
  const PROGRESS_POLL_MS = 20 * 1000;
  const MAX_LOG_LINES = 800;
  const NOTIFY_STORAGE_KEY = "vc_last_notified_finished_at";
  const SETUP_STORAGE_KEY = "vc_setup_draft_v1";
  const appState = {
    platform: "bili",
    sourceMode: "creator",
    selectedContents: [],
    rankLoading: false,
    taskStatus: "idle",
    trackingTask: false,
    previousStatus: "idle",
  };

  const STATUS_LABELS = {
    idle: "空闲",
    running: "运行中",
    stopping: "停止中",
    error: "错误",
  };

  const PLATFORM_LABELS = {
    xhs: "小红书",
    dy: "抖音",
    ks: "快手",
    bili: "B站",
    wb: "微博",
    tieba: "百度贴吧",
    zhihu: "知乎",
  };

  const CREATOR_RANK_META = {
    bili: {
      inputLabel: "创作者主页链接",
      placeholder: "https://space.bilibili.com/20813884",
      creatorTerm: "创作者",
      contentTerm: "视频",
    },
    dy: {
      inputLabel: "博主主页链接",
      placeholder: "https://www.douyin.com/user/MS4wLjABAAAA...",
      creatorTerm: "博主",
      contentTerm: "视频",
    },
    xhs: {
      inputLabel: "博主主页链接",
      placeholder: "https://www.xiaohongshu.com/user/profile/5e...",
      creatorTerm: "博主",
      contentTerm: "笔记",
    },
    ks: {
      inputLabel: "博主主页链接",
      placeholder: "https://www.kuaishou.com/profile/3x...",
      creatorTerm: "博主",
      contentTerm: "视频",
    },
    wb: {
      inputLabel: "博主主页链接",
      placeholder: "https://weibo.com/u/1234567890",
      creatorTerm: "博主",
      contentTerm: "微博",
    },
    tieba: {
      inputLabel: "用户主页链接",
      placeholder: "https://tieba.baidu.com/home/main?id=tb...",
      creatorTerm: "用户",
      contentTerm: "帖子",
    },
    zhihu: {
      inputLabel: "用户主页链接",
      placeholder: "https://www.zhihu.com/people/xxx",
      creatorTerm: "用户",
      contentTerm: "内容",
    },
  };

  const SAVE_PATH_STORAGE_KEY = "commentCrawlerSavePath";
  const SAFE_CRAWL_SLEEP_SEC = 4;
  const MAX_MULTI_SELECT = 20;
  const DEFAULT_SETUP_STATUS = "请选择平台并选择要采集的内容。";

  function buildFolderSlug(title, idLabel) {
    const slugId = idLabel || "content";
    return `${String(title || "").slice(0, 12).replace(/\s+/g, "_")}_${slugId}`.slice(0, 80);
  }

  function getSelectedIdsValue() {
    return appState.selectedContents.map((item) => item.value).filter(Boolean).join(",");
  }

  function isRankItemSelected(pickValue, idLabel) {
    const key = pickValue || idLabel;
    return appState.selectedContents.some((item) => item.key === key);
  }

  function renderSelectedContentCard() {
    const count = appState.selectedContents.length;
    if (!count) {
      selectedContentCard.hidden = true;
      if (selectedContentList) {
        selectedContentList.hidden = true;
        selectedContentList.innerHTML = "";
      }
      return;
    }

    selectedContentCard.hidden = false;
    if (selectedContentLabel) {
      selectedContentLabel.textContent = count > 1 ? `已选用 ${count} 条内容` : "已选择内容";
    }

    if (count === 1) {
      const item = appState.selectedContents[0];
      selectedContentTitle.textContent = item.title || "已选择内容";
      selectedContentMeta.textContent = item.meta || PLATFORM_LABELS[appState.platform];
      if (selectedContentList) {
        selectedContentList.hidden = true;
        selectedContentList.innerHTML = "";
      }
      updateSavePathPreview({ folder: item.folderSlug });
      return;
    }

    selectedContentTitle.textContent = `共 ${count} 条，将依次采集`;
    selectedContentMeta.textContent = "每条内容的评论会保存到独立子文件夹，互不混合。";
    if (selectedContentList) {
      selectedContentList.hidden = false;
      selectedContentList.innerHTML = appState.selectedContents
        .map((item) => `<li>${escapeHtml(item.title || item.value)}</li>`)
        .join("");
    }
    updateSavePathPreviewForMulti();
  }

  function updateSavePathPreviewForMulti() {
    if (!savePathPreviewTree || appState.selectedContents.length <= 1) return;
    const root = (saveDataPath?.value || "./data/comments").trim().replace(/\/+$/, "") || "./data/comments";
    const format = saveFormat?.value || "csv";
    const ext = format === "excel" ? "xlsx" : format;
    const date = new Date().toISOString().slice(0, 10);
    const fileName = ext === "xlsx" ? `comments_${date.replace(/-/g, "")}_120000.${ext}` : `comments_${date}.${ext}`;
    const folders = appState.selectedContents.slice(0, 4);
    const lines = folders.map((item, index) => {
      const prefix = index === folders.length - 1 && appState.selectedContents.length <= 4 ? "└──" : "├──";
      return `${prefix} ${item.folderSlug}/\n    └── ${fileName}`;
    });
    if (appState.selectedContents.length > 4) {
      lines.push(`└── … 共 ${appState.selectedContents.length} 个独立文件夹`);
    }
    savePathPreviewTree.textContent = `${root}/\n${lines.join("\n")}`;
  }

  function refreshRankRowStates() {
    creatorRankList.querySelectorAll(".rank-item").forEach((row) => {
      const pickValue = row.dataset.pickValue || "";
      const idLabel = row.dataset.idLabel || "";
      const selected = isRankItemSelected(pickValue, idLabel);
      row.classList.toggle("selected", selected);
      const btn = row.querySelector("button");
      if (btn) btn.textContent = selected ? "已选用" : "选用";
    });
  }

  function setDirectSelection(content) {
    appState.selectedContents = [
      {
        key: content.value,
        value: content.value,
        title: content.title || "直接粘贴的内容",
        meta: content.meta || PLATFORM_LABELS[appState.platform],
        idLabel: "",
        folderSlug: buildFolderSlug(content.title, "content"),
      },
    ];
    videoInput.value = content.value || "";
    renderSelectedContentCard();
    persistSetupDraft();
    updateStartAvailability();
  }

  function toggleRankSelection(item, meta, platformLabel) {
    const pickValue = item.url || item.video_id || item.bvid || "";
    const idLabel = item.id_label || item.bvid || item.video_id || "";
    const key = pickValue || idLabel;
    if (!key) return;

    const existingIndex = appState.selectedContents.findIndex((entry) => entry.key === key);
    if (existingIndex >= 0) {
      appState.selectedContents.splice(existingIndex, 1);
    } else {
      if (appState.selectedContents.length >= MAX_MULTI_SELECT) {
        setInlineStatus(
          creatorRankStatus,
          `最多同时选用 ${MAX_MULTI_SELECT} 条内容，请先取消部分选用。`,
          "error"
        );
        return;
      }
      appState.selectedContents.push({
        key,
        value: pickValue,
        title: item.title || `${meta.contentTerm} ${idLabel}`,
        meta: `${platformLabel} · ${item.comment_count.toLocaleString()} 条评论 · ${idLabel}`,
        idLabel,
        folderSlug: buildFolderSlug(item.title, idLabel),
      });
    }

    refreshRankRowStates();
    renderSelectedContentCard();
    persistSetupDraft();
    updateStartAvailability();
    if (appState.selectedContents.length) {
      selectedContentCard.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  }

  function formatApiError(detail, fallback) {
    if (detail == null || detail === "") return fallback;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      return detail
        .map((item) => {
          if (typeof item === "string") return item;
          if (item && typeof item === "object") {
            const field = Array.isArray(item.loc) ? item.loc.filter((p) => p !== "body").join(".") : "";
            const msg = item.msg || JSON.stringify(item);
            return field ? `${field}: ${msg}` : msg;
          }
          return String(item);
        })
        .join("；");
    }
    if (typeof detail === "object") {
      return detail.msg || detail.message || JSON.stringify(detail);
    }
    return String(detail);
  }

  async function apiFetch(path, options = {}) {
    const res = await fetch(`${API}${path}`, {
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
      ...options,
    });
    if (!res.ok) {
      let detail = res.statusText;
      try {
        const body = await res.json();
        detail = formatApiError(body.detail || body.message, detail);
      } catch (_) {}
      throw new Error(detail);
    }
    return res.json();
  }

  function buildSavePathPreview(rootPath, videoExample) {
    const root = (rootPath || "./data/comments").trim().replace(/\/+$/, "") || "./data/comments";
    const folder = videoExample?.folder || "视频标题简写_BV1xxxxxx";
    const format = saveFormat?.value || "csv";
    const ext = format === "excel" ? "xlsx" : format;
    const date = new Date().toISOString().slice(0, 10);
    const fileName = ext === "xlsx" ? `comments_${date.replace(/-/g, "")}_120000.${ext}` : `comments_${date}.${ext}`;
    return `${root}/\n└── ${folder}/\n    ├── ${fileName}\n    ├── videos_${date}.${ext === "xlsx" ? "csv" : ext}\n    └── creators_${date}.${ext === "xlsx" ? "csv" : ext}`;
  }

  function updateSavePathPreview(videoExample) {
    if (!savePathPreviewTree) return;
    savePathPreviewTree.textContent = buildSavePathPreview(saveDataPath?.value, videoExample);
  }

  function parseSaveDataPathInput() {
    const raw = (saveDataPath?.value || "").trim();
    if (!raw) {
      return { value: "./data/comments", error: "保存根目录不能为空，已使用默认路径 ./data/comments" };
    }
    if (raw.includes("..")) {
      return { value: null, error: "保存根目录不能包含 ..，请使用 ./data/ 下的路径" };
    }
    return { value: raw };
  }

  function persistSaveDataPath(path) {
    try {
      localStorage.setItem(SAVE_PATH_STORAGE_KEY, path);
    } catch (_) {}
  }

  function loadSavedSaveDataPath() {
    try {
      const saved = localStorage.getItem(SAVE_PATH_STORAGE_KEY);
      if (saved && saveDataPath) saveDataPath.value = saved;
      updateSavePathPreview();
    } catch (_) {}
  }

  async function loadDefaults() {
    try {
      const data = await apiFetch("/api/config/defaults");
      if (saveDataPath && !localStorage.getItem(SAVE_PATH_STORAGE_KEY) && data.save_data_path) {
        saveDataPath.value = data.save_data_path;
      }
      updateSavePathPreview();
    } catch (_) {}
  }

  function formatSize(bytes) {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }

  function formatTime(ts) {
    if (!ts) return "—";
    const d = new Date(ts);
    if (Number.isNaN(d.getTime())) return ts;
    return d.toLocaleString("zh-CN");
  }

  function appendLog(entry) {
    const line = document.createElement("div");
    line.className = `log-line ${entry.level || "info"}`;
    line.textContent = `[${entry.timestamp || ""}] ${entry.message || ""}`;
    logConsole.appendChild(line);
    while (logConsole.children.length > MAX_LOG_LINES) {
      logConsole.removeChild(logConsole.firstChild);
    }
    logConsole.scrollTop = logConsole.scrollHeight;
  }

  function clearLogs() {
    logConsole.innerHTML = '<div class="log-line info">日志已清空</div>';
  }

  async function copyLogs() {
    const text = Array.from(logConsole.querySelectorAll(".log-line"))
      .map((el) => el.textContent || "")
      .join("\n")
      .trim();
    if (!text) {
      appendLog({ level: "info", timestamp: "", message: "暂无日志可复制" });
      return;
    }
    try {
      await navigator.clipboard.writeText(text);
      appendLog({ level: "info", timestamp: "", message: "日志已复制到剪贴板" });
    } catch (err) {
      appendLog({ level: "error", timestamp: "", message: `复制失败：${err.message}` });
    }
  }

  function updateTaskResultBanner(status) {
    if (!taskResultBanner) return;
    if (!status?.result_kind || status.status === "running" || status.status === "stopping") {
      taskResultBanner.hidden = true;
      taskResultBanner.innerHTML = "";
      return;
    }
    taskResultBanner.hidden = false;
    taskResultBanner.className = `task-result-banner ${status.result_kind}`;
    taskResultBanner.innerHTML = `
      <strong>${escapeHtml(status.result_title || "任务结束")}</strong>
      <p>${escapeHtml(status.result_message || "")}</p>
      <div class="result-actions">
        <button class="btn primary sm" type="button" data-result-action="view">查看结果</button>
        <button class="btn ghost sm" type="button" data-result-action="new">建立新任务</button>
      </div>
    `;
    taskResultBanner.querySelector('[data-result-action="view"]')?.addEventListener("click", async () => {
      await refreshFiles({ selectLatest: true });
      document.querySelector(".results-card")?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
    taskResultBanner.querySelector('[data-result-action="new"]')?.addEventListener("click", () => {
      showSetup();
      clearSelectedContent(true);
      setupStatus.textContent = DEFAULT_SETUP_STATUS;
      setupStatus.className = "setup-status";
      window.scrollTo({ top: 0, behavior: "smooth" });
    });
  }

  async function ensureNotificationPermission() {
    if (!("Notification" in window)) return false;
    if (Notification.permission === "granted") return true;
    if (Notification.permission === "denied") return false;
    return (await Notification.requestPermission()) === "granted";
  }

  function notifyTaskResult(status) {
    if (!status?.result_kind || !status.finished_at) return;
    const notifyKey = status.finished_at;
    if (sessionStorage.getItem(NOTIFY_STORAGE_KEY) === notifyKey) {
      updateTaskResultBanner(status);
      return;
    }
    sessionStorage.setItem(NOTIFY_STORAGE_KEY, notifyKey);
    updateTaskResultBanner(status);

    if (!("Notification" in window) || Notification.permission !== "granted") {
      return;
    }
    try {
      new Notification(status.result_title || "抓取任务结束", {
        body: status.result_message || "",
        tag: `vc-crawl-${notifyKey}`,
        requireInteraction: status.result_kind !== "completed",
      });
    } catch (_) {}
  }

  function updateSetupStatusFromBackend(status) {
    if (!setupStatus || !setupView || setupView.hidden) return;
    if (!status) {
      setupStatus.textContent = DEFAULT_SETUP_STATUS;
      return;
    }
    if (status.status === "running" || status.status === "stopping") {
      setupStatus.textContent = "检测到抓取任务正在运行，正在打开运行视图…";
      return;
    }
    if (status.result_kind && status.result_message) {
      setupStatus.textContent = `${status.result_title || "上次任务结束"}：${status.result_message}`;
      return;
    }
    setupStatus.textContent = DEFAULT_SETUP_STATUS;
  }

  function maybeRefreshResultsAfterTask(status) {
    if (!workspace || workspace.hidden || !status?.result_kind) return;
    const refreshKey = status.finished_at || `${status.result_kind}:${status.started_at || ""}`;
    if (lastResultRefreshKey === refreshKey) return;
    lastResultRefreshKey = refreshKey;
    refreshFiles({ selectLatest: true });
  }

  function handleTerminalStatus(status) {
    const endedStates = new Set(["idle", "error"]);
    const wasActive =
      appState.trackingTask ||
      appState.previousStatus === "running" ||
      appState.previousStatus === "stopping";
    if (wasActive && endedStates.has(status.status) && status.result_kind) {
      notifyTaskResult(status);
      appState.trackingTask = false;
      updateSetupStatusFromBackend(status);
      maybeRefreshResultsAfterTask(status);
    }
    if (status.status === "running") {
      appState.trackingTask = true;
      if (taskResultBanner) {
        taskResultBanner.hidden = true;
      }
    }
    appState.previousStatus = status.status || "idle";
  }

  function formatProgress(status) {
    const crawled = status.comments_crawled;
    if (crawled == null) {
      if (status.status === "running" || status.status === "stopping") {
        return "统计中…";
      }
      return "—";
    }
    return `已抓取 ${crawled.toLocaleString()} 条`;
  }

  function updateStatusUI(status, options = {}) {
    const { updateProgress = false } = options;
    handleTerminalStatus(status);
    appState.taskStatus = status.status || "idle";
    statusBadge.textContent = STATUS_LABELS[appState.taskStatus] || appState.taskStatus;
    statusBadge.className = `status-badge ${appState.taskStatus}`;
    statusPlatform.textContent = status.platform
      ? PLATFORM_LABELS[status.platform] || status.platform
      : "—";
    statusMode.textContent = status.crawler_type === "detail" ? "详情模式" : (status.crawler_type || "详情模式");
    statusStarted.textContent = formatTime(status.started_at);
    if (updateProgress) {
      statusProgress.textContent = formatProgress(status);
    } else if (appState.taskStatus === "idle") {
      statusProgress.textContent = "—";
    }
    if (statusProgressBar) {
      const isActive = appState.taskStatus === "running" || appState.taskStatus === "stopping";
      statusProgressBar.className = isActive ? "indeterminate" : "";
      statusProgressBar.style.width = isActive ? "42%" : appState.taskStatus === "idle" ? "100%" : "0";
    }
    btnStop.disabled = appState.taskStatus !== "running" && appState.taskStatus !== "stopping";
  }

  async function refreshProgress() {
    try {
      const data = await apiFetch("/api/crawler/status?refresh_progress=true");
      updateStatusUI(data, { updateProgress: true });
    } catch (err) {
      appendLog({ level: "warning", timestamp: "", message: `状态更新失败：${err.message}` });
    }
  }

  function startProgressPolling() {
    stopProgressPolling();
    refreshProgress();
    progressPollTimer = setInterval(refreshProgress, PROGRESS_POLL_MS);
  }

  function stopProgressPolling() {
    if (progressPollTimer) {
      clearInterval(progressPollTimer);
      progressPollTimer = null;
    }
  }

  function setInlineStatus(element, message = "", level = "") {
    if (!element) return;
    element.textContent = message;
    element.className = `inline-status${level ? ` ${level}` : ""}`;
  }

  function persistSetupDraft() {
    try {
      localStorage.setItem(
        SETUP_STORAGE_KEY,
        JSON.stringify({
          platform: appState.platform,
          sourceMode: appState.sourceMode,
          creatorUrl: creatorInput?.value || "",
          directValue: appState.sourceMode === "direct" ? videoInput?.value || "" : "",
          saveFormat: saveFormat?.value || "csv",
          enableSubComments: Boolean(enableSubComments?.checked),
          savePath: saveDataPath?.value || "./data/comments",
        })
      );
    } catch (err) {
      console.warn("无法保存设置草稿", err);
    }
  }

  function loadSetupDraft() {
    try {
      const draft = JSON.parse(localStorage.getItem(SETUP_STORAGE_KEY) || "{}");
      if (draft.platform) appState.platform = draft.platform;
      if (draft.sourceMode) appState.sourceMode = draft.sourceMode;
      if (creatorInput && draft.creatorUrl) creatorInput.value = draft.creatorUrl;
      if (videoInput && draft.directValue) videoInput.value = draft.directValue;
      if (saveFormat && draft.saveFormat) saveFormat.value = draft.saveFormat;
      if (enableSubComments) enableSubComments.checked = Boolean(draft.enableSubComments);
      if (saveDataPath && draft.savePath) saveDataPath.value = draft.savePath;
    } catch (err) {
      console.warn("无法恢复设置草稿", err);
    }
  }

  function setSourceMode(mode) {
    appState.sourceMode = mode === "direct" ? "direct" : "creator";
    const isCreator = appState.sourceMode === "creator";
    tabCreator.classList.toggle("active", isCreator);
    tabDirect.classList.toggle("active", !isCreator);
    tabCreator.setAttribute("aria-selected", String(isCreator));
    tabDirect.setAttribute("aria-selected", String(!isCreator));
    creatorSourcePanel.hidden = !isCreator;
    directSourcePanel.hidden = isCreator;

    if (!isCreator && videoInput.value.trim()) {
      setDirectSelection({
        value: videoInput.value.trim(),
        title: "直接粘贴的内容",
        meta: `${PLATFORM_LABELS[appState.platform]} · 待采集`,
      });
    } else if (isCreator) {
      clearSelectedContent(false);
    }
    persistSetupDraft();
    updateStartAvailability();
  }

  function clearSelectedContent(clearInput = true) {
    appState.selectedContents = [];
    selectedContentCard.hidden = true;
    selectedContentTitle.textContent = "—";
    selectedContentMeta.textContent = "—";
    if (selectedContentList) {
      selectedContentList.hidden = true;
      selectedContentList.innerHTML = "";
    }
    refreshRankRowStates();
    if (clearInput) videoInput.value = "";
    updateSavePathPreview();
    persistSetupDraft();
    updateStartAvailability();
  }

  function validateSetup() {
    if (!appState.platform) return "请选择内容平台";
    if (!appState.selectedContents.length) {
      return appState.sourceMode === "creator"
        ? "请查询创作者并选用至少一条内容"
        : "请粘贴有效的内容链接或 ID";
    }
    const savePathResult = parseSaveDataPathInput();
    if (!savePathResult.value) return savePathResult.error;
    return "";
  }

  function updateStartAvailability() {
    const error = validateSetup();
    btnStart.disabled = Boolean(error) || appState.rankLoading;
    if (error) {
      launchSummaryTitle.textContent = "完成设置后即可开始";
      if (!setupStatus.textContent || setupStatus.dataset.transient !== "true") {
        setupStatus.textContent = error;
      }
      setupStatus.className = "setup-status";
      return;
    }
    const meta = CREATOR_RANK_META[appState.platform] || CREATOR_RANK_META.bili;
    const count = appState.selectedContents.length;
    if (count === 1) {
      launchSummaryTitle.textContent = `${PLATFORM_LABELS[appState.platform]} · ${meta.contentTerm}评论采集`;
      setupStatus.textContent = `已选择「${appState.selectedContents[0].title || "目标内容"}」，将保存为 ${saveFormat.value.toUpperCase()}。`;
    } else {
      launchSummaryTitle.textContent = `${PLATFORM_LABELS[appState.platform]} · 批量${meta.contentTerm}评论采集`;
      setupStatus.textContent = `已选用 ${count} 条${meta.contentTerm}，将依次采集并分别保存为 ${saveFormat.value.toUpperCase()}。`;
    }
    setupStatus.className = "setup-status success";
  }

  function updateCreatorRankUI() {
    const meta = CREATOR_RANK_META[appState.platform] || CREATOR_RANK_META.bili;
    const platformLabel = PLATFORM_LABELS[appState.platform] || appState.platform;
    const capabilities = platforms.find((item) => item.value === appState.platform) || {};
    if (rankPlatformChip) {
      rankPlatformChip.textContent = platformLabel;
    }
    if (creatorInputLabel) {
      creatorInputLabel.textContent = meta.inputLabel;
    }
    if (creatorInput && document.activeElement !== creatorInput) {
      creatorInput.placeholder = meta.placeholder;
    }
    if (videoInput && document.activeElement !== videoInput) {
      videoInput.placeholder = capabilities.direct_placeholder || `请输入${platformLabel}${meta.contentTerm}链接或 ID`;
    }
    if (directInputHelp) {
      directInputHelp.textContent = `支持${platformLabel}${meta.contentTerm}完整链接或平台内容 ID；排行中的「${capabilities.engagement_metric || "平台互动"}」按平台原始语意展示。`;
    }
  }

  function renderPlatforms() {
    platformGrid.innerHTML = "";
    platforms.forEach((p) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = `platform-btn${p.value === appState.platform ? " active" : ""}`;
      btn.textContent = p.label;
      btn.dataset.value = p.value;
      btn.setAttribute("aria-pressed", String(p.value === appState.platform));
      btn.addEventListener("click", () => {
        if (appState.platform !== p.value) {
          appState.platform = p.value;
          clearSelectedContent(false);
          creatorRankWrap.hidden = true;
          creatorRankEmpty.hidden = false;
          creatorRankStatus.textContent = "";
        }
        renderPlatforms();
        updateCreatorRankUI();
        persistSetupDraft();
        updateStartAvailability();
      });
      platformGrid.appendChild(btn);
    });
    updateCreatorRankUI();
  }

  function showWorkspace() {
    setupView.hidden = true;
    workspace.hidden = false;
    btnBackSetup.hidden = false;
  }

  function showSetup() {
    setupView.hidden = false;
    workspace.hidden = true;
    btnBackSetup.hidden = true;
    if (appState.taskStatus === "idle") {
      disconnectWebSockets();
    }
    apiFetch("/api/crawler/status?refresh_progress=true")
      .then((status) => {
        updateSetupStatusFromBackend(status);
        updateStatusUI(status, { updateProgress: true });
      })
      .catch(() => {
        if (setupStatus) setupStatus.textContent = DEFAULT_SETUP_STATUS;
      });
  }

  function connectWebSockets() {
    disconnectWebSockets();
    reconnectAttempt = 0;

    logsWs = new WebSocket(`${wsHost}/api/ws/logs`);
    logsWs.onmessage = (ev) => {
      try {
        const data = JSON.parse(ev.data);
        if (data.message) appendLog(data);
      } catch (_) {}
    };
    logsWs.onclose = () => {
      logsWs = null;
      scheduleWebSocketReconnect();
    };

    statusWs = new WebSocket(`${wsHost}/api/ws/status`);
    statusWs.onmessage = (ev) => {
      try {
        const data = JSON.parse(ev.data);
        updateStatusUI(data, { updateProgress: true });
        if (data.status === "idle") {
          stopProgressPolling();
        }
        updateTaskResultBanner(data);
      } catch (_) {}
    };
    statusWs.onclose = () => {
      statusWs = null;
      scheduleWebSocketReconnect();
    };

    startProgressPolling();
  }

  function scheduleWebSocketReconnect() {
    if (appState.taskStatus !== "running" && appState.taskStatus !== "stopping") return;
    if (reconnectTimer) return;
    const delay = Math.min(30000, 1000 * 2 ** reconnectAttempt);
    reconnectAttempt += 1;
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null;
      appendLog({ level: "warning", timestamp: "", message: "实时连接已中断，正在重新连接…" });
      connectWebSockets();
    }, delay);
  }

  function disconnectWebSockets() {
    stopProgressPolling();
    if (reconnectTimer) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
    if (logsWs) {
      logsWs.onclose = null;
      logsWs.close();
      logsWs = null;
    }
    if (statusWs) {
      statusWs.onclose = null;
      statusWs.close();
      statusWs = null;
    }
  }

  async function checkEnvironment() {
    envChip.textContent = "检查环境中…";
    envChip.className = "progress-chip";
    try {
      const result = await apiFetch("/api/env/check");
      if (result.success) {
        envChip.textContent = "环境就绪";
        envChip.className = "progress-chip ok";
        setupStatus.textContent = result.browser
          ? `已检测到 ${result.browser}。点击「查找高评论内容」后，Chrome 会自动打开 B 站登录页。`
          : result.message || "";
        setupStatus.className = "setup-status";
      } else {
        envChip.textContent = result.checks?.uv ? "浏览器未就绪" : "环境异常";
        envChip.className = "progress-chip error";
        setupStatus.textContent = result.error || result.message || "环境检查失败";
        setupStatus.className = "setup-status error";
      }
    } catch (err) {
      envChip.textContent = "环境检查失败";
      envChip.className = "progress-chip error";
      setupStatus.textContent = err.message;
      setupStatus.className = "setup-status error";
    }
  }

  function formatQueryError(message) {
    const text = String(message || "").trim();
    if (!text || text === "查询失败:" || text === "查询失败：") {
      return "排行查询失败。请保持自动打开的 Chrome 窗口不要关闭，等待 1-2 分钟后重试。";
    }
    if (text.includes("launch_persistent_context") || text.includes("BrowserType.launch")) {
      return "浏览器启动失败。请关闭其他 Chrome 窗口，在终端执行 ./run_web.sh 重启服务后再试。";
    }
    if (text.includes("Cannot connect to existing browser")) {
      return "无法连接 Chrome。请在 Chrome 地址栏打开 chrome://inspect/#remote-debugging 并开启远程调试，或重启 ./run_web.sh 让程序自动启动浏览器。";
    }
    if (text.includes("address already in use")) {
      return "服务端口被占用。请在终端执行 kill $(lsof -ti :8766) && ./run_web.sh 后重试。";
    }
    return text.replace(/^查询失败:\s*/i, "").replace(/^查询失败：\s*/i, "");
  }

  async function loadPlatforms() {
    try {
      const data = await apiFetch("/api/config/platforms");
      platforms = data.platforms || [];
      if (platforms.length && !platforms.find((p) => p.value === appState.platform)) {
        appState.platform = platforms[0].value;
      }
      renderPlatforms();
    } catch (err) {
      setupStatus.textContent = `平台加载失败：${err.message}。请刷新页面重试。`;
      setupStatus.className = "setup-status error";
    }
  }

  async function rankCreatorVideos() {
    const creatorUrl = creatorInput.value.trim();
    const meta = CREATOR_RANK_META[appState.platform] || CREATOR_RANK_META.bili;
    const platformLabel = PLATFORM_LABELS[appState.platform] || appState.platform;

    if (!appState.platform) {
      setInlineStatus(creatorRankStatus, "请先选择内容平台", "error");
      return;
    }
    if (!creatorUrl) {
      setInlineStatus(creatorRankStatus, `请输入${meta.inputLabel}`, "error");
      creatorInput.focus();
      return;
    }

    appState.rankLoading = true;
    btnRankCreator.disabled = true;
    btnRankCreator.textContent = "正在查找…";
    btnCancelRank.hidden = false;
    setInlineStatus(
      creatorRankStatus,
      `正在扫描${platformLabel}${meta.creatorTerm}的公开${meta.contentTerm}。Chrome 将自动打开 B 站并弹出登录二维码，请勿关闭该窗口。`,
      "loading"
    );
    creatorRankWrap.hidden = true;
    creatorRankEmpty.hidden = false;
    creatorRankEmpty.innerHTML = "<strong>正在读取公开内容</strong><span>数据较多时可能需要几分钟，请不要重复提交。</span>";
    creatorRankList.innerHTML = "";
    clearSelectedContent(false);
    updateStartAvailability();

    const body = {
      platform: appState.platform,
      creator_url: creatorUrl,
      top_n: parseInt(creatorTopN.value, 10) || 10,
      scan_all: true,
      fetch_order: "default",
    };

    try {
      const data = await apiFetch("/api/creator/comment-rank", {
        method: "POST",
        body: JSON.stringify(body),
      });
      renderCreatorRank(data);
      const completeText = data.scan_complete
        ? `已扫描全部 ${data.total_scanned} 条${meta.contentTerm}`
        : `已扫描 ${data.total_scanned} 条${meta.contentTerm}`;
      setInlineStatus(
        creatorRankStatus,
        `${completeText}，已按评论数从高到低排列。可选用一条或多条作为采集目标。`,
        "success"
      );
    } catch (err) {
      creatorRankEmpty.hidden = false;
      creatorRankEmpty.innerHTML = "<strong>暂时无法取得排行</strong><span>请检查主页链接、登录状态或稍后重试。</span>";
      setInlineStatus(creatorRankStatus, `查询失败：${formatQueryError(err.message)}`, "error");
    } finally {
      appState.rankLoading = false;
      btnRankCreator.disabled = false;
      btnRankCreator.textContent = "查找高评论内容";
      btnCancelRank.hidden = true;
      persistSetupDraft();
      updateStartAvailability();
    }
  }

  async function cancelCreatorRank() {
    btnCancelRank.disabled = true;
    setInlineStatus(creatorRankStatus, "正在取消扫描…", "loading");
    try {
      await apiFetch("/api/creator/cancel", { method: "POST" });
    } catch (err) {
      setInlineStatus(creatorRankStatus, `取消失败：${err.message}`, "error");
    } finally {
      btnCancelRank.disabled = false;
    }
  }

  function renderCreatorRank(data) {
    const meta = CREATOR_RANK_META[data.platform || appState.platform] || CREATOR_RANK_META.bili;
    const platformLabel = PLATFORM_LABELS[data.platform || appState.platform] || data.platform || "";
    creatorRankWrap.hidden = false;
    creatorRankEmpty.hidden = true;
    creatorRankSummary.innerHTML = `
      <strong>${escapeHtml(data.creator_name || meta.creatorTerm)}</strong>
      · ${escapeHtml(platformLabel)} · ID ${escapeHtml(data.creator_id)}
      · 已扫描 ${data.total_scanned} 条${meta.contentTerm}
      · 按<strong>评论数</strong>排序，显示前 ${(data.top_videos || []).length} 名
    `;
    creatorRankList.innerHTML = "";

    (data.top_videos || []).forEach((item) => {
      const pickValue = item.url || item.video_id || item.bvid || "";
      const idLabel = item.id_label || item.bvid || item.video_id || "";
      const row = document.createElement("div");
      const topClass = item.rank <= 3 ? ` top${item.rank}` : "";
      row.className = `rank-item${topClass}`;
      row.dataset.pickValue = pickValue;
      row.dataset.idLabel = idLabel;
      row.innerHTML = `
        <div class="col-rank"><span class="rank-badge">${item.rank}</span></div>
        <div class="rank-comments">${item.comment_count.toLocaleString()}<small>条评论</small></div>
        <div class="rank-title">
          <div>${escapeHtml(item.title)}</div>
          <div class="rank-meta">${escapeHtml(idLabel)} · ${escapeHtml(item.metric_label || "平台互动")} ${(item.play_count || 0).toLocaleString()}</div>
        </div>
        <div class="rank-action"><button class="btn secondary sm" type="button">选用</button></div>
      `;
      row.querySelector("button").addEventListener("click", () => {
        if (data.platform) {
          appState.platform = data.platform;
          renderPlatforms();
        }
        toggleRankSelection(item, meta, platformLabel);
      });
      if (isRankItemSelected(pickValue, idLabel)) {
        row.classList.add("selected");
        row.querySelector("button").textContent = "已选用";
      }
      creatorRankList.appendChild(row);
    });
  }

  function escapeHtml(text) {
    return String(text || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  async function startCrawler() {
    const validationError = validateSetup();
    if (validationError) {
      setupStatus.textContent = validationError;
      setupStatus.className = "setup-status error";
      return;
    }
    const videoIds = getSelectedIdsValue();
    const selectedCount = appState.selectedContents.length;

    btnStart.disabled = true;
    setupStatus.textContent = "正在启动抓取任务…";
    setupStatus.className = "setup-status loading";

    try {
      const runningCheck = await apiFetch("/api/crawler/status");
      if (runningCheck.status === "running" || runningCheck.status === "stopping") {
        appState.trackingTask = true;
        showWorkspace();
        connectWebSockets();
        updateStatusUI(runningCheck, { updateProgress: true });
        appendLog({
          level: "info",
          timestamp: "",
          message: "已有抓取任务在运行，已切换到运行视图",
        });
        return;
      }
    } catch (_) {}

    const savePathResult = parseSaveDataPathInput();
    if (savePathResult.error && !savePathResult.value) {
      setupStatus.textContent = savePathResult.error;
      btnStart.disabled = false;
      return;
    }

    const body = {
      platform: appState.platform,
      login_type: "qrcode",
      crawler_type: "detail",
      specified_ids: videoIds,
      enable_comments: true,
      enable_sub_comments: enableSubComments.checked,
      save_option: saveFormat.value,
      save_data_path: savePathResult.value,
      max_notes_count: selectedCount,
      headless: false,
      enable_safe_crawl: true,
      crawler_max_sleep_sec: SAFE_CRAWL_SLEEP_SEC,
      split_by_video: true,
    };

    try {
      await ensureNotificationPermission();
      await apiFetch("/api/crawler/start", {
        method: "POST",
        body: JSON.stringify(body),
      });
      persistSaveDataPath(savePathResult.value);
      persistSetupDraft();
      appState.trackingTask = true;
      appState.previousStatus = "running";
      showWorkspace();
      window.scrollTo({ top: 0, behavior: "smooth" });
      clearLogs();
      appendLog({
        level: "success",
        timestamp: "",
        message:
          selectedCount > 1
            ? `批量采集已启动：${selectedCount} 条内容，每条将保存到独立子文件夹（${savePathResult.value}）`
            : `抓取任务已启动，保存至 ${savePathResult.value}`,
      });
      connectWebSockets();
      const notices = [savePathResult.error].filter(Boolean);
      if (notices.length) {
        appendLog({ level: "warning", timestamp: "", message: notices.join("；") });
      }
    } catch (err) {
      setupStatus.textContent = `启动失败：${err.message}`;
      setupStatus.className = "setup-status error";
    } finally {
      updateStartAvailability();
    }
  }

  async function stopCrawler() {
    btnStop.disabled = true;
    try {
      await apiFetch("/api/crawler/stop", { method: "POST" });
      appendLog({ level: "warning", timestamp: "", message: "已发送停止请求" });
    } catch (err) {
      appendLog({ level: "error", timestamp: "", message: `停止失败：${err.message}` });
      btnStop.disabled = false;
    }
  }

  async function refreshFiles(options = {}) {
    const { selectLatest = false } = options;
    try {
      const data = await apiFetch("/api/data/files");
      const files = data.files || [];
      if (!files.length) {
        fileList.innerHTML = '<div class="empty-state"><strong>暂无结果文件</strong><span>采集完成后，文件会自动出现在这里。</span></div>';
        return;
      }

      fileList.innerHTML = "";
      files.forEach((file) => {
        const item = document.createElement("div");
        item.className = `file-item${file.path === selectedFilePath ? " active" : ""}`;
        const countText = file.record_count != null ? ` · ${file.record_count} 条` : "";
        item.innerHTML = `
          <div class="file-item-info">
            <span class="file-item-name">${file.name}</span>
            <span class="file-item-meta">${formatSize(file.size)}${countText}</span>
          </div>
        `;
        item.addEventListener("click", () => previewFile(file));
        fileList.appendChild(item);
      });
      if (selectLatest && files[0]) {
        await previewFile(files[0]);
        document.querySelector(".results-card")?.scrollIntoView({ behavior: "smooth", block: "nearest" });
      }
    } catch (err) {
      fileList.innerHTML = `<p class="hint center">加载失败：${err.message}</p>`;
    }
  }

  function renderPreviewTable(rows) {
    if (!rows || !rows.length) {
      previewTableWrap.hidden = true;
      previewContent.hidden = false;
      previewContent.textContent = "（无数据）";
      return;
    }
    const columns = Object.keys(rows[0]);
    const thead = `<tr>${columns.map((col) => `<th>${escapeHtml(col)}</th>`).join("")}</tr>`;
    const tbody = rows
      .map(
        (row) =>
          `<tr>${columns
            .map((col) => `<td title="${escapeHtml(row[col] ?? "")}">${escapeHtml(row[col] ?? "")}</td>`)
            .join("")}</tr>`
      )
      .join("");
    previewTableWrap.innerHTML = `<table class="preview-table"><thead>${thead}</thead><tbody>${tbody}</tbody></table>`;
    previewTableWrap.hidden = false;
    previewContent.hidden = true;
  }

  function renderPreviewJson(rows) {
    previewTableWrap.hidden = true;
    previewContent.hidden = false;
    previewContent.textContent = JSON.stringify(rows, null, 2);
  }

  async function previewFile(file) {
    if (previewAbortController) {
      previewAbortController.abort();
    }
    previewAbortController = new AbortController();
    const { signal } = previewAbortController;

    selectedFilePath = file.path;
    btnDownload.hidden = false;
    btnDownload.href = `/api/data/download/${encodeURI(file.path)}`;
    btnDownload.download = file.name;

    Array.from(fileList.querySelectorAll(".file-item")).forEach((el) => {
      el.classList.toggle("active", el.querySelector(".file-item-name")?.textContent === file.name);
    });

    previewMeta.textContent = "加载中…";
    previewPath.textContent = "";
    previewContent.textContent = "";
    previewTableWrap.hidden = true;
    previewTableWrap.innerHTML = "";

    try {
      const data = await apiFetch(`/api/data/files/${encodeURI(file.path)}?preview=true&limit=20`, { signal });
      if (signal.aborted) return;
      const rows = data.data || [];
      const totalLabel = data.total == null ? "?" : data.approximate ? `约 ${data.total}` : String(data.total);
      previewMeta.textContent = `${file.name} · 共 ${totalLabel} 条 · 预览前 ${rows.length} 条`;
      previewPath.textContent = `保存位置：data/${file.path}`;

      const isCsv = file.name.toLowerCase().endsWith(".csv");
      const isExcel = /\.xlsx?$/.test(file.name.toLowerCase());
      if (isCsv || isExcel) {
        renderPreviewTable(rows);
      } else {
        renderPreviewJson(rows);
      }
    } catch (err) {
      if (err.name === "AbortError") return;
      previewMeta.textContent = "";
      previewPath.textContent = "";
      previewTableWrap.hidden = true;
      previewContent.hidden = false;
      previewContent.textContent = `预览失败：${err.message}`;
    }
  }

  btnStart.addEventListener("click", startCrawler);
  btnRankCreator.addEventListener("click", rankCreatorVideos);
  btnCancelRank.addEventListener("click", cancelCreatorRank);
  btnBackSetup.addEventListener("click", showSetup);
  btnStop.addEventListener("click", stopCrawler);
  btnClearLogs.addEventListener("click", clearLogs);
  btnCopyLogs.addEventListener("click", copyLogs);
  btnRefreshFiles.addEventListener("click", refreshFiles);
  tabCreator.addEventListener("click", () => setSourceMode("creator"));
  tabDirect.addEventListener("click", () => setSourceMode("direct"));
  btnClearSelection.addEventListener("click", () => {
    clearSelectedContent(true);
    if (appState.sourceMode === "direct") videoInput.focus();
  });
  creatorInput.addEventListener("input", () => {
    persistSetupDraft();
    setInlineStatus(creatorRankStatus, "");
  });
  creatorInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      rankCreatorVideos();
    }
  });
  videoInput.addEventListener("input", () => {
    const value = videoInput.value.trim();
    if (appState.sourceMode === "direct" && value) {
      setDirectSelection({
        value,
        title: "直接粘贴的内容",
        meta: `${PLATFORM_LABELS[appState.platform]} · 待采集`,
      });
    } else if (appState.sourceMode === "direct") {
      clearSelectedContent(false);
    }
    persistSetupDraft();
  });
  if (saveDataPath) {
    saveDataPath.addEventListener("input", () => {
      updateSavePathPreview();
      persistSetupDraft();
      updateStartAvailability();
    });
  }
  if (saveFormat) {
    saveFormat.addEventListener("change", () => {
      updateSavePathPreview();
      persistSetupDraft();
      updateStartAvailability();
    });
  }
  enableSubComments.addEventListener("change", persistSetupDraft);

  async function resumeRunningTaskIfNeeded() {
    try {
      const status = await apiFetch("/api/crawler/status?refresh_progress=true");
      if (status.status === "running" || status.status === "stopping") {
        showWorkspace();
        connectWebSockets();
        updateStatusUI(status, { updateProgress: true });
        appState.trackingTask = true;
        appendLog({
          level: "info",
          timestamp: "",
          message: "已重新连接运行中的抓取任务（刷新页面不会终止后台任务）",
        });
        refreshFiles();
        return;
      }
      appState.trackingTask = false;
      appState.previousStatus = status.status || "idle";
      updateSetupStatusFromBackend(status);
      if (status.result_kind) {
        updateStatusUI(status, { updateProgress: true });
        notifyTaskResult(status);
      }
    } catch (err) {
      console.warn("无法恢复任务状态", err);
      if (setupStatus) setupStatus.textContent = DEFAULT_SETUP_STATUS;
    }
  }

  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState !== "visible") return;
    if (appState.taskStatus === "running" || appState.taskStatus === "stopping") {
      refreshProgress().catch((err) => console.warn("页面恢复时进度刷新失败", err));
    }
  });

  loadSetupDraft();
  loadPlatforms();
  loadSavedSaveDataPath();
  loadDefaults();
  checkEnvironment();
  updateSavePathPreview();
  setSourceMode(appState.sourceMode);
  updateStartAvailability();
  resumeRunningTaskIfNeeded();
})();
