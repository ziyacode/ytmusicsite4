// ============================================================
// app.js — Media Downloader Frontend Logic (v2.0 Turbo)
// ============================================================

const CONFIG = {
  API_BASE: (window.location.origin && window.location.origin.startsWith("http")) 
    ? window.location.origin 
    : "http://localhost:8000",
  INFO_DEBOUNCE_MS: 350,
  TOAST_DURATION_MS: 4000,
};

const State = {
  IDLE:        "idle",
  DETECTING:   "detecting",
  READY:       "ready",
  DOWNLOADING: "downloading",
  DONE:        "done",
  ERROR:       "error",
};

let currentState = State.IDLE;
let currentPlatform = null;
let infoDebounceTimer = null;
let abortController = null;
let lastAttemptedUrl = "";

// ── DOM References ──────────────────────────────────────────
const DOM = {
  // Inputs
  urlInput:          document.getElementById("url-input"),
  clearBtn:          document.getElementById("clear-btn"),
  pasteBtn:          document.getElementById("paste-btn"),

  // Platform badge
  platformBadge:     document.getElementById("platform-badge"),
  platformIcon:      document.getElementById("platform-icon"),
  platformName:      document.getElementById("platform-name"),

  // Media preview
  mediaInfo:         document.getElementById("media-info"),
  thumbnailImg:      document.getElementById("thumbnail-img"),
  mediaTitle:        document.getElementById("media-title"),
  mediaUploader:     document.getElementById("media-uploader"),
  mediaDuration:     document.getElementById("media-duration"),
  mediaSize:         document.getElementById("media-size"),

  // Format options
  formatSection:     document.getElementById("format-section"),
  formatMp4Card:     document.getElementById("format-mp4-card"),
  formatMp3Card:     document.getElementById("format-mp3-card"),
  formatMp4:         document.getElementById("format-mp4"),
  formatMp3:         document.getElementById("format-mp3"),
  watermarkSection:  document.getElementById("watermark-section"),
  watermarkToggle:   document.getElementById("watermark-toggle"),

  // Primary action button
  downloadBtn:       document.getElementById("download-btn"),
  downloadBtnText:   document.getElementById("download-btn-text"),
  downloadBtnIcon:   document.getElementById("download-btn-icon"),

  // Progress section
  progressSection:   document.getElementById("progress-section"),
  progressBar:       document.getElementById("progress-bar"),
  progressPercent:   document.getElementById("progress-percent"),
  progressSpeed:     document.getElementById("progress-speed"),
  progressEta:       document.getElementById("progress-eta"),
  progressSize:      document.getElementById("progress-size"),
  progressPhaseText: document.getElementById("progress-phase-text"),

  // Result section
  resultSection:     document.getElementById("result-section"),
  downloadLink:      document.getElementById("download-link"),
  resultFilename:    document.getElementById("result-filename"),
  resultFilesize:    document.getElementById("result-filesize"),
  resultFormat:      document.getElementById("result-format"),
  resetBtn:          document.getElementById("reset-btn"),

  // Error section
  errorSection:      document.getElementById("error-section"),
  errorMessage:      document.getElementById("error-message"),
  errorRetryBtn:     document.getElementById("error-retry-btn"),

  // Theme
  themeToggle:       document.getElementById("theme-toggle"),
  themeIcon:         document.getElementById("theme-icon"),

  // Toast notification
  toast:             document.getElementById("toast"),
  toastMessage:      document.getElementById("toast-message"),
};

