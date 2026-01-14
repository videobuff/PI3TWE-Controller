#!/usr/bin/env python3
# =============================================================================
# File        : /srv/pi3twe/app/tft/tft_app_fb.py
# Generated   : 2026-01-13  (Europe/Amsterdam)
# Updated     : 2026-01-14  (Europe/Amsterdam)
# Description :
#   PI3TWE TFT UI – framebuffer only (RGB565), NO touch actions.
#
#   Reads backend:
#     GET  {PI3TWE_BACKEND}/api/state
#
#   Screen (ACTIVE):
#   - Clock top-right with seconds
#   - Network line centered: "<IFACE> | WAN IP: <ip>"  (HAMNET if WAN in 44/8)
#   - Repeater status centered (AAN=BRIGHT RED block, UIT=blue block)
#   - Measurements:
#       INT/EXT/CPU (+ CPU LOAD% after CPU TEMP)
#       + COOLDOWN if >0, else UPTIME on bottom row
#
#   Idle / Standby:
#   - Based on backend last_user_action_age_s (if present)
#   - Last 5 seconds before standby shows: "TFT SCREEN IN STAND BY (Ns)" on bottom row
#   - TRUE standby: stop redraw + stop framebuffer writes (keeps last frame frozen)
#     and only poll backend every STANDBY_POLL_S seconds (big CPU reduction).
#
#   Stale handling:
#   - If no valid payload for >10s -> placeholders (but uptime/cpu-load local continue)
#
#   Logging:
#   - /var/log/pi3twe/tft.log
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
import re
from datetime import datetime
from typing import Optional, Any, Tuple

from PIL import Image, ImageDraw, ImageFont  # type: ignore


# ------------------------------ Config --------------------------------------

FB = os.environ.get("PI3TWE_FB", "/dev/fb1")
BACKEND_BASE = os.environ.get("PI3TWE_BACKEND", "http://127.0.0.1:3000")

W = 480
H = 320

# Backend poll interval (seconds)
REFRESH_S = float(os.environ.get("PI3TWE_TFT_REFRESH", "1.0"))
HTTP_TIMEOUT_S = float(os.environ.get("PI3TWE_TFT_HTTP_TIMEOUT", "2.0"))

LOGFILE = os.environ.get("PI3TWE_TFT_LOG", "/var/log/pi3twe/tft.log")

# Inactivity timeout (seconds) -> standby
INACTIVITY_OFF_S = float(os.environ.get("PI3TWE_TFT_IDLE_OFF_S", "300"))

# While ACTIVE: redraw cadence (seconds). 1.0 keeps seconds clock live.
DRAW_ACTIVE_S = float(os.environ.get("PI3TWE_TFT_DRAW_ACTIVE_S", "1.0"))

# While STANDBY: poll backend infrequently (seconds)
STANDBY_POLL_S = float(os.environ.get("PI3TWE_TFT_STANDBY_POLL_S", "5.0"))

# Countdown seconds shown before standby
STANDBY_COUNTDOWN_S = 5

# Interface label cache
IFACE_CACHE_S = float(os.environ.get("PI3TWE_TFT_IFACE_CACHE_S", "15.0"))

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
        pass


# ------------------------------ Helpers -------------------------------------

def pick_font(path: str, size: int) -> ImageFont.ImageFont:
    try:
        return ImageFont.truetype(path, size=size)
    except Exception:
        return ImageFont.load_default()


def http_get_json(url: str, timeout: float) -> Optional[dict]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "pi3twe-tft/2.5"})
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


# ------------------------------ CPU Load % (local) ---------------------------

def _read_proc_stat_cpu() -> Optional[Tuple[int, int]]:
    """
    Returns (total_jiffies, idle_jiffies) for aggregate CPU line.
    """
    try:
        with open("/proc/stat", "r", encoding="utf-8") as f:
            line = f.readline()
        if not line.startswith("cpu "):
            return None
        parts = line.strip().split()
        nums = [int(x) for x in parts[1:]]
        if len(nums) < 4:
            return None
        user, nice, system, idle = nums[0], nums[1], nums[2], nums[3]
        iowait = nums[4] if len(nums) > 4 else 0
        irq = nums[5] if len(nums) > 5 else 0
        softirq = nums[6] if len(nums) > 6 else 0
        steal = nums[7] if len(nums) > 7 else 0
        total = user + nice + system + idle + iowait + irq + softirq + steal
        idle_all = idle + iowait
        return total, idle_all
    except Exception:
        return None


