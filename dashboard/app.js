const PAUSE_THRESHOLDS = Object.freeze({
  voltageMax: 0.5,
  currentMax: 1,
  frequencyMin: 0.1
});

const elements = {
  siteName: document.querySelector("#site-name"),
  deviceName: document.querySelector("#device-name"),
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
  bannerTitle: document.querySelector("#banner-title"),
  bannerMessage: document.querySelector("#banner-message"),
  retryConnection: document.querySelector("#retry-connection"),
  recordsBody: document.querySelector("#records-body"),
  recordCount: document.querySelector("#record-count"),
  recordCountLabel: document.querySelector("#record-count-label"),
  historyMode: document.querySelector("#history-mode"),
  networkEndpoint: document.querySelector("#network-endpoint"),
  storageHealth: document.querySelector("#storage-health"),
  appVersion: document.querySelector("#app-version"),
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
  historicalCsvExport: document.querySelector("#historical-csv-export"),
  exportPeriod: document.querySelector("#export-period"),
  exportStatus: document.querySelector("#export-status"),
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
  focusRangeControls: document.querySelector("#focus-range-controls")
};

let currentReadings = [];
let currentRangeCount = 0;
let latestStatusData = null;
let activeRange = { key: "15m", minutes: 15, label: "Últimos 15 minutos", rolling: true };
let currentView = "live";
let historyQuality = "all";
let chartMode = "overview";
let chartPoints = [];
let rangeRefreshBusy = false;

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
}

function renderReadings(readings) {
  const filtered = readings.filter((reading) => {
    const mode = rowMode(reading);
    if (historyQuality === "alarm") return mode === "alarm";
    if (historyQuality === "valid") return mode !== "alarm";
    return true;
  });
  elements.recordCount.textContent = filtered.length.toLocaleString("es-AR");
  elements.recordCountLabel.textContent = filtered.length === currentRangeCount
    ? "lecturas del período"
    : `de ${currentRangeCount.toLocaleString("es-AR")} lecturas del período`;
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

  filtered.slice(-50).reverse().forEach((reading) => {
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
    elements.recordsBody.appendChild(row);
  });

}

function renderHistory(readings, count, modeLabel) {
  currentReadings = readings || [];
  currentRangeCount = Number(count || 0);
  elements.historyMode.textContent = modeLabel;
  renderReadings(currentReadings);
  drawChart(currentReadings);
  drawSparklines(currentReadings);
}

function renderStatus(data) {
  const latest = data.latest;
  const mode = processMode(data);
  elements.siteName.textContent = data.site_name;
  elements.deviceName.textContent = data.device_name;
  elements.appVersion.textContent = `VFREG Visor ${data.app_version}`;
  elements.networkEndpoint.textContent = data.network.mode === "modbus_tcp_client"
    ? `Conexión: ${data.network.tcp_host}:${data.network.tcp_port}`
    : `Puerto de escucha: ${data.network.tcp_port}`;

  const storage = data.diagnostics?.storage || {};
  const storageState = String(storage.storage_health || "STARTING").toUpperCase();
  const storageLabels = { HEALTHY: "saludable", WARNING: "advertencia", CRITICAL: "crítico", STARTING: "iniciando" };
  elements.storageHealth.textContent = `Almacenamiento: ${storageLabels[storageState] || storageState.toLowerCase()}`;

  const pollInterval = Number(data.network.poll_interval_seconds);
  if (Number.isFinite(pollInterval) && document.activeElement !== elements.pollInterval) {
    elements.pollInterval.value = String(pollInterval);
    updateSamplingEstimate(pollInterval);
  }

  if (latest) {
    const timestamp = timestampParts(latest.timestamp);
    elements.readingTime.textContent = timestamp.time;
    elements.readingDate.textContent = timestamp.date;
  } else {
    elements.readingTime.textContent = "--:--:--";
    elements.readingDate.textContent = "Sin lecturas";
  }

  updateConnectionAndProcess(data, mode);
  updateMetrics(data, mode);
  updateSystemBanner(data, mode);
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

function showChartTooltip(event) {
  if (!chartPoints.length) return;
  const bounds = elements.canvas.getBoundingClientRect();
  const pointerX = event.clientX - bounds.left;
  const point = chartPoints.reduce((closest, candidate) =>
    Math.abs(candidate.x - pointerX) < Math.abs(closest.x - pointerX) ? candidate : closest
  );
  const reading = point.reading;
  elements.chartTooltip.innerHTML = `<strong>${timestampParts(reading.timestamp).full}</strong>${CHART_SERIES.map((series) =>
    `<span>${series.label}: ${number(reading[series.key], series.digits)} ${series.unit}</span>`
  ).join("")}`;
  elements.chartTooltip.hidden = false;
  elements.chartTooltip.style.left = `${Math.min(bounds.width - 190, Math.max(8, point.x + 10))}px`;
  elements.chartTooltip.style.top = "12px";
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
    if (active) button.setAttribute("aria-current", "page");
    else button.removeAttribute("aria-current");
  });
  if (view === "live") window.requestAnimationFrame(() => {
    drawChart(currentReadings);
    drawSparklines(currentReadings);
  });
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