// ── Platform Definitions ─────────────────────────────────────
const PLATFORMS = {
  youtube: {
    name: "YouTube",
    emoji: "▶️",
    patterns: [/youtube\.com/, /youtu\.be/],
    supportsAudio: true,
    supportsWatermark: false,
  },
  tiktok: {
    name: "TikTok",
    emoji: "🎵",
    patterns: [/tiktok\.com/, /vm\.tiktok\.com/],
    supportsAudio: true,
    supportsWatermark: true,
  },
  instagram: {
    name: "Instagram",
    emoji: "📸",
    patterns: [/instagram\.com/],
    supportsAudio: true,
    supportsWatermark: false,
  },
  twitter: {
    name: "Twitter/X",
    emoji: "🐦",
    patterns: [/twitter\.com/, /x\.com/],
    supportsAudio: false,
    supportsWatermark: false,
  },
  facebook: {
    name: "Facebook",
    emoji: "📘",
    patterns: [/facebook\.com/, /fb\.watch/],
    supportsAudio: true,
    supportsWatermark: false,
  },
  reddit: {
    name: "Reddit",
    emoji: "🤖",
    patterns: [/reddit\.com/],
    supportsAudio: true,
    supportsWatermark: false,
  },
  pinterest: {
    name: "Pinterest",
    emoji: "📌",
    patterns: [/pinterest\.com/, /pin\.it/],
    supportsAudio: false,
    supportsWatermark: false,
  },
  generic: {
    name: "Digər sayt",
    emoji: "🌐",
    patterns: [],
    supportsAudio: true,
    supportsWatermark: false,
  },
};

// ── Helpers ──────────────────────────────────────────────────
function detectPlatform(url) {
  const lower = url.toLowerCase();
  for (const [key, config] of Object.entries(PLATFORMS)) {
    if (key === "generic") continue;
    if (config.patterns.some(p => p.test(lower))) return key;
  }
  return "generic";
}

function normalizeUrl(rawUrl) {
  let url = (rawUrl || "").trim();
  if (!url) return "";
  if (!/^https?:\/\//i.test(url)) {
    url = "https://" + url;
  }
  return url;
}

