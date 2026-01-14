#!/usr/bin/env python3
# =============================================================================
# File        : /srv/pi3twe/app/tft/tft_app_fb.py
# Generated   : 2026-01-14 19:00 (Europe/Amsterdam)
# Description :
#   PI3TWE TFT UI – framebuffer only (RGB565), NO touch actions.
#
#   Reads backend:
#     GET  {PI3TWE_BACKEND}/api/state
#
#   Screen:
#   - Clock top-right with seconds (always updates)
#   - WAN line centered: "<UPLINK> | WAN IP: x.x.x.x"
#   - Repeater status centered (AAN=BRIGHT RED block, UIT=blue block)
#   - Measurements directly under the repeater status block:
#       INT/EXT/CPU (+ COOLDOWN if >0, else UPTIME on bottom row)
#     CPU line includes CPU load % when provided by backend.
#   - Stale handling: if no valid payload for >10s -> placeholders
#   - Logging to /var/log/pi3twe/tft.log
#
#   Power management (requested):
#   - On any user action (web command or button), TFT screen turns ON
#   - After 5 minutes (300s) without further user action, TFT turns OFF
#   - Uses /sys/class/backlight/* when available; otherwise keeps drawing but cannot
#     physically switch off backlight (logs a warning).
#
#   Color rules:
#   - Repeater ON: bright red
#   - Temp thresholds: green <=70.0, orange <=80.0, red >80.0
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
from datetime import datetime
from typing import Optional, Any

from PIL import Image, ImageDraw, ImageFont  # type: ignore


# ------------------------------ Config --------------------------------------

FB = os.environ.get("PI3TWE_FB", "/dev/fb1")
BACKEND_BASE = os.environ.get("PI3TWE_BACKEND", "http://127.0.0.1:3000")

W = 480
H = 320

REFRESH_S = float(os.environ.get("PI3TWE_TFT_REFRESH", "1.0"))
HTTP_TIMEOUT_S = float(os.environ.get("PI3TWE_TFT_HTTP_TIMEOUT", "2.0"))

LOGFILE = os.environ.get("PI3TWE_TFT_LOG", "/var/log/pi3twe/tft.log")

# Inactivity timeout (seconds)
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
        pass


# ------------------------------ Helpers -------------------------------------

def pick_font(path: str, size: int) -> ImageFont.ImageFont:
    try:
        return ImageFont.truetype(path, size=size)
    except Exception:
        return ImageFont.load_default()


def http_get_json(url: str, timeout: float) -> Optional[dict]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "pi3twe-tft/2.4"})
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


def fmt_pct0(v: Optional[float]) -> str:
    if v is None:
        return "--%"
    try:
        return f"{int(round(float(v)))}%"
    except Exception:
        return "--%"


def color_for_temp_c(v: Optional[float]) -> tuple[int, int, int]:
    if v is None:
        return WHITE
    if v <= 70.0:
        return GREEN_OK
    if v <= 80.0:
        return ORANGE_WARN
    return RED_BAD


def color_for_hum_pct(v: Optional[float]) -> tuple[int, int, int]:
    if v is None:
        return WHITE
    if v < 60.0:
        return GREEN_OK
    if v <= 80.0:
        return ORANGE_WARN
    return RED_BAD


def read_uptime_seconds() -> Optional[int]:
    """
    Read system uptime from /proc/uptime.
    Returns seconds (int) or None on error.
    """
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
        "uplink": "WAN",
        "repeater": False,
        "cooldown": 0,
        "temp_int_c": None,
        "hum_int_pct": None,
        "temp_ext_c": None,
        "hum_ext_pct": None,
        "cpu_temp_c": None,
        "cpu_load_pct": None,
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

        upl = (payload.get("wan_uplink") or "").strip()
        out["uplink"] = upl if upl else "WAN"

        # power mgmt fields from backend
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


# ------------------------------ Backlight control ----------------------------

