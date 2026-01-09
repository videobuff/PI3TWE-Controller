#!/usr/bin/env python3
# =============================================================================
# File        : /srv/pi3twe/app/tft/tft_app_fb.py
# Generated   : 2026-01-09  (Europe/Amsterdam)
# Description :
#   PI3TWE TFT UI – framebuffer only (RGB565), NO buttons, NO touch actions.
#
#   This version reads the existing backend endpoint:
#     GET  {PI3TWE_BACKEND}/api/state
#   (No token header, because app.py is not modified.)
#
#   Screen:
#   - Clock top-right with seconds (always updates)
#   - WAN IP centered (yellow)
#   - Repeater status centered (AAN=red block, UIT=blue block)
#   - Bottom measurements: INT/EXT/CPU from /api/state.monitor.{int,ext,cpu}
#   - COOLDOWN line only shown if cooldown > 0
#   - Stale handling: if no valid payload for >10s -> placeholders
#   - Logging to /var/log/pi3twe/tft.log
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

# Layout
PAD = 16
HEADER_Y = 10

# Colors
WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
YELLOW = (255, 210, 0)
RED_ON = (180, 0, 0)
BLUE_OFF = (0, 80, 180)

GREEN_OK = (0, 220, 0)
ORANGE_WARN = (255, 140, 0)
RED_BAD = (230, 0, 0)

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
        req = urllib.request.Request(url, headers={"User-Agent": "pi3twe-tft/2.0"})
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


def color_for_temp_c(v: Optional[float]) -> tuple[int, int, int]:
    if v is None:
        return WHITE
    if v < 40.0:
        return GREEN_OK
    if v <= 55.0:
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


def placeholder_state() -> dict:
    return {
        "ip_external": "—",
        "repeater": False,
        "cooldown": 0,
        "temp_int_c": None,
        "hum_int_pct": None,
        "temp_ext_c": None,
        "hum_ext_pct": None,
        "cpu_temp_c": None,
    }


def parse_api_state(payload: dict) -> dict:
    """
    Convert app.py /api/state payload to TFT state dict expected by UI.
    app.py returns:
      {
        "repeater": bool,
        "cooldown": int,
        "wan_ip": str,
        "monitor": {"cpu":{temp,hum}, "int":{temp,hum}, "ext":{temp,hum}}
      }
    """
    out = placeholder_state()

    try:
        out["repeater"] = bool(payload.get("repeater", False))
        out["cooldown"] = int(payload.get("cooldown", 0) or 0)

        wan = (payload.get("wan_ip") or "").strip()
        out["ip_external"] = wan if wan else "—"

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

def build_screen(state: dict) -> Image.Image:
    im = Image.new("RGB", (W, H), BLACK)
    d = ImageDraw.Draw(im)

    font_h = pick_font(FONT_BOLD, 30)
    font_r = pick_font(FONT_BOLD, 36)
    font_s = pick_font(FONT_REG, 18)
    font_meas = pick_font(FONT_BOLD, 24)

    # Title (left)
    d.text((PAD, HEADER_Y), "PI3TWE STATUS", font=font_h, fill=WHITE)

    # Clock (right) - always updates
    clk = datetime.now().strftime("%H:%M:%S")
    tw = d.textlength(clk, font=font_h)
    d.text((W - PAD - int(tw), HEADER_Y), clk, font=font_h, fill=WHITE)

    # WAN IP centered
    wan = (state or {}).get("ip_external") or "—"
    wan_line = f"WAN IP: {wan}"
    wtw = d.textlength(wan_line, font=font_s)
    d.text(((W - int(wtw)) // 2, HEADER_Y + 44), wan_line, font=font_s, fill=YELLOW)

    # Repeater status block
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

    rows = [
        ("INT TEMP", fmt_1(t_int, " C"), fmt_1(h_int, " %"), color_for_temp_c(t_int), color_for_hum_pct(h_int)),
        ("EXT TEMP", fmt_1(t_ext, " C"), fmt_1(h_ext, " %"), color_for_temp_c(t_ext), color_for_hum_pct(h_ext)),
        ("CPU TEMP", fmt_1(t_cpu, " C"), None,              color_for_temp_c(t_cpu), WHITE),
    ]
    if cooldown > 0:
        rows.append(("COOLDOWN", f"{cooldown:02d} s", None, WHITE, WHITE))

    line_h = 32
    bottom_pad = 8
    start_y = H - (len(rows) * line_h) - bottom_pad - 10
    y = start_y

    def draw_centered_segments(ypos: int, segments: list[tuple[str, tuple[int, int, int]]]) -> None:
        total_w = 0.0
        for text, _col in segments:
            total_w += d.textlength(text, font=font_meas)
        x = (W - int(total_w)) // 2
        for text, col in segments:
            d.text((x, ypos), text, font=font_meas, fill=col)
            x += int(d.textlength(text, font=font_meas))

    for label, v1, v2, col_v1, col_v2 in rows:
        if v2 is None:
            segments = [(f"{label}: ", WHITE), (v1, col_v1)]
        else:
            segments = [(f"{label}: ", WHITE), (v1, col_v1), ("   ", WHITE), (v2, col_v2)]
        draw_centered_segments(y, segments)
        y += line_h

    return im


# ------------------------------ Main ----------------------------------------

RUN = True


def _sig(_a, _b) -> None:
    global RUN
    RUN = False


signal.signal(signal.SIGINT, _sig)
signal.signal(signal.SIGTERM, _sig)


def main() -> int:
    fb = Framebuffer(FB)

    state: dict = placeholder_state()
    last_fetch = 0.0
    last_ok = 0.0

    log(f"START backend={BACKEND_BASE} refresh={REFRESH_S}s timeout={HTTP_TIMEOUT_S}s fb={FB}")

    try:
        while RUN:
            now = time.time()

            # Fetch (throttled)
            if (now - last_fetch) >= REFRESH_S:
                payload = http_get_json(f"{BACKEND_BASE}/api/state", timeout=HTTP_TIMEOUT_S)
                if isinstance(payload, dict) and payload.get("repeater") is not None:
                    state = parse_api_state(payload)
                    last_ok = now
                else:
                    # If stale for too long: reset placeholders (but keep drawing clock)
                    if (now - last_ok) > 10.0:
                        state = placeholder_state()
                        log("TFT state stale >10s, reset placeholders")

                last_fetch = now

            # Always draw (clock must keep running)
            img = build_screen(state)
            fb.blit(image_to_rgb565(img))

            time.sleep(0.05)

    finally:
        fb.close()
        log("EXIT")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())