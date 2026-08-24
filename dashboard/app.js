const elements = {
  siteName: document.querySelector("#site-name"),
  deviceName: document.querySelector("#device-name"),
  connection: document.querySelector("#connection"),
  connectionLabel: document.querySelector("#connection-label"),
  readingTime: document.querySelector("#reading-time"),
  readingDate: document.querySelector("#reading-date"),
  voltage: document.querySelector("#voltage"),
  current: document.querySelector("#current"),
  frequency: document.querySelector("#frequency"),
  statusValue: document.querySelector("#status-value"),
  statusDetail: document.querySelector("#status-detail"),
  recordsBody: document.querySelector("#records-body"),
  recordCount: document.querySelector("#record-count"),
  networkEndpoint: document.querySelector("#network-endpoint"),
  emptyChart: document.querySelector("#empty-chart"),
  canvas: document.querySelector("#history-chart"),
  xlsxExport: document.querySelector("#xlsx-export"),
  exportStatus: document.querySelector("#export-status"),
  samplingForm: document.querySelector("#sampling-form"),
  pollInterval: document.querySelector("#poll-interval"),
  samplingSave: document.querySelector("#sampling-save"),
  samplingResult: document.querySelector("#sampling-result"),
  dailyReadingEstimate: document.querySelector("#daily-reading-estimate")
};

let currentReadings = [];

function number(value, digits = 1) {
  return value === null || value === undefined || value === ""
    ? "--"
    : Number(value).toFixed(digits);
}

function isNumeric(value) {
  return value !== null && value !== undefined && value !== "" && Number.isFinite(Number(value));
}

function timestampParts(value) {
  if (!value) return { date: "No readings", time: "--", full: "--" };
  const timestamp = new Date(value);
  return {
    date: timestamp.toLocaleDateString(),
    time: timestamp.toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit"
    }),
    full: timestamp.toLocaleString()
  };
}

function displayState(state) {
  if (!state) return "Waiting";
  return state.charAt(0) + state.slice(1).toLowerCase();
}

function updateSamplingEstimate(seconds) {
  const interval = Number(seconds);
  const readingsPerDay = interval > 0 ? Math.round(86400 / interval) : 0;
  elements.dailyReadingEstimate.textContent = `${readingsPerDay.toLocaleString()} readings/day.`;
}

function renderReadings(readings) {
  elements.recordsBody.replaceChildren();
  if (!readings.length) {
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = 5;
    cell.className = "empty-row";
    cell.textContent = "Waiting for readings";
    row.appendChild(cell);
    elements.recordsBody.appendChild(row);
    return;
  }

  readings.slice(-15).reverse().forEach((reading) => {
    const row = document.createElement("tr");
    const values = [
      timestampParts(reading.timestamp).full,
      `${number(reading.voltage_v, 2)} V`,
      `${number(reading.current_ma, 1)} mA`,
      `${number(reading.frequency_hz, 1)} Hz`,
      reading.status === "OK" ? "Connected" : reading.status
    ];

    values.forEach((value, index) => {
      const cell = document.createElement("td");
      cell.textContent = value;
      if (index === 4) {
        cell.className = reading.status === "OK" ? "status-connected" : "status-disconnected";
      }
      row.appendChild(cell);
    });
    elements.recordsBody.appendChild(row);
  });
}

function renderStatus(data) {
  const state = data.connection_state || "WAITING";
  const stateLabel = displayState(state);
  const latest = data.latest;

  elements.siteName.textContent = data.site_name;
  elements.deviceName.textContent = data.device_name;
  elements.connection.dataset.state = state;
  elements.connectionLabel.textContent = stateLabel;
  elements.statusValue.textContent = stateLabel;
  elements.statusDetail.textContent = state === "CONNECTED"
    ? "Receiving live readings"
    : "No recent VFREG response";
  elements.recordCount.textContent = data.summary.count || 0;
  elements.networkEndpoint.textContent = data.network.mode === "modbus_tcp_client"
    ? `Modbus endpoint: ${data.network.tcp_host}:${data.network.tcp_port}`
    : `Listener port: ${data.network.tcp_port}`;
  const pollInterval = Number(data.network.poll_interval_seconds);
  if (Number.isFinite(pollInterval) && document.activeElement !== elements.pollInterval) {
    elements.pollInterval.value = String(pollInterval);
    updateSamplingEstimate(pollInterval);
  }

  if (latest) {
    const timestamp = timestampParts(latest.timestamp);
    elements.readingTime.textContent = timestamp.time;
    elements.readingDate.textContent = timestamp.date;
    elements.voltage.textContent = number(latest.voltage_v, 2);
    elements.current.textContent = number(latest.current_ma, 1);
    elements.frequency.textContent = number(latest.frequency_hz, 1);
  }

  currentReadings = data.readings || [];
  renderReadings(currentReadings);
  drawChart(currentReadings);
}

