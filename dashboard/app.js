const PAUSE_THRESHOLDS = Object.freeze({
  voltageMax: 0.5,
  currentMax: 1,
  frequencyMin: 0.1
});
const SUPPORT_EMAIL = "mconsalvo95@gmail.com";
const CSV_DOWNLOAD_NAME = "Reporte de insensibilización.csv";
const XLSX_DOWNLOAD_NAME = "Reporte de insensibilización + graficos.xlsx";
const DAILY_XLSX_DOWNLOAD_NAME = "Promedios diarios de insensibilización.xlsx";

const elements = {
  dashboardStatus: document.querySelector("#dashboard-status"),
  connection: document.querySelector("#connection"),
  connectionLabel: document.querySelector("#connection-label"),
  connectionDetail: document.querySelector("#connection-detail"),
  connectionSymbol: document.querySelector(".connection-symbol"),
  currentTime: document.querySelector("#current-time"),
  currentDate: document.querySelector("#current-date"),
  readingTime: document.querySelector("#reading-time"),
  readingDate: document.querySelector("#reading-date"),
  voltage: document.querySelector("#voltage"),
  current: document.querySelector("#current"),
  frequency: document.querySelector("#frequency"),
  voltageCard: document.querySelector(".voltage-card"),
  currentCard: document.querySelector(".current-card"),
  frequencyCard: document.querySelector(".frequency-card"),
  qualityVoltage: document.querySelector("#quality-voltage"),
  qualityCurrent: document.querySelector("#quality-current"),
  qualityFrequency: document.querySelector("#quality-frequency"),
  processStrip: document.querySelector(".process-strip"),
  processState: document.querySelector("#process-state"),
  processDetail: document.querySelector("#process-detail"),
  systemBanner: document.querySelector("#system-banner"),
  bannerIcon: document.querySelector("#banner-icon"),
  bannerCopy: document.querySelector("#banner-copy"),
  bannerTitle: document.querySelector("#banner-title"),
  bannerMessage: document.querySelector("#banner-message"),
  retryConnection: document.querySelector("#retry-connection"),
  supportEmail: document.querySelector("#support-email"),
  recordsBody: document.querySelector("#records-body"),
  recordCount: document.querySelector("#record-count"),
  recordCountLabel: document.querySelector("#record-count-label"),
  historyMode: document.querySelector("#history-mode"),
  appVersion: document.querySelector("#app-version"),
  lastReading: document.querySelector("#last-reading"),
  emptyChart: document.querySelector("#empty-chart"),
  canvas: document.querySelector("#history-chart"),
  chartTooltip: document.querySelector("#chart-tooltip"),
  chartZoom: document.querySelector("#chart-zoom"),
  chartReset: document.querySelector("#chart-reset"),
  voltageSparkline: document.querySelector("#voltage-sparkline"),
  currentSparkline: document.querySelector("#current-sparkline"),
  frequencySparkline: document.querySelector("#frequency-sparkline"),
  csvExport: document.querySelector("#csv-export"),
  xlsxExport: document.querySelector("#xlsx-export"),
  dailyExport: document.querySelector("#daily-export"),
  reportDownload: document.querySelector("#report-download"),
  exportPeriod: document.querySelector("#export-period"),
  reportCount: document.querySelector("#report-count"),
  reportFormat: document.querySelector("#report-format"),
  reportContent: document.querySelector("#report-content"),
  chartIntervalStep: document.querySelector("#chart-interval-step"),
  chartIntervalSummaryRow: document.querySelector("#chart-interval-summary-row"),
  chartIntervalSummary: document.querySelector("#chart-interval-summary"),
  reportSummaryTitle: document.querySelector("#report-summary-title"),
  workbookPreview: document.querySelector("#workbook-preview"),
  previewReadingCount: document.querySelector("#preview-reading-count"),
  previewAverageVoltage: document.querySelector("#preview-average-voltage"),
  previewAverageCurrent: document.querySelector("#preview-average-current"),
  previewAverageFrequency: document.querySelector("#preview-average-frequency"),
  reportPreviewVoltage: document.querySelector("#report-preview-voltage"),
  reportPreviewCurrent: document.querySelector("#report-preview-current"),
  reportPreviewFrequency: document.querySelector("#report-preview-frequency"),
  exportStatus: document.querySelector("#export-status"),
  archiveWipeOpen: document.querySelector("#archive-wipe-open"),
  archiveWipeStatus: document.querySelector("#archive-wipe-status"),
  archiveWipeDialog: document.querySelector("#archive-wipe-dialog"),
  archiveWipeStep1: document.querySelector("#archive-wipe-step-1"),
  archiveWipeStep2: document.querySelector("#archive-wipe-step-2"),
  archiveWipeCancel: document.querySelector("#archive-wipe-cancel"),
  archiveWipeCancel2: document.querySelector("#archive-wipe-cancel-2"),
  archiveWipeContinue: document.querySelector("#archive-wipe-continue"),
  archiveWipeConfirm: document.querySelector("#archive-wipe-confirm"),
  archiveWipeConfirmBtn: document.querySelector("#archive-wipe-confirm-btn"),
  samplingForm: document.querySelector("#sampling-form"),
  pollInterval: document.querySelector("#poll-interval"),
  samplingSave: document.querySelector("#sampling-save"),
  samplingResult: document.querySelector("#sampling-result"),
  dailyReadingEstimate: document.querySelector("#daily-reading-estimate"),
  historyFilterForm: document.querySelector("#history-filter-form"),
  historyFrom: document.querySelector("#history-from"),
  historyTo: document.querySelector("#history-to"),
  historyFilterClear: document.querySelector("#history-filter-clear"),
  historyFilterResult: document.querySelector("#history-filter-result"),
  activeRangeLabel: document.querySelector("#active-range-label"),
  workdayFilter: document.querySelector("#workday-filter"),
  customRangeToggle: document.querySelector("#custom-range-toggle"),
  historyPeriodLabel: document.querySelector("#history-period-label"),
  historySourceLabel: document.querySelector("#history-source-label"),
  historyViewFilterForm: document.querySelector("#history-view-filter-form"),
  historyViewFrom: document.querySelector("#history-view-from"),
  historyViewTo: document.querySelector("#history-view-to"),
  historyViewFilterClear: document.querySelector("#history-view-filter-clear"),
  historyViewFilterResult: document.querySelector("#history-view-filter-result"),
  historyRangeResult: document.querySelector("#history-range-result"),
  recordsSection: document.querySelector(".records-section"),
  reportCustomForm: document.querySelector("#report-custom-form"),
  reportFrom: document.querySelector("#report-from"),
  reportTo: document.querySelector("#report-to"),
  reportCustomResult: document.querySelector("#report-custom-result")
};

let currentReadings = [];
let currentRangeCount = 0;
let historyReadings = [];
let historySampleMinutes = 15;
let historySourceRange = { key: "workday" };
let latestStatusData = null;
let activeRange = { key: "15m", minutes: 15, label: "Últimos 15 minutos", rolling: true };
let currentView = "live";
let historyQuality = "all";
let reportFormat = "xlsx";
let chartExportInterval = "auto";
let chartMode = "overview";
let chartPoints = [];
let chartPointIndex = -1;
let rangeRequestId = 0;
let historyRequestId = 0;
let lastDashboardStatus = "";

function isNumeric(value) {
  return value !== null && value !== undefined && value !== "" && Number.isFinite(Number(value));
}

function number(value, digits = 1) {
  if (!isNumeric(value)) return "--";
  return Number(value).toLocaleString("es-AR", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits
  });
}

function supportComposeHref(subject, detail) {
  const version = (elements.appVersion?.textContent || "").trim();
  const lastReading = (elements.lastReading?.textContent || "").trim();
  const body = [
    "Describa qué estaba haciendo cuando apareció el problema.",
    "",
    "---",
    `Asunto: ${subject}`,
    `Detalle: ${detail}`,
    version,
    lastReading
  ].filter(Boolean).join("\n");
  const query = new URLSearchParams({
    view: "cm",
    fs: "1",
    to: SUPPORT_EMAIL,
    su: subject,
    body
  });
  return `https://mail.google.com/mail/?${query.toString()}`;
}

