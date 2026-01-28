#!/usr/bin/env python3
# =============================================================================
# File        : /srv/pi3twe/app/tft/tft_app_fb.py
# Generated   : 2026-01-27 (Europe/Amsterdam)
# Description :
#   PI3TWE TFT UI – framebuffer only (RGB565), NO touch actions.
#
#   Reads backend:
#     GET  {PI3TWE_BACKEND}/api/state
#
#   Screen (active draw):
#   - Clock top-right with seconds
#   - WAN line centered: "<IFACE> | WAN IP: <ip>" where IFACE = WLAN0/ETH0/HAMNET/DEV
#   - Repeater status centered (AAN=BRIGHT RED block, UIT=blue block)
#   - Measurements under the status block:
#       INT/EXT/CPU (+ COOLDOWN if >0 else UPTIME)
#     CPU line shows CPU LOAD % after CPU TEMP.
#   - Countdown before standby: last row shows "TFT SCREEN IN STAND BY (5..1)"
#
#   Power / load management:
#   - Uses backend field last_user_action_age_s (if present) to decide draw_active.
#   - After INACTIVITY_OFF_S without user action:
#       * Stop drawing (skip fb.blit) so the last frame remains visible
#       * Slow down polling
#   - When activity resumes: draw becomes active again.
#
#   Logging:
#   - Logs to /var/log/pi3twe/tft.log (or PI3TWE_TFT_LOG)
# =============================================================================

from __future__ import annotations

import os
import time
import json
import mmap
import fcntl
import struct
import signal
import urllib.request
import subprocess
from datetime import datetime
from typing import Optional, Any, Tuple

from PIL import Image, ImageDraw, ImageFont  # type: ignore

try:
    import numpy as np
    _NUMPY_OK = True
except ImportError:
    np = None
    _NUMPY_OK = False


# ------------------------------ Config --------------------------------------

FB = os.environ.get("PI3TWE_FB", "/dev/fb1")
BACKEND_BASE = os.environ.get("PI3TWE_BACKEND", "http://127.0.0.1:3000")

W = 480
H = 320

# Active draw/poll interval
REFRESH_S_ACTIVE = float(os.environ.get("PI3TWE_TFT_REFRESH", "1.0"))
# Idle poll interval (much slower)
REFRESH_S_IDLE = float(os.environ.get("PI3TWE_TFT_REFRESH_IDLE", "5.0"))

HTTP_TIMEOUT_S = float(os.environ.get("PI3TWE_TFT_HTTP_TIMEOUT", "2.0"))

LOGFILE = os.environ.get("PI3TWE_TFT_LOG", "/var/log/pi3twe/tft.log")

# Inactivity timeout (seconds) – after this we stop drawing
INACTIVITY_OFF_S = float(os.environ.get("PI3TWE_TFT_IDLE_OFF_S", "300"))

# Layout
PAD = 16
HEADER_Y = 10

# Colors
WHITE = (255, 255, 255)
BLACK = (0, 0, 0)

# Repeater blocks
RED_ON = (255, 0, 0)         # BRIGHT RED
BLUE_OFF = (0, 80, 180)

# Measurement colors
GREEN_OK = (0, 220, 0)
ORANGE_WARN = (255, 140, 0)
RED_BAD = (255, 0, 0)        # BRIGHT RED for >80C

# Fonts
FONT_REG = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


# ------------------------------ Logging -------------------------------------

def _ensure_logdir() -> None:
    d = os.path.dirname(LOGFILE) or "."
    try:
        os.makedirs(d, exist_ok=True)
    except Exception:
        pass


def log(msg: str) -> None:
    _ensure_logdir()
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with open(LOGFILE, "a", encoding="utf-8") as f:
            f.write(f"{ts} {msg}\n")
    except Exception:
        # Do not crash on logging errors
        pass


# ------------------------------ Helpers -------------------------------------

def pick_font(path: str, size: int) -> ImageFont.ImageFont:
    try:
        return ImageFont.truetype(path, size=size)
    except Exception:
        return ImageFont.load_default()


def http_get_json(url: str, timeout: float) -> Optional[dict]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "pi3twe-tft/2.6"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", errors="replace"))
    except Exception as e:
        log(f"HTTP ERROR {url}: {type(e).__name__}: {e}")
        return None


def as_float(v: Any) -> Optional[float]:
    try:
        if v is None:
            return None
        return float(v)
    except Exception:
        return None