function drawChart(readings) {
  const chartReadings = readings.filter((row) =>
    isNumeric(row.voltage_v) && isNumeric(row.current_ma) && isNumeric(row.frequency_hz)
  );
  const canvas = elements.canvas;
  const bounds = canvas.getBoundingClientRect();
  const ratio = window.devicePixelRatio || 1;
  canvas.width = Math.max(1, Math.floor(bounds.width * ratio));
  canvas.height = Math.max(1, Math.floor(bounds.height * ratio));
  const context = canvas.getContext("2d");
  context.setTransform(ratio, 0, 0, ratio, 0, 0);
  context.clearRect(0, 0, bounds.width, bounds.height);
  elements.emptyChart.hidden = chartReadings.length > 1;
  if (chartReadings.length < 2) return;

  const padding = { left: 58, right: 18, top: 12, bottom: 24 };
  const plotWidth = bounds.width - padding.left - padding.right;
  const plotHeight = bounds.height - padding.top - padding.bottom;
  const lanes = [
    { key: "voltage_v", color: "#197f93", label: "V" },
    { key: "current_ma", color: "#6b5ca5", label: "mA" },
    { key: "frequency_hz", color: "#c98a22", label: "Hz" }
  ];
  const laneHeight = plotHeight / lanes.length;
  context.font = "11px Segoe UI, Arial";

  lanes.forEach((lane, laneIndex) => {
    const values = chartReadings.map((row) => Number(row[lane.key]));
    let minimum = Math.min(...values);
    let maximum = Math.max(...values);
    const spread = Math.max(maximum - minimum, Math.abs(maximum) * 0.015, 1);
    minimum = Math.max(0, minimum - spread * 0.2);
    maximum += spread * 0.2;
    const top = padding.top + laneIndex * laneHeight;
    const bottom = top + laneHeight;

    context.strokeStyle = "#dfe5e8";
    context.lineWidth = 1;
    context.beginPath();
    context.moveTo(padding.left, bottom);
    context.lineTo(bounds.width - padding.right, bottom);
    context.stroke();
    context.fillStyle = "#64717d";
    context.fillText(`${maximum.toFixed(0)} ${lane.label}`, 4, top + 12);
    context.fillText(minimum.toFixed(0), 18, bottom - 5);

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
}

async function refresh() {
  try {
    const response = await fetch("/api/status", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    renderStatus(await response.json());
  } catch (error) {
    elements.connection.dataset.state = "DISCONNECTED";
    elements.connectionLabel.textContent = "Disconnected";
    elements.statusValue.textContent = "Disconnected";
    elements.statusDetail.textContent = `Dashboard error: ${error.message}`;
  }
}

async function downloadXlsx(event) {
  event.preventDefault();
  if (elements.xlsxExport.dataset.busy === "true") return;
  elements.xlsxExport.dataset.busy = "true";
  elements.xlsxExport.setAttribute("aria-disabled", "true");
  elements.exportStatus.dataset.error = "false";
  elements.exportStatus.textContent = "Preparing Excel file...";
  try {
    const response = await fetch("/api/export.xlsx", { cache: "no-store" });
    if (!response.ok) {
      const result = await response.json().catch(() => ({}));
      throw new Error(result.error || `Excel export failed (HTTP ${response.status})`);
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
    elements.exportStatus.textContent = "Excel downloaded";
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
  elements.samplingResult.textContent = "Applying...";
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
    elements.samplingResult.textContent = "Saved and active";
  } catch (error) {
    elements.samplingResult.dataset.error = "true";
    elements.samplingResult.textContent = error.message;
  } finally {
    elements.samplingSave.disabled = false;
  }
}

refresh();
window.setInterval(refresh, 1000);
window.addEventListener("resize", () => drawChart(currentReadings));
elements.xlsxExport.addEventListener("click", downloadXlsx);
elements.pollInterval.addEventListener("change", () => updateSamplingEstimate(elements.pollInterval.value));
elements.samplingForm.addEventListener("submit", savePollingInterval);