function setSupportMailto(element, enabled, subject, detail) {
  if (!element) return;
  if (enabled) {
    element.setAttribute("href", supportComposeHref(subject, detail));
    element.setAttribute("target", "_blank");
    element.setAttribute("rel", "noopener noreferrer");
  } else {
    element.removeAttribute("href");
    element.removeAttribute("target");
    element.removeAttribute("rel");
  }
}

function updateSupportEmailLink() {
  setSupportMailto(
    elements.supportEmail,
    true,
    "Soporte VFREG Visor",
    "Consulta o duda desde el dashboard."
  );
}

function timestampParts(value) {
  if (!value) return { date: "Sin lecturas", time: "--:--:--", full: "--", ageSeconds: null };
  const timestamp = new Date(value);
  if (Number.isNaN(timestamp.getTime())) return { date: "Fecha inválida", time: "--:--:--", full: "--", ageSeconds: null };
  const date = timestamp.toLocaleDateString("es-AR", { year: "numeric", month: "2-digit", day: "2-digit" });
  const time = timestamp.toLocaleTimeString("es-AR", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
  return {
    date,
    time,
    full: `${date} ${time}`,
    ageSeconds: Math.max(0, (Date.now() - timestamp.getTime()) / 1000)
  };
}

function formatAge(seconds) {
  if (!Number.isFinite(seconds)) return "sin hora válida";
  if (seconds < 2) return "ahora";
  if (seconds < 60) return `hace ${Math.round(seconds)} s`;
  if (seconds < 3600) return `hace ${Math.round(seconds / 60)} min`;
  return `hace ${Math.round(seconds / 3600)} h`;
}

function updateClock() {
  const now = new Date();
  elements.currentTime.textContent = now.toLocaleTimeString("es-AR", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
  elements.currentDate.textContent = now.toLocaleDateString("es-AR", { weekday: "long", day: "2-digit", month: "long" });
}

function updateSamplingEstimate(seconds) {
  const interval = Number(seconds);
  const readingsPerDay = interval > 0 ? Math.round(86400 / interval) : 0;
  elements.dailyReadingEstimate.textContent = `${readingsPerDay.toLocaleString("es-AR")} lecturas/día.`;
}

function announceDashboardStatus(message) {
  if (message === lastDashboardStatus) return;
  lastDashboardStatus = message;
  elements.dashboardStatus.textContent = message;
}

function isProductionPaused(reading) {
  if (!reading || !isNumeric(reading.voltage_v) || !isNumeric(reading.current_ma) || !isNumeric(reading.frequency_hz)) return false;
  return Number(reading.voltage_v) <= PAUSE_THRESHOLDS.voltageMax
    && Number(reading.current_ma) <= PAUSE_THRESHOLDS.currentMax
    && Number(reading.frequency_hz) > PAUSE_THRESHOLDS.frequencyMin;
}

function isReadingStale(data) {
  if (!data?.latest || data.connection_state !== "CONNECTED") return false;
  const age = timestampParts(data.latest.timestamp).ageSeconds;
  const pollInterval = Number(data.network?.poll_interval_seconds || 5);
  const staleAfter = Math.max(15, pollInterval * 3);
  return Number.isFinite(age) && age > staleAfter;
}

function processMode(data) {
  if (!data || data.connection_state === "WAITING") return "waiting";
  if (data.connection_state !== "CONNECTED") return "disconnected";
  if (!data.latest) return "waiting";
  if (isReadingStale(data)) return "stale";
  if (isProductionPaused(data.latest)) return "paused";
  if (data.latest.alarm_status === "ALARM" || data.latest.quality_flag === "OUT_OF_RANGE") return "alarm";
  return "normal";
}

function rowMode(reading) {
  if (isProductionPaused(reading)) return "paused";
  if (reading.alarm_status === "ALARM" || reading.quality_flag === "OUT_OF_RANGE") return "alarm";
  if (reading.quality_flag === "UNVERIFIED") return "unverified";
  return "normal";
}

function rowModeLabel(mode) {
  return {
    paused: "Producción detenida",
    alarm: "Fuera de rango",
    unverified: "Sin límites configurados",
    normal: "Dato recibido"
  }[mode] || "Dato recibido";
}

function setMetric(card, badge, quality, label, symbol) {
  card.dataset.quality = quality;
  badge.innerHTML = `<b aria-hidden="true">${symbol}</b> ${label}`;
}

function fieldOutOfRange(field, value, data) {
  const limits = data?.limits;
  if (!limits || limits.confirmed === false || !limits[field] || !isNumeric(value)) return false;
  return Number(value) < Number(limits[field].min) || Number(value) > Number(limits[field].max);
}

function updateMetrics(data, mode) {
  const latest = data?.latest;
  if (!latest || mode === "disconnected" || mode === "waiting") {
    elements.voltage.textContent = "--";
    elements.current.textContent = "--";
    elements.frequency.textContent = "--";
    const quality = mode === "disconnected" ? "disconnected" : "waiting";
    const label = mode === "disconnected" ? "Sin conexión" : "Esperando";
    const symbol = mode === "disconnected" ? "×" : "…";
    setMetric(elements.voltageCard, elements.qualityVoltage, quality, label, symbol);
    setMetric(elements.currentCard, elements.qualityCurrent, quality, label, symbol);
    setMetric(elements.frequencyCard, elements.qualityFrequency, quality, label, symbol);
    return;
  }

  elements.voltage.textContent = number(latest.voltage_v, 1);
  elements.current.textContent = number(latest.current_ma, 0);
  elements.frequency.textContent = number(latest.frequency_hz, 1);

  if (mode === "paused") {
    setMetric(elements.voltageCard, elements.qualityVoltage, "paused", "Sin producción", "⏸");
    setMetric(elements.currentCard, elements.qualityCurrent, "paused", "Sin producción", "⏸");
    setMetric(elements.frequencyCard, elements.qualityFrequency, "normal", "Dato recibido", "✓");
    return;
  }
  if (mode === "stale") {
    setMetric(elements.voltageCard, elements.qualityVoltage, "stale", "Dato demorado", "!");
    setMetric(elements.currentCard, elements.qualityCurrent, "stale", "Dato demorado", "!");
    setMetric(elements.frequencyCard, elements.qualityFrequency, "stale", "Dato demorado", "!");
    return;
  }

  const confirmed = data.limits?.confirmed !== false;
  const fields = [
    ["voltage_v", latest.voltage_v, elements.voltageCard, elements.qualityVoltage],
    ["current_ma", latest.current_ma, elements.currentCard, elements.qualityCurrent],
    ["frequency_hz", latest.frequency_hz, elements.frequencyCard, elements.qualityFrequency]
  ];
  fields.forEach(([field, value, card, badge]) => {
    if (fieldOutOfRange(field, value, data)) setMetric(card, badge, "alarm", "Fuera de rango", "!");
    else if (!confirmed) setMetric(card, badge, "unverified", "Sin límites", "?");
    else setMetric(card, badge, "normal", "Normal", "✓");
  });
}

function setBanner(state, title, message, icon, showRetry = false) {
  elements.systemBanner.classList.remove("is-hidden");
  elements.systemBanner.dataset.state = state;
  elements.bannerTitle.textContent = title;
  elements.bannerMessage.textContent = message;
  elements.bannerIcon.textContent = icon;
  elements.bannerIcon.dataset.icon = icon === "⏸" ? "pause" : "";
  elements.retryConnection.hidden = !showRetry;
  if (state === "danger") {
    setSupportMailto(elements.bannerCopy, true, `VFREG Visor — ${title}`, message);
    elements.bannerCopy.setAttribute("aria-label", `Escribir a soporte: ${title}`);
  } else {
    setSupportMailto(elements.bannerCopy, false);
    elements.bannerCopy.removeAttribute("aria-label");
  }
}

function updateSystemBanner(data, mode) {
  const storage = data?.diagnostics?.storage || {};
  const storageState = String(storage.storage_health || "STARTING").toUpperCase();
  if (storageState === "CRITICAL") {
    setBanner("danger", "Error de almacenamiento", storage.last_error || "No se pueden guardar lecturas con normalidad. Solicite soporte.", "!", false);
    return;
  }
  if (mode === "disconnected") {
    setBanner("danger", "No se puede comunicar con el visor VFREG", "La aplicación seguirá intentando reconectar automáticamente. No se modificó el equipo.", "×", true);
    return;
  }
  if (mode === "waiting") {
    setBanner("info", "Iniciando monitoreo", "La aplicación está esperando la primera respuesta del visor VFREG.", "…", true);
    return;
  }
  if (mode === "stale") {
    setBanner("warning", "Sin datos recientes", "La conexión existe, pero la última lectura tiene más demora de la esperada.", "!", true);
    return;
  }
  if (mode === "paused") {
    setBanner("info", "Producción detenida", "El visor sigue conectado y enviando frecuencia; voltaje y corriente están en cero. No se considera una falla de conexión.", "⏸", false);
    return;
  }
  if (mode === "alarm") {
    setBanner("danger", "Una lectura requiere revisión", "Uno o más valores están fuera de los límites configurados. Revise el proceso.", "!", false);
    return;
  }
  if (storageState === "WARNING") {
    setBanner("warning", "Espacio de almacenamiento reducido", "La recolección continúa, pero conviene revisar el espacio disponible.", "!", false);
    return;
  }
  elements.systemBanner.classList.add("is-hidden");
  setSupportMailto(elements.bannerCopy, false);
  elements.bannerCopy.removeAttribute("aria-label");
}

function updateConnectionAndProcess(data, mode) {
  const state = data.connection_state || "WAITING";
  const latestParts = timestampParts(data.latest?.timestamp);
  elements.connection.dataset.state = state;
  elements.connection.dataset.process = mode;
  elements.processStrip.dataset.state = mode;

  if (state === "CONNECTED") {
    elements.connectionLabel.textContent = "Conectado";
    elements.connectionSymbol.textContent = mode === "paused" ? "⏸" : "✓";
    if (mode === "paused") elements.connectionDetail.textContent = `Producción detenida · ${formatAge(latestParts.ageSeconds)}`;
    else if (mode === "stale") elements.connectionDetail.textContent = `Sin datos recientes · ${formatAge(latestParts.ageSeconds)}`;
    else if (mode === "alarm") elements.connectionDetail.textContent = "Una lectura requiere revisión";
    else elements.connectionDetail.textContent = `Actualizado ${formatAge(latestParts.ageSeconds)}`;
  } else if (state === "WAITING") {
    elements.connectionLabel.textContent = "Iniciando";
    elements.connectionDetail.textContent = "Esperando al visor VFREG";
    elements.connectionSymbol.textContent = "…";
  } else {
    elements.connectionLabel.textContent = "Desconectado";
    elements.connectionDetail.textContent = "Intentando reconectar";
    elements.connectionSymbol.textContent = "×";
  }

  const processCopy = {
    normal: ["Funcionamiento normal", "El visor está conectado y las lecturas llegan a tiempo."],
    paused: ["Producción detenida", "Voltaje y corriente sin producción; la frecuencia continúa registrada."],
    alarm: ["Valor fuera de rango", "Revise la lectura marcada antes de continuar."],
    stale: ["Sin datos recientes", "La última lectura está demorada; la aplicación continúa verificando."],
    disconnected: ["Sin conexión", "No se reciben lecturas nuevas del visor VFREG."],
    waiting: ["Esperando datos", "La aplicación está iniciando y aún no recibió una lectura."]
  }[mode];
  elements.processState.textContent = processCopy[0];
  elements.processDetail.textContent = processCopy[1];
  announceDashboardStatus(`${elements.connectionLabel.textContent}. ${processCopy[0]}.`);
}

function renderReadings(readings = historyReadings) {
  const filtered = readings.filter((reading) => {
    const mode = rowMode(reading);
    if (historyQuality === "alarm") return mode === "alarm";
    if (historyQuality === "valid") return mode !== "alarm";
    return true;
  });
  elements.recordCount.textContent = filtered.length.toLocaleString("es-AR");
  elements.recordCountLabel.textContent = filtered.length === readings.length
    ? "muestras del período"
    : `de ${readings.length.toLocaleString("es-AR")} muestras del período`;
  elements.recordsBody.replaceChildren();
  if (!filtered.length) {
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = 6;
    cell.className = "empty-row";
    cell.textContent = readings.length ? "No hay lecturas con esta calidad" : "No hay lecturas en este período";
    row.appendChild(cell);
    elements.recordsBody.appendChild(row);
    return;
  }

  const fragment = document.createDocumentFragment();
  [...filtered].reverse().forEach((reading) => {
    const row = document.createElement("tr");
    const mode = rowMode(reading);
    const timestamp = timestampParts(reading.timestamp);
    row.dataset.quality = mode;
    const values = [
      timestamp.date,
      timestamp.time,
      `${number(reading.voltage_v, 1)} V`,
      `${number(reading.current_ma, 0)} mA`,
      `${number(reading.frequency_hz, 1)} Hz`,
      rowModeLabel(mode)
    ];
    values.forEach((value, index) => {
      const cell = document.createElement("td");
      cell.textContent = value;
      if (index === 5) cell.className = "table-status";
      row.appendChild(cell);
    });
    fragment.appendChild(row);
  });
  elements.recordsBody.appendChild(fragment);
}

function renderHistory(readings, count, modeLabel) {
  currentReadings = readings || [];
  currentRangeCount = Number(count || 0);
  if (currentView === "live") drawChart(currentReadings);
  updateReportSummary();
}

function renderSampledHistory(readings) {
  historyReadings = readings || [];
  if (currentView === "history") renderReadings(historyReadings);
}

function renderStatus(data) {
  const latest = data.latest;
  const mode = processMode(data);
  elements.appVersion.textContent = `VFREG Visor ${data.app_version}`;

  const pollInterval = Number(data.network.poll_interval_seconds);
  if (Number.isFinite(pollInterval) && document.activeElement !== elements.pollInterval) {
    elements.pollInterval.value = String(pollInterval);
    updateSamplingEstimate(pollInterval);
  }

  if (latest) {
    const timestamp = timestampParts(latest.timestamp);
    elements.readingTime.textContent = timestamp.time;
    elements.readingDate.textContent = timestamp.date;
    elements.lastReading.textContent = `Última lectura: ${timestamp.time}`;
  } else {
    elements.readingTime.textContent = "--:--:--";
    elements.readingDate.textContent = "Sin lecturas";
    elements.lastReading.textContent = "Última lectura: ninguna";
  }
  updateSupportEmailLink();

  updateConnectionAndProcess(data, mode);
  updateMetrics(data, mode);
  updateSystemBanner(data, mode);
  drawSparklines(data.readings || []);
}

const CHART_SERIES = Object.freeze([
  { key: "voltage_v", color: "#0b929d", label: "Voltaje", unit: "V", digits: 1 },
  { key: "current_ma", color: "#7255a5", label: "Corriente", unit: "mA", digits: 0 },
  { key: "frequency_hz", color: "#c47a13", label: "Frecuencia", unit: "Hz", digits: 1 }
]);

function visibleChartReadings(readings) {
  const valid = readings.filter((row) => CHART_SERIES.every((series) => isNumeric(row[series.key])));
  const zoom = Number(elements.chartZoom.value || 1);
  const visibleCount = Math.max(2, Math.ceil(valid.length / zoom));
  return valid.slice(-visibleCount);
}

function drawSparkline(canvas, readings, series) {
  const values = readings.slice(-40).filter((row) => isNumeric(row[series.key])).map((row) => Number(row[series.key]));
  const bounds = canvas.getBoundingClientRect();
  if (!bounds.width || !bounds.height) return;
  const ratio = window.devicePixelRatio || 1;
  canvas.width = Math.floor(bounds.width * ratio);
  canvas.height = Math.floor(bounds.height * ratio);
  const context = canvas.getContext("2d");
  context.setTransform(ratio, 0, 0, ratio, 0, 0);
  context.clearRect(0, 0, bounds.width, bounds.height);
  if (values.length < 2) return;
  let minimum = Math.min(...values);
  let maximum = Math.max(...values);
  if (minimum === maximum) { minimum -= 1; maximum += 1; }
  context.strokeStyle = series.color;
  context.lineWidth = 1.7;
  context.beginPath();
  values.forEach((value, index) => {
    const x = 2 + (index / (values.length - 1)) * (bounds.width - 4);
    const y = bounds.height - 3 - ((value - minimum) / (maximum - minimum)) * (bounds.height - 6);
    if (index === 0) context.moveTo(x, y); else context.lineTo(x, y);
  });
  context.stroke();
}

function drawSparklines(readings) {
  drawSparkline(elements.voltageSparkline, readings, CHART_SERIES[0]);
  drawSparkline(elements.currentSparkline, readings, CHART_SERIES[1]);
  drawSparkline(elements.frequencySparkline, readings, CHART_SERIES[2]);
}

function positiveAverage(readings, key) {
  const values = readings
    .filter((row) => isNumeric(row[key]) && Number(row[key]) > 0)
    .map((row) => Number(row[key]));
  if (!values.length) return null;
  return values.reduce((total, value) => total + value, 0) / values.length;
}

function drawReportPreviewLine(canvas, readings, series) {
  if (!canvas) return;
  const numericRows = readings.filter((row) => isNumeric(row[series.key]));
  const step = Math.max(1, Math.ceil(numericRows.length / 120));
  const values = numericRows.filter((_row, index) => index % step === 0 || index === numericRows.length - 1)
    .map((row) => Number(row[series.key]));
  const bounds = canvas.getBoundingClientRect();
  if (!bounds.width || !bounds.height) return;
  const ratio = window.devicePixelRatio || 1;
  canvas.width = Math.max(1, Math.floor(bounds.width * ratio));
  canvas.height = Math.max(1, Math.floor(bounds.height * ratio));
  const context = canvas.getContext("2d");
  context.setTransform(ratio, 0, 0, ratio, 0, 0);
  context.clearRect(0, 0, bounds.width, bounds.height);
  context.strokeStyle = "#e3e9eb";
  context.lineWidth = 1;
  [0.25, 0.5, 0.75].forEach((position) => {
    const y = bounds.height * position;
    context.beginPath();
    context.moveTo(0, y);
    context.lineTo(bounds.width, y);
    context.stroke();
  });
  if (values.length < 2) return;
  let minimum = Math.min(...values);
  let maximum = Math.max(...values);
  if (minimum === maximum) { minimum -= 1; maximum += 1; }
  context.strokeStyle = series.color;
  context.lineWidth = 2;
  context.beginPath();
  values.forEach((value, index) => {
    const x = 3 + (index / (values.length - 1)) * (bounds.width - 6);
    const y = bounds.height - 5 - ((value - minimum) / (maximum - minimum)) * (bounds.height - 10);
    if (index === 0) context.moveTo(x, y); else context.lineTo(x, y);
  });
  context.stroke();
}

function aggregateChartPreview(readings) {
  if (chartExportInterval === "auto") return readings;
  const intervalMs = Number(chartExportInterval) * 60000;
  if (!Number.isFinite(intervalMs) || intervalMs <= 0) return readings;
  const buckets = new Map();
  readings.forEach((reading) => {
    const timestamp = new Date(reading.timestamp);
    if (Number.isNaN(timestamp.getTime())) return;
    const bucketTime = Math.floor(timestamp.getTime() / intervalMs) * intervalMs;
    let bucket = buckets.get(bucketTime);
    if (!bucket) {
      bucket = { timestamp: bucketTime, sums: {}, counts: {}, paused: null };
      buckets.set(bucketTime, bucket);
    }
    CHART_SERIES.forEach((series) => {
      if (!isNumeric(reading[series.key])) return;
      bucket.sums[series.key] = (bucket.sums[series.key] || 0) + Number(reading[series.key]);
      bucket.counts[series.key] = (bucket.counts[series.key] || 0) + 1;
    });
  });
  return [...buckets.values()].map((bucket) => {
    const average = { timestamp: new Date(bucket.timestamp).toISOString() };
    CHART_SERIES.forEach((series) => {
      average[series.key] = bucket.counts[series.key]
        ? bucket.sums[series.key] / bucket.counts[series.key]
        : null;
    });
    return average;
  });
}

function renderWorkbookPreview() {
  const averages = [
    [elements.previewAverageVoltage, positiveAverage(currentReadings, "voltage_v"), "V"],
    [elements.previewAverageCurrent, positiveAverage(currentReadings, "current_ma"), "mA"],
    [elements.previewAverageFrequency, positiveAverage(currentReadings, "frequency_hz"), "Hz"]
  ];
  averages.forEach(([element, average, unit]) => {
    element.textContent = average === null ? "--" : `${number(average, 1)} ${unit}`;
  });
  const chartReadings = aggregateChartPreview(currentReadings);
  drawReportPreviewLine(elements.reportPreviewVoltage, chartReadings, CHART_SERIES[0]);
  drawReportPreviewLine(elements.reportPreviewCurrent, chartReadings, CHART_SERIES[1]);
  drawReportPreviewLine(elements.reportPreviewFrequency, chartReadings, CHART_SERIES[2]);
}

function drawChart(readings) {
  const chartReadings = visibleChartReadings(readings);
  const canvas = elements.canvas;
  const bounds = canvas.getBoundingClientRect();
  if (!bounds.width || !bounds.height) return;
  const ratio = window.devicePixelRatio || 1;
  canvas.width = Math.max(1, Math.floor(bounds.width * ratio));
  canvas.height = Math.max(1, Math.floor(bounds.height * ratio));
  const context = canvas.getContext("2d");
  context.setTransform(ratio, 0, 0, ratio, 0, 0);
  context.clearRect(0, 0, bounds.width, bounds.height);
  chartPoints = [];
  chartPointIndex = -1;
  elements.emptyChart.hidden = chartReadings.length > 1;
  if (chartReadings.length < 2) return;

  const padding = { left: 62, right: 18, top: 12, bottom: 24 };
  const plotWidth = bounds.width - padding.left - padding.right;
  const plotHeight = bounds.height - padding.top - padding.bottom;
  const lanes = chartMode === "overview"
    ? CHART_SERIES
    : CHART_SERIES.filter((series) => series.key === chartMode);
  const laneHeight = plotHeight / lanes.length;
  context.font = "10px Segoe UI, Arial";
  chartPoints = chartReadings.map((reading, index) => ({
    reading,
    x: padding.left + (index / (chartReadings.length - 1)) * plotWidth
  }));

  lanes.forEach((lane, laneIndex) => {
    const values = chartReadings.map((row) => Number(row[lane.key]));
    let minimum = Math.min(...values);
    let maximum = Math.max(...values);
    const spread = Math.max(maximum - minimum, Math.abs(maximum) * 0.015, 1);
    minimum = Math.max(0, minimum - spread * 0.2);
    maximum += spread * 0.2;
    const top = padding.top + laneIndex * laneHeight;
    const bottom = top + laneHeight;

    context.strokeStyle = "#e4eaec";
    context.lineWidth = 1;
    context.setLineDash([3, 4]);
    context.beginPath();
    context.moveTo(padding.left, bottom);
    context.lineTo(bounds.width - padding.right, bottom);
    context.stroke();
    context.setLineDash([]);
    context.fillStyle = "#657780";
    context.fillText(`${maximum.toFixed(lane.digits)} ${lane.unit}`, 5, top + 12);
    context.fillText(minimum.toFixed(0), 20, bottom - 5);

    context.strokeStyle = lane.color;
    context.lineWidth = 2;
    context.beginPath();
    chartReadings.forEach((row, index) => {
      const value = Number(row[lane.key]);
      const x = padding.left + (index / (chartReadings.length - 1)) * plotWidth;
      const y = bottom - 8 - ((value - minimum) / (maximum - minimum)) * (laneHeight - 20);
      if (index === 0) context.moveTo(x, y);
      else context.lineTo(x, y);
    });
    context.stroke();
  });

  const first = timestampParts(chartReadings[0].timestamp).time;
  const last = timestampParts(chartReadings.at(-1).timestamp).time;
  context.fillStyle = "#657780";
  context.fillText(first, padding.left, bounds.height - 5);
  context.textAlign = "right";
  context.fillText(last, bounds.width - padding.right, bounds.height - 5);
  context.textAlign = "left";
}

function showChartTooltipForPoint(point) {
  const bounds = elements.canvas.getBoundingClientRect();
  const reading = point.reading;
  elements.chartTooltip.innerHTML = `<strong>${timestampParts(reading.timestamp).full}</strong>${CHART_SERIES.map((series) =>
    `<span>${series.label}: ${number(reading[series.key], series.digits)} ${series.unit}</span>`
  ).join("")}`;
  elements.chartTooltip.hidden = false;
  elements.chartTooltip.style.left = `${Math.min(bounds.width - 190, Math.max(8, point.x + 10))}px`;
  elements.chartTooltip.style.top = "12px";
}

function showChartTooltip(event) {
  if (!chartPoints.length) return;
  const bounds = elements.canvas.getBoundingClientRect();
  const pointerX = event.clientX - bounds.left;
  const point = chartPoints.reduce((closest, candidate) =>
    Math.abs(candidate.x - pointerX) < Math.abs(closest.x - pointerX) ? candidate : closest
  );
  chartPointIndex = chartPoints.indexOf(point);
  showChartTooltipForPoint(point);
}

function moveChartPoint(event) {
  if (!chartPoints.length) return;
  if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
  event.preventDefault();
  if (event.key === "Home") chartPointIndex = 0;
  else if (event.key === "End") chartPointIndex = chartPoints.length - 1;
  else if (chartPointIndex < 0) chartPointIndex = event.key === "ArrowLeft" ? chartPoints.length - 1 : 0;
  else chartPointIndex = Math.min(
    chartPoints.length - 1,
    Math.max(0, chartPointIndex + (event.key === "ArrowLeft" ? -1 : 1))
  );
  showChartTooltipForPoint(chartPoints[chartPointIndex]);
}

function showDashboardError(error) {
  elements.connection.dataset.state = "DISCONNECTED";
  elements.connection.dataset.process = "disconnected";
  elements.connectionLabel.textContent = "Dashboard sin respuesta";
  elements.connectionDetail.textContent = "Reintente la conexión local";
  elements.connectionSymbol.textContent = "×";
  elements.processStrip.dataset.state = "disconnected";
  elements.processState.textContent = "Sin datos del dashboard";
  elements.processDetail.textContent = "El recolector puede continuar en segundo plano; reintente esta pantalla.";
  updateMetrics(null, "disconnected");
  setBanner("danger", "No se pudo actualizar el dashboard", `Error local: ${error.message}`, "×", true);
  announceDashboardStatus("Dashboard sin respuesta. Sin datos del dashboard.");
}

async function refresh() {
  try {
    const response = await fetch("/api/status", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    latestStatusData = await response.json();
    renderStatus(latestStatusData);
  } catch (error) {
    showDashboardError(error);
  }
}

function setView(view) {
  currentView = view;
  document.querySelectorAll("[data-view-panel]").forEach((panel) => {
    const active = panel.dataset.viewPanel === view;
    panel.hidden = !active;
    panel.classList.toggle("is-active", active);
  });
  document.querySelectorAll("[data-view]").forEach((button) => {
    const active = button.dataset.view === view;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-pressed", String(active));
    if (active) button.setAttribute("aria-current", "page");
    else button.removeAttribute("aria-current");
  });
  if (view === "live") window.requestAnimationFrame(() => {
    drawChart(currentReadings);
    drawSparklines(latestStatusData?.readings || []);
  });
  if (view === "history") {
    window.requestAnimationFrame(() => renderReadings(historyReadings));
    loadHistorySamples();
  }
  if (view === "reports" && reportFormat === "xlsx") {
    window.requestAnimationFrame(renderWorkbookPreview);
  }
}

function localInputValue(date) {
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60000);
  return local.toISOString().slice(0, 19);
}

function productionStartTime() {
  return latestStatusData?.factory?.production_start_time || "06:00";
}

function resolvedRange() {
  if (activeRange.key === "custom") return { from: activeRange.from, to: activeRange.to };
  if (activeRange.key === "history") return { from: "", to: "" };
  const to = new Date();
  if (activeRange.key === "workday") {
    const [hours, minutes] = productionStartTime().split(":").map(Number);
    const from = new Date(to);
    from.setHours(hours || 0, minutes || 0, 0, 0);
    if (from > to) from.setDate(from.getDate() - 1);
    return { from: localInputValue(from), to: localInputValue(to) };
  }
  return {
    from: localInputValue(new Date(to.getTime() - activeRange.minutes * 60000)),
    to: localInputValue(to)
  };
}

function filterQuery() {
  const range = resolvedRange();
  const query = new URLSearchParams();
  if (range.from) query.set("from", range.from);
  if (range.to) query.set("to", range.to);
  if (reportFormat === "xlsx" && chartExportInterval !== "auto") {
    query.set("chart_interval_minutes", chartExportInterval);
  }
  const encoded = query.toString();
  return encoded ? `?${encoded}` : "";
}

function updateReportSummary() {
  const query = filterQuery();
  const intraDay = reportFormat === "xlsx";
  const daily = reportFormat === "daily";
  elements.reportDownload.href = `${daily ? "/api/export.daily.xlsx" : intraDay ? "/api/export.xlsx" : "/api/export.csv"}${query}`;
  elements.reportDownload.download = daily ? DAILY_XLSX_DOWNLOAD_NAME : intraDay ? XLSX_DOWNLOAD_NAME : CSV_DOWNLOAD_NAME;
  elements.reportDownload.textContent = reportFormat === "csv" ? "Descargar CSV" : "Descargar XLSX";
  elements.exportPeriod.textContent = activeRange.label;
  elements.activeRangeLabel.textContent = activeRange.label;
  elements.reportCount.textContent = currentRangeCount.toLocaleString("es-AR");
  elements.previewReadingCount.textContent = `${currentRangeCount.toLocaleString("es-AR")} filas del período seleccionado`;
  elements.reportFormat.textContent = daily ? "Promedios diarios" : intraDay ? "Excel + gráficos" : "CSV sin procesar";
  elements.chartIntervalStep.hidden = !intraDay;
  elements.chartIntervalSummaryRow.hidden = !intraDay;
  elements.chartIntervalSummary.textContent = chartExportInterval === "auto"
    ? "Automático"
    : `Cada ${chartExportInterval} min`;
  elements.reportContent.textContent = daily
    ? "Promedio, mínimo y máximo por día"
    : intraDay ? "Raw Data + Reporte y gráficos" : "Fecha, Hora, Volts, mAmp y Frec";
  elements.reportSummaryTitle.textContent = activeRange.key === "workday"
    ? "Reporte de jornada actual"
    : activeRange.key === "history" ? "Reporte histórico completo" : "Reporte del período seleccionado";
  elements.workbookPreview.hidden = !intraDay;
  if (intraDay && currentView === "reports") window.requestAnimationFrame(renderWorkbookPreview);
}

function updateExportLinks() {
  updateReportSummary();
}

function selectPresetButton() {
  document.querySelectorAll("[data-range-minutes]").forEach((button) => {
    const selected = activeRange.key === `${button.dataset.rangeMinutes}m`;
    button.dataset.active = String(selected);
    button.setAttribute("aria-pressed", String(selected));
  });
  const workdaySelected = activeRange.key === "workday";
  elements.workdayFilter.dataset.active = String(workdaySelected);
  elements.workdayFilter.setAttribute("aria-pressed", String(workdaySelected));
  elements.customRangeToggle.dataset.active = String(activeRange.key === "custom");
  document.querySelectorAll("[data-report-scope]").forEach((button) => {
    const selected = button.dataset.reportScope === activeRange.key;
    button.classList.toggle("is-selected", selected);
    button.setAttribute("aria-pressed", String(selected));
  });
}

function setRangeStatus(message, error = false, offerSupport = false) {
  [elements.historyFilterResult].forEach((element) => {
    element.dataset.error = String(error);
    element.textContent = message;
    setSupportMailto(element, error && offerSupport, "Soporte VFREG Visor — Historial", message);
  });
}

async function loadActiveRange({ announce = true } = {}) {
  const requestId = ++rangeRequestId;
  const rangeLabel = activeRange.label;
  const { from, to } = resolvedRange();
  if (from && to && new Date(from) > new Date(to)) {
    setRangeStatus("La fecha Desde debe ser anterior a Hasta", true);
    return;
  }
  updateExportLinks();
  if (announce) setRangeStatus("Cargando período…");
  const query = new URLSearchParams({ limit: "10000" });
  if (from) query.set("from", from);
  if (to) query.set("to", to);
  try {
    const response = await fetch(`/api/readings?${query.toString()}`, { cache: "no-store" });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || `HTTP ${response.status}`);
    if (requestId !== rangeRequestId) return;
    renderHistory(result.readings || [], result.count || 0, rangeLabel);
    const hiddenCount = Math.max(0, Number(result.count || 0) - (result.readings || []).length);
    setRangeStatus(hiddenCount
      ? `${Number(result.count).toLocaleString("es-AR")} coincidencias; se muestran las últimas ${(result.readings || []).length.toLocaleString("es-AR")}`
      : `${Number(result.count || 0).toLocaleString("es-AR")} lecturas en ${rangeLabel.toLowerCase()}`);
  } catch (error) {
    if (requestId !== rangeRequestId) return;
    setRangeStatus(error.message, true, true);
  }
}

function currentWorkdayRange() {
  const to = new Date();
  const [hours, minutes] = productionStartTime().split(":").map(Number);
  const from = new Date(to);
  from.setHours(hours || 0, minutes || 0, 0, 0);
  if (from > to) from.setDate(from.getDate() - 1);
  return { from: localInputValue(from), to: localInputValue(to) };
}

function resolvedHistorySourceRange() {
  if (historySourceRange.key === "custom") {
    return { from: historySourceRange.from, to: historySourceRange.to };
  }
  return currentWorkdayRange();
}

function historyIntervalLabel(minutes = historySampleMinutes) {
  return minutes === 60 ? "Cada hora" : `Cada ${minutes} minutos`;
}

function selectHistoryControls() {
  elements.historyPeriodLabel.textContent = historyIntervalLabel();
  const sourceLabel = historySourceRange.key === "custom"
    ? "Rango personalizado"
    : `Inicio de jornada · ${productionStartTime()}`;
  elements.historySourceLabel.textContent = sourceLabel;
  elements.historyMode.textContent = `${historyIntervalLabel()} · ${sourceLabel.toLowerCase()}`;
  document.querySelectorAll("[data-history-minutes]").forEach((button) => {
    const selected = Number(button.dataset.historyMinutes) === historySampleMinutes;
    button.dataset.active = String(selected);
    button.setAttribute("aria-pressed", String(selected));
  });
  document.querySelectorAll("[data-history-workday]").forEach((button) => {
    const selected = historySourceRange.key === "workday";
    button.dataset.active = String(selected);
    button.setAttribute("aria-pressed", String(selected));
  });
  document.querySelectorAll("[data-history-custom]").forEach((button) => {
    const selected = historySourceRange.key === "custom";
    button.dataset.active = String(selected);
    button.setAttribute("aria-pressed", String(selected));
  });
}

function setHistoryStatus(message, error = false, offerSupport = false) {
  [elements.historyViewFilterResult, elements.historyRangeResult].forEach((element) => {
    element.dataset.error = String(error);
    element.textContent = message;
    setSupportMailto(element, error && offerSupport, "Soporte VFREG Visor — Historial", message);
  });
}

async function loadHistorySamples({ announce = true } = {}) {
  const requestId = ++historyRequestId;
  const { from, to } = resolvedHistorySourceRange();
  const interval = historySampleMinutes;
  if (!from || !to || new Date(from) > new Date(to)) {
    setHistoryStatus("La fecha Desde debe ser anterior a Hasta", true);
    return;
  }
  selectHistoryControls();
  elements.recordsSection.dataset.loading = "true";
  elements.recordsSection.setAttribute("aria-busy", "true");
  setHistoryStatus(announce ? "Cargando muestras…" : "Actualizando muestras…");
  const query = new URLSearchParams({
    from,
    to,
    sample_minutes: String(interval)
  });
  try {
    const response = await fetch(`/api/readings?${query.toString()}`, { cache: "no-store" });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || `HTTP ${response.status}`);
    if (requestId !== historyRequestId) return;
    renderSampledHistory(result.readings || []);
    const source = historySourceRange.key === "custom"
      ? "en el rango personalizado"
      : `desde las ${productionStartTime()}`;
    setHistoryStatus(
      `${Number(result.count || 0).toLocaleString("es-AR")} muestras · una cada ${interval === 60 ? "hora" : `${interval} minutos`} ${source}`
    );
  } catch (error) {
    if (requestId !== historyRequestId) return;
    setHistoryStatus(error.message, true, true);
  } finally {
    if (requestId === historyRequestId) {
      elements.recordsSection.dataset.loading = "false";
      elements.recordsSection.setAttribute("aria-busy", "false");
    }
  }
}