class BacklightController:
    """
    Best effort backlight control using /sys/class/backlight/*
    """

    def __init__(self) -> None:
        self.brightness_path: Optional[str] = None
        self.bl_power_path: Optional[str] = None
        self.max_brightness: Optional[int] = None
        self._is_on: Optional[bool] = None
        self._discover()

    def _discover(self) -> None:
        base = "/sys/class/backlight"
        try:
            if not os.path.isdir(base):
                log("BACKLIGHT: /sys/class/backlight not present; cannot control backlight.")
                return
            entries = sorted(os.listdir(base))
            for name in entries:
                d = os.path.join(base, name)
                bp = os.path.join(d, "brightness")
                mp = os.path.join(d, "max_brightness")
                pp = os.path.join(d, "bl_power")
                if os.path.isfile(bp):
                    self.brightness_path = bp
                    if os.path.isfile(mp):
                        try:
                            with open(mp, "r", encoding="utf-8") as f:
                                self.max_brightness = int(f.read().strip() or "0") or None
                        except Exception:
                            self.max_brightness = None
                    if os.path.isfile(pp):
                        self.bl_power_path = pp
                    log(f"BACKLIGHT: using {d} (brightness={bool(self.brightness_path)} bl_power={bool(self.bl_power_path)} max={self.max_brightness})")
                    return

            log("BACKLIGHT: no usable backlight entries found under /sys/class/backlight.")
        except Exception as e:
            log(f"BACKLIGHT: discovery error: {type(e).__name__}: {e}")

    def _write_sysfs(self, path: str, value: str) -> bool:
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(value)
            return True
        except Exception as e:
            log(f"BACKLIGHT: write failed {path}={value!r}: {type(e).__name__}: {e}")
            return False

    def on(self) -> None:
        if self._is_on is True:
            return
        ok = False

        if self.bl_power_path:
            ok = self._write_sysfs(self.bl_power_path, "0")

        if self.brightness_path:
            if self.max_brightness and self.max_brightness > 0:
                val = str(self.max_brightness)
            else:
                val = "255"
            ok2 = self._write_sysfs(self.brightness_path, val)
            ok = ok or ok2

        if ok:
            self._is_on = True

    def off(self) -> None:
        if self._is_on is False:
            return
        ok = False

        if self.bl_power_path:
            ok = self._write_sysfs(self.bl_power_path, "4")

        if self.brightness_path:
            ok2 = self._write_sysfs(self.brightness_path, "0")
            ok = ok or ok2

        if ok:
            self._is_on = False

    def is_supported(self) -> bool:
        return bool(self.brightness_path or self.bl_power_path)


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

def build_screen(state: dict) -> Image.Image:
    im = Image.new("RGB", (W, H), BLACK)
    d = ImageDraw.Draw(im)

    font_h = pick_font(FONT_BOLD, 30)
    font_r = pick_font(FONT_BOLD, 36)

    # WAN font iets kleiner (ruimte bij lange IPs)
    font_wan = pick_font(FONT_REG, 23)

    font_meas = pick_font(FONT_BOLD, 24)

    # Uptime-regel: expliciet font size 23
    font_uptime = pick_font(FONT_BOLD, 23)

    # Title
    d.text((PAD, HEADER_Y), "PI3TWE STATUS", font=font_h, fill=WHITE)

    # Clock
    clk = datetime.now().strftime("%H:%M:%S")
    tw = d.textlength(clk, font=font_h)
    d.text((W - PAD - int(tw), HEADER_Y), clk, font=font_h, fill=WHITE)

    # WAN IP line: "<UPLINK> | WAN IP: x.x.x.x"
    uplink = (state or {}).get("uplink") or "WAN"
    wan = (state or {}).get("ip_external") or "—"
    wan_line = f"{uplink} | WAN IP: {wan}"
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
    cpu_load = as_float((state or {}).get("cpu_load_pct"))

    # CPU shows temp + load
    cpu_temp_txt = fmt_1(t_cpu, " C")
    cpu_load_txt = fmt_pct0(cpu_load)

    rows = [
        ("INT TEMP", fmt_1(t_int, " C"), fmt_1(h_int, " %"), color_for_temp_c(t_int), color_for_hum_pct(h_int)),
        ("EXT TEMP", fmt_1(t_ext, " C"), fmt_1(h_ext, " %"), color_for_temp_c(t_ext), color_for_hum_pct(h_ext)),
        ("CPU TEMP", cpu_temp_txt, cpu_load_txt, color_for_temp_c(t_cpu), WHITE),
    ]

    # Onderste regel: cooldown OF uptime
    if cooldown > 0:
        rows.append(("COOLDOWN", f"{cooldown:02d} s", None, WHITE, WHITE))
    else:
        uptime_text = (state or {}).get("uptime_text") or "—"
        rows.append(("UPTIME", uptime_text, None, WHITE, WHITE))

    # Measurements directly under status block
    line_h = 32
    y = ry + block_h + 14

    def draw_centered_segments(ypos: int, segments: list[tuple[str, tuple[int, int, int]]], font: ImageFont.ImageFont) -> None:
        total_w = 0.0
        for text, _col in segments:
            total_w += d.textlength(text, font=font)
        x = (W - int(total_w)) // 2
        for text, col in segments:
            d.text((x, ypos), text, font=font, fill=col)
            x += int(d.textlength(text, font=font))

    for label, v1, v2, col_v1, col_v2 in rows:
        use_font = font_uptime if label == "UPTIME" else font_meas

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