function filterQuery({ historical = false } = {}) {
  const range = resolvedRange();
  const query = new URLSearchParams();
  if (!historical && range.from) query.set("from", range.from);
  if (range.to) query.set("to", range.to);
  return `?${query.toString()}`;
}

function updateExportLinks() {
  const query = filterQuery();
  elements.csvExport.href = `/api/export.csv${query}`;
  elements.xlsxExport.href = `/api/export.xlsx${query}`;
  elements.historicalCsvExport.href = `/api/export.csv${filterQuery({ historical: true })}`;
  elements.exportPeriod.textContent = activeRange.label;
  elements.activeRangeLabel.textContent = activeRange.label;
}

function selectPresetButton(selected) {
  document.querySelectorAll(".shared-range .preset-filters button").forEach((button) => {
    button.dataset.active = String(button === selected);
  });
}

async function loadActiveRange({ announce = true } = {}) {
  if (rangeRefreshBusy) return;
  const { from, to } = resolvedRange();
  if (from && to && new Date(from) > new Date(to)) {
    elements.historyFilterResult.dataset.error = "true";
    elements.historyFilterResult.textContent = "La fecha Desde debe ser anterior a Hasta";
    return;
  }
  rangeRefreshBusy = true;
  updateExportLinks();
  elements.historyFilterResult.dataset.error = "false";
  if (announce) elements.historyFilterResult.textContent = "Cargando período…";
  const query = new URLSearchParams({ limit: "5000" });
  if (from) query.set("from", from);
  if (to) query.set("to", to);
  try {
    const response = await fetch(`/api/readings?${query.toString()}`, { cache: "no-store" });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || `HTTP ${response.status}`);
    renderHistory(result.readings || [], result.count || 0, activeRange.label);
    const hiddenCount = Math.max(0, Number(result.count || 0) - (result.readings || []).length);
    elements.historyFilterResult.textContent = hiddenCount
      ? `${Number(result.count).toLocaleString("es-AR")} coincidencias; se muestran las últimas 5.000`
      : `${Number(result.count || 0).toLocaleString("es-AR")} lecturas en ${activeRange.label.toLowerCase()}`;
  } catch (error) {
    elements.historyFilterResult.dataset.error = "true";
    elements.historyFilterResult.textContent = error.message;
  } finally {
    rangeRefreshBusy = false;
  }
}

function applyPreset(minutes, button) {
  activeRange = {
    key: `${minutes}m`,
    minutes,
    label: minutes === 60 ? "Última hora" : `Últimos ${minutes} minutos`,
    rolling: true
  };
  selectPresetButton(button);
  elements.historyFilterForm.hidden = true;
  elements.customRangeToggle.setAttribute("aria-expanded", "false");
  loadActiveRange();
}

function applyWorkday() {
  activeRange = { key: "workday", label: `Jornada actual · desde ${productionStartTime()}`, rolling: true };
  selectPresetButton(elements.workdayFilter);
  elements.historyFilterForm.hidden = true;
  elements.customRangeToggle.setAttribute("aria-expanded", "false");
  loadActiveRange();
}

function submitHistoryFilter(event) {
  event.preventDefault();
  const from = elements.historyFrom.value;
  const to = elements.historyTo.value;
  if (!from || !to) {
    elements.historyFilterResult.dataset.error = "true";
    elements.historyFilterResult.textContent = "Complete Desde y Hasta para aplicar el período";
    return;
  }
  if (new Date(from) > new Date(to)) {
    elements.historyFilterResult.dataset.error = "true";
    elements.historyFilterResult.textContent = "La fecha Desde debe ser anterior a Hasta";
    return;
  }
  activeRange = { key: "custom", from, to, label: "Período personalizado", rolling: false };
  selectPresetButton(elements.customRangeToggle);
  loadActiveRange();
}

function clearHistoryFilter() {
  elements.historyFrom.value = "";
  elements.historyTo.value = "";
  const defaultButton = document.querySelector('[data-range-minutes="15"]');
  applyPreset(15, defaultButton);
}