def fmt_1(v: Optional[float], suffix: str = "") -> str:
    if v is None:
        return "--.-" + suffix
    try:
        return f"{float(v):.1f}{suffix}"
    except Exception:
        return "--.-" + suffix


def color_for_temp_c(v: Optional[float]) -> Tuple[int, int, int]:
    if v is None:
        return WHITE
    if v <= 70.0:
        return GREEN_OK
    if v <= 80.0:
        return ORANGE_WARN
    return RED_BAD


def color_for_hum_pct(v: Optional[float]) -> Tuple[int, int, int]:
    if v is None:
        return WHITE
    if v < 60.0:
        return GREEN_OK
    if v <= 80.0:
        return ORANGE_WARN
    return RED_BAD


def read_uptime_seconds() -> Optional[int]:
    try:
        with open("/proc/uptime", "r", encoding="utf-8") as f:
            txt = f.read().strip().split()
        if not txt:
            return None
        return int(float(txt[0]))
    except Exception:
        return None


def format_uptime(secs: Optional[int]) -> str:
    if secs is None or secs < 0:
        return "—"
    days = secs // 86400
    rem = secs % 86400
    h = rem // 3600
    rem %= 3600
    m = rem // 60
    s = rem % 60
    if days > 0:
        return f"{days}d {h:02d}:{m:02d}:{s:02d}"
    return f"{h:02d}:{m:02d}:{s:02d}"


def placeholder_state() -> dict:
    return {
        "ip_external": "—",
        "wan_iface": "—",
        "repeater": False,
        "cooldown": 0,
        "temp_int_c": None,
        "hum_int_pct": None,
        "temp_ext_c": None,
        "hum_ext_pct": None,
        "cpu_temp_c": None,
        "cpu_load_pct": None,
        "last_user_action_ts": None,
        "last_user_action_age_s": None,
        "uptime_text": "—",
    }


def parse_api_state(payload: dict) -> dict:
    out = placeholder_state()
    try:
        out["repeater"] = bool(payload.get("repeater", False))
        out["cooldown"] = int(payload.get("cooldown", 0) or 0)

        wan = (payload.get("wan_ip") or "").strip()
        out["ip_external"] = wan if wan else "—"

        # activity fields from backend (if present)
        out["last_user_action_ts"] = payload.get("last_user_action_ts")
        out["last_user_action_age_s"] = payload.get("last_user_action_age_s")

        mon = payload.get("monitor") or {}
        it = mon.get("int") if isinstance(mon, dict) else None
        ex = mon.get("ext") if isinstance(mon, dict) else None
        cpu = mon.get("cpu") if isinstance(mon, dict) else None

        if isinstance(it, dict):
            out["temp_int_c"] = as_float(it.get("temp"))
            out["hum_int_pct"] = as_float(it.get("hum"))

        if isinstance(ex, dict):
            out["temp_ext_c"] = as_float(ex.get("temp"))
            out["hum_ext_pct"] = as_float(ex.get("hum"))

        if isinstance(cpu, dict):
            out["cpu_temp_c"] = as_float(cpu.get("temp"))
            out["cpu_load_pct"] = as_float(cpu.get("load"))
    except Exception as e:
        log(f"PARSE ERROR: {type(e).__name__}: {e}")
    return out


def _run_cmd(cmd: list[str], timeout_s: float = 1.0) -> str:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s)
        return (p.stdout or "").strip()
    except Exception:
        return ""


def detect_wan_iface_label(wan_ip: str, cached_dev: str) -> str:
    """
    Determine WAN label:
    - If WAN IP starts with 44. -> HAMNET
    - Else use default route dev -> wlan0/eth0/...
    """
    if isinstance(wan_ip, str) and wan_ip.startswith("44."):
        return "HAMNET"

    dev = cached_dev.strip()
    if not dev:
        return "WAN"

    d = dev.lower()
    if d.startswith("wlan"):
        return d.upper()  # WLAN0
    if d.startswith("eth"):
        return d.upper()   # ETH0
    # fallback: show dev as-is upper (e.g., usb0)
    return dev.upper()


def read_default_route_dev() -> str:
    """
    Cheap(ish) call, so we will cache it and only refresh occasionally.
    """
    out = _run_cmd(["/sbin/ip", "route", "show", "default"])
    # typical: "default via 192.168.2.1 dev wlan0 proto dhcp src ..."
    for token_i, tok in enumerate(out.split()):
        if tok == "dev" and token_i + 1 < len(out.split()):
            return out.split()[token_i + 1]
    return ""


# ------------------------------ CPU load % (proc/stat) ----------------------

