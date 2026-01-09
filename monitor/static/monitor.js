/*
File: monitor/static/monitor.js
Generated: 2026-01-06 15:56 (Europe/Amsterdam)
Description:
- Donkere Chart.js grafieken (CPU/INT/EXT) met 1 decimaal (temp + hum)
- Auto-start bij openen pagina (geen handmatig verversen nodig)
- Auto-refresh (default 10s) + pauze bij inactieve tab (visibilitychange)
- Update-in-place (geen destroy/rebuild) zodat grafiek niet “van onder” opbouwt
- Rolling gemiddelde lijn (60s) per grafiek (trend)
*/

Chart.defaults.color = "#e6e6e6";
Chart.defaults.borderColor = "#2a2f3a";

let cpuChart = null;
let intChart = null;
let extChart = null;

let refreshTimer = null;
let refreshIntervalSec = 10; // default
let tabIsVisible = true;

/* ---------- helpers ---------- */

function timeLabel(ts) {
  return new Date(ts * 1000).toLocaleTimeString();
}

function labels(arr) {
  return (arr || []).map((p) => timeLabel(p.ts));
}

function series(arr, key) {
  return (arr || []).map((p) =>
    (p[key] === null || p[key] === undefined) ? null : Number(p[key].toFixed(1))
  );
}

function tsArr(arr) {
  return (arr || []).map((p) => p?.ts ?? null);
}