def should_screen_be_on(state: dict, last_ok: float) -> bool:
    """
    Decide ON/OFF based on backend last_user_action_age_s.
    - If backend provides age: ON when age <= INACTIVITY_OFF_S
    - If no age provided yet: keep ON (avoid accidental blank)
    - If stale backend >10s: keep current behavior (handled by caller)
    """
    age = (state or {}).get("last_user_action_age_s")
    try:
        if age is None:
            return True
        return float(age) <= float(INACTIVITY_OFF_S)
    except Exception:
        return True


def main() -> int:
    fb = Framebuffer(FB)
    bl = BacklightController()

    state: dict = placeholder_state()
    last_fetch = 0.0
    last_ok = 0.0

    screen_on = True
    bl.on()

    log(f"START backend={BACKEND_BASE} refresh={REFRESH_S}s timeout={HTTP_TIMEOUT_S}s fb={FB} idle_off={INACTIVITY_OFF_S}s backlight_supported={bl.is_supported()}")

    try:
        while RUN:
            now = time.time()

            # Altijd lokale uptime updaten (ook als backend stale is)
            up_s = read_uptime_seconds()
            up_txt = format_uptime(up_s)
            state["uptime_text"] = up_txt

            # Fetch (throttled)
            if (now - last_fetch) >= REFRESH_S:
                payload = http_get_json(f"{BACKEND_BASE}/api/state", timeout=HTTP_TIMEOUT_S)
                if isinstance(payload, dict) and payload.get("repeater") is not None:
                    state_new = parse_api_state(payload)
                    # behoud lokaal berekende uptime
                    state_new["uptime_text"] = up_txt
                    state = state_new
                    last_ok = now
                else:
                    # Stale handling
                    if (now - last_ok) > 10.0:
                        st = placeholder_state()
                        st["uptime_text"] = up_txt
                        state = st
                        log("TFT state stale >10s, reset placeholders")

                last_fetch = now

            # Power management decision
            desired_on = True
            if (now - last_ok) <= 10.0:
                desired_on = should_screen_be_on(state, last_ok)
            else:
                # backend stale; keep current (avoid flicker/blackout due to missing data)
                desired_on = screen_on

            if desired_on != screen_on:
                screen_on = desired_on
                if screen_on:
                    bl.on()
                    log("SCREEN: ON (activity detected or within timeout)")
                else:
                    bl.off()
                    log("SCREEN: OFF (idle timeout reached)")

            # Drawing
            if screen_on:
                img = build_screen(state)
            else:
                img = Image.new("RGB", (W, H), BLACK)

            fb.blit(image_to_rgb565(img))
            time.sleep(0.05)

    finally:
        try:
            bl.on()
        except Exception:
            pass
        fb.close()
        log("EXIT")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())