_prev_cpu: Optional[Tuple[int, int]] = None  # (total, idle)

def read_cpu_load_pct() -> Optional[int]:
    """
    Returns integer cpu utilization percent based on /proc/stat delta.
    Very light; call ~1x/sec when active.
    """
    global _prev_cpu
    try:
        with open("/proc/stat", "r", encoding="utf-8") as f:
            line = f.readline()
        if not line.startswith("cpu "):
            return None
        parts = line.split()
        vals = [int(x) for x in parts[1:8]]  # user nice system idle iowait irq softirq
        user, nice, system, idle, iowait, irq, softirq = vals
        idle_all = idle + iowait
        non_idle = user + nice + system + irq + softirq
        total = idle_all + non_idle

        if _prev_cpu is None:
            _prev_cpu = (total, idle_all)
            return None

        prev_total, prev_idle = _prev_cpu
        dt = total - prev_total
        di = idle_all - prev_idle
        _prev_cpu = (total, idle_all)

        if dt <= 0:
            return None
        usage = (dt - di) / dt
        pct = int(round(usage * 100.0))
        if pct < 0:
            pct = 0
        if pct > 100:
            pct = 100
        return pct
    except Exception:
        return None


# ------------------------------ Framebuffer ---------------------------------

FBIOGET_VSCREENINFO = 0x4600
FBIOGET_FSCREENINFO = 0x4602


class Framebuffer:
    def __init__(self, path: str):
        self.path = path
        self.fd = os.open(self.path, os.O_RDWR)

        vbuf = bytearray(256)
        fbuf = bytearray(256)
        v = fcntl.ioctl(self.fd, FBIOGET_VSCREENINFO, vbuf, True)
        f = fcntl.ioctl(self.fd, FBIOGET_FSCREENINFO, fbuf, True)

        if not isinstance(v, (bytes, bytearray)):
            v = vbuf
        if not isinstance(f, (bytes, bytearray)):
            f = fbuf

        self.w, self.h = struct.unpack_from("II", v, 0)
        self.bpp = struct.unpack_from("I", v, 24)[0]
        self.size = struct.unpack_from("I", f, 24)[0]
        self.line = struct.unpack_from("I", f, 44)[0]

        if int(self.bpp) != 16:
            raise RuntimeError(f"Framebuffer bpp={self.bpp} not supported (expected 16)")

        if int(self.size) <= 0:
            self.size = int(self.w) * int(self.h) * 2

        self.mm = mmap.mmap(self.fd, int(self.size), mmap.MAP_SHARED, mmap.PROT_WRITE | mmap.PROT_READ)
        log(f"FB open path={self.path} xres={self.w} yres={self.h} bpp={self.bpp} line={self.line} size={self.size}")

    def close(self) -> None:
        try:
            self.mm.close()
        except Exception:
            pass
        try:
            os.close(self.fd)
        except Exception:
            pass

    def blit(self, rgb565: bytes) -> None:
        self.mm.seek(0)
        self.mm.write(rgb565)