function applyHistorySampling(minutes) {
  historySampleMinutes = minutes;
  selectHistoryControls();
  loadHistorySamples();
}

function applyHistoryWorkday() {
  historySourceRange = { key: "workday" };
  elements.historyViewFilterForm.hidden = true;
  selectHistoryControls();
  loadHistorySamples();
}

function applyHistoryCustomRange(from, to) {
  if (!from || !to) {
    setHistoryStatus("Complete Desde y Hasta para aplicar el rango", true);
    return;
  }
  if (new Date(from) > new Date(to)) {
    setHistoryStatus("La fecha Desde debe ser anterior a Hasta", true);
    return;
  }
  historySourceRange = { key: "custom", from, to };
  selectHistoryControls();
  loadHistorySamples();
}

function hideCustomRangeForms() {
  elements.historyFilterForm.hidden = true;
  elements.historyViewFilterForm.hidden = true;
  elements.reportCustomForm.hidden = true;
  elements.customRangeToggle.setAttribute("aria-expanded", "false");
}

function applyPreset(minutes) {
  activeRange = {
    key: `${minutes}m`,
    minutes,
    label: minutes === 60 ? "Última hora" : `Últimos ${minutes} minutos`,
    rolling: true
  };
  hideCustomRangeForms();
  selectPresetButton();
  loadActiveRange();
}

