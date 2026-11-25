"""Demo site -> short PDF brochure: the 5-6 parts that sell (hero, services, about, visit/map, phone view, whole page).
Usage: pdfmaker.py <demo index.html> <out.pdf> <labels json>   (own headless Chrome, never the Radar Chrome)"""
import base64, json, sys
from playwright.sync_api import sync_playwright

html, out, labels = sys.argv[1], sys.argv[2], json.loads(sys.argv[3])
shots = []
with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=True)
    pg = b.new_page(viewport={"width": 1280, "height": 800}, device_scale_factor=1.5)
    pg.goto("file://" + html); pg.wait_for_timeout(2500)
    def el(sel, i=0, label=""):
        loc = pg.locator(sel)
        if loc.count() > i:
            shots.append((label, loc.nth(i).screenshot(type="jpeg", quality=82)))
    shots.append((labels["hero"], pg.screenshot(type="jpeg", quality=82, clip={"x": 0, "y": 0, "width": 1280, "height": 760})))
    el(".two", 0, labels["about"])
    el(".two", 1, labels["visit"])
    m = b.new_page(viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True)
    m.goto("file://" + html); m.wait_for_timeout(2000)
    shots.append(("📱 " + labels["mobile"], m.screenshot(type="jpeg", quality=80)))
    shots.append((labels["full"], pg.screenshot(type="jpeg", quality=70, full_page=True)))
    import os
    pages = os.path.join(os.path.dirname(out), "pages"); os.makedirs(pages, exist_ok=True)
    for n, (_, img) in enumerate(shots, 1):   # same pictures for Instagram, which takes no PDF
        open(os.path.join(pages, "%d.jpg" % n), "wb").write(img)
    page = lambda lab, img, tall: (
        '<section><h2>%s</h2><img class="%s" src="data:image/jpeg;base64,%s"></section>' % (lab, "tall" if tall else "", base64.b64encode(img).decode()))
    body = "".join(page(l, i, n >= 3) for n, (l, i) in enumerate(shots))
    doc = """<!doctype html><meta charset="utf-8"><style>
@page{size:A4 landscape;margin:0}body{margin:0;font-family:-apple-system,Segoe UI,Roboto,sans-serif;color:#111827}
section{height:210mm;page-break-after:always;display:flex;flex-direction:column;align-items:center;justify-content:center;background:#f5f5f4;padding:10mm;box-sizing:border-box}
.cover{background:linear-gradient(135deg,#111827,#1f2937);color:#fff;text-align:center}.cover h1{font-size:40px;margin:0 0 10px}.cover p{color:#d1d5db;font-size:18px}
h2{margin:0 0 6mm;font-size:22px}img{max-width:100%%;max-height:170mm;border-radius:10px;box-shadow:0 8px 28px rgba(0,0,0,.18)}img.tall{max-height:178mm}
</style><section class="cover"><h1>%s</h1><p>%s</p></section>%s""" % (labels["title"], labels["sub"], body)
    pg.set_content(doc); pg.wait_for_timeout(500)
    pg.pdf(path=out, landscape=True, format="A4", print_background=True)
    b.close()
print(out)
