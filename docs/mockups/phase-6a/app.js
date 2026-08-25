const palette = {
  voltage: "#0b929d",
  current: "#7255a5",
  frequency: "#c47a13",
  grid: "#dfe7e9",
  muted: "#6a7b83",
  ink: "#17313d",
};

const state = {
  view: "live",
  demo: "normal",
  chartMode: "overview",
  range: "15",
  historyQuality: "all",
  reportScope: "workday",
  reportFormat: "xlsx",
};

const elements = {
  connectionPill: document.querySelector("#connection-pill"),
  connectionTitle: document.querySelector("#connection-title"),
  connectionDetail: document.querySelector("#connection-detail"),
  connectionSymbol: document.querySelector(".connection-symbol"),
  currentTime: document.querySelector("#current-time"),
  currentDate: document.querySelector("#current-date"),
  demoState: document.querySelector("#demo-state"),
  systemBanner: document.querySelector("#system-banner"),
  bannerTitle: document.querySelector("#banner-title"),
  bannerMessage: document.querySelector("#banner-message"),
  metricVoltage: document.querySelector("#metric-voltage"),
  metricCurrent: document.querySelector("#metric-current"),
  metricFrequency: document.querySelector("#metric-frequency"),
  selectedPeriod: document.querySelector("#selected-period"),
  customRange: document.querySelector("#custom-range"),
  customFrom: document.querySelector("#custom-from"),
  customTo: document.querySelector("#custom-to"),
  customResult: document.querySelector("#custom-result"),
  chart: document.querySelector("#main-chart"),
  chartTooltip: document.querySelector("#chart-tooltip"),
  chartLegend: document.querySelector("#chart-legend"),
  liveRows: document.querySelector("#live-reading-rows"),
  historyRows: document.querySelector("#history-reading-rows"),
  historyCount: document.querySelector("#history-count"),
  historyPeriod: document.querySelector("#history-period"),
  reportPeriod: document.querySelector("#report-period"),
  reportCount: document.querySelector("#report-count"),
  reportFormat: document.querySelector("#report-format"),
  reportContent: document.querySelector("#report-content"),
  simulateDownload: document.querySelector("#simulate-download"),
  exportDialog: document.querySelector("#export-dialog"),
  toast: document.querySelector("#toast"),
};

function generateReadings(count = 96) {
  const readings = [];
  const end = new Date(2026, 7, 25, 10, 42, 15);
  for (let index = 0; index < count; index += 1) {
    const reverseIndex = count - 1 - index;
    const timestamp = new Date(end.getTime() - reverseIndex * 15_000);
    const wave = Math.sin(index / 6.3);
    const secondaryWave = Math.sin(index / 2.7);
    let voltage = 36.6 + wave * 0.65 + secondaryWave * 0.2;
    let current = 421 + wave * 31 + secondaryWave * 18 + (index % 8) * 2;
    let frequency = 202.15 + Math.sin(index / 5.1) * 0.25 + (index % 5) * 0.025;
    let quality = "valid";
    if ([17, 44, 72].includes(index)) {
      current = index === 72 ? 575 : 238;
      quality = "alarm";
    }
    readings.push({
      timestamp,
      voltage: Number(voltage.toFixed(1)),
      current: Math.round(current),
      frequency: Number(frequency.toFixed(1)),
      quality,
    });
  }
  return readings;
}

const readings = generateReadings();
let hoverPoints = [];
let toastTimer = null;

function formatDate(date) {
  return new Intl.DateTimeFormat("es-AR", { day: "2-digit", month: "2-digit", year: "numeric" }).format(date);
}

