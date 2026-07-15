# Windows Launcher

This is a small Windows launcher, not a second parser. It serves the bundled
`gstr_web` application only on `127.0.0.1` and opens it in the user's default browser.
Client PDFs and outputs stay in the browser on that computer.

Build a portable folder and ZIP:

```bash
python desktop_launcher/build_portable.py
```

The output is under `release/`. Users run `StatutoryReturnLauncher.exe` and keep its
small window open while using the analyser. The launcher has no network connection and
includes the same pinned WebAssembly engine as the web deployment.
