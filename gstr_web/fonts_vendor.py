"""Vendor the default (Swiss) theme fonts locally → fonts/swiss-fonts.css + woff2.
Run from gstr_web/ :  python fonts_vendor.py
"""
import os, re, urllib.request

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
CSS_URLS = {
    "Archivo": "https://fonts.googleapis.com/css2?family=Archivo:wght@400;500;600;700;800&display=swap",
    "IBM Plex Mono": "https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&display=swap",
}
KEEP = ("latin", "latin-ext")  # English UI — keep latin subsets only

os.makedirs("fonts", exist_ok=True)

def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    return urllib.request.urlopen(req).read().decode("utf-8")

out_css = []
count = 0
block_re = re.compile(r"/\*\s*([\w-]+)\s*\*/\s*(@font-face\s*\{[^}]*\})", re.S)
for fam, url in CSS_URLS.items():
    css = fetch(url)
    for subset, block in block_re.findall(css):
        if subset not in KEEP:
            continue
        weight = re.search(r"font-weight:\s*([\d ]+)", block).group(1).strip()
        style = re.search(r"font-style:\s*(\w+)", block).group(1)
        woff2 = re.search(r"url\((https://[^)]+\.woff2)\)", block).group(1)
        slug = f"{fam.replace(' ', '')}-{weight}-{style}-{subset}.woff2"
        urllib.request.urlretrieve(woff2, os.path.join("fonts", slug))
        local = block.replace(woff2, f"./{slug}")
        out_css.append(local)
        count += 1
        print(f"  + fonts/{slug}")

open("fonts/swiss-fonts.css", "w", encoding="utf-8").write("\n".join(out_css) + "\n")
print(f"\nWrote fonts/swiss-fonts.css with {count} faces.")
