<!--
  Bestandsnaam : /var/www/pi3twe/index.html
  Gegenereerd  : 2026-01-04 (Europe/Amsterdam)
  Beschrijving : PI3TWE Controller UI (Bootstrap 5, dark mode, responsive)
                 - Info / Repeater / Sensors + Log
                 - Login/Logout + 2FA setup/enable + Wachtwoord wijzigen
                 - Admin: users list/create/deactivate + SUPERADMIN: 2FA disable per user + Alarm settings
                 - NEW: Fail2ban bans in Info card (LAN/WAN + Bans)
                 - Small font tweak (subtle, no layout loss)

  API:
  - GET  /api/me
  - POST /api/login
  - POST /api/logout
  - GET  /api/2fa/setup
  - POST /api/2fa/enable
  - POST /api/user/password
  - GET  /api/state
  - POST /api/repeater/on
  - POST /api/repeater/off
  - GET  /api/log?limit=10 -> {"entries":[{ts_utc,ip,event,details},...]}
  - GET  /api/fail2ban -> {"total": number|null, "jails": {name:count}, "error"?:string}
  - GET  /api/admin/users
  - POST /api/admin/users
  - POST /api/admin/users/<id>/delete
  - POST /api/admin/users/<id>/2fa/disable   (superadmin only)
  - GET  /api/admin/alarm
  - POST /api/admin/alarm
-->

