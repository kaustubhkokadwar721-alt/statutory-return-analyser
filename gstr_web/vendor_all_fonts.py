"""Vendor EVERY theme's fonts locally → fonts/<theme>-fonts.css + woff2, and rewrite
each theme's @import to point local. Reuses the exact Google URL already in each skin.
Run from gstr_web/ :  python vendor_all_fonts.py
"""
import os, re, glob, urllib.request

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
KEEP = ("latin", "latin-ext")
os.makedirs("fonts", exist_ok=True)
block_re = re.compile(r"/\*\s*([\w-]+)\s*\*/\s*(@font-face\s*\{[^}]*\})", re.S)
imp_re = re.compile(r"@import url\((['\"]?)(https://fonts\.googleapis\.com/[^'\")]+)\1\)")

def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    return urllib.request.urlopen(req).read().decode("utf-8")

themes = [f for f in glob.glob("themes/*.css")
          if os.path.basename(f) not in ("base.css", "swiss.css")]
dl_count = 0
for tf in sorted(themes):
    name = os.path.splitext(os.path.basename(tf))[0]
    css = open(tf, encoding="utf-8").read()
    m = imp_re.search(css)
    if not m:
        print(f"{name}: no google import, skip"); continue
    gcss = fetch(m.group(2))
    faces = []
    for subset, block in block_re.findall(gcss):
        if subset not in KEEP:
            continue
        fam = re.search(r"font-family:\s*'([^']+)'", block).group(1)
        weight = re.search(r"font-weight:\s*([\d ]+)", block).group(1).strip().replace(" ", "_")
        style = re.search(r"font-style:\s*(\w+)", block).group(1)
        woff2 = re.search(r"url\((https://[^)]+\.woff2)\)", block).group(1)
        slug = f"{fam.replace(' ', '')}-{weight}-{style}-{subset}.woff2"
        dest = os.path.join("fonts", slug)
        if not os.path.exists(dest):
            urllib.request.urlretrieve(woff2, dest); dl_count += 1
        faces.append(block.replace(woff2, f"./{slug}"))
    open(f"fonts/{name}-fonts.css", "w", encoding="utf-8").write("\n".join(faces) + "\n")
    open(tf, "w", encoding="utf-8").write(css.replace(m.group(0), f"@import url('../fonts/{name}-fonts.css')"))
    print(f"{name}: {len(faces)} faces")
print(f"\nDownloaded {dl_count} new woff2. All themes now offline.")
