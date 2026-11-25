"""One dedicated Chrome (own profile in data/chrome-profile) driven by Playwright on one thread.
The operator logs into Google/Gmail, Instagram and WhatsApp Web there once; the logins stay. No macOS
"control Chrome" permission is involved, so there is no "Not authorized" error.
The window sits on the laptop's built-in screen (macOS only; falls back to a fixed position elsewhere)."""
import os, queue, threading, time, random, json, subprocess, re
from concurrent.futures import Future, TimeoutError

HERE = os.path.dirname(os.path.abspath(__file__))
PROFILE = os.path.join(os.environ.get("LEAD_RADAR_DATA") or os.path.join(HERE, "data"), "chrome-profile")
_q = queue.Queue()
_state = {"ctx": None, "page": None, "pw": None}
EMAIL_RE = r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"   # sender address shown in the Gmail tab title


def _builtin_screen():
    js = ("ObjC.import('AppKit');var s=$.NSScreen.screens,m=s.objectAtIndex(0).frame,r='';for(var i=0;i<s.count;i++){"
          "var n=ObjC.unwrap(s.objectAtIndex(i).localizedName);if(/Built-in/.test(n)){var f=s.objectAtIndex(i).frame;"
          "r=[f.origin.x,m.size.height-(f.origin.y+f.size.height),f.size.width,f.size.height].join(',')}};r")
    try:
        x, y, w, h = [int(float(v)) for v in subprocess.run(["osascript", "-l", "JavaScript", "-e", js], capture_output=True,
                                                            text=True, timeout=10).stdout.strip().split(",")]
        return x + 10, y + 30, w - 20, h - 40
    except Exception:
        return 40, 40, 1400, 900


def _ctx():
    ctx = _state["ctx"]
    if ctx:
        try:
            live = [pg for pg in ctx.pages if not pg.is_closed()]
            _state["page"] = live[0] if live else ctx.new_page()   # the operator may close tabs; the browser stays
            return _state["page"]
        except Exception:
            _state["ctx"] = None
    from playwright.sync_api import sync_playwright
    if not _state["pw"]:
        _state["pw"] = sync_playwright().start()
    x, y, w, h = _builtin_screen()
    # a Radar Chrome left over from an earlier run holds the profile lock: close it (logins are on disk)
    subprocess.run(["pkill", "-f", "user-data-dir=" + PROFILE], capture_output=True); time.sleep(1.5)
    ctx = _state["pw"].chromium.launch_persistent_context(
        PROFILE, channel="chrome", headless=False, no_viewport=True, locale="en-US",
        args=["--window-position=%d,%d" % (x, y), "--window-size=%d,%d" % (w, h),
              "--disable-blink-features=AutomationControlled", "--no-first-run", "--no-default-browser-check"],
        ignore_default_args=["--enable-automation", "--no-sandbox"])
    _state["ctx"] = ctx
    _state["page"] = ctx.pages[0] if ctx.pages else ctx.new_page()
    return _state["page"]


def _worker():
    while True:
        fn, args, fut = _q.get()
        try:
            fut.set_result(fn(*args))
        except Exception as ex:
            fut.set_exception(ex)


threading.Thread(target=_worker, daemon=True).start()


def reset():
    """Watchdog: kill the Radar Chrome so a hung Playwright call fails at once and the worker is free again.
    Logins stay on disk; the next task opens a fresh window."""
    subprocess.run(["pkill", "-f", "user-data-dir=" + PROFILE], capture_output=True)
    _state["ctx"] = None


def run(fn, *args, timeout=240):
    """Run fn on the browser thread (Playwright sync API is single-threaded). A task that hangs past
    `timeout` gets the browser killed (watchdog), so one stuck page never blocks the whole queue."""
    f = Future(); _q.put((fn, args, f))
    try:
        return f.result(timeout=timeout)
    except TimeoutError:
        reset()
        try: f.result(timeout=30)   # let the killed call unwind before the next task
        except Exception: pass
        raise RuntimeError("browser did not answer within %d s, reopening the Radar Chrome (watchdog)" % timeout)