function lastNonNull(arr, key) {
  for (let i = (arr?.length || 0) - 1; i >= 0; i--) {
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

  const t = (temp === null || temp === undefined) ? "—" : `${temp.toFixed(1)} °C`;
  if (hum === null || hum === undefined) {
    el.textContent = t;
  } else {
    el.textContent = `${t} • ${hum.toFixed(1)} %`;
  }
}

/**
 * Rolling average over windowSec, gebaseerd op timestamps.
 * - timestampsSec: array met unix ts (sec)
 * - valuesArr: array met numbers/null (zelfde lengte)
 * Retourneert array met rolling gemiddelden (numbers/null) met 1 decimaal.
 */
function rollingAverage(timestampsSec, valuesArr, windowSec) {
  const n = Math.min(timestampsSec?.length || 0, valuesArr?.length || 0);
  const out = new Array(n).fill(null);
  if (!n) return out;

  for (let i = 0; i < n; i++) {
    const ti = timestampsSec[i];
    if (!Number.isFinite(ti)) {
      out[i] = null;
      continue;
    }

    const from = ti - windowSec;
    let sum = 0;
    let cnt = 0;

    // scan terug zolang ts binnen window; n is klein genoeg (max ~ paar duizend)
    for (let j = i; j >= 0; j--) {
      const tj = timestampsSec[j];
      if (!Number.isFinite(tj)) continue;
      if (tj < from) break;

      const v = valuesArr[j];
      if (v !== null && v !== undefined && Number.isFinite(v)) {
        sum += v;
        cnt += 1;
      }
    }

    out[i] = cnt ? Number((sum / cnt).toFixed(1)) : null;
  }

  return out;
}

/* ---------- chart builders ---------- */

const commonScaleOptions = {
  ticks: { callback: (v) => Number(v).toFixed(1) }
};

const commonTooltipOptions = {
  callbacks: {
    label: (ctx) => {
      const v = ctx.parsed.y;
      return (v === null || v === undefined) ? "—" : `${Number(v).toFixed(1)}`;
    }
  }
};

function makeSingleDatasetChart(canvasId, label, labelsArr, valuesArr, avgArr) {
  const ctx = document.getElementById(canvasId);

  return new Chart(ctx, {
    type: "line",
    data: {
      labels: labelsArr,
      datasets: [
        {
          label: label,
          data: valuesArr,
          tension: 0.25,
          borderWidth: 2,
          pointRadius: 0,
          borderColor: "#4da3ff",
          backgroundColor: "rgba(77,163,255,0.15)",
          fill: true
        },
        {
          label: "Gemiddelde (60s)",
          data: avgArr,
          borderColor: "#ff9f43",
          borderWidth: 1,
          borderDash: [6, 6],
          pointRadius: 0,
          fill: false
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
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

function makeExtDualAxisChart(canvasId, labelsArr, tempArr, tempAvgArr, humArr, humAvgArr) {
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
          label: "EXT temp avg (60s)",
          data: tempAvgArr,
          borderColor: "#ff9f43",
          borderWidth: 1,
          borderDash: [6, 6],
          pointRadius: 0,
          fill: false,
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
        },
        {
          label: "EXT hum avg (60s)",
          data: humAvgArr,
          borderColor: "#ffd166",
          borderWidth: 1,
          borderDash: [6, 6],
          pointRadius: 0,
          fill: false,
          yAxisID: "yHum"
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
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
  const hoursEl = document.getElementById("hours");
  const hours = hoursEl ? (hoursEl.value || 24) : 24;

  const r = await fetch(`/monitor/api/data?hours=${encodeURIComponent(hours)}`, { cache: "no-store" });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return await r.json();
}

async function reload() {
  try {
    setStatus("laden…");
    const data = await loadData();

    // actuele waardes
    const cpuLast = lastNonNull(data.cpu, "temp");
    const intLast = lastNonNull(data.int, "temp");
    const extTempLast = lastNonNull(data.ext, "temp");
    const extHumLast = lastNonNull(data.ext, "hum");

    setNow("nowCpu", cpuLast, null);
    setNow("nowInt", intLast, null);
    setNow("nowExt", extTempLast, extHumLast);

    // series + timestamps
    const cpuLbl = labels(data.cpu);
    const cpuTemp = series(data.cpu, "temp");
    const cpuTs = tsArr(data.cpu);
    const cpuAvg60 = rollingAverage(cpuTs, cpuTemp, 60);

    const intLbl = labels(data.int);
    const intTemp = series(data.int, "temp");
    const intTs = tsArr(data.int);
    const intAvg60 = rollingAverage(intTs, intTemp, 60);

    const extLbl = labels(data.ext);
    const extTemp = series(data.ext, "temp");
    const extHum = series(data.ext, "hum");
    const extTs = tsArr(data.ext);
    const extTempAvg60 = rollingAverage(extTs, extTemp, 60);
    const extHumAvg60 = rollingAverage(extTs, extHum, 60);

    // charts: create once, then update in-place
    if (!cpuChart) {
      cpuChart = makeSingleDatasetChart("cpuChart", "CPU temp (°C)", cpuLbl, cpuTemp, cpuAvg60);
    } else {
      cpuChart.data.labels = cpuLbl;
      cpuChart.data.datasets[0].data = cpuTemp;
      cpuChart.data.datasets[1].data = cpuAvg60;
      cpuChart.update("none");
    }

    if (!intChart) {
      intChart = makeSingleDatasetChart("intChart", "INT temp (°C)", intLbl, intTemp, intAvg60);
    } else {
      intChart.data.labels = intLbl;
      intChart.data.datasets[0].data = intTemp;
      intChart.data.datasets[1].data = intAvg60;
      intChart.update("none");
    }

    if (!extChart) {
      extChart = makeExtDualAxisChart("extChart", extLbl, extTemp, extTempAvg60, extHum, extHumAvg60);
    } else {
      extChart.data.labels = extLbl;
      extChart.data.datasets[0].data = extTemp;
      extChart.data.datasets[1].data = extTempAvg60;
      extChart.data.datasets[2].data = extHum;
      extChart.data.datasets[3].data = extHumAvg60;
      extChart.update("none");
    }

    setStatus("ok");
  } catch (e) {
    setStatus(`fout: ${e?.message ?? e}`);
  }
}

/* ---------- auto refresh + pause on inactive tab ---------- */

function safeReload() {
  try {
    const p = reload();
    if (p && typeof p.catch === "function") p.catch(() => {});
  } catch (_) {
    /* bewust leeg */
  }
}

function stopRefreshTimer() {
  if (refreshTimer) {
    clearInterval(refreshTimer);
    refreshTimer = null;
  }
}

function startRefreshTimer() {
  if (refreshTimer || refreshIntervalSec <= 0 || !tabIsVisible) return;
  refreshTimer = setInterval(safeReload, refreshIntervalSec * 1000);
}

function applyAutoRefresh() {
  // Volg dropdown als die bestaat; anders default 10s
  const sel = document.getElementById("refresh");
  if (sel) {
    const v = parseInt(sel.value, 10);
    refreshIntervalSec = Number.isFinite(v) ? v : 10;
    if (!sel.value) sel.value = String(refreshIntervalSec);
  } else {
    refreshIntervalSec = 10;
  }

  stopRefreshTimer();
  startRefreshTimer();
}

document.addEventListener("visibilitychange", () => {
  tabIsVisible = !document.hidden;

  if (!tabIsVisible) {
    stopRefreshTimer();
  } else {
    // bij terugkomen: 1x refresh + timer weer aan
    safeReload();
    startRefreshTimer();
  }
});

/* ---------- init ---------- */

document.addEventListener("DOMContentLoaded", () => {
  // direct laden bij openen pagina
  safeReload();

  // autorefresh configureren
  applyAutoRefresh();

  // hooks
  const refreshSel = document.getElementById("refresh");
  if (refreshSel) refreshSel.addEventListener("change", applyAutoRefresh);

  const hoursSel = document.getElementById("hours");
  if (hoursSel) hoursSel.addEventListener("change", safeReload);
});