function applyWorkday() {
  activeRange = { key: "workday", label: `Jornada actual · desde ${productionStartTime()}`, rolling: true };
  hideCustomRangeForms();
  selectPresetButton();
  loadActiveRange();
}

function applyHistoricalRange() {
  activeRange = { key: "history", label: "Histórico completo", rolling: false };
  hideCustomRangeForms();
  selectPresetButton();
  loadActiveRange();
}

function applyCustomRange(from, to, resultElement) {
  if (!from || !to) {
    resultElement.dataset.error = "true";
    resultElement.textContent = "Complete Desde y Hasta para aplicar el período";
    setSupportMailto(resultElement, false);
    return;
  }
  if (new Date(from) > new Date(to)) {
    resultElement.dataset.error = "true";
    resultElement.textContent = "La fecha Desde debe ser anterior a Hasta";
    setSupportMailto(resultElement, false);
    return;
  }
  resultElement.dataset.error = "false";
  resultElement.textContent = "Período aplicado";
  setSupportMailto(resultElement, false);
  activeRange = { key: "custom", from, to, label: "Período personalizado", rolling: false };
  selectPresetButton();
  loadActiveRange();
}

function submitHistoryFilter(event) {
  event.preventDefault();
  applyCustomRange(elements.historyFrom.value, elements.historyTo.value, elements.historyFilterResult);
}