function formatDuration(seconds) {
  if (!seconds || seconds <= 0) return "";
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

function setState(newState) {
  currentState = newState;
  updateUI();
}

function setVisible(el, visible) {
  if (!el) return;
  if (visible) {
    el.classList.remove("hidden");
    el.classList.add("flex");
  } else {
    el.classList.add("hidden");
    el.classList.remove("flex");
  }
}

// ── UI State Machine ─────────────────────────────────────────
function updateUI() {
  const isIdle        = currentState === State.IDLE;
  const isDetecting   = currentState === State.DETECTING;
  const isReady       = currentState === State.READY;
  const isDownloading = currentState === State.DOWNLOADING;
  const isDone        = currentState === State.DONE;
  const isError       = currentState === State.ERROR;

  // Sections visibility
  setVisible(DOM.formatSection,    isReady || isDownloading || isDetecting);
  setVisible(DOM.mediaInfo,        isReady || isDownloading);
  setVisible(DOM.progressSection,  isDownloading);
  setVisible(DOM.resultSection,    isDone);
  setVisible(DOM.errorSection,     isError);

  // Button state & labels
  if (isDetecting) {
    DOM.downloadBtn.disabled = false; // Allow user to click download immediately without waiting for preview!
    DOM.downloadBtnText.textContent = "Yüklə (Məlumat oxunur...)";
    DOM.downloadBtnIcon.innerHTML = `<div class="spinner w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin"></div>`;
  } else if (isDownloading) {
    DOM.downloadBtn.disabled = true;
    DOM.downloadBtnText.textContent = "Yüklənir...";
    DOM.downloadBtnIcon.innerHTML = `<div class="spinner w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin"></div>`;
  } else if (isDone) {
    DOM.downloadBtn.disabled = false;
    DOM.downloadBtnText.textContent = "Yenidən yüklə";
    DOM.downloadBtnIcon.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" class="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M21 12a9 9 0 11-6.219-8.56"/></svg>`;
  } else if (isReady) {
    DOM.downloadBtn.disabled = false;
    DOM.downloadBtnText.textContent = "Yüklə";
    DOM.downloadBtnIcon.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" class="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>`;
  } else {
    // Idle
    DOM.downloadBtn.disabled = true;
    DOM.downloadBtnText.textContent = "Yüklə";
    DOM.downloadBtnIcon.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" class="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>`;
  }
}

// ── Platform Badge ───────────────────────────────────────────
function showPlatformBadge(platformKey) {
  const p = PLATFORMS[platformKey] || PLATFORMS.generic;
  DOM.platformBadge.classList.remove("hidden");
  DOM.platformBadge.classList.add("flex");
  DOM.platformIcon.textContent = p.emoji;
  DOM.platformName.textContent = p.name;

  if (p.supportsWatermark) {
    DOM.watermarkSection.classList.remove("hidden");
    DOM.watermarkSection.classList.add("flex");
  } else {
    DOM.watermarkSection.classList.add("hidden");
    DOM.watermarkSection.classList.remove("flex");
  }

  if (!p.supportsAudio) {
    DOM.formatMp3Card.classList.add("opacity-40", "pointer-events-none");
    selectFormat("mp4");
  } else {
    DOM.formatMp3Card.classList.remove("opacity-40", "pointer-events-none");
  }
}

function hidePlatformBadge() {
  DOM.platformBadge.classList.add("hidden");
  DOM.platformBadge.classList.remove("flex");
}

// ── Format Selection ─────────────────────────────────────────
let selectedFormat = "mp4";

function selectFormat(format) {
  selectedFormat = format;
  const isMp4 = format === "mp4";
  
  DOM.formatMp4Card.classList.toggle("selected", isMp4);
  DOM.formatMp4Card.classList.toggle("border-brand-500", isMp4);
  DOM.formatMp4Card.classList.toggle("border-gray-200", !isMp4);
  DOM.formatMp4Card.classList.toggle("dark:border-gray-700", !isMp4);

  DOM.formatMp3Card.classList.toggle("selected", !isMp4);
  DOM.formatMp3Card.classList.toggle("border-brand-500", !isMp4);
  DOM.formatMp3Card.classList.toggle("border-gray-200", isMp4);
  DOM.formatMp3Card.classList.toggle("dark:border-gray-700", isMp4);

  DOM.formatMp4.checked = isMp4;
  DOM.formatMp3.checked = !isMp4;
}

DOM.formatMp4Card.addEventListener("click", () => selectFormat("mp4"));
DOM.formatMp3Card.addEventListener("click", () => selectFormat("mp3"));

// ── URL Input Handlers ───────────────────────────────────────
function handleUrlChange(immediate = false) {
  const raw = DOM.urlInput.value.trim();
  DOM.clearBtn.classList.toggle("hidden", !raw);
  clearTimeout(infoDebounceTimer);

  if (!raw) {
    setState(State.IDLE);
    hidePlatformBadge();
    currentPlatform = null;
    return;
  }

  const url = normalizeUrl(raw);
  const platform = detectPlatform(url);
  currentPlatform = platform;
  showPlatformBadge(platform);

  setState(State.DETECTING);

  if (immediate) {
    fetchMediaInfo(url);
  } else {
    infoDebounceTimer = setTimeout(() => fetchMediaInfo(url), CONFIG.INFO_DEBOUNCE_MS);
  }
}

DOM.urlInput.addEventListener("input", () => handleUrlChange(false));

DOM.urlInput.addEventListener("paste", () => {
  setTimeout(() => handleUrlChange(true), 20);
});

// Clipboard Paste button
if (DOM.pasteBtn) {
  DOM.pasteBtn.addEventListener("click", async () => {
    try {
      const text = await navigator.clipboard.readText();
      if (text && text.trim()) {
        DOM.urlInput.value = text.trim();
        DOM.urlInput.focus();
        handleUrlChange(true);
        showToast("📋 Link buferdən yapışdırıldı", "info");
      } else {
        DOM.urlInput.focus();
      }
    } catch {
      DOM.urlInput.focus();
    }
  });
}

// Clear button
DOM.clearBtn.addEventListener("click", () => {
  resetAll();
  DOM.urlInput.focus();
});

// Reset Button in Result section
if (DOM.resetBtn) {
  DOM.resetBtn.addEventListener("click", () => {
    resetAll();
    DOM.urlInput.focus();
  });
}

// Retry Button in Error section
if (DOM.errorRetryBtn) {
  DOM.errorRetryBtn.addEventListener("click", () => {
    const url = normalizeUrl(DOM.urlInput.value);
    if (url) {
      startDownload();
    } else {
      resetAll();
      DOM.urlInput.focus();
    }
  });
}

// Enter key starts download immediately
DOM.urlInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") {
    e.preventDefault();
    clearTimeout(infoDebounceTimer);
    const raw = DOM.urlInput.value.trim();
    if (!raw) return;
    startDownload();
  }
});