<!doctype html>
<html lang="nl" data-bs-theme="dark">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>PI3TWE CONTROLLER</title>

    <!-- Bootstrap 5 -->
    <link
      href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css"
      rel="stylesheet"
      integrity="sha384-QWTKZyjpPEjISv5WaRU9OFeRpok6YctnYmDr5pNlyT2bRjXh0JMhjY6hW+ALEwIH"
      crossorigin="anonymous" />

    <!-- Bootstrap Icons -->
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.min.css" />

    <style>
      :root {
        --card-radius: 1rem;
      }

      body {
        background: radial-gradient(1000px 500px at 50% -10%, rgba(255, 255, 255, 0.06), transparent 60%),
          radial-gradient(900px 500px at 80% 20%, rgba(0, 123, 255, 0.1), transparent 55%),
          radial-gradient(900px 600px at 10% 35%, rgba(0, 255, 128, 0.08), transparent 55%), #0b0f16;
        min-height: 100vh;
      }

      .app-wrap {
        max-width: 980px;
      }
      .title {
        letter-spacing: 0.08em;
        font-weight: 800;
        text-transform: uppercase;
      }

      .card {
        border-radius: var(--card-radius);
        border: 1px solid rgba(255, 255, 255, 0.1);
        box-shadow: 0 12px 30px rgba(0, 0, 0, 0.25);
        backdrop-filter: blur(6px);
      }

      .mono {
        font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
      }

      .muted {
        opacity: 0.7;
      }

      /* Slight global compactness (subtle) */
      .kv-row, .logline, .muted, .mono { font-size: 0.97rem; }
      .small { font-size: 0.82rem !important; }

      /* Status badge */
      @keyframes pulseGreen {
        0% { box-shadow: 0 0 0 0 rgba(25, 135, 84, 0.65); transform: translateZ(0); }
        70% { box-shadow: 0 0 0 18px rgba(25, 135, 84, 0); }
        100% { box-shadow: 0 0 0 0 rgba(25, 135, 84, 0); }
      }
      .pulse {
        animation: pulseGreen 1.4s infinite;
      }

      .badge-onair {
        background: rgba(25, 135, 84, 0.22);
        color: #9ff2c7;
        border: 1px solid rgba(25, 135, 84, 0.45);
        padding: 0.55rem 0.9rem;
        border-radius: 999px;
        font-weight: 800;
        letter-spacing: 0.06em;
        display: inline-flex;
        align-items: center;
        gap: 0.55rem;
      }
      .badge-off {
        background: rgba(220, 53, 69, 0.15);
        color: #ffb3bb;
        border: 1px solid rgba(220, 53, 69, 0.35);
      }
      .dot {
        width: 12px;
        height: 12px;
        border-radius: 999px;
        background: #20c997;
        box-shadow: 0 0 14px rgba(32, 201, 151, 0.9);
      }
      .dot-off {
        background: #ff6b6b;
        box-shadow: 0 0 14px rgba(255, 107, 107, 0.8);
      }

      /* 3D Button CSS */
      .btn3d {
        position: relative;
        top: -6px;
        border: 0;
        transition: all 40ms linear;
        margin: 10px 2px;
      }
      .btn3d:active:focus,
      .btn3d:focus:hover,
      .btn3d:focus {
        -moz-outline-style: none;
        outline: medium none;
      }
      .btn3d:active,
      .btn3d.active {
        top: 2px;
      }

      .btn3d.btn-success {
        box-shadow:
          0 0 0 1px #31c300 inset,
          0 0 0 2px rgba(255, 255, 255, 0.15) inset,
          0 8px 0 0 #5eb924,
          0 8px 8px 1px rgba(0, 0, 0, 0.5);
        background-color: #78d739;
      }
      .btn3d.btn-success:active,
      .btn3d.btn-success.active {
        box-shadow:
          0 0 0 1px #30cd00 inset,
          0 0 0 1px rgba(255, 255, 255, 0.15) inset,
          0 1px 3px 1px rgba(0, 0, 0, 0.3);
        background-color: #78d739;
      }
      .btn3d.btn-danger {
        box-shadow:
          0 0 0 1px #b93802 inset,
          0 0 0 2px rgba(255, 255, 255, 0.15) inset,
          0 8px 0 0 #aa0000,
          0 8px 8px 1px rgba(0, 0, 0, 0.5);
        background-color: #d73814;
      }
      .btn3d.btn-danger:active,
      .btn3d.btn-danger.active {
        box-shadow:
          0 0 0 1px #b93802 inset,
          0 0 0 1px rgba(255, 255, 255, 0.15) inset,
          0 1px 3px 1px rgba(0, 0, 0, 0.3);
        background-color: #d73814;
      }

      /* Key-value compact row */
      .kv-row {
        display: flex;
        align-items: baseline;
        justify-content: space-between;
        gap: 0.75rem;
      }
      .kv-row .k {
        opacity: 0.75;
        font-weight: 600;
        white-space: nowrap;
      }
      .kv-row .v {
        font-weight: 800;
      }
      .kv-row .v.mono {
        font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
      }

      /* Log */
      .logbox {
        max-height: 260px;
        overflow: auto;
      }

      .logline {
        font-size: 0.80rem;     /* slightly smaller */
        line-height: 1.15;
        padding: 0.18rem 0;
        border-bottom: 1px solid rgba(255, 255, 255, 0.06);
        white-space: pre-wrap;
        word-break: break-word;
      }

      /* Fail2ban "small frown" line */
      .f2b-warn {
        margin-top: .35rem;
        font-size: .78rem;
        opacity: .85;
      }

      /* Mobile compact */
      @media (max-width: 575.98px) {
        .card { padding: 0.85rem !important; }
        .logline { font-size: 0.80rem; padding: 0.25rem 0; line-height: 1.15; }
        .logline { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
        .top-actions .btn { padding: 0.25rem 0.45rem; }
      }

      .top-actions {
        display: flex;
        gap: 0.4rem;
        justify-content: flex-end;
        flex-wrap: wrap;
      }
      .toast-wrap {
        position: fixed;
        right: 12px;
        bottom: 12px;
        z-index: 1080;
      }

      .pill {
        border: 1px solid rgba(255, 255, 255, 0.12);
        border-radius: 999px;
        padding: 0.15rem 0.55rem;
        font-weight: 700;
      }
    </style>
  </head>

  <body>
    <div class="container py-4 app-wrap">
      <div class="d-flex justify-content-between align-items-start mb-2">
        <div class="text-start">
          <div class="title h3 mb-1">PI3TWE CONTROLLER</div>
          <div class="muted">Repeater monitoring &amp; control</div>
        </div>

        <div class="text-end">
          <div id="whoami" class="small muted mb-1">Niet ingelogd</div>
          <div class="top-actions">
            <button id="btnLoginOpen" class="btn btn-outline-light btn-sm">
              <i class="bi bi-box-arrow-in-right me-1"></i>Login
            </button>
            <button id="btnLogout" class="btn btn-outline-light btn-sm" style="display: none">
              <i class="bi bi-box-arrow-right me-1"></i>Logout
            </button>
            <button id="btn2faOpen" class="btn btn-outline-light btn-sm" style="display: none">
              <i class="bi bi-shield-lock me-1"></i>2FA
            </button>
            <button id="btnPwOpen" class="btn btn-outline-light btn-sm" style="display: none">
              <i class="bi bi-key me-1"></i>Wachtwoord
            </button>
            <button id="btnAdminOpen" class="btn btn-outline-light btn-sm" style="display: none">
              <i class="bi bi-gear me-1"></i>Admin
            </button>
          </div>
        </div>
      </div>

      <div class="row g-3">
        <!-- Card: Info -->
        <div class="col-12 col-lg-4">
          <div class="card p-3 h-100">
            <div class="d-flex align-items-center justify-content-between mb-2">
              <div class="fw-bold">Info</div>
              <i class="bi bi-clock-history muted"></i>
            </div>

            <div class="kv-row">
              <div class="k">Datum</div>
              <div id="dateVal" class="v mono">--</div>
            </div>

            <div class="kv-row mt-1">
              <div class="k">Tijd</div>
              <div id="timeVal" class="v mono">--:--</div>
            </div>

            <div class="kv-row mt-1">
              <div class="k">LAN</div>
              <div id="lanAddr" class="v mono">--</div>
            </div>

            <div class="kv-row mt-1">
              <div class="k">WAN</div>
              <div id="wanAddr" class="v mono">--</div>
            </div>

            <hr class="my-2 opacity-25" />

            <div class="kv-row mt-1">
              <div class="k">Bans</div>
              <div class="v mono"><span id="banTotal">--</span></div>
            </div>
            <div class="small muted mono mt-1" id="banDetail" style="display:none"></div>
            <div class="f2b-warn text-warning" id="banWarn" style="display:none">
              <i class="bi bi-emoji-frown me-1"></i><span id="banWarnText">fail2ban onbekend</span>
            </div>
          </div>
        </div>

        <!-- Card: Repeater status + control -->
        <div class="col-12 col-lg-4">
          <div class="card p-3 h-100">
            <div class="d-flex align-items-center justify-content-between mb-2">
              <div class="fw-bold">Repeater status</div>
              <i class="bi bi-broadcast-pin muted"></i>
            </div>

            <div class="mb-3 text-center">
              <div id="statusBadge" class="badge-onair badge-off mx-auto">
                <span id="statusDot" class="dot dot-off"></span>
                <span id="statusText">OFF</span>
              </div>
            </div>

            <div class="text-center">
              <button id="toggleBtn" type="button" class="btn btn-success btn-lg btn3d w-100">
                <i class="bi bi-power me-2"></i>
                <span id="btnLabel">PI3TWE AAN</span>
              </button>
              <div id="cooldownHint" class="small muted mt-2" style="display: none"></div>
            </div>
          </div>
        </div>

        <!-- Card: Sensors -->
        <div class="col-12 col-lg-4">
          <div class="card p-3 h-100">
            <div class="d-flex align-items-center justify-content-between mb-2">
              <div class="fw-bold">Sensors</div>
              <i class="bi bi-thermometer-half muted"></i>
            </div>

            <!-- Internal -->
            <div class="kv-row">
              <div class="k">INT TEMP</div>
              <div class="v mono">
                <span id="intTemp">--.-</span> <span class="muted">°C</span>
              </div>
            </div>
            <div class="kv-row mt-1">
              <div class="k">INT HUM</div>
              <div class="v mono">
                <span id="intHum">--</span> <span class="muted">%</span>
              </div>
            </div>

            <hr class="my-2 opacity-25" />

            <!-- External -->
            <div class="kv-row">
              <div class="k">EXT TEMP</div>
              <div class="v mono">
                <span id="extTemp">--.-</span> <span class="muted">°C</span>
              </div>
            </div>
            <div class="kv-row mt-1">
              <div class="k">EXT HUM</div>
              <div class="v mono">
                <span id="extHum">--</span> <span class="muted">%</span>
              </div>
            </div>

            <hr class="my-2 opacity-25" />

            <!-- CPU -->
            <div class="kv-row">
              <div class="k">CPU TEMP</div>
              <div class="v mono">
                <span id="cpuTemp">--.-</span> <span class="muted">°C</span>
              </div>
            </div>

            <div class="small muted mt-2 mono" id="sensorErr" style="display: none"></div>
          </div>
        </div>

        <!-- Log -->
        <div class="col-12">
          <div class="card p-3">
            <div class="d-flex align-items-center justify-content-between mb-2">
              <div class="fw-bold">Log (laatste 10)</div>
              <div class="small muted mono" id="logMeta">/api/log?limit=10</div>
            </div>
            <div class="logbox" id="logBox">
              <div class="logline muted">Geen data.</div>
            </div>
          </div>
        </div>
      </div>

      <div class="text-center small muted mt-3">
        <span class="mono" id="footerHost">--</span>
      </div>
    </div>

    <!-- LOGIN MODAL -->
    <div class="modal fade" id="loginModal" tabindex="-1" aria-hidden="true">
      <div class="modal-dialog modal-dialog-centered">
        <div class="modal-content">
          <div class="modal-header">
            <h5 class="modal-title">Login</h5>
            <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
          </div>
          <div class="modal-body">
            <div class="mb-2">
              <label class="form-label small muted mb-1">Username of email</label>
              <input id="loginIdent" class="form-control" autocomplete="username" />
            </div>
            <div class="mb-2">
              <label class="form-label small muted mb-1">Wachtwoord</label>
              <input id="loginPw" type="password" class="form-control" autocomplete="current-password" />
            </div>
            <div class="mb-2">
              <label class="form-label small muted mb-1">OTP (alleen als 2FA aan staat)</label>
              <input id="loginOtp" class="form-control" inputmode="numeric" autocomplete="one-time-code" />
            </div>
            <div id="loginMsg" class="small muted"></div>
          </div>
          <div class="modal-footer">
            <button id="btnDoLogin" class="btn btn-outline-light">Login</button>
          </div>
        </div>
      </div>
    </div>

    <!-- 2FA MODAL -->
    <div class="modal fade" id="twofaModal" tabindex="-1" aria-hidden="true">
      <div class="modal-dialog modal-dialog-centered">
        <div class="modal-content">
          <div class="modal-header">
            <h5 class="modal-title">2FA (TOTP)</h5>
            <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
          </div>
          <div class="modal-body">
            <div class="small muted mb-2">Scan de QR met Authenticator en voer daarna de code in.</div>

            <div class="d-grid mb-2">
              <button id="btn2faSetup" class="btn btn-outline-light">2FA Setup</button>
            </div>

            <div id="twofaBox" style="display: none">
              <div class="text-center">
                <img
                  id="twofaQr"
                  alt="QR"
                  src="data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw=="
                  style="max-width: 220px; border-radius: 12px" />
                <div class="mt-2 small muted mono" id="twofaSecret"></div>
              </div>
              <div class="mt-2">
                <label class="form-label small muted mb-1">Code</label>
                <input id="twofaCode" class="form-control" inputmode="numeric" autocomplete="one-time-code" />
              </div>
              <div class="d-grid mt-2">
                <button id="btn2faEnable" class="btn btn-outline-light">2FA Activeren</button>
              </div>
            </div>

            <div id="twofaMsg" class="small muted mt-2"></div>
          </div>
        </div>
      </div>
    </div>

    <!-- PASSWORD MODAL -->
    <div class="modal fade" id="pwModal" tabindex="-1" aria-hidden="true">
      <div class="modal-dialog modal-dialog-centered">
        <div class="modal-content">
          <div class="modal-header">
            <h5 class="modal-title">Wachtwoord wijzigen</h5>
            <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
          </div>
          <div class="modal-body">
            <div class="mb-2">
              <label class="form-label small muted mb-1">Oud wachtwoord</label>
              <input id="pwOld" type="password" class="form-control" autocomplete="current-password" />
            </div>
            <div class="mb-2">
              <label class="form-label small muted mb-1">Nieuw wachtwoord</label>
              <input id="pwNew" type="password" class="form-control" autocomplete="new-password" />
            </div>
            <div class="d-grid">
              <button id="btnPwChange" class="btn btn-outline-light">Opslaan</button>
            </div>
            <div id="pwMsg" class="small muted mt-2"></div>
          </div>
        </div>
      </div>
    </div>

    <!-- ADMIN MODAL -->
    <div class="modal fade" id="adminModal" tabindex="-1" aria-hidden="true">
      <div class="modal-dialog modal-xl modal-dialog-scrollable modal-dialog-centered">
        <div class="modal-content">
          <div class="modal-header">
            <h5 class="modal-title">Admin</h5>
            <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
          </div>

          <div class="modal-body">
            <div class="row g-3">
              <!-- USERS -->
              <div class="col-12 col-lg-7">
                <div class="card p-3">
                  <div class="d-flex justify-content-between align-items-center mb-2">
                    <div class="fw-bold">Gebruikers</div>
                    <button id="btnNewUserOpen" class="btn btn-outline-light btn-sm">
                      <i class="bi bi-person-plus me-1"></i>Nieuwe gebruiker
                    </button>
                  </div>
                  <div class="small muted mb-2">
                    <span class="pill mono me-2">Delete = deactiveren</span>
                    <span class="pill mono">2FA disable = superadmin</span>
                  </div>
                  <div id="usersMsg" class="small muted mb-2"></div>
                  <div id="usersBox" class="table-responsive"></div>
                </div>
              </div>

              <!-- ALARM -->
              <div class="col-12 col-lg-5">
                <div class="card p-3">
                  <div class="fw-bold mb-2">Alarm instellingen</div>
                  <div class="form-check form-switch mb-2">
                    <input class="form-check-input" type="checkbox" id="alarmEnabled" />
                    <label class="form-check-label" for="alarmEnabled">Alarm actief</label>
                  </div>
                  <div class="row g-2">
                    <div class="col-6">
                      <label class="form-label small muted mb-1">Trip (°C)</label>
                      <input class="form-control" type="number" step="0.1" id="alarmTrip" />
                    </div>
                    <div class="col-6">
                      <label class="form-label small muted mb-1">Clear (°C)</label>
                      <input class="form-control" type="number" step="0.1" id="alarmClear" />
                    </div>
                  </div>
                  <div class="d-grid mt-2">
                    <button id="btnSaveAlarm" class="btn btn-outline-light">
                      <i class="bi bi-save2 me-1"></i>Opslaan
                    </button>
                  </div>
                  <div id="alarmMsg" class="small muted mt-2"></div>
                </div>
              </div>
            </div>
          </div>

          <div class="modal-footer">
            <div class="small muted me-auto">Delete-knop en 2FA disable zijn alleen zichtbaar voor superadmin.</div>
            <button type="button" class="btn btn-outline-light" data-bs-dismiss="modal">Sluiten</button>
          </div>
        </div>
      </div>
    </div>

    <!-- NEW USER MODAL -->
    <div class="modal fade" id="newUserModal" tabindex="-1" aria-hidden="true">
      <div class="modal-dialog modal-dialog-centered">
        <div class="modal-content">
          <div class="modal-header">
            <h5 class="modal-title">Nieuwe gebruiker</h5>
            <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
          </div>
          <div class="modal-body">
            <div class="mb-2">
              <label class="form-label small muted mb-1">Username</label>
              <input id="nuUsername" class="form-control" />
            </div>
            <div class="mb-2">
              <label class="form-label small muted mb-1">Email</label>
              <input id="nuEmail" class="form-control" />
            </div>
            <div class="form-check form-switch mb-2">
              <input class="form-check-input" type="checkbox" id="nuIsAdmin" checked />
              <label class="form-check-label" for="nuIsAdmin">Admin</label>
            </div>
            <div class="form-check form-switch mb-2">
              <input class="form-check-input" type="checkbox" id="nuNotify" checked />
              <label class="form-check-label" for="nuNotify">Alarm mail ontvangen</label>
            </div>
            <div id="nuMsg" class="small muted"></div>
          </div>
          <div class="modal-footer">
            <button id="btnCreateUser" class="btn btn-outline-light">Aanmaken</button>
          </div>
        </div>
      </div>
    </div>

    <!-- Bootstrap bundle -->
    <script
      src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"
      integrity="sha384-YvpcrYf0tY3lHB60NNkmXc5s9fDVZLESaAA55NDzOxhy9GkcIdslK1eN7N6jIeHz"
      crossorigin="anonymous"></script>

    <script>
      // -------------------- Helpers --------------------
      function escapeHtml(s) {
        return String(s)
          .replaceAll("&", "&amp;")
          .replaceAll("<", "&lt;")
          .replaceAll(">", "&gt;")
          .replaceAll('"', "&quot;")
          .replaceAll("'", "&#039;");
      }

      async function fetchJson(url, opts = {}) {
        const r = await fetch(url, { cache: "no-store", ...opts });
        const ct = (r.headers.get("content-type") || "").toLowerCase();

        if (!r.ok) {
          if (ct.includes("application/json")) {
            const j = await r.json().catch(() => null);
            const msg = j?.error?.message || `HTTP ${r.status}`;
            throw new Error(msg);
          }
          const t = await r.text().catch(() => "");
          throw new Error(t ? `HTTP ${r.status}` : `HTTP ${r.status}`);
        }

        if (ct.includes("application/json")) return await r.json();
        return { ok: true, text: await r.text().catch(() => "") };
      }

      function applyTimeString(ts) {
        // "YYYY-MM-DD HH:MM:SS"
        if (!ts || typeof ts !== "string") {
          elDate.textContent = "--";
          elTime.textContent = "--:--";
          return;
        }
        const parts = ts.trim().split(" ");
        const d = parts[0] || "";
        const t = parts[1] || "";

        if (/^\d{4}-\d{2}-\d{2}$/.test(d)) {
          const [yy, mm, dd] = d.split("-");
          elDate.textContent = `${dd}-${mm}-${yy}`;
        } else {
          elDate.textContent = d || "--";
        }

        if (/^\d{2}:\d{2}:\d{2}$/.test(t)) elTime.textContent = t.substring(0, 5);
        else if (/^\d{2}:\d{2}$/.test(t)) elTime.textContent = t;
        else elTime.textContent = "--:--";
      }

      function toHHMM(ts_utc) {
        if (!ts_utc || typeof ts_utc !== "string") return "--:--";
        const s = ts_utc.replace(" UTC", "").trim();
        const m = s.match(/\b(\d{2}):(\d{2}):\d{2}\b/);
        if (m) return `${m[1]}:${m[2]}`;
        const m2 = s.match(/\b(\d{2}):(\d{2})\b/);
        if (m2) return `${m2[1]}:${m2[2]}`;
        return "--:--";
      }

      function setNum(el, v, digits = 1, fallback = "--") {
        if (typeof v === "number" && isFinite(v)) el.textContent = v.toFixed(digits);
        else el.textContent = fallback;
      }

      // -------------------- API constants --------------------
      const API_STATE = "/api/state";
      const API_ON = "/api/repeater/on";
      const API_OFF = "/api/repeater/off";
      const API_LOG = "/api/log?limit=10";
      const API_FAIL2BAN = "/api/fail2ban";

      const API_ME = "/api/me";
      const API_LOGIN = "/api/login";
      const API_LOGOUT = "/api/logout";

      const API_2FA_SETUP = "/api/2fa/setup";
      const API_2FA_ENABLE = "/api/2fa/enable";
      const API_PW_CHANGE = "/api/user/password";

      const API_ADMIN_USERS = "/api/admin/users";
      const API_ADMIN_ALARM = "/api/admin/alarm";

      const POLL_STATE_MS = 1200;
      const POLL_LOG_MS = 3000;
      const POLL_F2B_MS = 5000;

      // -------------------- DOM refs --------------------
      const elDate = document.getElementById("dateVal");
      const elTime = document.getElementById("timeVal");
      const elLan  = document.getElementById("lanAddr");
      const elWan  = document.getElementById("wanAddr");

      const elBanTotal = document.getElementById("banTotal");
      const elBanDetail = document.getElementById("banDetail");
      const elBanWarn = document.getElementById("banWarn");
      const elBanWarnText = document.getElementById("banWarnText");

      const elStatusBadge = document.getElementById("statusBadge");
      const elStatusText = document.getElementById("statusText");
      const elStatusDot = document.getElementById("statusDot");

      const elBtn = document.getElementById("toggleBtn");
      const elBtnLabel = document.getElementById("btnLabel");
      const elCooldownHint = document.getElementById("cooldownHint");

      // Sensors
      const elIntTemp = document.getElementById("intTemp");
      const elIntHum  = document.getElementById("intHum");
      const elExtTemp = document.getElementById("extTemp");
      const elExtHum  = document.getElementById("extHum");
      const elCpuTemp = document.getElementById("cpuTemp");
      const elSensorErr = document.getElementById("sensorErr");

      const elLogBox = document.getElementById("logBox");
      const elFooterHost = document.getElementById("footerHost");

      const elWho = document.getElementById("whoami");
      const btnLoginOpen = document.getElementById("btnLoginOpen");
      const btnLogout = document.getElementById("btnLogout");
      const btn2faOpen = document.getElementById("btn2faOpen");
      const btnPwOpen = document.getElementById("btnPwOpen");
      const btnAdminOpen = document.getElementById("btnAdminOpen");

      // Admin modal elements
      const usersBox = document.getElementById("usersBox");
      const usersMsg = document.getElementById("usersMsg");
      const btnNewUserOpen = document.getElementById("btnNewUserOpen");
      const alarmEnabled = document.getElementById("alarmEnabled");
      const alarmTrip = document.getElementById("alarmTrip");
      const alarmClear = document.getElementById("alarmClear");
      const btnSaveAlarm = document.getElementById("btnSaveAlarm");
      const alarmMsg = document.getElementById("alarmMsg");

      // New user modal elements
      const nuUsername = document.getElementById("nuUsername");
      const nuEmail = document.getElementById("nuEmail");
      const nuIsAdmin = document.getElementById("nuIsAdmin");
      const nuNotify = document.getElementById("nuNotify");
      const btnCreateUser = document.getElementById("btnCreateUser");
      const nuMsg = document.getElementById("nuMsg");

      // Login modal
      const loginModal = new bootstrap.Modal(document.getElementById("loginModal"));
      const loginIdent = document.getElementById("loginIdent");
      const loginPw = document.getElementById("loginPw");
      const loginOtp = document.getElementById("loginOtp");
      const btnDoLogin = document.getElementById("btnDoLogin");
      const loginMsg = document.getElementById("loginMsg");

      // 2FA modal
      const twofaModal = new bootstrap.Modal(document.getElementById("twofaModal"));
      const btn2faSetup = document.getElementById("btn2faSetup");
      const twofaBox = document.getElementById("twofaBox");
      const twofaQr = document.getElementById("twofaQr");
      const twofaSecret = document.getElementById("twofaSecret");
      const twofaCode = document.getElementById("twofaCode");
      const btn2faEnable = document.getElementById("btn2faEnable");
      const twofaMsg = document.getElementById("twofaMsg");

      // PW modal
      const pwModal = new bootstrap.Modal(document.getElementById("pwModal"));
      const pwOld = document.getElementById("pwOld");
      const pwNew = document.getElementById("pwNew");
      const btnPwChange = document.getElementById("btnPwChange");
      const pwMsg = document.getElementById("pwMsg");

      // Admin modal
      const adminModal = new bootstrap.Modal(document.getElementById("adminModal"));
      const newUserModal = new bootstrap.Modal(document.getElementById("newUserModal"));

      // -------------------- State --------------------
      let lastState = null;
      let busy = false;
      let me = { logged_in: false };

      // Local countdown
      let cdRemaining = 0;
      let cdTick = null;

      function setRepeaterUI(isOn) {
        if (isOn) {
          elStatusText.textContent = "ON AIR";
          elStatusBadge.classList.remove("badge-off");
          elStatusDot.classList.remove("dot-off");
          elStatusBadge.classList.add("pulse");

          elBtn.classList.remove("btn-success");
          elBtn.classList.add("btn-danger");
          elBtnLabel.textContent = "PI3TWE UIT";
        } else {
          elStatusText.textContent = "OFF";
          elStatusBadge.classList.add("badge-off");
          elStatusDot.classList.add("dot-off");
          elStatusBadge.classList.remove("pulse");

          elBtn.classList.remove("btn-danger");
          elBtn.classList.add("btn-success");
          elBtnLabel.textContent = "PI3TWE AAN";
        }

        if (cdRemaining > 0) elBtnLabel.textContent += ` (${cdRemaining}s)`;
      }

      function stopCountdown() {
        cdRemaining = 0;
        if (cdTick) {
          clearInterval(cdTick);
          cdTick = null;
        }
      }

      function startCountdown(seconds) {
        const s = typeof seconds === "number" && isFinite(seconds) ? Math.floor(seconds) : 0;
        if (s <= 0) {
          stopCountdown();
          elCooldownHint.style.display = "none";
          elCooldownHint.textContent = "";
          return;
        }

        cdRemaining = s;
        elCooldownHint.style.display = "block";
        elCooldownHint.textContent = `Wacht ${cdRemaining}s...`;
        elBtn.disabled = true;

        if (cdTick) return;
        cdTick = setInterval(() => {
          if (cdRemaining > 0) cdRemaining -= 1;

          if (cdRemaining <= 0) {
            stopCountdown();
            elCooldownHint.style.display = "none";
            elCooldownHint.textContent = "";
          } else {
            elCooldownHint.textContent = `Wacht ${cdRemaining}s...`;
          }

          if (lastState) setRepeaterUI(!!lastState.repeater);
        }, 1000);
      }

      function applyCooldownFromState(sec) {
        const s = typeof sec === "number" && isFinite(sec) && sec > 0 ? Math.floor(sec) : 0;
        if (s > cdRemaining) startCountdown(s);
        if (s === 0 && !busy) stopCountdown();
        elBtn.disabled = busy || cdRemaining > 0;
        if (cdRemaining <= 0) {
          elCooldownHint.style.display = "none";
          elCooldownHint.textContent = "";
        }
      }

      // -------------------- Auth/UI --------------------
      async function refreshMe() {
        me = await fetchJson(API_ME).catch(() => ({ logged_in: false }));
        if (!me.logged_in) {
          elWho.textContent = "Niet ingelogd";
          btnLoginOpen.style.display = "";
          btnLogout.style.display = "none";
          btn2faOpen.style.display = "none";
          btnPwOpen.style.display = "none";
          btnAdminOpen.style.display = "none";
          return;
        }

        elWho.innerHTML =
          `<span class="text-success">Ingelogd</span><br>` +
          `<span class="mono">${escapeHtml(me.username)} &lt;${escapeHtml(me.email)}&gt;</span>`;

        btnLoginOpen.style.display = "none";
        btnLogout.style.display = "";
        btn2faOpen.style.display = "";
        btnPwOpen.style.display = "";
        btnAdminOpen.style.display = me.is_admin ? "" : "none";
      }

      // -------------------- Fail2ban --------------------
      function setFail2banUI(total, jails, errMsg) {
        if (typeof total === "number" && isFinite(total)) elBanTotal.textContent = String(total);
        else elBanTotal.textContent = "--";

        if (jails && typeof jails === "object") {
          const parts = Object.entries(jails).map(([k,v]) => `${k}:${v}`);
          elBanDetail.textContent = parts.join("  ");
          elBanDetail.style.display = parts.length ? "" : "none";
        } else {
          elBanDetail.style.display = "none";
          elBanDetail.textContent = "";
        }

        if (errMsg) {
          elBanWarn.style.display = "";
          elBanWarnText.textContent = errMsg;
        } else {
          elBanWarn.style.display = "none";
          elBanWarnText.textContent = "";
        }
      }

      async function pollFail2ban() {
        try {
          const d = await fetchJson(API_FAIL2BAN);
          const total = (typeof d.total === "number" && isFinite(d.total)) ? d.total : null;
          const jails = (d.jails && typeof d.jails === "object") ? d.jails : null;
          const err = (typeof d.error === "string" && d.error.trim()) ? d.error.trim() : "";
          setFail2banUI(total, jails, err || "");
        } catch (e) {
          setFail2banUI(null, null, e.message || "fail2ban niet beschikbaar");
        }
      }

      // -------------------- Polling --------------------
      async function pollState() {
        try {
          const st = await fetchJson(API_STATE);
          lastState = st;

          setRepeaterUI(!!st.repeater);
          applyTimeString(st.time);

          // LAN/WAN from backend (preferred). Fallback to old fields if needed.
          const lan = (typeof st.ip_lan === "string" && st.ip_lan.trim()) ? st.ip_lan.trim() : "--";
          const wan = (typeof st.ip_wan === "string" && st.ip_wan.trim()) ? st.ip_wan.trim()
                    : (typeof st.ip_external === "string" && st.ip_external.trim()) ? st.ip_external.trim()
                    : "--";

          elLan.textContent = lan;
          elWan.textContent = wan;

          // Sensors
          setNum(elIntTemp, st.temp_int_c, 1, "--.-");
          setNum(elIntHum, st.hum_int_pct, 0, "--");

          setNum(elExtTemp, st.temp_ext_c, 1, "--.-");
          setNum(elExtHum, st.hum_ext_pct, 0, "--");

          setNum(elCpuTemp, st.cpu_temp_c, 1, "--.-");

          if (st.sensor_err) {
            elSensorErr.style.display = "";
            elSensorErr.textContent = `sensor_err: ${st.sensor_err}`;
          } else {
            elSensorErr.style.display = "none";
            elSensorErr.textContent = "";
          }

          applyCooldownFromState(st.cooldown);
          elFooterHost.textContent = location.host;
        } catch (e) {
          elStatusText.textContent = "NO DATA";
          elStatusBadge.classList.remove("pulse");
        }
      }

      async function pollLog() {
        if (!me.logged_in) {
          elLogBox.innerHTML = `<div class="logline muted">Login vereist.</div>`;
          return;
        }
        try {
          const data = await fetchJson(API_LOG);
          const entries = data && Array.isArray(data.entries) ? data.entries : [];

          if (!entries.length) {
            elLogBox.innerHTML = `<div class="logline muted">Geen logregels.</div>`;
            return;
          }

          const view = entries.slice(0, 10);

          elLogBox.innerHTML = view
            .map((e) => {
              const hhmm = toHHMM(e.ts_utc);
              const ip = e.ip || "-";
              const ev = e.event || "-";
              const detail = e.details ? ` (${e.details})` : "";
              const line = `${hhmm} | ${ip} | ${ev}${detail}`;
              return `<div class="logline mono">${escapeHtml(line)}</div>`;
            })
            .join("");
        } catch (e) {
          elLogBox.innerHTML = `<div class="logline muted">${escapeHtml(e.message)}</div>`;
        }
      }

      // -------------------- Admin --------------------
      async function loadUsers() {
        usersMsg.textContent = "";
        usersBox.innerHTML = "";
        try {
          const data = await fetchJson(API_ADMIN_USERS);
          const users = data.users || [];

          if (!users.length) {
            usersBox.innerHTML = `<div class="small muted">Geen gebruikers.</div>`;
            return;
          }

          const canDelete = !!me.is_superadmin;
          const canDisable2fa = !!me.is_superadmin;

          usersBox.innerHTML = `
            <table class="table table-sm table-dark align-middle mb-0">
              <thead>
                <tr>
                  <th>ID</th>
                  <th>Username</th>
                  <th>Email</th>
                  <th>Admin</th>
                  <th>Super</th>
                  <th>Actief</th>
                  <th>Notify</th>
                  <th>2FA</th>
                  <th class="text-end">Actie</th>
                </tr>
              </thead>
              <tbody>
                ${users
                  .map((u) => {
                    const badge2fa = u.totp_enabled
                      ? `<span class="badge text-bg-success">aan</span>`
                      : `<span class="badge text-bg-secondary">uit</span>`;

                    const btnDel =
                      canDelete && !u.is_superadmin && u.is_active
                        ? `<button class="btn btn-outline-danger btn-sm" data-del="${u.id}">
                             <i class="bi bi-trash me-1"></i>Delete
                           </button>`
                        : `<span class="muted">-</span>`;

                    const btn2fa =
                      canDisable2fa && u.is_active && u.totp_enabled && !u.is_superadmin
                        ? `<button class="btn btn-outline-warning btn-sm ms-1" data-2fadis="${u.id}" data-user="${escapeHtml(u.username)}">
                             <i class="bi bi-shield-x me-1"></i>2FA uit
                           </button>`
                        : `<span class="muted ms-1">-</span>`;

                    const btn2faSuper =
                      canDisable2fa && u.is_active && u.totp_enabled && u.is_superadmin
                        ? `<span class="muted ms-1">super</span>`
                        : "";

                    return `
                      <tr>
                        <td class="mono">${u.id}</td>
                        <td>${escapeHtml(u.username)}</td>
                        <td class="mono">${escapeHtml(u.email)}</td>
                        <td>${u.is_admin ? "ja" : "nee"}</td>
                        <td>${u.is_superadmin ? "ja" : "nee"}</td>
                        <td>${u.is_active ? "ja" : "nee"}</td>
                        <td>${u.notify_enabled ? "ja" : "nee"}</td>
                        <td>${badge2fa}</td>
                        <td class="text-end">
                          ${btnDel}
                          ${btn2fa}
                          ${btn2faSuper}
                        </td>
                      </tr>
                    `;
                  })
                  .join("")}
              </tbody>
            </table>
          `;

          usersBox.querySelectorAll("[data-del]").forEach((btn) => {
            btn.addEventListener("click", async () => {
              const id = btn.getAttribute("data-del");
              if (!confirm(`Gebruiker ${id} deactiveren?`)) return;
              try {
                await fetchJson(`/api/admin/users/${id}/delete`, { method: "POST" });
                await loadUsers();
                await pollLog();
              } catch (e) {
                usersMsg.textContent = e.message;
              }
            });
          });

          usersBox.querySelectorAll("[data-2fadis]").forEach((btn) => {
            btn.addEventListener("click", async () => {
              const id = btn.getAttribute("data-2fadis");
              const uname = btn.getAttribute("data-user") || id;

              const ok = confirm(
                `Je staat op het punt 2FA uit te schakelen voor:\n${uname} (id=${id})\n\n` +
                `Dit zet totp_enabled op 0 en wist totp_secret.`
              );
              if (!ok) return;

              try {
                await fetchJson(`/api/admin/users/${id}/2fa/disable`, { method: "POST" });
                await loadUsers();
                await pollLog();
              } catch (e) {
                usersMsg.textContent = e.message;
              }
            });
          });

        } catch (e) {
          usersMsg.textContent = e.message;
        }
      }

      async function loadAlarm() {
        alarmMsg.textContent = "";
        try {
          const a = await fetchJson(API_ADMIN_ALARM);
          alarmEnabled.checked = !!a.enabled;
          alarmTrip.value = a.trip_c;
          alarmClear.value = a.clear_c;
        } catch (e) {
          alarmMsg.textContent = e.message;
        }
      }

      // -------------------- Events --------------------
      btnLoginOpen.addEventListener("click", () => {
        loginMsg.textContent = "";
        loginIdent.value = "";
        loginPw.value = "";
        loginOtp.value = "";
        loginModal.show();
      });

      btnDoLogin.addEventListener("click", async () => {
        loginMsg.textContent = "Inloggen...";
        try {
          await fetchJson(API_LOGIN, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              ident: loginIdent.value.trim(),
              password: loginPw.value,
              otp: loginOtp.value.trim() || undefined
            })
          });

          loginModal.hide();
          await refreshMe();
          await pollState();
          await pollLog();
        } catch (e) {
          loginMsg.textContent = e.message;
        }
      });

      btnLogout.addEventListener("click", async () => {
        try { await fetchJson(API_LOGOUT, { method: "POST" }); } catch {}
        await refreshMe();
        await pollLog();
      });

      btn2faOpen.addEventListener("click", () => {
        twofaMsg.textContent = "";
        twofaBox.style.display = "none";
        twofaCode.value = "";
        twofaSecret.textContent = "";
        twofaModal.show();
      });

      btn2faSetup.addEventListener("click", async () => {
        twofaMsg.textContent = "Ophalen...";
        try {
          const d = await fetchJson(API_2FA_SETUP);
          twofaBox.style.display = "";
          twofaQr.src = d.qr;
          twofaSecret.textContent = d.secret;
          twofaMsg.textContent = "Scan de QR en voer de code in.";
        } catch (e) {
          twofaMsg.textContent = e.message;
        }
      });

      btn2faEnable.addEventListener("click", async () => {
        twofaMsg.textContent = "Activeren...";
        try {
          await fetchJson(API_2FA_ENABLE, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ code: twofaCode.value.trim() })
          });
          twofaMsg.textContent = "2FA geactiveerd.";
          await refreshMe();
        } catch (e) {
          twofaMsg.textContent = e.message;
        }
      });

      btnPwOpen.addEventListener("click", () => {
        pwMsg.textContent = "";
        pwOld.value = "";
        pwNew.value = "";
        pwModal.show();
      });

      btnPwChange.addEventListener("click", async () => {
        pwMsg.textContent = "Opslaan...";
        try {
          await fetchJson(API_PW_CHANGE, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ old_password: pwOld.value, new_password: pwNew.value })
          });
          pwMsg.textContent = "Wachtwoord gewijzigd.";
          pwOld.value = "";
          pwNew.value = "";
        } catch (e) {
          pwMsg.textContent = e.message;
        }
      });

      btnAdminOpen.addEventListener("click", async () => {
        usersMsg.textContent = "";
        alarmMsg.textContent = "";
        adminModal.show();
        await loadUsers();
        await loadAlarm();
      });

      btnSaveAlarm.addEventListener("click", async () => {
        alarmMsg.textContent = "Opslaan...";
        try {
          await fetchJson(API_ADMIN_ALARM, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              enabled: alarmEnabled.checked,
              trip_c: parseFloat(alarmTrip.value),
              clear_c: parseFloat(alarmClear.value)
            })
          });
          alarmMsg.textContent = "Opgeslagen.";
        } catch (e) {
          alarmMsg.textContent = e.message;
        }
      });

      btnNewUserOpen.addEventListener("click", () => {
        nuMsg.textContent = "";
        nuUsername.value = "";
        nuEmail.value = "";
        nuIsAdmin.checked = true;
        nuNotify.checked = true;
        newUserModal.show();
      });

      btnCreateUser.addEventListener("click", async () => {
        nuMsg.textContent = "Aanmaken...";
        try {
          await fetchJson(API_ADMIN_USERS, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              username: nuUsername.value.trim(),
              email: nuEmail.value.trim(),
              is_admin: nuIsAdmin.checked,
              notify_enabled: nuNotify.checked
            })
          });
          nuMsg.textContent = "Gebruiker aangemaakt (mail verstuurd).";
          newUserModal.hide();
          await loadUsers();
          await pollLog();
        } catch (e) {
          nuMsg.textContent = e.message;
        }
      });

      elBtn.addEventListener("click", async (ev) => {
        ev.preventDefault();
        if (!me.logged_in) {
          loginModal.show();
          return;
        }
        if (busy || elBtn.disabled) return;

        const wantOn = elBtn.classList.contains("btn-success");

        try {
          busy = true;
          elBtn.disabled = true;
          elCooldownHint.style.display = "block";
          elCooldownHint.textContent = "Schakelen...";

          await fetchJson(wantOn ? API_ON : API_OFF, { method: "POST" });

          await pollState();
          await pollLog();

          if (lastState && typeof lastState.cooldown === "number" && lastState.cooldown > 0) {
            startCountdown(Math.floor(lastState.cooldown));
          }
        } catch (e) {
          elCooldownHint.textContent = e.message;
        } finally {
          busy = false;
          if (lastState) applyCooldownFromState(lastState.cooldown);
        }
      });

      // -------------------- Init --------------------
      (async () => {
        elFooterHost.textContent = location.host;

        await refreshMe();
        await pollState();
        await pollLog();
        await pollFail2ban();

        setInterval(pollState, POLL_STATE_MS);
        setInterval(pollLog, POLL_LOG_MS);
        setInterval(pollFail2ban, POLL_F2B_MS);
      })();
    </script>
  </body>
</html>