function clearHistoryFilter() {
  elements.historyFrom.value = "";
  elements.historyTo.value = "";
  applyPreset(15);
}

async function downloadXlsx(event) {
  event.preventDefault();
  if (elements.reportDownload.dataset.busy === "true") return;
  elements.reportDownload.dataset.busy = "true";
  elements.reportDownload.setAttribute("aria-disabled", "true");
  elements.exportStatus.dataset.error = "false";
  elements.exportStatus.textContent = "Preparando archivo Excel…";
  setSupportMailto(elements.exportStatus, false);
  try {
    const response = await fetch(elements.reportDownload.href, { cache: "no-store" });
    if (!response.ok) {
      const result = await response.json().catch(() => ({}));
      throw new Error(result.error || `No se pudo exportar Excel (HTTP ${response.status})`);
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const download = document.createElement("a");
    download.href = url;
    download.download = elements.reportDownload.download;
    document.body.appendChild(download);
    download.click();
    download.remove();
    URL.revokeObjectURL(url);
    elements.exportStatus.textContent = "Excel descargado correctamente";
    setSupportMailto(elements.exportStatus, false);
  } catch (error) {
    elements.exportStatus.dataset.error = "true";
    elements.exportStatus.textContent = error.message;
    setSupportMailto(elements.exportStatus, true, "Soporte VFREG Visor — Excel", error.message);
  } finally {
    elements.reportDownload.dataset.busy = "false";
    elements.reportDownload.removeAttribute("aria-disabled");
  }
}

function setArchiveWipeStatus(message, isError = false) {
  elements.archiveWipeStatus.dataset.error = isError ? "true" : "false";
  elements.archiveWipeStatus.textContent = message;
}

function resetArchiveWipeDialog() {
  elements.archiveWipeStep1.hidden = false;
  elements.archiveWipeStep2.hidden = true;
  elements.archiveWipeConfirm.value = "";
  elements.archiveWipeConfirmBtn.disabled = true;
  elements.archiveWipeConfirmBtn.removeAttribute("aria-disabled");
}

function closeArchiveWipeDialog() {
  resetArchiveWipeDialog();
  if (elements.archiveWipeDialog.open) elements.archiveWipeDialog.close();
}

function openArchiveWipeDialog() {
  if (elements.archiveWipeOpen.dataset.busy === "true") return;
  resetArchiveWipeDialog();
  setArchiveWipeStatus("");
  elements.archiveWipeDialog.showModal();
  elements.archiveWipeContinue.focus();
}

function showArchiveWipeStep2() {
  elements.archiveWipeStep1.hidden = true;
  elements.archiveWipeStep2.hidden = false;
  elements.archiveWipeConfirm.focus();
}

function syncArchiveWipeConfirm() {
  const ready = elements.archiveWipeConfirm.value.trim().toUpperCase() === "VACIAR";
  elements.archiveWipeConfirmBtn.disabled = !ready;
}

async function confirmArchiveAndWipe() {
  if (elements.archiveWipeConfirm.value.trim().toUpperCase() !== "VACIAR") return;
  if (elements.archiveWipeOpen.dataset.busy === "true") return;
  elements.archiveWipeOpen.dataset.busy = "true";
  elements.archiveWipeConfirmBtn.disabled = true;
  elements.archiveWipeConfirmBtn.setAttribute("aria-disabled", "true");
  elements.archiveWipeOpen.disabled = true;
  setArchiveWipeStatus("Archivando y vaciando… no cierre esta ventana.");
  closeArchiveWipeDialog();
  try {
    const response = await fetch("/api/archive-and-wipe", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ confirm: "VACIAR" })
    });
    if (!response.ok) {
      const result = await response.json().catch(() => ({}));
      throw new Error(result.error || `No se pudo archivar (HTTP ${response.status})`);
    }
    const blob = await response.blob();
    const headerName = response.headers.get("Content-Disposition") || "";
    const matched = /filename="([^"]+)"/.exec(headerName);
    const filename = matched ? matched[1] : "vfreg-archive.zip";
    const url = URL.createObjectURL(blob);
    const download = document.createElement("a");
    download.href = url;
    download.download = filename;
    document.body.appendChild(download);
    download.click();
    download.remove();
    URL.revokeObjectURL(url);
    setArchiveWipeStatus("ZIP descargado y historial vaciado. Abra readings.csv en Excel. Conserve el archivo. Las lecturas nuevas se siguen guardando.");
    refresh();
  } catch (error) {
    setArchiveWipeStatus(
      `${error.message} Si el historial se vació y no tiene el archivo, busque la carpeta archives junto a la base de datos.`,
      true
    );
  } finally {
    elements.archiveWipeOpen.dataset.busy = "false";
    elements.archiveWipeOpen.disabled = false;
  }
}