// ── Fetch Media Preview ──────────────────────────────────────
async function fetchMediaInfo(url) {
  lastAttemptedUrl = url;
  if (abortController) {
    abortController.abort();
  }
  abortController = new AbortController();

  try {
    const res = await fetch(`${CONFIG.API_BASE}/api/info`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
      signal: abortController.signal,
    });

    if (!res.ok) {
      if (currentState === State.DETECTING) {
        setState(State.READY);
      }
      return;
    }

    const info = await res.json();

    // Thumbnail
    if (info.thumbnail) {
      DOM.thumbnailImg.src = info.thumbnail;
      DOM.thumbnailImg.classList.remove("hidden");
    } else {
      DOM.thumbnailImg.classList.add("hidden");
    }

    // Details
    DOM.mediaTitle.textContent = info.title || "Video";
    DOM.mediaUploader.textContent = info.uploader || "";
    DOM.mediaDuration.textContent = formatDuration(info.duration);

    if (info.estimated_size && DOM.mediaSize) {
      DOM.mediaSize.textContent = `💾 ${info.estimated_size}`;
      DOM.mediaSize.classList.remove("hidden");
    } else if (DOM.mediaSize) {
      DOM.mediaSize.classList.add("hidden");
    }

    // Ready to download
    if (currentState === State.DETECTING) {
      setState(State.READY);
    }
  } catch (err) {
    if (err.name === "AbortError") return;
    if (currentState === State.DETECTING) {
      // Don't show hard error for info failure yet, user can still click Download
      setState(State.READY);
    }
  }
}

// ── Real-Time Streaming Download ─────────────────────────────
DOM.downloadBtn.addEventListener("click", () => {
  startDownload();
});

async function startDownload() {
  const raw = DOM.urlInput.value.trim();
  if (!raw) return;

  const url = normalizeUrl(raw);
  lastAttemptedUrl = url;

  setState(State.DOWNLOADING);
  resetProgress();

  try {
    const response = await fetch(`${CONFIG.API_BASE}/api/download`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        url,
        format: selectedFormat,
        no_watermark: DOM.watermarkToggle.checked,
      }),
    });

    if (!response.ok) {
      const err = await response.json().catch(() => ({}));
      showError(err.detail || "Yükləmə xətası baş verdi.");
      return;
    }

    // Read SSE Stream
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop(); // Hold incomplete line

      for (const line of lines) {
        const trimmed = line.trim();
        if (trimmed.startsWith("data: ")) {
          try {
            const event = JSON.parse(trimmed.slice(6));
            handleDownloadEvent(event);
          } catch {
            // JSON parse skip
          }
        }
      }
    }
  } catch (err) {
    showError("Yükləmə zamanı şəbəkə kəsildi. Zəhmət olmasa interneti yoxlayıb yenidən cəhd edin.");
  }
}

function handleDownloadEvent(event) {
  if (event.status === "progress") {
    updateProgress(event.percent, event.speed, event.eta, event.phase, event.size_info);
  } else if (event.status === "done") {
    onDownloadDone(event);
  } else if (event.status === "error") {
    showError(event.message || "Gözlənilməz xəta baş verdi.");
  }
}