def cpu_load_percent(prev: Optional[Tuple[int, int]], cur: Optional[Tuple[int, int]]) -> Optional[float]:
    if not prev or not cur:
        return None
    prev_total, prev_idle = prev
    cur_total, cur_idle = cur
    dt = cur_total - prev_total
    di = cur_idle - prev_idle
    if dt <= 0:
        return None
    busy = dt - di
    pct = 100.0 * (busy / float(dt))
    if pct < 0.0:
        pct = 0.0
    if pct > 100.0:
        pct = 100.0
    return pct


# ------------------------------ Network iface label (local) ------------------

_RE_DEV = re.compile(r"\bdev\s+([a-zA-Z0-9_.:-]+)\b")

def _route_dev_for_target(target: str) -> Optional[str]:
    """
    Best effort: ask kernel routing which dev would be used.
    """
    try:
        # ip is usually in /sbin or /usr/sbin
        cmd = ["ip", "route", "get", target]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=1.0)
        if r.returncode != 0:
            return None
        m = _RE_DEV.search(r.stdout)
        if not m:
            return None
        return m.group(1)
    except Exception:
        return None


def _iface_label_from_dev(dev: Optional[str]) -> str:
    if not dev:
        return "WAN"
    d = dev.lower()
    if d == "wlan0":
        return "WLAN0"
    if d == "eth0":
        return "ETH0"
    return dev.upper()


def decide_wan_iface_label(wan_ip: str) -> str:
    wan_ip = (wan_ip or "").strip()
    if wan_ip.startswith("44."):
        return "HAMNET"
    # Default internet route device (works for normal WAN)
    dev = _route_dev_for_target("1.1.1.1")
    return _iface_label_from_dev(dev)


# ------------------------------ State parsing --------------------------------

def placeholder_state() -> dict:
    return {
        "ip_external": "—",
        "wan_iface": "WAN",
        "repeater": False,
        "cooldown": 0,
        "temp_int_c": None,
        "hum_int_pct": None,
        "temp_ext_c": None,
        "hum_ext_pct": None,
        "cpu_temp_c": None,
        "cpu_load_pct": None,  # local computed
        # power mgmt
        "last_user_action_ts": None,
        "last_user_action_age_s": None,
        # local uptime
        "uptime_text": "—",
    }


