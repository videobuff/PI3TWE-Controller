#!/usr/bin/env python3
# =============================================================================
# File: ip_test.py
# Generated: 2026-01-04 (Europe/Amsterdam)
# Description:
#   CLI test voor LAN/WAN IP detectie
#   - LAN (jouw methode): socket.gethostname() -> socket.gethostbyname(hostname)
#   - WAN (jouw methode): requests.get('https://api.ipify.org')
#   Extra controle:
#   - LAN (route-based): UDP "connect" -> getsockname() (meestal meest betrouwbaar)
# =============================================================================

import socket
import sys

def lan_by_hostname():
    try:
        hostname = socket.gethostname()
        ip = socket.gethostbyname(hostname)
        return hostname, ip, None
    except Exception as e:
        return None, None, f"{type(e).__name__}: {e}"

def lan_by_route():
    """
    Betrouwbare LAN detectie: gebruikt default route.
    Let op: dit verstuurt geen TCP verkeer; connect() bepaalt alleen route/interface.
    """
    s = None
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        return ip, None
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"
    finally:
        if s:
            try:
                s.close()
            except Exception:
                pass

def wan_by_ipify_requests():
    try:
        import requests  # pip install requests (als nodig)
        r = requests.get("https://api.ipify.org", timeout=5)
        r.raise_for_status()
        return r.text.strip(), None
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"

def wan_by_ipify_urllib():
    """
    Fallback zonder requests.
    """
    try:
        import urllib.request
        with urllib.request.urlopen("https://api.ipify.org", timeout=5) as resp:
            data = resp.read().decode("utf-8", errors="replace").strip()
        return data, None
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"

def main():
    print("=== PI3TWE IP Test ===")

    hn, lan1, err1 = lan_by_hostname()
    print("\n[LAN] Methode 1 (hostname -> gethostbyname)")
    print(f"  hostname : {hn if hn else '-'}")
    print(f"  lan_ip   : {lan1 if lan1 else '-'}")
    if err1:
        print(f"  error    : {err1}")

    lan2, err2 = lan_by_route()
    print("\n[LAN] Extra controle (route-based UDP -> getsockname)")
    print(f"  lan_ip   : {lan2 if lan2 else '-'}")
    if err2:
        print(f"  error    : {err2}")

    wan1, err3 = wan_by_ipify_requests()
    print("\n[WAN] Methode 2 (requests -> ipify.org)")
    print(f"  wan_ip   : {wan1 if wan1 else '-'}")
    if err3:
        print(f"  error    : {err3}")
        # fallback zonder requests
        wan2, err4 = wan_by_ipify_urllib()
        print("\n[WAN] Fallback (urllib -> ipify.org)")
        print(f"  wan_ip   : {wan2 if wan2 else '-'}")
        if err4:
            print(f"  error    : {err4}")

    print("\n=== Interpretatie ===")
    print("- Als 'LAN methode 1' een WAN-adres geeft, dan staat je hostname-resolutie verkeerd (hosts/DNS).")
    print("- In dat geval is 'LAN route-based' meestal correct voor je echte LAN-interface.")
    print("- WAN hoort gelijk te zijn aan ipify-resultaat.")
    return 0

if __name__ == "__main__":
    sys.exit(main())