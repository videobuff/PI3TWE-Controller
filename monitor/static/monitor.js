/*
File: monitor/static/monitor.js
Generated: 2026-01-05
Description: Donkere Chart.js grafieken (CPU/INT/EXT) met 1 decimaal (temp + hum), auto-refresh en actuele waarden.
*/

Chart.defaults.color = "#e6e6e6";
Chart.defaults.borderColor = "#2a2f3a";

let cpuChart = null;
let intChart = null;
let extChart = null;
let refreshTimer = null;

/* ---------- helpers ---------- */

function timeLabel(ts) {
  return new Date(ts * 1000).toLocaleTimeString();
}

function labels(arr) {
  return arr.map(p => timeLabel(p.ts));
}

function series(arr, key) {
  return arr.map(p =>
    (p[key] === null || p[key] === undefined)
      ? null
      : Number(p[key].toFixed(1))
  );
}

function lastNonNull(arr, key) {
  for (let i = arr.length - 1; i >= 0; i--) {
    const v = arr[i]?.[key];
    if (v !== null && v !== undefined) return Number(v.toFixed(1));
  }
  return null;
}

function setStatus(text) {
  const el = document.getElementById("statusPill");
  if (el) el.textContent = text;
}

function setNow(id, temp, hum) {
  const el = document.getElementById(id);
  if (!el) return;

  const t = (temp === null) ? "—" : `${temp.toFixed(1)} °C`;
  if (hum === null || hum === undefined) {
    el.textContent = t;
  } else {
    el.textContent = `${t} • ${hum.toFixed(1)} %`;
  }
}

/* ---------- chart builders ---------- */

const commonScaleOptions = {
  ticks: {
    callback: (v) => Number(v).toFixed(1)
  }
};

const commonTooltipOptions = {
  callbacks: {
    label: (ctx) => {
      const v = ctx.parsed.y;
      return (v === null || v === undefined)
        ? "—"
        : `${Number(v).toFixed(1)}`;
    }
  }
};

function makeSingleDatasetChart(canvasId, label, labelsArr, valuesArr) {
  const ctx = document.getElementById(canvasId);

  return new Chart(ctx, {
    type: "line",
    data: {
      labels: labelsArr,
      datasets: [{
        label: label,
        data: valuesArr,
        tension: 0.25,
        borderWidth: 2,
        pointRadius: 0,
        borderColor: "#4da3ff",
        backgroundColor: "rgba(77,163,255,0.15)",
        fill: true
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: commonTooltipOptions
      },
      scales: {
        x: { ticks: { maxTicksLimit: 8 } },
        y: { ...commonScaleOptions, beginAtZero: false }
      }
    }
  });
}

function makeExtDualAxisChart(canvasId, labelsArr, tempArr, humArr) {
  const ctx = document.getElementById(canvasId);

  return new Chart(ctx, {
    type: "line",
    data: {
      labels: labelsArr,
      datasets: [
        {
          label: "EXT temp (°C)",
          data: tempArr,
          tension: 0.25,
          borderWidth: 2,
          pointRadius: 0,
          borderColor: "#4da3ff",
          backgroundColor: "rgba(77,163,255,0.12)",
          fill: true,
          yAxisID: "yTemp"
        },
        {
          label: "EXT hum (%)",
          data: humArr,
          tension: 0.25,
          borderWidth: 2,
          pointRadius: 0,
          borderColor: "#45d483",
          backgroundColor: "rgba(69,212,131,0.10)",
          fill: true,
          yAxisID: "yHum"
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        tooltip: commonTooltipOptions,
        legend: {
          display: true,
          labels: { boxWidth: 12, boxHeight: 12 }
        }
      },
      scales: {
        x: { ticks: { maxTicksLimit: 8 } },
        yTemp: {
          type: "linear",
          position: "left",
          beginAtZero: false,
          ...commonScaleOptions,
          title: { display: true, text: "°C" }
        },
        yHum: {
          type: "linear",
          position: "right",
          beginAtZero: true,
          suggestedMax: 100,
          ...commonScaleOptions,
          grid: { drawOnChartArea: false },
          title: { display: true, text: "%" }
        }
      }
    }
  });
}

/* ---------- data flow ---------- */

async function loadData() {
  const hours = document.getElementById("hours").value || 24;
  const r = await fetch(`/monitor/api/data?hours=${encodeURIComponent(hours)}`, { cache: "no-store" });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return await r.json();
}

async function reload() {
  try {
    setStatus("laden…");
    const data = await loadData();

    const cpuLast = lastNonNull(data.cpu, "temp");
    const intLast = lastNonNull(data.int, "temp");
    const extTempLast = lastNonNull(data.ext, "temp");
    const extHumLast = lastNonNull(data.ext, "hum");

    setNow("nowCpu", cpuLast, null);
    setNow("nowInt", intLast, null);
    setNow("nowExt", extTempLast, extHumLast);

    if (cpuChart) cpuChart.destroy();
    if (intChart) intChart.destroy();
    if (extChart) extChart.destroy();

    cpuChart = makeSingleDatasetChart(
      "cpuChart",
      "CPU temp (°C)",
      labels(data.cpu),
      series(data.cpu, "temp")
    );

    intChart = makeSingleDatasetChart(
      "intChart",
      "INT temp (°C)",
      labels(data.int),
      series(data.int, "temp")
    );

    extChart = makeExtDualAxisChart(
      "extChart",
      labels(data.ext),
      series(data.ext, "temp"),
      series(data.ext, "hum")
    );

    setStatus("ok");
  } catch (e) {
    setStatus(`fout: ${e?.message ?? e}`);
  }
}

function applyAutoRefresh() {
  const sel = document.getElementById("refresh");
  const sec = parseInt(sel.value, 10) || 0;

  if (refreshTimer) {
    clearInterval(refreshTimer);
    refreshTimer = null;
  }

  if (sec > 0) {
    refreshTimer = setInterval(reload, sec * 1000);
  }
}

document.getElementById("refresh").addEventListener("change", applyAutoRefresh);

/* init */
reload();
applyAutoRefresh();