def image_to_rgb565(im: Image.Image) -> bytes:
    """
    Convert PIL Image to RGB565 bytes for framebuffer.
    Uses numpy if available (10x+ faster), falls back to pure Python.
    """
    if _NUMPY_OK:
        # Fast numpy conversion
        arr = np.array(im.convert("RGB"), dtype=np.uint16)
        r = (arr[:, :, 0] & 0xF8) << 8
        g = (arr[:, :, 1] & 0xFC) << 3
        b = arr[:, :, 2] >> 3
        rgb565 = (r | g | b).astype(np.uint16)
        return rgb565.tobytes()
    else:
        # Fallback: pure Python (slow)
        raw = im.convert("RGB").tobytes()
        out = bytearray((len(raw) // 3) * 2)
        j = 0
        for i in range(0, len(raw), 3):
            r, g, b = raw[i], raw[i + 1], raw[i + 2]
            v = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
            out[j] = v & 0xFF
            out[j + 1] = (v >> 8) & 0xFF
            j += 2
        return bytes(out)


# ------------------------------ UI ------------------------------------------

def build_screen(state: dict, standby_countdown: Optional[int]) -> Image.Image:
    im = Image.new("RGB", (W, H), BLACK)
    d = ImageDraw.Draw(im)

    font_h = pick_font(FONT_BOLD, 30)
    font_r = pick_font(FONT_BOLD, 36)
    font_wan = pick_font(FONT_REG, 24)
    font_meas = pick_font(FONT_BOLD, 24)
    font_uptime = pick_font(FONT_BOLD, 23)

    # Title
    d.text((PAD, HEADER_Y), "PI3TWE STATUS", font=font_h, fill=WHITE)

    # Clock
    clk = datetime.now().strftime("%H:%M:%S")
    tw = d.textlength(clk, font=font_h)
    d.text((W - PAD - int(tw), HEADER_Y), clk, font=font_h, fill=WHITE)

    # WAN line with iface label
    wan = (state or {}).get("ip_external") or "—"
    iface = (state or {}).get("wan_iface") or "WAN"
    wan_line = f"{iface} | WAN IP: {wan}"
    wtw = d.textlength(wan_line, font=font_wan)
    d.text(((W - int(wtw)) // 2, HEADER_Y + 44), wan_line, font=font_wan, fill=WHITE)

    # Repeater block
    rep = bool((state or {}).get("repeater", False))
    rep_txt = "REPEATER = AAN" if rep else "REPEATER = UIT"
    rep_col = RED_ON if rep else BLUE_OFF

    block_w = int(W * 0.92)
    block_h = 78
    rx = (W - block_w) // 2
    ry = HEADER_Y + 78

    d.rounded_rectangle([rx, ry, rx + block_w, ry + block_h], radius=18, fill=rep_col)

    bb = d.textbbox((0, 0), rep_txt, font=font_r)
    txt_w = bb[2] - bb[0]
    txt_h = bb[3] - bb[1]
    tx = rx + (block_w - txt_w) // 2
    ty = ry + (block_h - txt_h) // 2 - 4
    d.text((tx, ty), rep_txt, font=font_r, fill=WHITE)

    cooldown = int((state or {}).get("cooldown", 0) or 0)

    t_int = as_float((state or {}).get("temp_int_c"))
    h_int = as_float((state or {}).get("hum_int_pct"))
    t_ext = as_float((state or {}).get("temp_ext_c"))
    h_ext = as_float((state or {}).get("hum_ext_pct"))
    t_cpu = as_float((state or {}).get("cpu_temp_c"))

    cpu_pct = (state or {}).get("cpu_load_pct")
    cpu_pct_txt = ""
    if cpu_pct is not None:
        try:
            pct_val = int(round(float(cpu_pct)))
            if 0 <= pct_val <= 100:
                cpu_pct_txt = f"   {pct_val}%"
        except (ValueError, TypeError):
            pass

    rows = [
        ("INT TEMP", fmt_1(t_int, " C"), fmt_1(h_int, " %"), color_for_temp_c(t_int), color_for_hum_pct(h_int)),
        ("EXT TEMP", fmt_1(t_ext, " C"), fmt_1(h_ext, " %"), color_for_temp_c(t_ext), color_for_hum_pct(h_ext)),
        ("CPU RPI", fmt_1(t_cpu, " C") + cpu_pct_txt, None, color_for_temp_c(t_cpu), WHITE),
    ]

    # Bottom row: cooldown OR uptime, but if standby_countdown is active (5..1) override text
    if standby_countdown is not None and 1 <= standby_countdown <= 5:
        rows.append(("TFT", f"SCREEN IN STAND BY ({standby_countdown})", None, WHITE, WHITE))
    else:
        if cooldown > 0:
            rows.append(("COOLDOWN", f"{cooldown} s", None, WHITE, WHITE))
        else:
            uptime_text = (state or {}).get("uptime_text") or "—"
            rows.append(("UPTIME", uptime_text, None, WHITE, WHITE))

    line_h = 32
    y = ry + block_h + 14

    def draw_centered_segments(ypos: int, segments: list[tuple[str, Tuple[int, int, int]]], font: ImageFont.ImageFont) -> None:
        total_w = 0.0
        for text, _col in segments:
            total_w += d.textlength(text, font=font)
        x = (W - int(total_w)) // 2
        for text, col in segments:
            d.text((x, ypos), text, font=font, fill=col)
            x += int(d.textlength(text, font=font))

    for label, v1, v2, col_v1, col_v2 in rows:
        use_font = font_uptime if (label == "UPTIME") else font_meas

        if v2 is None:
            segments = [(f"{label}: ", WHITE), (v1, col_v1)]
        else:
            segments = [(f"{label}: ", WHITE), (v1, col_v1), ("   ", WHITE), (v2, col_v2)]

        draw_centered_segments(y, segments, use_font)
        y += line_h

    return im


# ------------------------------ Main ----------------------------------------

RUN = True


def _sig(_a, _b) -> None:
    global RUN
    RUN = False


signal.signal(signal.SIGINT, _sig)
signal.signal(signal.SIGTERM, _sig)


def should_draw_be_active(state: dict) -> bool:
    """
    Decide draw_active based on backend last_user_action_age_s.
    - If backend provides age: active when age <= INACTIVITY_OFF_S
    - If no age provided: keep active (avoid accidental never-draw)
    """
    age = (state or {}).get("last_user_action_age_s")
    try:
        if age is None:
            return True
        return float(age) <= float(INACTIVITY_OFF_S)
    except Exception:
        return True


def standby_countdown_value(state: dict) -> Optional[int]:
    """
    If age is within last 5 seconds before idle cutoff, return countdown 5..1.
    """
    age = (state or {}).get("last_user_action_age_s")
    try:
        if age is None:
            return None
        remaining = float(INACTIVITY_OFF_S) - float(age)
        if 0 < remaining <= 5.0:
            return int(round(remaining))
        return None
    except Exception:
        return None


def main() -> int:
    fb = Framebuffer(FB)

    state: dict = placeholder_state()
    last_fetch = 0.0
    last_ok = 0.0

    draw_active = True
    last_draw_active = None  # type: Optional[bool]

    # cache route dev, refresh only occasionally
    cached_dev = ""
    last_dev_check = 0.0

    # CPU load cache (updates when active)
    last_cpu_check = 0.0

    log(
        f"START backend={BACKEND_BASE} fb={FB} refresh_active={REFRESH_S_ACTIVE}s refresh_idle={REFRESH_S_IDLE}s "
        f"timeout={HTTP_TIMEOUT_S}s idle_off={INACTIVITY_OFF_S}s"
    )

    try:
        while RUN:
            now = time.time()

            # local uptime always maintained in memory (but shown only when drawing)
            up_s = read_uptime_seconds()
            up_txt = format_uptime(up_s)
            state["uptime_text"] = up_txt

            # Choose poll interval based on current draw_active
            poll_interval = REFRESH_S_ACTIVE if draw_active else REFRESH_S_IDLE

            # Fetch (throttled)
            if (now - last_fetch) >= poll_interval:
                payload = http_get_json(f"{BACKEND_BASE}/api/state", timeout=HTTP_TIMEOUT_S)

                if isinstance(payload, dict) and payload.get("repeater") is not None:
                    state_new = parse_api_state(payload)
                    state_new["uptime_text"] = up_txt
                    state = state_new
                    last_ok = now
                else:
                    # Stale handling: if >10s no valid payload -> placeholders
                    if (now - last_ok) > 10.0:
                        st = placeholder_state()
                        st["uptime_text"] = up_txt
                        state = st
                        log("TFT state stale >10s, reset placeholders")

                last_fetch = now

            # WAN iface detection (cached, refresh every 60s when drawing; every 5 min when idle)
            dev_refresh = 60.0 if draw_active else 300.0
            if (now - last_dev_check) >= dev_refresh:
                cached_dev = read_default_route_dev()
                last_dev_check = now

            wan_ip = (state or {}).get("ip_external") or "—"
            state["wan_iface"] = detect_wan_iface_label(str(wan_ip), cached_dev)

            # CPU load: use API value, fallback to local sampling
            if draw_active and (now - last_cpu_check) >= 1.0:
                api_cpu_load = (state or {}).get("cpu_load_pct")
                if api_cpu_load is None:
                    pct = read_cpu_load_pct()
                    if pct is not None:
                        state["cpu_load_pct"] = pct
                last_cpu_check = now

            # Determine draw_active based on backend activity age (only if backend not stale)
            if (now - last_ok) <= 10.0:
                draw_active = should_draw_be_active(state)
            # else: backend stale -> keep last draw_active to avoid flipping

            if last_draw_active is None or draw_active != last_draw_active:
                log(f"DRAW_ACTIVE={'1' if draw_active else '0'} age={state.get('last_user_action_age_s')}")
                last_draw_active = draw_active

            # Drawing:
            # - If draw_active: render and blit at low rate (2Hz) to reduce CPU
            # - If not active: do not blit; keep last frame visible (no black)
            if draw_active:
                # Countdown only shown in the last 5 seconds
                cd = standby_countdown_value(state)
                img = build_screen(state, cd)
                fb.blit(image_to_rgb565(img))
                time.sleep(0.5)  # 2 FPS is enough; reduces CPU substantially
            else:
                # Idle: keep last frame, no drawing, just sleep
                time.sleep(1.0)

    finally:
        fb.close()
        log("EXIT")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())