# ---------- tasks (run on the browser thread) ----------
def google(query):
    p = _ctx()
    p.goto("https://www.google.com/search?hl=en&num=20&q=" + __import__("urllib.parse").parse.quote_plus(query), wait_until="domcontentloaded", timeout=45000)
    p.wait_for_timeout(1200)
    body = p.inner_text("body")[:3000]
    if re.search(r"unusual traffic|not a robot|captcha", body, re.I):
        raise RuntimeError("Google captcha: tick 'I am not a robot' in the Radar Chrome window")
    # organic results = links that wrap an <h3>; "Website" button = Google business panel (local pack / right panel)
    j = p.evaluate("""() => {
      const real = h => { try { const u = new URL(h); if (/google\\./.test(u.host)) { const v = u.searchParams.get('q') || u.searchParams.get('url') || ''; return /^https?:/.test(v) ? v : '' } return h } catch(e) { return '' } };
      // Google often hides targets behind opaque /goto links; the <cite> shows "domain › path"
      const fromCite = a => { const c = a.querySelector('cite') || (a.closest('[data-hveid],[data-ved]')||a).querySelector('cite'); if (!c) return '';
        let t = c.innerText.split('\\n')[0].replace(/ › /g, '/').replace(/\\s.*$/, '').trim(); return t ? (/^https?:/.test(t) ? t : 'https://' + t) : '' };
      const u = [...document.querySelectorAll('a:has(h3)')].map(a => real(a.href) || fromCite(a)).filter(h => /^https?:\\/\\/[^\\/\\s]+\\.[a-z]{2,}/i.test(h) && !/google\\./.test(h));
      const site = [...document.querySelectorAll('a')].filter(a => /^(Website|Site web|Sitio web|Webseite|Веб-сайт|Сайт)$/i.test((a.innerText||'').trim()) && !a.closest('[data-attrid*="kc"], .ULSxyf')).map(a => real(a.href) || 'google-panel');
      const txt = document.body.innerText.slice(0, 6000);
      const m = txt.match(/(\\d[.,]\\d)\\s*(?:★+|\\n)?\\s*\\(([\\d.,]+\\s?[KkMm]?)\\)/);
      return {u, site, rating: m ? m[1].replace(',', '.') : '', reviews: m ? m[2] : ''};
    }""")
    return j


def gmail_account():
    p = _ctx()
    p.goto("https://mail.google.com/mail/u/0/#inbox", wait_until="domcontentloaded", timeout=60000)
    p.wait_for_timeout(3000)
    m = re.search(EMAIL_RE, p.title())
    return m.group(0) if m else ""


def gmail_send(expect_from, to, subject, body, attachment=None):
    p = _ctx()
    p.goto("https://mail.google.com/mail/u/0/?view=cm&fs=1&tf=1", wait_until="domcontentloaded", timeout=60000)
    p.wait_for_selector("input[name=subjectbox]", timeout=45000)
    who = re.search(EMAIL_RE, p.title())
    if not who or who.group(0).lower() != expect_from.lower():
        raise RuntimeError("The Gmail account in the Radar Chrome is not %s (%s). Log in with the Accounts button." % (expect_from, who.group(0) if who else "not logged in"))
    p.locator("input[peoplekit-id], input[aria-label*='To'], textarea[name=to]").first.fill(to)
    p.keyboard.press("Enter")
    p.fill("input[name=subjectbox]", subject)
    box = p.locator("div[aria-label='Message Body'], div[role=textbox][contenteditable=true]").first
    box.click(); box.fill(body)
    if attachment:
        p.locator("input[type=file][name=Filedata]").first.set_input_files(attachment)
        p.wait_for_timeout(1500)
        p.wait_for_function("() => !document.querySelector('[role=progressbar]')", timeout=60000)
    p.wait_for_timeout(random.randint(800, 1600))
    p.keyboard.press("Meta+Enter")
    p.wait_for_selector("text=/Message sent|Message envoyé|Mensaje enviado|Nachricht gesendet|Сообщение отправлено/", timeout=30000)
    return True


def open_accounts():
    p = _ctx(); ctx = _state["ctx"]
    p.goto("https://accounts.google.com/AccountChooser?continue=https://mail.google.com/mail/u/0/")
    for u in ("https://www.instagram.com/accounts/login/", "https://web.whatsapp.com/"):
        ctx.new_page().goto(u)
    return True


def status():
    """Which accounts are logged in inside the Radar Chrome."""
    p = _ctx(); ctx = _state["ctx"]
    ck = {c["domain"] + ":" + c["name"] for c in ctx.cookies()}
    return {"gmail": gmail_account(), "instagram": any(x.endswith(":sessionid") and "instagram" in x for x in ck),
            "whatsapp": wa_status()}