def parse_api_state(payload: dict) -> dict:
    out = placeholder_state()
    try:
        out["repeater"] = bool(payload.get("repeater", False))
        out["cooldown"] = int(payload.get("cooldown", 0) or 0)

        wan = (payload.get("wan_ip") or "").strip()
        out["ip_external"] = wan if wan else "—"

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
    except Exception as e:
        log(f"PARSE ERROR: {type(e).__name__}: {e}")
    return out


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
    """
    standby_countdown:
      None -> normal screen
      int  -> show "TFT SCREEN IN STAND BY (Ns)" on bottom row (N seconds left)
    """
    im = Image.new("RGB", (W, H), BLACK)
    d = ImageDraw.Draw(im)

    font_h = pick_font(FONT_BOLD, 30)
    font_r = pick_font(FONT_BOLD, 36)

    # Net-line font
    font_net = pick_font(FONT_REG, 24)

    font_meas = pick_font(FONT_BOLD, 24)
    font_uptime = pick_font(FONT_BOLD, 23)

    # Title
    d.text((PAD, HEADER_Y), "PI3TWE STATUS", font=font_h, fill=WHITE)

    # Clock
    clk = datetime.now().strftime("%H:%M:%S")
    tw = d.textlength(clk, font=font_h)
    d.text((W - PAD - int(tw), HEADER_Y), clk, font=font_h, fill=WHITE)

    # Network line: "<IFACE> | WAN IP: <ip>"
    wan = (state or {}).get("ip_external") or "—"
    iface = (state or {}).get("wan_iface") or "WAN"
    net_line = f"{iface} | WAN IP: {wan}"
    wtw = d.textlength(net_line, font=font_net)
    d.text(((W - int(wtw)) // 2, HEADER_Y + 44), net_line, font=font_net, fill=WHITE)

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

    cpu_load = (state or {}).get("cpu_load_pct")
    cpu_load_txt = "--%" if cpu_load is None else f"{int(round(float(cpu_load))):d}%"

    rows = [
        ("INT TEMP", fmt_1(t_int, " C"), fmt_1(h_int, " %"), color_for_temp_c(t_int), color_for_hum_pct(h_int)),
        ("EXT TEMP", fmt_1(t_ext, " C"), fmt_1(h_ext, " %"), color_for_temp_c(t_ext), color_for_hum_pct(h_ext)),
        ("CPU TEMP", fmt_1(t_cpu, " C"), f"LOAD {cpu_load_txt}", color_for_temp_c(t_cpu), WHITE),
    ]

    # Bottom row: countdown OR cooldown OR uptime
    if standby_countdown is not None:
        rows.append(("TFT", f"SCREEN IN STAND BY ({standby_countdown}s)", None, WHITE, WHITE))
    elif cooldown > 0:
        rows.append(("COOLDOWN", f"{cooldown:02d} s", None, WHITE, WHITE))
    else:
        uptime_text = (state or {}).get("uptime_text") or "—"
        rows.append(("UPTIME", uptime_text, None, WHITE, WHITE))

    # Measurements under status block
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
        use_font = font_uptime if label in ("UPTIME", "TFT") else font_meas
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


def _activity_age_s(state: dict) -> Optional[float]:
    age = (state or {}).get("last_user_action_age_s")
    if age is None:
        return None
    try:
        return float(age)
    except Exception:
        return None


def _standby_countdown(age_s: Optional[float]) -> Optional[int]:
    if age_s is None:
        return None
    remaining = int(round(INACTIVITY_OFF_S - age_s))
    if 1 <= remaining <= STANDBY_COUNTDOWN_S:
        return remaining
    return None


def _should_be_active(age_s: Optional[float]) -> bool:
    if age_s is None:
        return True
    return age_s <= INACTIVITY_OFF_S


def main() -> int:
    fb = Framebuffer(FB)

    state: dict = placeholder_state()
    last_fetch = 0.0
    last_ok = 0.0

    # CPU load sampling
    prev_stat = _read_proc_stat_cpu()
    last_cpu_sample = time.time()

    # Interface label caching
    last_iface_check = 0.0
    cached_iface = "WAN"
    cached_wan = ""

    # Active/standby control
    active = True
    last_draw = 0.0

    log(
        "START "
        f"backend={BACKEND_BASE} refresh={REFRESH_S}s timeout={HTTP_TIMEOUT_S}s fb={FB} "
        f"idle_off={INACTIVITY_OFF_S}s draw_active={DRAW_ACTIVE_S}s standby_poll={STANDBY_POLL_S}s "
        f"iface_cache={IFACE_CACHE_S}s"
    )

    try:
        while RUN:
            now = time.time()

            # Local uptime always available
            up_s = read_uptime_seconds()
            state["uptime_text"] = format_uptime(up_s)

            # Local CPU load % (sample about once per second)
            if (now - last_cpu_sample) >= 1.0:
                cur_stat = _read_proc_stat_cpu()
                pct = cpu_load_percent(prev_stat, cur_stat)
                state["cpu_load_pct"] = pct
                prev_stat = cur_stat
                last_cpu_sample = now

            # Backend fetch cadence differs in ACTIVE vs STANDBY
            fetch_interval = REFRESH_S if active else STANDBY_POLL_S

            if (now - last_fetch) >= fetch_interval:
                payload = http_get_json(f"{BACKEND_BASE}/api/state", timeout=HTTP_TIMEOUT_S)
                if isinstance(payload, dict) and payload.get("repeater") is not None:
                    state_new = parse_api_state(payload)

                    # preserve locals
                    state_new["uptime_text"] = state["uptime_text"]
                    state_new["cpu_load_pct"] = state.get("cpu_load_pct")

                    state = state_new
                    last_ok = now
                else:
                    if (now - last_ok) > 10.0:
                        st = placeholder_state()
                        st["uptime_text"] = state["uptime_text"]
                        st["cpu_load_pct"] = state.get("cpu_load_pct")
                        # keep last iface label
                        st["wan_iface"] = state.get("wan_iface") or cached_iface
                        state = st
                        log("TFT state stale >10s, reset placeholders")

                last_fetch = now

            # Update iface label (cached, best effort)
            wan_now = (state.get("ip_external") or "").strip()
            if (wan_now != cached_wan) or ((now - last_iface_check) >= IFACE_CACHE_S):
                cached_wan = wan_now
                cached_iface = decide_wan_iface_label(wan_now)
                last_iface_check = now
                state["wan_iface"] = cached_iface

            # Decide ACTIVE vs STANDBY (only if backend not stale)
            if (now - last_ok) <= 10.0:
                age = _activity_age_s(state)
                desired_active = _should_be_active(age)
            else:
                desired_active = active

            if desired_active != active:
                active = desired_active
                if active:
                    log("MODE: ACTIVE (activity detected)")
                    last_draw = 0.0
                else:
                    log("MODE: STANDBY (idle timeout reached)")

            # Drawing & framebuffer writes:
            if active:
                if (now - last_draw) >= DRAW_ACTIVE_S:
                    age = _activity_age_s(state) if (now - last_ok) <= 10.0 else None
                    countdown = _standby_countdown(age)
                    img = build_screen(state, countdown)
                    fb.blit(image_to_rgb565(img))
                    last_draw = now
                time.sleep(0.05)
            else:
                # standby: intentionally no draw/no blit -> minimal CPU
                time.sleep(0.20)

    finally:
        fb.close()
        log("EXIT")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())