function formatTime(date) {
  return new Intl.DateTimeFormat("es-AR", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(date);
}

function updateClock() {
  const now = new Date();
  elements.currentTime.textContent = formatTime(now);
  elements.currentDate.textContent = new Intl.DateTimeFormat("es-AR", {
    weekday: "long",
    day: "numeric",
    month: "long",
  }).format(now);
}

function setView(view) {
  state.view = view;
  document.querySelectorAll("[data-view-panel]").forEach((panel) => {
    panel.classList.toggle("is-active", panel.dataset.viewPanel === view);
  });
  document.querySelectorAll(".nav-button").forEach((button) => {
    const active = button.dataset.view === view;
    button.classList.toggle("is-active", active);
    if (active) button.setAttribute("aria-current", "page");
    else button.removeAttribute("aria-current");
  });
  window.scrollTo({ top: 0, behavior: "smooth" });
  if (view === "live") window.requestAnimationFrame(drawAllCharts);
}

function qualityText(quality) {
  return quality === "alarm" ? "Fuera de rango" : "Válida";
}

function rowMarkup(reading) {
  return `<tr data-quality="${reading.quality}">
    <td>${formatDate(reading.timestamp)}</td>
    <td>${formatTime(reading.timestamp)}</td>
    <td>${reading.voltage.toFixed(1)} V</td>
    <td>${reading.current} mA</td>
    <td>${reading.frequency.toFixed(1)} Hz</td>
    <td><span class="table-status">${qualityText(reading.quality)}</span></td>
  </tr>`;
}

function renderTables() {
  elements.liveRows.innerHTML = readings.slice(-5).reverse().map(rowMarkup).join("");
  let historyRows = readings.slice(-48).reverse();
  if (state.historyQuality === "valid") historyRows = historyRows.filter((reading) => reading.quality === "valid");
  if (state.historyQuality === "alarm") historyRows = historyRows.filter((reading) => reading.quality === "alarm");
  elements.historyRows.innerHTML = historyRows.length
    ? historyRows.map(rowMarkup).join("")
    : `<tr><td colspan="6" style="height:120px;text-align:center;color:#657780">No hay lecturas para este filtro.</td></tr>`;
  elements.historyCount.textContent = historyRows.length.toLocaleString("es-AR");
}

function prepareCanvas(canvas) {
  const rect = canvas.getBoundingClientRect();
  const ratio = Math.max(1, window.devicePixelRatio || 1);
  const width = Math.max(1, Math.round(rect.width));
  const height = Math.max(1, Math.round(rect.height));
  canvas.width = Math.round(width * ratio);
  canvas.height = Math.round(height * ratio);
  const context = canvas.getContext("2d");
  context.setTransform(ratio, 0, 0, ratio, 0, 0);
  context.lineCap = "round";
  context.lineJoin = "round";
  return { context, width, height };
}

function drawSparkline(canvas, values, color) {
  const { context, width, height } = prepareCanvas(canvas);
  context.clearRect(0, 0, width, height);
  if (state.demo === "disconnected") {
    context.setLineDash([4, 5]);
    context.strokeStyle = "#b5c0c5";
    context.beginPath();
    context.moveTo(0, height / 2);
    context.lineTo(width, height / 2);
    context.stroke();
    return;
  }
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = Math.max(0.1, max - min);
  const points = values.map((value, index) => ({
    x: (index / (values.length - 1)) * width,
    y: height - 5 - ((value - min) / span) * (height - 10),
  }));
  const gradient = context.createLinearGradient(0, 0, 0, height);
  gradient.addColorStop(0, `${color}30`);
  gradient.addColorStop(1, `${color}00`);
  context.beginPath();
  context.moveTo(points[0].x, height);
  points.forEach((point) => context.lineTo(point.x, point.y));
  context.lineTo(points.at(-1).x, height);
  context.closePath();
  context.fillStyle = gradient;
  context.fill();
  context.beginPath();
  points.forEach((point, index) => index ? context.lineTo(point.x, point.y) : context.moveTo(point.x, point.y));
  context.strokeStyle = color;
  context.lineWidth = 2;
  context.stroke();
}

function visibleReadings() {
  const countMap = { "5": 20, "15": 60, "30": 80, "60": 96, workday: 96, custom: 45 };
  return readings.slice(-countMap[state.range]);
}

function drawGrid(context, left, top, width, height, rows = 4) {
  context.strokeStyle = palette.grid;
  context.lineWidth = 1;
  context.setLineDash([2, 4]);
  for (let index = 0; index <= rows; index += 1) {
    const y = top + (index / rows) * height;
    context.beginPath();
    context.moveTo(left, y);
    context.lineTo(left + width, y);
    context.stroke();
  }
  context.setLineDash([]);
}

function drawSeries(context, values, color, left, top, width, height, min, max, lineWidth = 1.8) {
  const span = Math.max(0.0001, max - min);
  const points = values.map((value, index) => ({
    x: left + (index / Math.max(1, values.length - 1)) * width,
    y: top + height - ((value - min) / span) * height,
  }));
  context.beginPath();
  points.forEach((point, index) => index ? context.lineTo(point.x, point.y) : context.moveTo(point.x, point.y));
  context.strokeStyle = color;
  context.lineWidth = lineWidth;
  context.stroke();
  return points;
}

function drawOverview(context, width, height, data) {
  const left = 72;
  const right = 18;
  const top = 8;
  const bottom = 22;
  const gap = 10;
  const plotWidth = width - left - right;
  const laneHeight = (height - top - bottom - gap * 2) / 3;
  const configs = [
    { key: "voltage", label: "Voltaje", unit: "V", color: palette.voltage },
    { key: "current", label: "Corriente", unit: "mA", color: palette.current },
    { key: "frequency", label: "Frecuencia", unit: "Hz", color: palette.frequency },
  ];
  hoverPoints = [];
  configs.forEach((config, laneIndex) => {
    const laneTop = top + laneIndex * (laneHeight + gap);
    const values = data.map((row) => row[config.key]);
    const min = Math.min(...values);
    const max = Math.max(...values);
    const padding = Math.max((max - min) * 0.15, config.key === "frequency" ? 0.1 : 1);
    drawGrid(context, left, laneTop, plotWidth, laneHeight, 2);
    context.fillStyle = palette.muted;
    context.font = "700 9px Segoe UI, Arial";
    context.fillText(config.label, 5, laneTop + 13);
    context.font = "8px Segoe UI, Arial";
    context.fillText(config.unit, 5, laneTop + 25);
    const points = drawSeries(context, values, config.color, left, laneTop + 4, plotWidth, laneHeight - 8, min - padding, max + padding);
    points.forEach((point, index) => {
      hoverPoints[index] ??= { x: point.x, reading: data[index], y: laneTop + laneHeight / 2 };
    });
  });
  drawTimeLabels(context, data, left, top + laneHeight * 3 + gap * 2, plotWidth);
}

function drawDetail(context, width, height, data, key) {
  const configMap = {
    voltage: { label: "Voltaje", unit: "V", color: palette.voltage },
    current: { label: "Corriente", unit: "mA", color: palette.current },
    frequency: { label: "Frecuencia", unit: "Hz", color: palette.frequency },
  };
  const config = configMap[key];
  const left = 54;
  const right = 18;
  const top = 16;
  const bottom = 28;
  const plotWidth = width - left - right;
  const plotHeight = height - top - bottom;
  const values = data.map((row) => row[key]);
  const minValue = Math.min(...values);
  const maxValue = Math.max(...values);
  const padding = Math.max((maxValue - minValue) * 0.2, key === "frequency" ? 0.2 : 2);
  const min = minValue - padding;
  const max = maxValue + padding;
  drawGrid(context, left, top, plotWidth, plotHeight, 4);
  context.fillStyle = palette.muted;
  context.font = "8px Segoe UI, Arial";
  for (let index = 0; index <= 4; index += 1) {
    const value = max - (index / 4) * (max - min);
    context.fillText(key === "current" ? value.toFixed(0) : value.toFixed(1), 6, top + (index / 4) * plotHeight + 3);
  }
  const points = drawSeries(context, values, config.color, left, top, plotWidth, plotHeight, min, max, 2.2);
  hoverPoints = points.map((point, index) => ({ ...point, reading: data[index] }));
  drawTimeLabels(context, data, left, top + plotHeight, plotWidth);
}

function drawTimeLabels(context, data, left, bottomY, width) {
  const indexes = [0, Math.floor((data.length - 1) / 2), data.length - 1];
  context.fillStyle = palette.muted;
  context.font = "8px Segoe UI, Arial";
  indexes.forEach((dataIndex, labelIndex) => {
    const x = left + (labelIndex / 2) * width;
    context.textAlign = labelIndex === 0 ? "left" : labelIndex === 2 ? "right" : "center";
    context.fillText(formatTime(data[dataIndex].timestamp).slice(0, 5), x, bottomY + 15);
  });
  context.textAlign = "left";
}

function drawMainChart() {
  const { context, width, height } = prepareCanvas(elements.chart);
  context.clearRect(0, 0, width, height);
  const data = visibleReadings();
  if (state.chartMode === "overview") drawOverview(context, width, height, data);
  else drawDetail(context, width, height, data, state.chartMode);
  elements.chartLegend.hidden = false;
  elements.chartLegend.querySelectorAll("span").forEach((item) => {
    const key = item.className.replace("legend-", "");
    item.hidden = state.chartMode !== "overview" && key !== state.chartMode;
  });
}

function drawAllCharts() {
  const recent = readings.slice(-28);
  drawSparkline(document.querySelector("#spark-voltage"), recent.map((row) => row.voltage), palette.voltage);
  drawSparkline(document.querySelector("#spark-current"), recent.map((row) => row.current), palette.current);
  drawSparkline(document.querySelector("#spark-frequency"), recent.map((row) => row.frequency), palette.frequency);
  drawMainChart();
}

function updateMetricCard(card, quality, label, symbol) {
  card.dataset.quality = quality;
  const badge = card.querySelector(".quality-badge");
  badge.innerHTML = `<b aria-hidden="true">${symbol}</b> ${label}`;
}

function applyDemoState(mode) {
  state.demo = mode;
  elements.connectionPill.dataset.state = mode;
  const cards = [...document.querySelectorAll(".metric-card")];
  const latest = readings.at(-1);
  elements.systemBanner.classList.toggle("is-hidden", mode === "normal");
  elements.systemBanner.dataset.state = mode === "disconnected" ? "danger" : mode === "paused" ? "info" : "warning";

  if (mode === "normal") {
    elements.connectionTitle.textContent = "Conectado";
    elements.connectionDetail.textContent = "Actualizado hace 3 s";
    elements.connectionSymbol.textContent = "✓";
    elements.metricVoltage.textContent = latest.voltage.toFixed(1);
    elements.metricCurrent.textContent = String(latest.current);
    elements.metricFrequency.textContent = latest.frequency.toFixed(1);
    cards.forEach((card) => updateMetricCard(card, "normal", "Normal", "✓"));
  } else if (mode === "paused") {
    elements.connectionTitle.textContent = "Conectado";
    elements.connectionDetail.textContent = "Producción detenida · actualizado hace 3 s";
    elements.connectionSymbol.textContent = "⏸";
    elements.metricVoltage.textContent = "0.0";
    elements.metricCurrent.textContent = "0";
    elements.metricFrequency.textContent = latest.frequency.toFixed(1);
    updateMetricCard(cards[0], "paused", "Sin producción", "⏸");
    updateMetricCard(cards[1], "paused", "Sin producción", "⏸");
    updateMetricCard(cards[2], "normal", "Dato recibido", "✓");
    elements.bannerTitle.textContent = "Producción detenida";
    elements.bannerMessage.textContent = "El visor sigue conectado y enviando frecuencia; voltaje y corriente están en cero. No se considera una falla de conexión.";
  } else if (mode === "alarm") {
    elements.connectionTitle.textContent = "Conectado";
    elements.connectionDetail.textContent = "1 valor requiere revisión";
    elements.connectionSymbol.textContent = "!";
    elements.metricVoltage.textContent = latest.voltage.toFixed(1);
    elements.metricCurrent.textContent = "585";
    elements.metricFrequency.textContent = latest.frequency.toFixed(1);
    updateMetricCard(cards[0], "normal", "Normal", "✓");
    updateMetricCard(cards[1], "alarm", "Fuera de rango", "!");
    updateMetricCard(cards[2], "normal", "Normal", "✓");
    elements.bannerTitle.textContent = "Corriente fuera del rango configurado";
    elements.bannerMessage.textContent = "La lectura simulada es 585 mA. Revise el proceso y los límites aprobados.";
  } else if (mode === "stale") {
    elements.connectionTitle.textContent = "Sin datos recientes";
    elements.connectionDetail.textContent = "Última lectura hace 42 s";
    elements.connectionSymbol.textContent = "!";
    elements.metricVoltage.textContent = latest.voltage.toFixed(1);
    elements.metricCurrent.textContent = String(latest.current);
    elements.metricFrequency.textContent = latest.frequency.toFixed(1);
    cards.forEach((card) => updateMetricCard(card, "stale", "Dato demorado", "!"));
    elements.bannerTitle.textContent = "No se reciben datos recientes";
    elements.bannerMessage.textContent = "La conexión existe, pero la última lectura tiene más demora de la esperada.";
  } else {
    elements.connectionTitle.textContent = "Desconectado";
    elements.connectionDetail.textContent = "Intentando reconectar";
    elements.connectionSymbol.textContent = "×";
    elements.metricVoltage.textContent = "--";
    elements.metricCurrent.textContent = "--";
    elements.metricFrequency.textContent = "--";
    cards.forEach((card) => updateMetricCard(card, "disconnected", "Sin conexión", "×"));
    elements.bannerTitle.textContent = "No se puede comunicar con el visor VFREG";
    elements.bannerMessage.textContent = "La aplicación seguirá intentando reconectar automáticamente. No se modificó el equipo.";
  }
  drawAllCharts();
}

function setRange(range, button) {
  state.range = range;
  document.querySelectorAll(".range-toolbar button").forEach((item) => item.classList.toggle("is-active", item === button));
  elements.customRange.classList.toggle("is-hidden", range !== "custom");
  const labelMap = {
    "5": "Hoy, 10:37–10:42",
    "15": "Hoy, 10:27–10:42",
    "30": "Hoy, 10:12–10:42",
    "60": "Hoy, 09:42–10:42",
    workday: "Hoy, 06:00–10:42",
    custom: "Seleccione fecha y hora",
  };
  elements.selectedPeriod.textContent = labelMap[range];
  drawMainChart();
}

function setChartMode(mode, button) {
  state.chartMode = mode;
  document.querySelectorAll("[data-chart-mode]").forEach((item) => {
    const active = item === button;
    item.classList.toggle("is-active", active);
    item.setAttribute("aria-selected", String(active));
  });
  drawMainChart();
}

function setHistoryQuality(quality, button) {
  state.historyQuality = quality;
  document.querySelectorAll("[data-quality-filter]").forEach((item) => item.classList.toggle("is-active", item === button));
  renderTables();
}

function showToast(message) {
  window.clearTimeout(toastTimer);
  elements.toast.textContent = message;
  elements.toast.classList.remove("is-hidden");
  toastTimer = window.setTimeout(() => elements.toast.classList.add("is-hidden"), 3200);
}

function setReportScope(scope, button) {
  state.reportScope = scope;
  document.querySelectorAll("[data-scope]").forEach((item) => item.classList.toggle("is-selected", item === button));
  const config = {
    workday: ["Reporte de jornada actual", "25/08/2026 · 06:00 hasta ahora", "1.644"],
    history: ["Reporte histórico completo", "21/08/2026–25/08/2026", "17.912"],
    custom: ["Reporte de periodo personalizado", "Periodo pendiente de configuración", "—"],
  }[scope];
  document.querySelector(".download-summary h2").textContent = config[0];
  elements.reportPeriod.textContent = config[1];
  elements.reportCount.textContent = config[2];
}

function setReportFormat(format, button) {
  state.reportFormat = format;
  document.querySelectorAll("[data-format]").forEach((item) => item.classList.toggle("is-selected", item === button));
  const xlsx = format === "xlsx";
  elements.reportFormat.textContent = xlsx ? "Excel con reporte" : "CSV sin procesar";
  elements.reportContent.textContent = xlsx ? "Raw Data + Report" : "Fecha, Hora, Volts, mAmp y Frec";
  elements.simulateDownload.textContent = xlsx ? "Descargar XLSX" : "Descargar CSV";
  document.querySelector(".workbook-preview").hidden = !xlsx;
}

function openExportDialog() {
  if (typeof elements.exportDialog.showModal === "function") elements.exportDialog.showModal();
  else setView("reports");
}

function handleChartPointer(event) {
  if (!hoverPoints.length) return;
  const rect = elements.chart.getBoundingClientRect();
  const pointerX = event.clientX - rect.left;
  const nearest = hoverPoints.reduce((best, point) => Math.abs(point.x - pointerX) < Math.abs(best.x - pointerX) ? point : best);
  const reading = nearest.reading;
  elements.chartTooltip.innerHTML = `<strong>${formatTime(reading.timestamp)}</strong><br>Voltaje: ${reading.voltage.toFixed(1)} V<br>Corriente: ${reading.current} mA<br>Frecuencia: ${reading.frequency.toFixed(1)} Hz`;
  elements.chartTooltip.style.left = `${Math.min(rect.width - 66, Math.max(66, nearest.x + 13))}px`;
  elements.chartTooltip.style.top = `${Math.max(72, nearest.y ?? 90)}px`;
  elements.chartTooltip.classList.remove("is-hidden");
}

document.querySelectorAll(".nav-button").forEach((button) => button.addEventListener("click", () => setView(button.dataset.view)));
document.querySelectorAll("[data-view-target]").forEach((button) => button.addEventListener("click", () => setView(button.dataset.viewTarget)));
document.querySelectorAll("[data-open-export]").forEach((button) => button.addEventListener("click", openExportDialog));
document.querySelectorAll("[data-chart-mode]").forEach((button) => button.addEventListener("click", () => setChartMode(button.dataset.chartMode, button)));
document.querySelectorAll(".range-toolbar button").forEach((button) => button.addEventListener("click", () => setRange(button.dataset.range, button)));
document.querySelectorAll("[data-quality-filter]").forEach((button) => button.addEventListener("click", () => setHistoryQuality(button.dataset.qualityFilter, button)));
document.querySelectorAll("[data-scope]").forEach((button) => button.addEventListener("click", () => setReportScope(button.dataset.scope, button)));
document.querySelectorAll("[data-format]").forEach((button) => button.addEventListener("click", () => setReportFormat(button.dataset.format, button)));

document.querySelectorAll("[data-history-range]").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll("[data-history-range]").forEach((item) => item.classList.toggle("is-active", item === button));
    const labels = { "5": "Últimos 5 minutos", "15": "Últimos 15 minutos", "30": "Últimos 30 minutos", "60": "Última hora", workday: "25/08/2026 · 06:00 hasta ahora", custom: "Periodo personalizado" };
    elements.historyPeriod.textContent = labels[button.dataset.historyRange];
  });
});