// ── Progress UI ──────────────────────────────────────────────
function resetProgress() {
  DOM.progressBar.style.width = "0%";
  DOM.progressPercent.textContent = "0%";
  DOM.progressSpeed.textContent = "";
  DOM.progressEta.textContent = "";
  if (DOM.progressSize) DOM.progressSize.textContent = "";
  if (DOM.progressPhaseText) DOM.progressPhaseText.textContent = "Yüklənməyə hazırlanır...";
}

function updateProgress(percent, speed, eta, phase, sizeInfo) {
  const p = Math.min(Math.max(percent || 0, 0), 100);
  DOM.progressBar.style.width = `${p}%`;
  DOM.progressBar.setAttribute("aria-valuenow", Math.round(p));
  DOM.progressPercent.textContent = `${Math.round(p)}%`;
  
  if (speed) DOM.progressSpeed.textContent = `⚡ ${speed}`;
  if (eta)   DOM.progressEta.textContent = `⏳ ${eta}`;
  if (sizeInfo && DOM.progressSize) DOM.progressSize.textContent = `(${sizeInfo})`;
  
  if (DOM.progressPhaseText && phase) {
    DOM.progressPhaseText.textContent = phase;
  }
}

// ── Download Completion ──────────────────────────────────────
function onDownloadDone(event) {
  updateProgress(100, "", "", "Tamamlandı!", "");
  const downloadUrl = event.download_url || "";
  const displayName = event.display_name || "media";
  const sizeFormatted = event.size_formatted || "";
  const formatName = event.format || (selectedFormat ? selectedFormat.toUpperCase() : "MP4");

  const fullDownloadUrl = `${CONFIG.API_BASE}${downloadUrl}`;
  DOM.downloadLink.href = fullDownloadUrl;
  DOM.downloadLink.setAttribute("download", displayName);

  if (DOM.resultFilename) {
    DOM.resultFilename.textContent = displayName;
  }
  if (DOM.resultFilesize) {
    DOM.resultFilesize.textContent = sizeFormatted ? `💾 ${sizeFormatted}` : "";
    DOM.resultFilesize.style.display = sizeFormatted ? "inline-block" : "none";
  }
  if (DOM.resultFormat) {
    DOM.resultFormat.textContent = formatName;
  }

  setState(State.DONE);
  showToast(`✅ Yükləmə tamamlandı! (${sizeFormatted})`, "success");

  // Trigger browser download safely
  try {
    const triggerLink = document.createElement("a");
    triggerLink.href = fullDownloadUrl;
    triggerLink.setAttribute("download", displayName);
    document.body.appendChild(triggerLink);
    triggerLink.click();
    document.body.removeChild(triggerLink);
  } catch {
    // If popup blocked, user has the prominent 'Cihaza Endir' button
  }
}

// ── Error & Reset Handlers ───────────────────────────────────
function showError(message) {
  DOM.errorMessage.textContent = message;
  setState(State.ERROR);
}

function resetToReady() {
  setState(State.READY);
  setVisible(DOM.resultSection,   false);
  setVisible(DOM.errorSection,    false);
  setVisible(DOM.progressSection, false);
}

function resetAll() {
  clearTimeout(infoDebounceTimer);
  if (abortController) abortController.abort();
  DOM.urlInput.value = "";
  DOM.clearBtn.classList.add("hidden");
  hidePlatformBadge();
  currentPlatform = null;
  setState(State.IDLE);
}

// ── Toast Notification ───────────────────────────────────────
let toastTimer = null;