async function savePollingInterval(event) {
  event.preventDefault();
  const seconds = Number(elements.pollInterval.value);
  elements.samplingSave.disabled = true;
  elements.samplingResult.dataset.error = "false";
  elements.samplingResult.textContent = "Aplicando…";
  setSupportMailto(elements.samplingResult, false);
  try {
    const response = await fetch("/api/poll-interval", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ seconds })
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || `HTTP ${response.status}`);
    elements.pollInterval.value = String(result.poll_interval_seconds);
    updateSamplingEstimate(result.poll_interval_seconds);
    elements.samplingResult.textContent = "Guardado y activo";
    setSupportMailto(elements.samplingResult, false);
  } catch (error) {
    elements.samplingResult.dataset.error = "true";
    elements.samplingResult.textContent = error.message;
    setSupportMailto(elements.samplingResult, true, "Soporte VFREG Visor — Intervalo", error.message);
  } finally {
    elements.samplingSave.disabled = false;
  }
}

function adjustReportDateInputs() {
  if (reportFormat === "daily") {
    elements.reportFrom.type = "date";
    elements.reportTo.type = "date";
    if (elements.reportFrom.value.length >= 10) {
      elements.reportFrom.value = elements.reportFrom.value.slice(0, 10);
    }
    if (elements.reportTo.value.length >= 10) {
      elements.reportTo.value = elements.reportTo.value.slice(0, 10);
    }
  } else {
    elements.reportFrom.type = "datetime-local";
    elements.reportTo.type = "datetime-local";
    if (elements.reportFrom.value.length === 10) {
      elements.reportFrom.value = `${elements.reportFrom.value}T00:00:00`;
    }
    if (elements.reportTo.value.length === 10) {
      elements.reportTo.value = `${elements.reportTo.value}T23:59:59`;
    }
  }
}