elements.demoState.addEventListener("change", () => applyDemoState(elements.demoState.value));
elements.chart.addEventListener("pointermove", handleChartPointer);
elements.chart.addEventListener("pointerleave", () => elements.chartTooltip.classList.add("is-hidden"));
document.querySelector("#custom-apply").addEventListener("click", () => {
  const from = elements.customFrom.value;
  const to = elements.customTo.value;
  if (!from || !to) {
    elements.customResult.textContent = "Complete ambas fechas.";
    return;
  }
  if (new Date(from) > new Date(to)) {
    elements.customResult.textContent = "Desde debe ser anterior a Hasta.";
    return;
  }
  elements.customResult.textContent = "";
  elements.selectedPeriod.textContent = `${from.replace("T", " ")} – ${to.replace("T", " ")}`;
  showToast("Periodo personalizado aplicado al gráfico y las lecturas.");
});
document.querySelector("#custom-clear").addEventListener("click", () => {
  elements.customFrom.value = "";
  elements.customTo.value = "";
  elements.customResult.textContent = "";
});
document.querySelector("#banner-action").addEventListener("click", () => showToast("En producción, este botón abrirá el historial relacionado."));
elements.simulateDownload.addEventListener("click", () => showToast(`Simulación: ${state.reportFormat.toUpperCase()} preparado para descargar.`));
document.querySelector("#quick-download").addEventListener("click", () => {
  const selected = document.querySelector('input[name="quick-format"]:checked').value.toUpperCase();
  showToast(`Simulación: ${selected} preparado para descargar.`);
});

window.addEventListener("resize", () => window.requestAnimationFrame(drawAllCharts));

updateClock();
window.setInterval(updateClock, 1000);
renderTables();
applyDemoState("normal");
setReportFormat("xlsx", document.querySelector('[data-format="xlsx"]'));