def wa_status():
    """'ok' = chat list visible, 'qr' = needs a scan, '' = undecided. Reuses an open WhatsApp tab."""
    ctx = _state["ctx"]
    pg = next((x for x in ctx.pages if not x.is_closed() and "web.whatsapp.com" in x.url), None)
    if not pg:
        pg = ctx.new_page(); pg.goto("https://web.whatsapp.com/", wait_until="domcontentloaded", timeout=60000)
    for _ in range(40):   # WhatsApp Web loads its chats slowly
        if pg.locator("#pane-side, [aria-label='Chat list'], [data-testid='chat-list']").count():
            return "ok"
        if pg.locator("canvas[aria-label*='QR'], canvas[aria-label*='Scan'], [data-ref]").count():
            return "qr"
        pg.wait_for_timeout(1000)
    return ""


def _type_lines(p, box, text):
    box.click()
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if line: p.keyboard.insert_text(line)
        if i < len(lines) - 1: p.keyboard.press("Shift+Enter")


def ig_dm(handle, text, image=None):
    """Instagram DM to one profile: demo picture first, then the message. Only on the operator's click / outreach run."""
    p = _ctx()
    p.goto("https://www.instagram.com/%s/" % handle, wait_until="domcontentloaded", timeout=45000)
    p.wait_for_timeout(3000)
    if "accounts/login" in p.url:
        raise RuntimeError("Instagram is not logged in in the Radar Chrome: use the Accounts button")
    if p.get_by_text(re.compile(r"this page isn.t available", re.I)).count():
        raise RuntimeError("Instagram profile not found (@%s)" % handle)
    btn = p.get_by_role("button", name=re.compile(r"^(Message|Envoyer un message|Enviar mensaje|Nachricht|Сообщение|Send message)$", re.I))
    if not btn.count():
        btn = p.get_by_role("link", name=re.compile(r"^(Message|Envoyer un message)$", re.I))
    if not btn.count():
        raise RuntimeError("No \"Message\" button on the profile (private account or DMs closed)")
    btn.first.click()
    box = p.locator("div[role=textbox][contenteditable=true]").first
    box.wait_for(timeout=30000)
    p.wait_for_timeout(1500)
    for b in p.get_by_role("button", name=re.compile(r"^(Not Now|Not now)$")).all():   # notifications pop-up
        try: b.click(timeout=2000)
        except Exception: pass
    if image:
        files = image if isinstance(image, list) else [image]
        p.locator("input[type=file]").last.set_input_files(files)
        p.wait_for_timeout(2500 + 800 * len(files))
    _type_lines(p, box, text)
    p.wait_for_timeout(random.randint(700, 1400)); p.keyboard.press("Enter")
    p.wait_for_timeout(4000)
    if p.get_by_text(re.compile(r"Try Again Later|Action Blocked|We restrict certain activity", re.I)).count():
        raise RuntimeError("Instagram: action blocked / try again later")
    if box.inner_text().strip():
        raise RuntimeError("Instagram message was not sent (text stayed in the box)")
    return True


def wa_send(digits, text, image=None):
    """WhatsApp Web in the Radar Chrome: demo picture with the message as its caption (one message)."""
    p = _ctx()
    p.goto("https://web.whatsapp.com/send?phone=%s" % digits, timeout=60000)
    box = p.locator("footer div[contenteditable=true]")
    for _ in range(90):   # chat box, or WhatsApp's own "isn't on WhatsApp" notice, whichever comes first
        if box.count(): break
        if p.get_by_text(re.compile(r"isn.t on WhatsApp|invalid", re.I)).count():
            raise RuntimeError("This number is not on WhatsApp")
        if p.locator("canvas[aria-label*='QR'], canvas[aria-label*='Scan']").count():
            raise RuntimeError("WhatsApp Web QR code not scanned: use the Accounts button")
        p.wait_for_timeout(1000)
    else:
        raise RuntimeError("WhatsApp Web did not open within 90 s")
    p.wait_for_timeout(random.randint(1200, 2500))
    if image:
        p.locator("footer button[title='Attach'], footer [aria-label='Attach'], footer span[data-icon*='plus'], footer span[data-icon*='attach']").first.click()
        p.wait_for_timeout(800)
        item = r"^(Document|Documento|Dokument|Документ)$" if image.lower().endswith(".pdf") else r"^(Photos & videos|Photos et vidéos|Fotos y videos|Fotos und Videos|Фото и видео)$"
        with p.expect_file_chooser(timeout=15000) as fc:   # never "New sticker"
            p.get_by_text(re.compile(item)).first.click()
        fc.value.set_files(image)
        cap = p.locator("[contenteditable=true]:not(footer [contenteditable])").last
        cap.wait_for(timeout=30000); p.wait_for_timeout(1200)
        _type_lines(p, cap, text)
        p.wait_for_timeout(random.randint(700, 1400)); p.keyboard.press("Enter")
        cap.wait_for(state="detached", timeout=30000)
    else:
        _type_lines(p, box.first, text)
        p.wait_for_timeout(random.randint(700, 1400)); p.keyboard.press("Enter")
    p.wait_for_timeout(4000)
    return True