function openCustomForm(form, fromElement, toElement) {
  const opening = form.hidden;
  form.hidden = !opening;
  if (!opening) return;
  if (form === elements.reportCustomForm) adjustReportDateInputs();
  const range = resolvedRange();
  const now = new Date();
  let fromValue = range.from || localInputValue(new Date(now.getTime() - 15 * 60000));
  let toValue = range.to || localInputValue(now);
  if (fromElement.type === "date") {
    fromValue = fromValue.slice(0, 10);
    toValue = toValue.slice(0, 10);
  }
  fromElement.value = fromValue;
  toElement.value = toValue;
  fromElement.focus();
}

function openHistoryCustomForm() {
  const opening = elements.historyViewFilterForm.hidden;
  elements.historyViewFilterForm.hidden = !opening;
  if (!opening) return;
  const range = resolvedHistorySourceRange();
  elements.historyViewFrom.value = range.from;
  elements.historyViewTo.value = range.to;
  elements.historyViewFrom.focus();
}

function setReportFormat(format) {
  reportFormat = format;
  document.querySelectorAll("[data-report-format]").forEach((button) => {
    const selected = button.dataset.reportFormat === format;
    button.classList.toggle("is-selected", selected);
    button.setAttribute("aria-pressed", String(selected));
  });
  adjustReportDateInputs();
  updateReportSummary();
}

