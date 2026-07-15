"""Local-only Windows launcher for the browser application."""

from __future__ import annotations

import http.server
import sys
import threading
import urllib.request
import webbrowser
from pathlib import Path
from tkinter import Button, Label, Tk, messagebox


def web_root() -> Path:
    """Find the bundled browser app beside the packaged launcher."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "gstr_web"
    return Path(__file__).resolve().parents[1] / "gstr_web"


class LocalHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, directory: Path, **kwargs):
        super().__init__(*args, directory=str(directory), **kwargs)

    def log_message(self, format, *args):
        pass

    def end_headers(self):
        if self.path.split("?", 1)[0] == "/sw.js":
            self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        super().end_headers()


def start_server(root: Path):
    def handler(*args, **kwargs):
        return LocalHandler(*args, directory=root, **kwargs)

    server = None
    for port in range(8765, 8775):
        try:
            server = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
            break
        except OSError:
            continue
    if server is None:
        raise RuntimeError("Could not reserve a local port for the analyser.")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{server.server_port}/"


def smoke_test(root: Path) -> int:
    server, url = start_server(root)
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            return 0 if response.status == 200 else 1
    finally:
        server.shutdown()
        server.server_close()


def run_window(root: Path) -> None:
    server, url = start_server(root)
    window = Tk()
    window.title("Statutory Return Analyser")
    window.geometry("430x220")
    window.resizable(False, False)

    Label(window, text="Statutory Return Analyser", font=("Segoe UI", 16, "bold")).pack(pady=(30, 8))
    Label(window, text="Running privately on this computer.", font=("Segoe UI", 10)).pack()
    Label(window, text="Keep this window open while you work.", font=("Segoe UI", 9)).pack(pady=(5, 20))
    Button(window, text="Open analyser", width=22, command=lambda: webbrowser.open(url)).pack(pady=4)

    def close():
        server.shutdown()
        server.server_close()
        window.destroy()

    Button(window, text="Close", width=22, command=close).pack(pady=4)
    window.protocol("WM_DELETE_WINDOW", close)
    webbrowser.open(url)
    window.mainloop()


def main() -> int:
    root = web_root()
    if not (root / "index.html").is_file():
        messagebox.showerror("Statutory Return Analyser", "The bundled web application is missing.")
        return 1
    if "--smoke" in sys.argv:
        return smoke_test(root)
    run_window(root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