def wa_self():
    """The operator's own number in the Radar Chrome's WhatsApp (for a self-test)."""
    p = _ctx()
    if "web.whatsapp.com" not in p.url:
        p.goto("https://web.whatsapp.com/", timeout=60000); p.wait_for_timeout(6000)
    v = p.evaluate("() => localStorage.getItem('last-wid-md') || localStorage.getItem('last-wid') || ''")
    m = re.search(r"(\d{8,15})", v or "")
    return m.group(1) if m else ""


def gmail_sent_top(n=3):
    """Diagnostic: top rows of Sent in the Radar Chrome's Gmail."""
    p = _ctx()
    p.goto("https://mail.google.com/mail/u/0/#sent", wait_until="domcontentloaded", timeout=60000)
    p.wait_for_timeout(4000)
    return p.evaluate("(n) => [...document.querySelectorAll('tr[role=row], tr.zA')].filter(r => r.offsetParent && /\\S/.test(r.innerText)).slice(0, n).map(r => r.innerText.replace(/\\n/g, ' | ').slice(0, 220))", n)


# ---------- reply detection: only titles/previews are read here; radar.py keeps ONLY rows that match a sent lead ----------
def wa_chatlist():
    """Top chats of the Radar WhatsApp: title + whether the LAST message is ours (tick icon) or theirs."""
    p = _ctx()
    p.goto("https://web.whatsapp.com/", wait_until="domcontentloaded", timeout=60000)
    p.locator("#pane-side").wait_for(timeout=90000); p.wait_for_timeout(2500)
    return p.evaluate("""() => [...document.querySelectorAll('#pane-side [role=listitem], #pane-side [role=row]')].slice(0, 60).map(r => ({
        t: (r.querySelector('span[title]') || {}).title || '',
        own: !!r.querySelector('[data-icon^="msg-"], [data-icon*="status-dblcheck"], [data-icon*="status-check"]') ||
             [...r.querySelectorAll('svg title')].some(x => /wds-ic-(read|delivered|sent|pending|check|msg)/.test(x.textContent)),
        seen: [...r.querySelectorAll('svg title')].some(x => /wds-ic-read/.test(x.textContent)),
        unread: !!r.querySelector('[aria-label*="unread" i], [aria-label*="non lu" i]')}))""")


def ig_inbox():
    """Instagram DM threads: visible text of each thread row; own=True when the preview is our own last message."""
    p = _ctx()
    p.goto("https://www.instagram.com/direct/inbox/", wait_until="domcontentloaded", timeout=60000)
    p.wait_for_timeout(6000)
    if "accounts/login" in p.url:
        raise RuntimeError("Instagram is not logged in in the Radar Chrome")
    js = """() => [...document.querySelectorAll('a[href*="/direct/t/"], div[role=listitem], div[role=button]')]
        .map(e => e.innerText.trim()).filter(t => t && t.length < 300 && t.includes('\\n'))"""
    seen = {}
    for _ in range(10):   # the thread list is virtualised: scroll to load older threads (many sent DMs)
        for t in p.evaluate(js): seen.setdefault(t.split("\n")[0], t)
        last = p.locator('a[href*="/direct/t/"], div[role=listitem], div[role=button]:has(img)').last
        try: last.hover(timeout=3000)
        except Exception: break
        p.mouse.wheel(0, 3000); p.wait_for_timeout(1500)
    return [{"text": t, "own": bool(re.search(r"(?im)^(you|vous|tú|du|вы)\b", "\n".join(t.split("\n")[1:])))} for t in seen.values()]


def gmail_inbox_from(emails):
    """Which of these addresses wrote to the Radar Gmail inbox."""
    p = _ctx()
    q = "in:inbox from:(" + " OR ".join(emails[:40]) + ")"
    p.goto("https://mail.google.com/mail/u/0/#search/" + __import__("urllib.parse").parse.quote(q), wait_until="domcontentloaded", timeout=60000)
    p.wait_for_timeout(5000)
    return p.evaluate("() => [...new Set([...document.querySelectorAll('tr.zA span[email]')].map(e => e.getAttribute('email')))]")