function showToast(message, type = "success") {
  clearTimeout(toastTimer);
  DOM.toastMessage.textContent = message;
  DOM.toast.classList.remove("hidden", "opacity-0", "translate-y-4");

  const colors = {
    success: ["bg-emerald-600", "dark:bg-emerald-700"],
    error:   ["bg-rose-600", "dark:bg-rose-700"],
    info:    ["bg-indigo-600", "dark:bg-indigo-700"],
  };

  DOM.toast.classList.remove("bg-emerald-600", "dark:bg-emerald-700", "bg-rose-600", "dark:bg-rose-700", "bg-indigo-600", "dark:bg-indigo-700");
  const selectedColors = colors[type] || colors.success;
  DOM.toast.classList.add(...selectedColors);

  toastTimer = setTimeout(() => {
    DOM.toast.classList.add("opacity-0", "translate-y-4");
    setTimeout(() => DOM.toast.classList.add("hidden"), 300);
  }, CONFIG.TOAST_DURATION_MS);
}

// ── Dark / Light Mode ────────────────────────────────────────
const SUN_ICON = `<svg xmlns="http://www.w3.org/2000/svg" class="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg>`;
const MOON_ICON = `<svg xmlns="http://www.w3.org/2000/svg" class="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12.79A9 9 0 1111.21 3 7 7 0 0021 12.79z"/></svg>`;

function applyTheme(isDark) {
  document.documentElement.classList.toggle("dark", isDark);
  DOM.themeIcon.innerHTML = isDark ? SUN_ICON : MOON_ICON;
  localStorage.setItem("theme", isDark ? "dark" : "light");
}

DOM.themeToggle.addEventListener("click", () => {
  const isDark = !document.documentElement.classList.contains("dark");
  applyTheme(isDark);
});

(function initTheme() {
  const saved = localStorage.getItem("theme");
  const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
  applyTheme(saved === "dark" || (!saved && prefersDark));
})();

// ── Global Keyboard Shortcuts ────────────────────────────────
document.addEventListener("keydown", (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "v" && document.activeElement !== DOM.urlInput) {
    DOM.urlInput.focus();
  }
  if (e.key === "Escape" && DOM.urlInput.value) {
    DOM.clearBtn.click();
  }
});

// Initialize default format
selectFormat("mp4");

async function refreshCookieStatus() {
  const statusEl = document.getElementById("cookie-status-text");
  if (!statusEl) return;
  try {
    const res = await fetch(`${CONFIG.API_BASE}/api/health`);
    const data = await res.json();
    const cookies = data.cookies || {};
    if (cookies.loaded && cookies.has_login) {
      statusEl.textContent = `Cookie aktiv (${cookies.count})`;
    } else if (cookies.loaded) {
      statusEl.textContent = "Cookie var, amma login cookie tapılmadı";
    } else {
      statusEl.textContent = "Cookie yüklənməyib";
    }
  } catch {
    statusEl.textContent = "";
  }
}

const cookieUploadBtn = document.getElementById("cookie-upload-btn");
if (cookieUploadBtn) {
  cookieUploadBtn.addEventListener("click", async () => {
    const text = (document.getElementById("cookie-text") || {}).value || "";
    const token = (document.getElementById("cookie-token") || {}).value || "";
    const statusEl = document.getElementById("cookie-status-text");
    if (!text.trim()) {
      showToast("Cookie mətnini yapışdırın", "error");
      return;
    }
    try {
      const res = await fetch(`${CONFIG.API_BASE}/api/cookies`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ cookies: text, token }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        const detail = data.detail || "Cookie qəbul olunmadı";
        if (statusEl) statusEl.textContent = detail;
        showToast(typeof detail === "string" ? detail : "Cookie qəbul olunmadı", "error");
        return;
      }
      if (statusEl) statusEl.textContent = `Cookie aktiv (${(data.cookies || {}).count || 0})`;
      showToast("Cookie qəbul olundu", "success");
    } catch {
      showToast("Cookie yüklənə bilmədi", "error");
    }
  });
  refreshCookieStatus();
}

// Global exports for inline HTML calls
window.setState = setState;
window.State = State;
window.resetToReady = resetToReady;
window.resetAll = resetAll;
window.startDownload = startDownload;