async function downloadXlsx(event) {
  event.preventDefault();
  if (elements.xlsxExport.dataset.busy === "true") return;
  elements.xlsxExport.dataset.busy = "true";
  elements.xlsxExport.setAttribute("aria-disabled", "true");
  elements.exportStatus.dataset.error = "false";
  elements.exportStatus.textContent = "Preparando archivo Excel…";
  try {
    const response = await fetch(elements.xlsxExport.href, { cache: "no-store" });
    if (!response.ok) {
      const result = await response.json().catch(() => ({}));
      throw new Error(result.error || `No se pudo exportar Excel (HTTP ${response.status})`);
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const download = document.createElement("a");
    download.href = url;
    download.download = "vfreg-readings.xlsx";
    document.body.appendChild(download);
    download.click();
    download.remove();
    URL.revokeObjectURL(url);
    elements.exportStatus.textContent = "Excel descargado correctamente";
  } catch (error) {
    elements.exportStatus.dataset.error = "true";
    elements.exportStatus.textContent = error.message;
  } finally {
    elements.xlsxExport.dataset.busy = "false";
    elements.xlsxExport.removeAttribute("aria-disabled");
  }
}

async function savePollingInterval(event) {
  event.preventDefault();
  const seconds = Number(elements.pollInterval.value);
  elements.samplingSave.disabled = true;
  elements.samplingResult.dataset.error = "false";
  elements.samplingResult.textContent = "Aplicando…";
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
  } catch (error) {
    elements.samplingResult.dataset.error = "true";
    elements.samplingResult.textContent = error.message;
  } finally {
    elements.samplingSave.disabled = false;
  }
}

document.querySelectorAll("[data-view]").forEach((button) => button.addEventListener("click", () => setView(button.dataset.view)));
document.querySelectorAll("[data-view-target]").forEach((button) => button.addEventListener("click", () => setView(button.dataset.viewTarget)));
document.querySelectorAll("[data-go-reports]").forEach((button) => button.addEventListener("click", () => setView("reports")));
elements.retryConnection.addEventListener("click", refresh);
elements.xlsxExport.addEventListener("click", downloadXlsx);
elements.csvExport.addEventListener("click", () => {
  elements.exportStatus.dataset.error = "false";
  elements.exportStatus.textContent = "Descarga CSV iniciada";
});
elements.historicalCsvExport.addEventListener("click", () => {
  elements.exportStatus.dataset.error = "false";
  elements.exportStatus.textContent = "Descarga histórica iniciada";
});
elements.pollInterval.addEventListener("change", () => updateSamplingEstimate(elements.pollInterval.value));
elements.samplingForm.addEventListener("submit", savePollingInterval);
elements.historyFilterForm.addEventListener("submit", submitHistoryFilter);
elements.historyFilterClear.addEventListener("click", clearHistoryFilter);
elements.workdayFilter.addEventListener("click", applyWorkday);
elements.customRangeToggle.addEventListener("click", () => {
  const opening = elements.historyFilterForm.hidden;
  elements.historyFilterForm.hidden = !opening;
  elements.customRangeToggle.setAttribute("aria-expanded", String(opening));
  if (opening) {
    const range = resolvedRange();
    elements.historyFrom.value = range.from;
    elements.historyTo.value = range.to;
    elements.historyFrom.focus();
  }
});
elements.focusRangeControls.addEventListener("click", () => {
  document.querySelector(".shared-range").scrollIntoView({ behavior: "smooth", block: "start" });
  elements.customRangeToggle.focus();
});
document.querySelectorAll("[data-range-minutes]").forEach((button) => {
  button.addEventListener("click", () => applyPreset(Number(button.dataset.rangeMinutes), button));
});
document.querySelectorAll("[data-quality-filter]").forEach((button) => {
  button.addEventListener("click", () => {
    historyQuality = button.dataset.qualityFilter;
    document.querySelectorAll("[data-quality-filter]").forEach((candidate) => {
      candidate.dataset.active = String(candidate === button);
    });
    renderReadings(currentReadings);
  });
});
document.querySelectorAll("[data-chart-mode]").forEach((button) => {
  button.addEventListener("click", () => {
    chartMode = button.dataset.chartMode;
    document.querySelectorAll("[data-chart-mode]").forEach((candidate) => {
      candidate.dataset.active = String(candidate === button);
    });
    drawChart(currentReadings);
  });
});
elements.chartZoom.addEventListener("input", () => drawChart(currentReadings));
elements.chartReset.addEventListener("click", () => {
  chartMode = "overview";
  elements.chartZoom.value = "1";
  document.querySelectorAll("[data-chart-mode]").forEach((button) => {
    button.dataset.active = String(button.dataset.chartMode === "overview");
  });
  drawChart(currentReadings);
});
elements.canvas.addEventListener("pointermove", showChartTooltip);
elements.canvas.addEventListener("pointerleave", () => { elements.chartTooltip.hidden = true; });
window.addEventListener("resize", () => {
  if (currentView === "live") {
    drawChart(currentReadings);
    drawSparklines(currentReadings);
  }
});

updateClock();
setView("live");
updateExportLinks();
refresh();
loadActiveRange();
window.setInterval(updateClock, 1000);
window.setInterval(refresh, 1000);
window.setInterval(() => loadActiveRange({ announce: false }), 5000);