function setChartExportInterval(value) {
  const allowed = new Set(["auto", "1", "5", "10", "15", "30"]);
  if (!allowed.has(value)) return;
  chartExportInterval = value;
  document.querySelectorAll("[data-chart-export-interval]").forEach((button) => {
    const selected = button.dataset.chartExportInterval === value;
    button.classList.toggle("is-selected", selected);
    button.setAttribute("aria-checked", String(selected));
    button.tabIndex = selected ? 0 : -1;
  });
  updateReportSummary();
}

function moveChartExportIntervalFocus(event) {
  const buttons = [...document.querySelectorAll("[data-chart-export-interval]")];
  const current = buttons.indexOf(event.currentTarget);
  let target = current;
  if (event.key === "ArrowRight" || event.key === "ArrowDown") target = (current + 1) % buttons.length;
  else if (event.key === "ArrowLeft" || event.key === "ArrowUp") target = (current - 1 + buttons.length) % buttons.length;
  else if (event.key === "Home") target = 0;
  else if (event.key === "End") target = buttons.length - 1;
  else return;
  event.preventDefault();
  setChartExportInterval(buttons[target].dataset.chartExportInterval);
  buttons[target].focus();
}

document.querySelectorAll("[data-view]").forEach((button) => button.addEventListener("click", () => setView(button.dataset.view)));
document.querySelectorAll("[data-view-target]").forEach((button) => button.addEventListener("click", () => setView(button.dataset.viewTarget)));
document.querySelectorAll("[data-go-reports]").forEach((button) => button.addEventListener("click", () => {
  selectPresetButton();
  setView("reports");
}));
elements.retryConnection.addEventListener("click", refresh);
elements.reportDownload.addEventListener("click", (event) => {
  if (reportFormat === "csv") {
    elements.exportStatus.dataset.error = "false";
    elements.exportStatus.textContent = "Descarga CSV iniciada";
    setSupportMailto(elements.exportStatus, false);
  } else downloadXlsx(event);
});
elements.archiveWipeOpen.addEventListener("click", openArchiveWipeDialog);
elements.archiveWipeCancel.addEventListener("click", closeArchiveWipeDialog);
elements.archiveWipeCancel2.addEventListener("click", closeArchiveWipeDialog);
elements.archiveWipeContinue.addEventListener("click", showArchiveWipeStep2);
elements.archiveWipeConfirm.addEventListener("input", syncArchiveWipeConfirm);
elements.archiveWipeConfirm.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    confirmArchiveAndWipe();
  }
});
elements.archiveWipeConfirmBtn.addEventListener("click", confirmArchiveAndWipe);
elements.archiveWipeDialog.addEventListener("cancel", (event) => {
  event.preventDefault();
  closeArchiveWipeDialog();
});
elements.csvExport.addEventListener("click", () => setReportFormat("csv"));
elements.xlsxExport.addEventListener("click", () => setReportFormat("xlsx"));
elements.dailyExport.addEventListener("click", () => setReportFormat("daily"));
document.querySelectorAll("[data-chart-export-interval]").forEach((button) => {
  button.addEventListener("click", () => setChartExportInterval(button.dataset.chartExportInterval));
  button.addEventListener("keydown", moveChartExportIntervalFocus);
});
elements.pollInterval.addEventListener("change", () => updateSamplingEstimate(elements.pollInterval.value));
elements.samplingForm.addEventListener("submit", savePollingInterval);
elements.historyFilterForm.addEventListener("submit", submitHistoryFilter);
elements.historyFilterClear.addEventListener("click", clearHistoryFilter);
elements.workdayFilter.addEventListener("click", applyWorkday);
elements.customRangeToggle.addEventListener("click", () => {
  openCustomForm(elements.historyFilterForm, elements.historyFrom, elements.historyTo);
  elements.customRangeToggle.setAttribute("aria-expanded", String(!elements.historyFilterForm.hidden));
});
document.querySelectorAll("[data-range-minutes]").forEach((button) => {
  button.addEventListener("click", () => applyPreset(Number(button.dataset.rangeMinutes)));
});
document.querySelectorAll("[data-history-minutes]").forEach((button) => {
  button.addEventListener("click", () => applyHistorySampling(Number(button.dataset.historyMinutes)));
});
document.querySelectorAll("[data-history-workday]").forEach((button) => button.addEventListener("click", applyHistoryWorkday));
document.querySelectorAll("[data-history-custom]").forEach((button) => {
  button.addEventListener("click", openHistoryCustomForm);
});
elements.historyViewFilterForm.addEventListener("submit", (event) => {
  event.preventDefault();
  applyHistoryCustomRange(elements.historyViewFrom.value, elements.historyViewTo.value);
});
elements.historyViewFilterClear.addEventListener("click", () => {
  elements.historyViewFrom.value = "";
  elements.historyViewTo.value = "";
  elements.historyViewFilterForm.hidden = true;
  applyHistoryWorkday();
});
document.querySelectorAll("[data-report-scope]").forEach((button) => {
  button.addEventListener("click", () => {
    const scope = button.dataset.reportScope;
    if (scope === "workday") applyWorkday();
    else if (scope === "history") applyHistoricalRange();
    else {
      document.querySelectorAll("[data-report-scope]").forEach((candidate) => {
        const selected = candidate === button;
        candidate.classList.toggle("is-selected", selected);
        candidate.setAttribute("aria-pressed", String(selected));
      });
      openCustomForm(elements.reportCustomForm, elements.reportFrom, elements.reportTo);
    }
  });
});
elements.reportCustomForm.addEventListener("submit", (event) => {
  event.preventDefault();
  applyCustomRange(elements.reportFrom.value, elements.reportTo.value, elements.reportCustomResult);
});
document.querySelectorAll("[data-quality-filter]").forEach((button) => {
  button.addEventListener("click", () => {
    historyQuality = button.dataset.qualityFilter;
    document.querySelectorAll("[data-quality-filter]").forEach((candidate) => {
      const selected = candidate === button;
      candidate.dataset.active = String(selected);
      candidate.setAttribute("aria-pressed", String(selected));
    });
    renderReadings(historyReadings);
  });
});
document.querySelectorAll("[data-chart-mode]").forEach((button) => {
  button.addEventListener("click", () => {
    chartMode = button.dataset.chartMode;
    document.querySelectorAll("[data-chart-mode]").forEach((candidate) => {
      const selected = candidate === button;
      candidate.dataset.active = String(selected);
      candidate.setAttribute("aria-pressed", String(selected));
    });
    drawChart(currentReadings);
  });
});
elements.chartZoom.addEventListener("input", () => drawChart(currentReadings));
elements.chartReset.addEventListener("click", () => {
  chartMode = "overview";
  elements.chartZoom.value = "1";
  document.querySelectorAll("[data-chart-mode]").forEach((button) => {
    const selected = button.dataset.chartMode === "overview";
    button.dataset.active = String(selected);
    button.setAttribute("aria-pressed", String(selected));
  });
  drawChart(currentReadings);
});
elements.canvas.addEventListener("pointermove", showChartTooltip);
elements.canvas.addEventListener("pointerleave", () => { elements.chartTooltip.hidden = true; });
elements.canvas.addEventListener("keydown", moveChartPoint);
elements.canvas.addEventListener("blur", () => { elements.chartTooltip.hidden = true; });
window.addEventListener("resize", () => {
  if (currentView === "live") {
    drawChart(currentReadings);
    drawSparklines(latestStatusData?.readings || []);
  }
  if (currentView === "reports" && reportFormat === "xlsx") renderWorkbookPreview();
});

updateClock();
setView("live");
selectPresetButton();
selectHistoryControls();
setChartExportInterval("auto");
setReportFormat("xlsx");
updateExportLinks();
refresh();
loadActiveRange();
window.setInterval(updateClock, 1000);
window.setInterval(refresh, 1000);
window.setInterval(() => {
  if (currentView === "history" && historySourceRange.key === "workday") {
    loadHistorySamples({ announce: false });
  } else if (currentView !== "history") {
    loadActiveRange({ announce: false });
  }
}, 5000);
