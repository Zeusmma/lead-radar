#!/usr/bin/env python3
"""Lead Radar - finds small businesses without a website, builds a demo site for each,
drafts the first message, and sends only what the operator approves. Stdlib only (Playwright for browser tasks); data in data/radar.db.

Run: python3 radar.py            (server on http://127.0.0.1:8790)
     python3 radar.py --selftest
"""
import json, os, re, sqlite3, subprocess, sys, threading, time, random, html, urllib.parse, urllib.request
import smtplib, ssl
from email.message import EmailMessage
from email.utils import make_msgid
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.environ.get("LEAD_RADAR_DATA") or os.path.join(HERE, "data")   # override to keep a separate data set
DEMO = os.path.join(DATA, "demo")
DB = os.path.join(DATA, "radar.db")
PORT = int(os.environ.get("LEAD_RADAR_PORT", "8790"))
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36"
OVERPASS = ["https://overpass-api.de/api/interpreter", "https://maps.mail.ru/osm/tools/overpass/api/interpreter"]
CHROME = os.environ.get("CHROME_BIN", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")   # set CHROME_BIN on Linux/Windows
DAILY_EMAIL_CAP = 40
# Germany/Austria (UWG / TKG): cold e-mail to businesses needs prior consent -> e-mail disabled there.
SKIP_COUNTRIES = set()   # ISO codes that are never contacted (empty by default; edit freely)
EMAIL_BLOCKED = {"DE": "Germany (UWG)", "AT": "Austria (TKG)"}
# UK PECR: a free-mail address usually means a sole trader (an individual) -> needs prior consent; use WhatsApp/phone instead
FREEMAIL = re.compile(r"@(gmail|googlemail|hotmail|outlook|live|yahoo|icloud|aol|btinternet|sky|mail|gmx|web|yandex|proton)\.", re.I)                   # shortcut: fixed cap; raise only after the account has a sending history

# ---------- catalogues ----------
COUNTRIES = {  # ISO: (English name, message language)
    "US": ("United States", "en"), "CA": ("Canada", "en"), "GB": ("United Kingdom", "en"), "IE": ("Ireland", "en"),
    "FR": ("France", "fr"), "BE": ("Belgium", "fr"), "ES": ("Spain", "es"), "IT": ("Italy", "it"),
    "PT": ("Portugal", "pt"), "NL": ("Netherlands", "nl"), "PL": ("Poland", "pl"), "SE": ("Sweden", "en"),
    "DK": ("Denmark", "en"), "NO": ("Norway", "en"), "FI": ("Finland", "en"), "CH": ("Switzerland", "de"),
    "DE": ("Germany", "de"), "AT": ("Austria", "de"), "CZ": ("Czechia", "en"), "GR": ("Greece", "en"),
    "RO": ("Romania", "en"), "BG": ("Bulgaria", "en"), "HU": ("Hungary", "en"), "CY": ("Cyprus", "en"),
    "MX": ("Mexico", "es"), "BR": ("Brazil", "pt"), "AR": ("Argentina", "es"), "CO": ("Colombia", "es"),
    "CL": ("Chile", "es"), "PE": ("Peru", "es"), "AU": ("Australia", "en"), "AE": ("United Arab Emirates", "en"),
    "GE": ("Georgia", "en"), "KZ": ("Kazakhstan", "ru"), "TR": ("Turkey", "tr"),
}
CATEGORIES = {  # key: (English label, OSM filter)
    "restaurant": ("Restaurant", '["amenity"="restaurant"]'), "cafe": ("Cafe", '["amenity"="cafe"]'),
    "fast_food": ("Fast food", '["amenity"="fast_food"]'), "barber": ("Barber / hairdresser", '["shop"="hairdresser"]'),
    "beauty": ("Beauty salon", '["shop"="beauty"]'), "dentist": ("Dentist", '["amenity"="dentist"]'),
    "car_repair": ("Car repair", '["shop"="car_repair"]'), "bakery": ("Bakery / pastry", '["shop"="bakery"]'),
    "hotel": ("Hotel / guest house", '["tourism"~"^(hotel|guest_house|hostel)$"]'),
    "gym": ("Gym", '["leisure"="fitness_centre"]'), "florist": ("Florist", '["shop"="florist"]'),
    "clothes": ("Clothing store", '["shop"="clothes"]'), "pharmacy": ("Pharmacy", '["amenity"="pharmacy"]'),
    "vet": ("Veterinarian", '["amenity"="veterinary"]'), "car_wash": ("Car wash", '["amenity"="car_wash"]'),
    # trades: tradespeople tend to answer messages best
    "plumber": ("Plumber", '["craft"="plumber"]'), "electrician": ("Electrician", '["craft"="electrician"]'),
    "builder": ("Builder / renovation", '["craft"~"^(builder|carpenter|tiler|painter)$"]'),
}
SOCIAL_OR_DIRECTORY = re.compile(r"facebook|instagram|tiktok|twitter|x\.com|youtube|linkedin|tripadvisor|yelp|foursquare|"
                                 r"google\.|goo\.gl|wikipedia|booking\.|zomato|"
                                 r"wolt|glovo|uber|deliveroo|justeat|lieferando|thefork|opentable|bing\.|msn\.|wa\.me|"
                                 r"mapcarta|cylex|yellowpages|foursquare|restaurantguru|"
                                 r"menupages|treatwell|fresha|planity|doctolib|zocdoc|osm\.org|openstreetmap|wheree|booksy|wantside|setmore|"
                                 r"yell\.com|freeindex|hotfrog|scoot\.co|thomsonlocal|trustpilot|nextdoor|groupon|vagaro|styleseat|"
                                 r"salonized|pagesjaunes|paginasamarillas|paginegialle|gelbeseiten|cybo\.|waze\.com|mapquest|"
                                 r"negocioscerca|sheerme|tiktok|pinterest|threads\.net|linktr\.ee|ubereats|doordash|grubhub|"
                                 r"just-eat|wolt\.com|glovoapp|thuisbezorgd|pyszne|deliveroo|tupalo|infobel|europages|top-rated\.online|"
                                 r"birdeye|chamberofcommerce|manta\.com|bbb\.org|bizapedia|opencorporates|companieshouse|endole", re.I)

# ---------- text (demo site + messages) ----------   # message templates per language
T = {"en": {"cat": {"restaurant": "restaurant", "cafe": "café", "fast_food": "fast food", "barber": "barber & hair salon", "beauty": "beauty salon", "dentist": "dental clinic", "car_repair": "car repair shop", "bakery": "bakery", "hotel": "hotel", "gym": "gym", "florist": "florist", "clothes": "clothing store", "pharmacy": "pharmacy", "vet": "veterinary clinic", "car_wash": "car wash"}, "hero": "Your trusted {cat} in {city}", "sub": "Call us, get directions or message us on WhatsApp.", "call": "Call now", "wa": "WhatsApp", "route": "Directions", "about": "About us", "about_t": "{name} is a {cat} in {city} that takes care of every customer: good service, friendly people and fair prices.", "hours": "Opening hours", "contact": "Contact", "demo": "This page is a sample design made for {name}.", "subject": "A free website design for {name}", "email": "Hello {name} team,\n\nI looked for you online but could not find a website. Most customers search on Google first, and businesses without a site lose them to competitors.\n\nI made a free sample design for you (attached): phone, WhatsApp, directions, opening hours, mobile-friendly.\n\nIf you like it, I can put it online within a few days{price}. If you are not interested, just reply \"no\" and I will not write again.\n\nBest regards,\n{sender}\n{contact}", "short": "Hello! I made a free sample website for {name} (phone, WhatsApp, directions, mobile-friendly). Would you like to see it? No problem if not. — {sender}", "price": " for {price}"}}   # English base pack; other languages load from i18n/<lang>.json

def _load_i18n():
    """i18n/<lang>.json: full packs for new languages, extra keys (services, why) for the hand-written ones."""
    d = os.path.join(HERE, "i18n")
    for f in sorted(os.listdir(d)):
        if re.fullmatch(r"[a-z]{2}\.json", f):
            j = json.load(open(os.path.join(d, f), encoding="utf-8"))
            T.setdefault(f[:2], {}).update({k: v for k, v in j.items() if f[:2] not in T or k not in T[f[:2]]})
    extra = json.load(open(os.path.join(d, "en_extra.json"), encoding="utf-8"))
    T["en"].update({k: v for k, v in extra.items() if k not in T["en"]})
_load_i18n()
for _f in sorted(os.listdir(os.path.join(HERE, "i18n", "dm"))) if os.path.isdir(os.path.join(HERE, "i18n", "dm")) else []:   # persuasion DM pack, overrides the old short message
    if _f.endswith(".json"):
        _d = json.load(open(os.path.join(HERE, "i18n", "dm", _f), encoding="utf-8")); _L = T.setdefault(_f[:2], {})
        _L["cat"] = {**_L.get("cat", {}), **_d.pop("cat_trade", {})}; _L["services"] = {**_L.get("services", {}), **_d.pop("services_trade", {})}
        _L.update(_d)

# ---------- storage ----------
def db():
    os.makedirs(DEMO, exist_ok=True)
    c = sqlite3.connect(DB, timeout=30)
    c.row_factory = sqlite3.Row
    c.executescript("""
    create table if not exists leads(id text primary key, country text, city text, category text, name text, phone text,
      email text, instagram text, whatsapp text, address text, lat real, lon real, hours text, lang text,
      site text default 'unchecked', site_hits text, status text default 'new', msg_subject text, msg_body text,
      msg_short text, demo text, png text, sent_at text, notes text, created text);
    create table if not exists settings(k text primary key, v text);
    create table if not exists log(ts text, what text);
    create table if not exists cities(country text, name text, lat real, lon real, pop integer, primary key(country,name));
    create table if not exists touches(lead_id text, ts text, channel text, step integer, kind text);
    """)
    have = {r[1] for r in c.execute("pragma table_info(leads)")}
    for col, typ in (("rating", "real"), ("reviews", "integer"), ("platforms", "text"), ("score", "integer"), ("reasons", "text"), ("pdf", "text"),
                     ("fu_step", "integer"), ("next_fu", "text"), ("replied_at", "text"), ("last_ch", "text")):
        if col not in have: c.execute("alter table leads add column %s %s" % (col, typ))
    return c

def setting(c, k, default=""):
    r = c.execute("select v from settings where k=?", (k,)).fetchone()
    return r["v"] if r else default

def log(c, what):
    c.execute("insert into log values(?,?)", (time.strftime("%Y-%m-%d %H:%M:%S"), what)); c.commit()

# ---------- network ----------
def http_get(url, timeout=30, headers=None):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en", **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "ignore")

def overpass(q):
    err = ""
    for ep in OVERPASS * 2:   # busy servers answer 502/504; second pass after a pause
        if err: time.sleep(5)
        try:
            data = urllib.parse.urlencode({"data": q}).encode()
            req = urllib.request.Request(ep, data=data, headers={"User-Agent": "LeadRadar/1.0", "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=200) as r:
                return json.load(r)["elements"]
        except Exception as ex:
            err = "%s: %s" % (ep, ex)
    raise RuntimeError("Overpass request failed: " + err)

def cities(c, iso):
    rows = c.execute("select name,lat,lon,pop from cities where country=? order by pop desc", (iso,)).fetchall()
    if rows:
        return [dict(r) for r in rows]
    els = overpass('[out:json][timeout:180];area["ISO3166-1"="%s"][admin_level=2]->.a;node(area.a)["place"~"^(city|town)$"];out 2000;' % iso)
    out = []
    for e in els:
        t = e.get("tags", {})
        nm = t.get("name:en") if COUNTRIES[iso][1] in ("en",) and t.get("name:en") else t.get("name")
        try: pop = int(re.sub(r"\D", "", t.get("population", "0")) or 0)
        except ValueError: pop = 0
        if t.get("place") == "city": pop += 10**8   # cities first even when OSM has no population tag
        if nm: out.append((iso, nm, e["lat"], e["lon"], pop))
    out.sort(key=lambda x: -x[4]); out = out[:120]
    c.executemany("insert or ignore into cities values(?,?,?,?,?)", out); c.commit()
    return [{"name": n, "lat": la, "lon": lo, "pop": p} for _, n, la, lo, p in out]

def find_leads(c, iso, city, cat, radius_km=8, limit=60, want_all=False):
    cy = next((x for x in cities(c, iso) if x["name"] == city), None)
    if not cy:
        raise RuntimeError("City not found: " + city)
    f = CATEGORIES[cat][1]
    q = ('[out:json][timeout:90];nwr(around:%d,%f,%f)%s["name"][!"website"][!"contact:website"][!"url"]'
         '[!"brand"];out center tags %d;' % (radius_km * 1000, cy["lat"], cy["lon"], f, max(limit * 12, 300)))
    new = 0
    for e in overpass(q):
        t = e.get("tags", {})
        phone = t.get("phone") or t.get("contact:phone") or t.get("contact:mobile") or ""
        email = t.get("email") or t.get("contact:email") or ""
        insta = t.get("contact:instagram") or t.get("instagram") or ""
        wa = t.get("contact:whatsapp") or ""
        if not (phone or email or insta or wa) and not want_all:
            continue
        lid = "%s/%s" % (e["type"], e["id"])
        if c.execute("select 1 from leads where id=?", (lid,)).fetchone():
            continue
        lat = e.get("lat") or e.get("center", {}).get("lat"); lon = e.get("lon") or e.get("center", {}).get("lon")
        addr = " ".join(x for x in [t.get("addr:street", ""), t.get("addr:housenumber", ""), t.get("addr:city", "") or city] if x)
        c.execute("insert into leads(id,country,city,category,name,phone,email,instagram,whatsapp,address,lat,lon,hours,lang,created)"
                  " values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (lid, iso, city, cat, t["name"], phone.split(";")[0].strip(), email.split(";")[0].strip(),
                   insta_handle(insta), wa, addr, lat, lon, t.get("opening_hours", ""), lang_for(iso, city, t), time.strftime("%Y-%m-%d %H:%M")))
        new += 1
        if new >= limit:
            break
    c.commit()
    log(c, "search %s/%s/%s: %d new" % (iso, city, cat, new))
    return new

def insta_handle(v):
    v = (v or "").strip()
    m = re.search(r"instagram\.com/([A-Za-z0-9_.]+)", v)
    return (m.group(1) if m else v.lstrip("@")).strip("/")

def norm(s):
    s = s.lower().replace("ß", "ss")
    for b, group in (("c", "ç"), ("g", "ğ"), ("i", "ıíìî"), ("o", "öóòôõ"), ("s", "ş"), ("u", "üúùû"), ("e", "éèêë"),
                     ("a", "äáàâã"), ("n", "ñ")):
        for a in group:
            s = s.replace(a, b)
    return re.sub(r"[^a-z0-9]", "", s)

STOP = {"restaurant", "restoran", "cafe", "kafe", "kebap", "kebab", "the", "and", "salon", "kuafor", "berber", "hotel", "otel", "bar", "pizza", "lokanta",
        "barber", "barbers", "barbershop", "barberia", "barbearia", "nails", "nail", "beauty", "hair", "hairdresser", "hairdressers", "studio",
        "spa", "lounge", "clinic", "dental", "dentist", "pharmacy", "bakery", "florist", "flowers", "garage", "motors", "auto", "carwash",
        "peluqueria", "coiffure", "parrucchiere", "friseur", "ristorante", "trattoria", "pizzeria", "boulangerie", "cafeteria", "tanning",
        "inspiration", "design", "house", "shop", "store", "london", "madrid", "paris", "cuts", "kitchen", "grill", "express"}

QC = r"montr[ée]al|qu[ée]bec|laval|gatineau|longueuil|sherbrooke|trois-rivi[èe]res|l[ée]vis|terrebonne|saguenay"
BE_FR = r"bruxelles|brussel|li[èe]ge|charleroi|namur|mons|tournai|louvain-la-neuve|wavre|arlon"
CH_FR = r"gen[èe]ve|geneva|lausanne|neuch[âa]tel|fribourg|sion|montreux|vevey|yverdon"

def lang_for(iso, city, tags=None):
    """Language of the region, not only the country: Montreal writes French, Lugano Italian, Ghent Dutch.
    shortcut: city lists cover the big cities only; OSM's name:<lang> tags are not used yet."""
    cy = (city or "").lower()
    if iso == "CA" and re.search(QC, cy): return "fr"
    if iso == "BE": return "fr" if re.search(BE_FR, cy) else "nl"
    if iso == "CH": return "fr" if re.search(CH_FR, cy) else "it" if re.search(r"lugano|locarno|bellinzona", cy) else "de"
    return COUNTRIES[iso][1]

SITE_LINKS = {}   # query -> website links from Google's business panel
GINFO = {}        # query -> (rating, reviews) from Google's business panel

def search_urls(query):
    """Google in the Radar Chrome (own profile); Brave as fallback."""
    try:
        import browser
        j = browser.run(browser.google, query, timeout=90)
        SITE_LINKS[query] = j.get("site", []); GINFO[query] = (j.get("rating", ""), j.get("reviews", ""))
        if j["u"] or j["site"]:
            return list(dict.fromkeys(j["u"]))
    except Exception as ex:
        if "captcha" in str(ex): raise
    page = http_get("https://search.brave.com/search?q=%s&source=web" % urllib.parse.quote_plus(query), timeout=25)
    urls = list(dict.fromkeys(u for u in re.findall(r'href="(https?://[^"]+)"', page) if not re.search(r"brave\.com|bravesoftware|imgs\.search", u)))
    if not urls:
        raise RuntimeError("search returned nothing (Google / Brave)")
    return urls

EXTRA_OK = {"", "official", "salon", "studio", "shop", "store", "cafe", "restaurant", "bar", "barber", "barbershop", "hair",
            "beauty", "clinic", "dental", "group", "online", "web", "es", "uk", "de", "fr", "it", "co", "the", "and"}

def _strip_rest(rest, parts):
    """Remove known pieces (name words, generic words, city) from the start of `rest` greedily."""
    changed = True
    while rest and changed:
        changed = False
        for x in sorted(parts, key=len, reverse=True):
            if x and rest.startswith(x):
                rest = rest[len(x):]; changed = True; break
    return rest

def own_domain(label, full, words, city, allw=()):
    """Domain label is the business name, optionally plus its own words, the city or a generic word
    (acmehairandbeauty = Acme Hair & Beauty; zoneonelyceum is not Zone One; samplenails = Sample's Nail Spa)."""
    if len(full) < 4 or not label:
        return False
    parts = set(EXTRA_OK) | STOP | {norm(city)} | set(allw) | {w.rstrip("s") for w in allw}
    keys = [full] + [w for w in words if len(w) >= 6] + [w.rstrip("s") for w in allw[:1] if len(w.rstrip("s")) >= 4]
    for key in keys:
        if label.startswith(key) or label.endswith(key):
            rest = label.replace(key, "", 1)
            if _strip_rest(rest, parts) == "" or (len(rest) <= 3 and len(key) >= 6):
                return True
    return False

def weak_match(host, allw):
    h = norm(host)
    return any(w.rstrip("s") in h for w in allw if len(w.rstrip("s")) >= 4 and w not in STOP)

COUNTRY_TLD = {k: k.lower() for k in ("US", "CA", "GB", "IE", "FR", "BE", "ES", "IT", "PT", "NL", "PL", "SE", "DK", "NO", "FI", "CH", "DE", "AT",
                                       "CZ", "GR", "RO", "BG", "HU", "CY", "MX", "BR", "AR", "CO", "CL", "PE", "AU", "AE", "GE", "KZ", "TR")}
GENERIC_TLD = {"com", "net", "org", "info", "biz", "io", "co", "shop", "site", "online", "store", "business", "salon", "beauty", "website", "page", "me", "app", "eu"}

LAST_INFO = {}

def site_check(name, city, catword="", country=""):
    """Google's business panel "Website" button, or a result domain that contains the business
    name, means it has a site. Returns (status, hits, instagram handle or "")."""
    q = " ".join(x for x in (name, catword, city) if x)
    urls = search_urls(q)
    LAST_INFO.update(rating=GINFO.get(q, ("", ""))[0], reviews=GINFO.get(q, ("", ""))[1], urls=urls)
    panel = [u for u in SITE_LINKS.pop(q, []) if not SOCIAL_OR_DIRECTORY.search(u)]
    if not panel and catword:   # second look without the category word catches own-domain sites Google ranked lower
        time.sleep(random.uniform(2, 4)); q2 = "%s %s web" % (name, city)
        urls += [u for u in search_urls(q2) if u not in urls]
        panel = [u for u in SITE_LINKS.pop(q2, []) if not SOCIAL_OR_DIRECTORY.search(u)]
    words = [norm(w) for w in re.split(r"\s+", name) if len(norm(w)) >= 4 and norm(w) not in STOP]
    allw = [norm(w) for w in re.split(r"[\s&'’.,-]+", name) if norm(w)]
    full = norm(name)
    cc = COUNTRY_TLD.get(country, "")
    ig = ""
    for u in urls:
        m = re.search(r"instagram\.com\S*?/([A-Za-z0-9_.]{3,30})", u.replace(" › ", "/"))
        if m and not ig and m.group(1).lower() not in ("p", "reel", "reels", "explore", "stories", "accounts", "popular", "tv"):
            h = norm(m.group(1))
            if (len(full) >= 5 and full[:8] in h) or any(w[:6] in h for w in words if len(w) >= 5):
                ig = m.group(1)
    panel = [u for u in panel if u == "google-panel" or weak_match(u.split("/")[2] if "//" in u else u, allw)]
    if panel:
        return "has", panel[0], ig
    for u in urls:
        host = re.sub(r"^https?://(www\.)?", "", u).split("/")[0].split(" ")[0].lower()
        dom = norm(host); label = norm(host.split(".")[0])
        if SOCIAL_OR_DIRECTORY.search(u):
            continue
        tld = host.rsplit(".", 1)[-1]
        if len(tld) == 2 and tld not in GENERIC_TLD and tld != cc and not (cc == "gb" and tld == "uk"):
            continue   # example-salon.example.org is not a London salon
        if own_domain(label, full, words, city, allw):
            return "has", u, ig
    return "none", " | ".join(urls[:5]), ig

# ---------- demo site ----------
def esc(s): return html.escape(s or "")

def osm_tiles(lat, lon, color, z=16):
    """Static map from OpenStreetMap tiles (iframes stay blank in the headless screenshot)."""
    import math
    n = 2 ** z; fx = (lon + 180) / 360 * n
    fy = (1 - math.log(math.tan(math.radians(lat)) + 1 / math.cos(math.radians(lat))) / math.pi) / 2 * n
    tx, ty = int(fx), int(fy); W, Hh = 520, 300
    ox, oy = W / 2 - (fx - tx) * 256, Hh / 2 - (fy - ty) * 256   # pixel position of tile (tx,ty)
    imgs = "".join('<img src="https://tile.openstreetmap.org/%d/%d/%d.png" style="left:%dpx;top:%dpx">' % (z, tx + dx, ty + dy, ox + dx * 256, oy + dy * 256)
                   for dx in (-2, -1, 0, 1) for dy in (-1, 0, 1))
    return '<div class="map" style="width:100%%">%s<div class="pin" style="left:%dpx;top:%dpx;background:%s"></div></div>' % (imgs, W / 2, Hh / 2, color)

ICONS = {"plumber": "🚰", "electrician": "⚡", "builder": "🏗️", "restaurant": "🍽️", "cafe": "☕", "fast_food": "🍔", "barber": "💈", "beauty": "💅", "dentist": "🦷", "car_repair": "🔧",
         "bakery": "🥐", "hotel": "🛏️", "gym": "🏋️", "florist": "💐", "clothes": "👗", "pharmacy": "💊", "vet": "🐾", "car_wash": "🚿"}

def kind(r):
    """OSM's hairdresser tag covers women's salons and its beauty tag covers nail bars:
    the name decides, so a ladies' salon never gets "beard trim" and a nail bar leads with nails."""
    n = r["name"].lower()
    if r["category"] == "barber" and not re.search(r"barb|berber|kuaf.r erkek", n): return "hair"
    if r["category"] == "beauty" and re.search(r"nail|ongle|unghi|uña|unha|nagel|paznok|manicur|manikür", n): return "nails"
    return r["category"]

def cat_of(r, L):
    k = kind(r); return L["cat_x"][k] if k in L.get("cat_x", {}) else L["cat"][r["category"]]

def services_of(r, L):
    k = kind(r); return L["services_x"][k] if k in L.get("services_x", {}) else L["services"][r["category"]]

def demo_html(r, c):
    L = T[r["lang"]]; cat = cat_of(r, L)
    phone = r["phone"] or ""; digits = re.sub(r"\D", "", r["whatsapp"] or phone)
    color = random.Random(r["id"]).choice(["#0f766e", "#b45309", "#7c3aed", "#be123c", "#1d4ed8", "#15803d"])
    maps = osm_tiles(r["lat"], r["lon"], color)
    route = "https://www.google.com/maps/dir/?api=1&destination=%f,%f" % (r["lat"], r["lon"])
    f = dict(name=r["name"], city=r["city"], cat=cat); ic = {"hair": "✂️", "nails": "💅"}.get(kind(r), ICONS[r["category"]])
    btn_wa = '<a class="b g" href="https://wa.me/%s">%s</a>' % (digits, L["wa"]) if digits else ""
    btn_call = '<a class="b" href="tel:%s">%s</a>' % (esc(phone), L["call"]) if phone else ""
    serv = "".join('<div class="sv"><span>%s</span><b>%s</b></div>' % (ic, esc(x)) for x in services_of(r, L))
    why = "".join('<li>✓ %s</li>' % esc(x) for x in L["why"])
    return """<!doctype html><html lang="%(lang)s"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>%(name)s</title><style>
*{box-sizing:border-box}body{margin:0;font-family:-apple-system,Segoe UI,Roboto,sans-serif;color:#1f2937;background:#fafaf9}
nav{display:flex;justify-content:space-between;align-items:center;padding:18px 32px;background:#111827;color:#fff}nav b{font-size:20px}nav a{color:#fff;text-decoration:none;font-weight:600}
header{background:radial-gradient(circle at 20%% 20%%,%(c)s,#111827 75%%);color:#fff;padding:80px 24px 110px;text-align:center}
header .ic{font-size:56px}header small{display:block;letter-spacing:.2em;text-transform:uppercase;opacity:.8;margin-top:10px}
h1{font-size:clamp(36px,6vw,62px);margin:8px 0}header p{font-size:20px;opacity:.92;margin:0 0 30px}
.b{display:inline-block;margin:6px;padding:15px 28px;border-radius:999px;background:#fff;color:%(c)s;font-weight:700;text-decoration:none;box-shadow:0 6px 20px rgba(0,0,0,.25)}
.g{background:#22c55e;color:#fff}.o{background:transparent;border:2px solid #fff;color:#fff;box-shadow:none}
.sec{max-width:1040px;margin:0 auto;padding:0 18px}.svs{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:16px;margin-top:-60px}
.sv{background:#fff;border-radius:20px;padding:28px;box-shadow:0 12px 34px rgba(0,0,0,.09);display:flex;gap:14px;align-items:center;font-size:17px}.sv span{font-size:30px}
h2{color:%(c)s;font-size:26px;margin:46px 0 16px}.two{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:18px}
.card{background:#fff;border-radius:20px;padding:26px;box-shadow:0 12px 34px rgba(0,0,0,.07);font-size:16px;line-height:1.6}.card ul{list-style:none;padding:0;margin:0}
.map{position:relative;height:300px;border-radius:20px;overflow:hidden;background:#e5e7eb}.map img{position:absolute;width:256px;height:256px}
.pin{position:absolute;width:22px;height:22px;border-radius:50%% 50%% 50%% 0;transform:translate(-50%%,-100%%) rotate(-45deg);border:3px solid #fff;box-shadow:0 2px 8px rgba(0,0,0,.4)}footer{text-align:center;color:#6b7280;font-size:13px;padding:34px}
</style></head><body><nav><b>%(ic)s %(name)s</b><a href="%(tel)s">%(phone)s</a></nav>
<header><div class="ic">%(ic)s</div><h1>%(name)s</h1><p>%(hero)s</p>%(call)s%(wa)s<a class="b o" href="%(route)s">%(route_t)s</a><small>%(cat)s · %(city)s</small></header>
<div class="sec"><div class="svs">%(serv)s</div>
<h2>%(about)s</h2><div class="two"><div class="card">%(about_t)s</div><div class="card"><b>%(why_t)s</b><ul>%(why)s</ul></div></div>
<h2>%(visit)s</h2><div class="two"><div class="card"><b>%(contact_t)s</b><br>%(phone)s<br>%(addr)s%(hours_block)s</div><a href="%(route)s">%(maps)s</a></div></div>
<footer>%(demo)s</footer></body></html>""" % dict(
        lang=r["lang"], c=color, ic=ic, name=esc(r["name"]), cat=esc(cat), city=esc(r["city"]), hero=esc(L["hero"].format(**f)),
        call=btn_call, wa=btn_wa, route=route, route_t=esc(L["route"]), about=esc(L["about"]), about_t=esc(L["about_t"].format(**f)),
        why_t=esc(L["why_title"]), why=why, serv=serv, visit=esc(L["visit"]), tel="tel:" + esc(phone), hours_t=esc(L["hours"]),
        hours_block=("<br><br><b>%s</b><br>%s" % (esc(L["hours"]), esc(r["hours"]))) if r["hours"] else "", contact_t=esc(L["contact"]), phone=esc(phone), addr=esc(r["address"]), maps=maps,
        demo=esc(L["demo"].format(**f)))

def build_demo(c, lid):
    r = c.execute("select * from leads where id=?", (lid,)).fetchone()
    slug = re.sub(r"[^a-z0-9]+", "-", norm(r["name"]) or "x")[:40] + "-" + lid.split("/")[1]
    d = os.path.join(DEMO, slug); os.makedirs(d, exist_ok=True)
    hp = os.path.join(d, "index.html"); open(hp, "w", encoding="utf-8").write(demo_html(r, c))
    png = os.path.join(d, "demo.png")
    subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--window-size=1280,1380",
                    "--virtual-time-budget=9000", "--screenshot=" + png, "file://" + hp], capture_output=True, timeout=90)
    if not os.path.exists(png):
        raise RuntimeError("PNG was not created (headless Chrome)")
    c.execute("update leads set demo=?, png=? where id=?", (hp, png, lid)); c.commit()
    build_pdf(c, lid)
    return png

def build_pdf(c, lid):
    """5-6 best parts of the demo in one PDF: sent instead of a single picture."""
    r = c.execute("select * from leads where id=?", (lid,)).fetchone(); L = T[r["lang"]]
    out = os.path.join(os.path.dirname(r["demo"]), re.sub(r"[^A-Za-z0-9]+", "-", r["name"]).strip("-")[:40] + "-website.pdf")
    lab = dict(title=r["name"], sub=L["pdf_sub"], hero=r["name"], services=L["services_title"], about=L["about"], visit=L["visit"],
               mobile=L["pdf_mobile"], full=L["pdf_full"])
    p = subprocess.run([sys.executable, os.path.join(HERE, "pdfmaker.py"), r["demo"], out, json.dumps(lab, ensure_ascii=False)],
                       capture_output=True, text=True, timeout=180)
    if p.returncode or not os.path.exists(out):
        raise RuntimeError("PDF was not created: " + (p.stderr or "")[-300:])
    c.execute("update leads set pdf=? where id=?", (out, lid)); c.commit()
    return out

def short_with(short, facts):
    """Put the personal facts right after the greeting ("Hello! <facts> I made …")."""
    if not facts: return short
    i = short.find("!") + 1
    return (short[:i] + " " + " ".join(facts) + short[i:]) if 0 < i < 30 else " ".join(facts) + " " + short

def draft(c, lid):
    r = c.execute("select * from leads where id=?", (lid,)).fetchone()
    L = T[r["lang"]]; price = setting(c, "price")
    f = dict(name=r["name"], sender=setting(c, "sender", "—"), contact=setting(c, "contact", ""),
             price=L["price"].format(price=price) if price else "")
    body = L["email"].format(**f)
    hooks, shorts = [], []
    if (r["reviews"] or 0) >= 10 and (r["rating"] or 0) >= 4.0:
        hooks.append(L["hook_reviews"].format(rating=("%.1f" % r["rating"]), reviews=r["reviews"])); shorts.append(L["short_reviews"].format(rating=("%.1f" % r["rating"]), reviews=r["reviews"]))
    plats = [p for p in (r["platforms"] or "").split(", ") if p and p not in ("Facebook", "Yelp", "Tripadvisor")]
    if plats:
        hooks.append(L["hook_platform"].format(platform=plats[0])); shorts.append(L["short_platform"].format(platform=plats[0]))
    elif r["instagram"]:
        hooks.append(L["hook_instagram"])
    serv = list(services_of(r, L))
    if r["category"] in ("barber", "beauty", "dentist", "vet", "gym"): serv.append(L["booking"])
    if r["category"] in ("restaurant", "cafe", "fast_food", "bakery"): serv.insert(0, L["menu"])
    hooks.append(L["hook_offer"].format(services=", ".join(x.lower() if i else x for i, x in enumerate(serv))))
    parts = body.split("\n\n")
    if shorts: parts[1] = "\n\n".join(hooks)          # facts about them replace the generic "I could not find your site"
    else: parts.insert(2, "\n\n".join(hooks))
    body = "\n\n".join(parts)
    if r["country"] in ("US", "CA") and setting(c, "postal"):   # CAN-SPAM / CASL: sender's postal address in commercial e-mail
        body += "\n" + setting(c, "postal")
    c.execute("update leads set msg_subject=?, msg_body=?, msg_short=?, status=case when status='new' then 'ready' else status end where id=?",
              (L["subject"].format(**f), body, dm_text(r, L, f["sender"], plats), lid)); c.commit()

def dm_text(r, L, sender, plats):
    """WhatsApp / Instagram message: their own fact (social proof), the free demo (reciprocity), the gain,
    a no-oriented question (easy to answer) and the opt-out."""
    if (r["reviews"] or 0) >= 10 and (r["rating"] or 0) >= 4.0:
        fact = L["dm_reviews"].format(rating="%.1f" % r["rating"], reviews=r["reviews"])
    elif plats: fact = L["dm_platform"].format(platform=plats[0])
    elif r["instagram"]: fact = L["dm_insta"]
    else: fact = L["dm_none"]
    gain = L["gain_platform"] if plats else L["gain_default"]
    return L["dm"].format(name=r["name"], fact=fact, gain=gain, sender=sender)

PLATFORMS = [("Fresha", "fresha."), ("Treatwell", "treatwell."), ("Booksy", "booksy."), ("Facebook", "facebook."),
             ("Tripadvisor", "tripadvisor."), ("Uber Eats", "ubereats."), ("Just Eat", "just-eat"), ("Deliveroo", "deliveroo."),
             ("Glovo", "glovoapp."), ("Yelp", "yelp."), ("Planity", "planity."), ("Vagaro", "vagaro."), ("StyleSeat", "styleseat.")]
CAT_VALUE = {"dentist": 25, "car_repair": 22, "beauty": 20, "barber": 18, "vet": 18, "gym": 16, "hotel": 16, "restaurant": 14,
             "florist": 12, "bakery": 10, "cafe": 10, "clothes": 10, "car_wash": 10, "pharmacy": 5, "fast_food": 6,
             "plumber": 24, "electrician": 22, "builder": 25}
RICH = {"US", "CA", "GB", "IE", "NL", "BE", "CH", "SE", "DK", "NO", "FI", "AU", "AE", "FR", "DE", "AT", "IT", "ES"}

def to_int(v):
    v = (v or "").strip().upper().replace(",", "").replace(" ", "")
    try: return int(float(v[:-1]) * 1000) if v.endswith("K") else int(float(v))
    except ValueError: return 0

def score_lead(r, rating, reviews, platforms):
    """0-100: how likely this business pays for a site. Busy (many reviews), well rated, already online
    (Instagram / booking platforms) but without its own site, reachable, higher-ticket category, richer country."""
    pts, why = 0, []
    if reviews >= 200: pts += 30; why.append("%d reviews" % reviews)
    elif reviews >= 50: pts += 22; why.append("%d reviews" % reviews)
    elif reviews >= 10: pts += 12; why.append("%d reviews" % reviews)
    if rating >= 4.5: pts += 10; why.append("%.1f★" % rating)
    elif rating >= 4.0: pts += 6
    elif 0 < rating < 3.5: pts -= 10; why.append("low rating")
    if r["instagram"]: pts += 10; why.append("active on Instagram")
    if any(p in ("Fresha", "Treatwell", "Booksy", "Planity", "Vagaro", "StyleSeat", "Uber Eats", "Just Eat", "Deliveroo", "Glovo") for p in platforms):
        pts += 12; why.append("depends on platform: " + ", ".join(p for p in platforms if p not in ("Facebook", "Yelp", "Tripadvisor"))[:40])
    elif platforms: pts += 5
    pts += CAT_VALUE.get(r["category"], 8)
    if r["country"] in RICH: pts += 8
    if r["email"]: pts += 4
    if re.sub(r"\D", "", r["phone"] or ""): pts += 3
    if r["hours"]: pts += 2
    return max(0, min(100, pts)), "; ".join(why)

def generic_name(name):
    return not [w for w in re.split(r"\s+", name) if len(norm(w)) >= 4 and norm(w) not in STOP]

def prepare(c, lid):
    """site check -> demo -> draft. Leads that already have a site are marked and skipped."""
    r = c.execute("select * from leads where id=?", (lid,)).fetchone()
    if r["site"] == "unchecked":
        LAST_INFO.clear()
        st, hits, ig = site_check(r["name"], r["city"], T[r["lang"]]["cat"].get(r["category"], ""), r["country"])
        try: rating = float(LAST_INFO.get("rating") or 0)
        except ValueError: rating = 0.0
        reviews = to_int(LAST_INFO.get("reviews"))
        plats = [nm for nm, k in PLATFORMS if any(k in u for u in LAST_INFO.get("urls", []))]
        if generic_name(r["name"]):   # "Nails Design": Google's rating may belong to another salon, never quote it
            rating, reviews, plats = 0.0, 0, []
        rr = dict(r); rr["instagram"] = r["instagram"] or ig
        sc, why = score_lead(rr, rating, reviews, plats)
        c.execute("update leads set rating=?, reviews=?, platforms=?, score=?, reasons=? where id=?", (rating or None, reviews or None, ", ".join(plats), sc, why, lid)); c.commit()
        c.execute("update leads set site=?, site_hits=?, instagram=coalesce(nullif(instagram,''),?) where id=?", (st, hits, ig, lid)); c.commit()
        if st == "has":
            c.execute("update leads set status='has site' where id=?", (lid,)); c.commit()
            return "has site"
        time.sleep(random.uniform(4, 8))   # slow pace keeps Google from showing a captcha
        r = c.execute("select * from leads where id=?", (lid,)).fetchone()
    if not (r["phone"] or r["email"] or r["instagram"] or r["whatsapp"]):
        c.execute("update leads set status='no contact' where id=?", (lid,)); c.commit()
        return "no contact"
    build_demo(c, lid); draft(c, lid)
    return "ready"

# ---------- sending (only on the operator's click) ----------
def smtp_password():
    """Optional SMTP app password, from the environment only (never stored in the DB or the repo)."""
    return os.environ.get("SMTP_PASSWORD", "")

def sent_today(c):
    return c.execute("select count(*) n from leads where sent_at like ? and notes like '%email%'", (time.strftime("%Y-%m-%d") + "%",)).fetchone()["n"]

def send_email(c, lid):
    r = c.execute("select * from leads where id=?", (lid,)).fetchone()
    if not r["email"]:
        raise RuntimeError("No e-mail address")
    if r["country"] == "GB" and FREEMAIL.search(r["email"]):
        raise RuntimeError("Law (UK PECR): no unsolicited marketing to a personal mailbox (sole trader) without consent, use WhatsApp")
    if r["country"] in EMAIL_BLOCKED:
        raise RuntimeError("Law: unsolicited marketing e-mail is prohibited in %s" % EMAIL_BLOCKED[r["country"]])
    if r["status"] in ("sent", "replied", "rejected"):
        raise RuntimeError("Already sent")
    if sent_today(c) >= DAILY_EMAIL_CAP:
        raise RuntimeError("Daily limit (%d) reached" % DAILY_EMAIL_CAP)
    user = setting(c, "gmail") or os.environ.get("SMTP_USER", ""); pw = smtp_password()
    if not user:
        raise RuntimeError("No sender address (set it in Settings or SMTP_USER)")
    if not pw:   # default: Gmail web in the Radar Chrome, no password needed
        import browser
        browser.run(browser.gmail_send, user, r["email"], r["msg_subject"], r["msg_body"], next((x for x in (r["pdf"], r["png"]) if x and os.path.exists(x)), None))
        c.execute("update leads set status='sent', sent_at=?, notes=coalesce(notes,'')||' email' where id=?",
                  (time.strftime("%Y-%m-%d %H:%M"), lid)); c.commit()
        log(c, "email(web) → %s" % r["name"]); record_send(c, lid, "email", 0); return
    m = EmailMessage(); m["From"] = "%s <%s>" % (setting(c, "sender", user), user); m["To"] = r["email"]
    m["Subject"] = r["msg_subject"]; m["Message-ID"] = make_msgid(); m.set_content(r["msg_body"])
    if r["pdf"] and os.path.exists(r["pdf"]):
        m.add_attachment(open(r["pdf"], "rb").read(), maintype="application", subtype="pdf", filename=os.path.basename(r["pdf"]))
    elif r["png"] and os.path.exists(r["png"]):
        m.add_attachment(open(r["png"], "rb").read(), maintype="image", subtype="png", filename="demo.png")
    with smtplib.SMTP_SSL(os.environ.get("SMTP_HOST", "smtp.gmail.com"), int(os.environ.get("SMTP_PORT", "465")), context=ssl.create_default_context(), timeout=60) as s:
        s.login(user, pw); s.send_message(m)
    c.execute("update leads set status='sent', sent_at=?, notes=coalesce(notes,'')||' email' where id=?",
              (time.strftime("%Y-%m-%d %H:%M"), lid)); c.commit()
    log(c, "email → %s" % r["name"]); record_send(c, lid, "email", 0)

def mark(c, lid, status, channel=""):
    if status in ("replied", "interested", "meeting", "won", "rejected"):   # any answer stops the follow-ups
        c.execute("update leads set replied_at=coalesce(replied_at,?), next_fu=null where id=?", (time.strftime("%Y-%m-%d %H:%M"), lid))
    c.execute("update leads set status=?, sent_at=coalesce(sent_at,?), notes=coalesce(notes,'')||? where id=?",
              (status, time.strftime("%Y-%m-%d %H:%M") if status == "sent" else None, (" " + channel) if channel else "", lid)); c.commit()

DM_CAP = {"instagram": 40, "whatsapp": 40}   # shortcut: fixed daily caps against bans; raise slowly if no warnings

def dm_today(c, ch):
    return c.execute("select count(*) n from log where ts like ? and what like ?", (time.strftime("%Y-%m-%d") + "%", ch + " →%")).fetchone()["n"]

TZ = {"GB": "Europe/London", "IE": "Europe/Dublin", "PT": "Europe/Lisbon", "FR": "Europe/Paris", "ES": "Europe/Madrid", "IT": "Europe/Rome",
      "NL": "Europe/Amsterdam", "BE": "Europe/Brussels", "PL": "Europe/Warsaw", "TR": "Europe/Istanbul"}

def local_hour(r):
    """Business's local hour: zoneinfo for one-zone countries, longitude for wide ones (US, CA, ...)."""
    from datetime import datetime, timezone, timedelta
    from zoneinfo import ZoneInfo
    if r["country"] in TZ: return datetime.now(ZoneInfo(TZ[r["country"]])).hour
    off = round((r["lon"] or 0) / 15) + (1 if r["country"] in ("SE", "DK", "NO", "CH", "DE", "AT", "CZ", "HU") else 0)
    return (datetime.now(timezone.utc) + timedelta(hours=off)).hour

def in_window(r):
    return 9 <= local_hour(r) < 19   # nobody likes a sales message at night

def send_dm(c, lid, ch, cap=None):
    import browser
    r = c.execute("select * from leads where id=?", (lid,)).fetchone()
    if r["status"] in ("sent", "replied", "rejected"): raise RuntimeError("Already sent")
    if r["country"] in EMAIL_BLOCKED: raise RuntimeError("Law: unsolicited marketing messages are prohibited in %s" % EMAIL_BLOCKED[r["country"]])
    if r["country"] in SKIP_COUNTRIES: raise RuntimeError("This country is excluded (SKIP_COUNTRIES)")
    img = r["png"] if r["png"] and os.path.exists(r["png"]) else None
    pdf = r["pdf"] if r["pdf"] and os.path.exists(r["pdf"]) else None
    pd = os.path.join(os.path.dirname(pdf), "pages") if pdf else ""
    album = [os.path.join(pd, f) for f in sorted(os.listdir(pd))] if pd and os.path.isdir(pd) else []
    if dm_today(c, ch) >= (cap or DM_CAP[ch]): raise RuntimeError("%s daily limit (%d) reached" % (ch, cap or DM_CAP[ch]))
    if ch == "instagram":
        if not r["instagram"]: raise RuntimeError("No Instagram profile")
        browser.run(browser.ig_dm, r["instagram"], r["msg_short"], album or img)
    else:
        digits = re.sub(r"\D", "", r["whatsapp"] or r["phone"] or "")
        if len(digits) < 8: raise RuntimeError("No phone number")
        browser.run(browser.wa_send, digits, r["msg_short"], pdf or img)
    mark(c, lid, "sent", ch); log(c, "%s → %s" % (ch, r["name"])); record_send(c, lid, ch, 0)

# ---------- follow-up (sequence) and replies ----------
FU_GAP = {0: 3, 1: 4}   # day 3 after the first message, day 7 after it; then stop (3 touches, no more)
PIPE = ("new", "ready", "sent", "replied", "interested", "meeting", "won", "rejected")

def record_send(c, lid, ch, step):
    """Every touch is kept; the next follow-up date is set (none after the last step)."""
    from datetime import date, timedelta
    nxt = (date.today() + timedelta(days=FU_GAP[step])).isoformat() if step in FU_GAP else None
    c.execute("insert into touches values(?,?,?,?,?)", (lid, time.strftime("%Y-%m-%d %H:%M"), ch, step, "send"))
    c.execute("update leads set last_ch=?, fu_step=?, next_fu=? where id=?", (ch, step, nxt, lid)); c.commit()

def fu_text(r, step, sender):
    L = T[r["lang"]]
    return L["fu%d" % step].format(name=r["name"], sender=sender)

def followups_due(c):
    rows = c.execute("select * from leads where status='sent' and replied_at is null and next_fu is not null "
                     "and next_fu<=? and coalesce(fu_step,0)<2 order by coalesce(score,0) desc", (time.strftime("%Y-%m-%d"),)).fetchall()
    return [r for r in rows if r["country"] not in SKIP_COUNTRIES]

def send_followup(c, lid, cap=None):
    """Short reminder on the same channel as the first message (no attachment). Only on the operator's click / run."""
    import browser
    r = c.execute("select * from leads where id=?", (lid,)).fetchone()
    if r["status"] != "sent" or r["replied_at"]: raise RuntimeError("A reply arrived or the status changed: no follow-up")
    step = (r["fu_step"] or 0) + 1
    if step > 2: raise RuntimeError("Follow-up sequence finished")
    ch = r["last_ch"] or "whatsapp"; text = fu_text(r, step, setting(c, "sender", "—"))
    if ch == "email":
        if sent_today(c) >= DAILY_EMAIL_CAP: raise RuntimeError("email daily limit reached")
        browser.run(browser.gmail_send, setting(c, "gmail"), r["email"], "Re: " + (r["msg_subject"] or r["name"]), text, None)
    else:
        if dm_today(c, ch) >= (cap or DM_CAP[ch]): raise RuntimeError("%s daily limit reached" % ch)
        if ch == "instagram": browser.run(browser.ig_dm, r["instagram"], text, None)
        else: browser.run(browser.wa_send, re.sub(r"\D", "", r["whatsapp"] or r["phone"] or ""), text, None)
    log(c, "%s → %s (follow-up %d)" % ("email(web)" if ch == "email" else ch, r["name"], step)); record_send(c, lid, ch, step)

def job_followup(limit=40, cap=None):
    c = db(); JOB.update(run=True, stop=False); ok = bad = later = 0
    try:
        rows = followups_due(c)
        log(c, "▶ follow-up: %d businesses queued" % len(rows))
        for i, r in enumerate(rows, 1):
            if JOB["stop"] or ok >= limit: break
            if not in_window(r): later += 1; continue
            JOB["text"] = "follow-up %d/%d: %s" % (i, len(rows), r["name"])
            try:
                send_followup(c, r["id"], cap); ok += 1
                log(c, "✓ follow-up %d sent: %s · %s" % ((r["fu_step"] or 0) + 1, r["name"], r["last_ch"]))
            except Exception as ex:
                bad += 1; log(c, "✗ follow-up failed: %s: %s" % (r["name"], str(ex)[:140]))
            if i < len(rows):
                w = random.uniform(90, 240)
                for _ in range(int(w)):
                    if JOB["stop"]: break
                    time.sleep(1)
        JOB["text"] = "follow-up: sent %d, failed %d, outside business hours %d" % (ok, bad, later); log(c, "■ " + JOB["text"])
    finally:
        JOB["run"] = False

def digits_tail(s, n=9):
    d = re.sub(r"\D", "", s or ""); return d[-n:] if len(d) >= 8 else ""

def check_replies(c):
    """Who answered? WhatsApp chat titles / Instagram threads / Gmail inbox are matched ONLY against sent leads;
    nothing else is read or stored. A reply stops the follow-ups at once."""
    import browser
    sent = c.execute("select * from leads where status='sent' and replied_at is null").fetchall()
    if not sent: return []
    found = []
    wa = {digits_tail(r["whatsapp"] or r["phone"]): r for r in sent if r["last_ch"] == "whatsapp" and digits_tail(r["whatsapp"] or r["phone"])}
    ig = {(r["instagram"] or "").lower(): r for r in sent if r["last_ch"] == "instagram" and r["instagram"]}
    em = {(r["email"] or "").lower(): r for r in sent if r["last_ch"] == "email" and r["email"]}
    if wa:
        for row in browser.run(browser.wa_chatlist, timeout=150):
            k = digits_tail(row.get("t", ""))
            if k in wa and not row.get("own"): found.append((wa[k], "whatsapp"))
            elif k in wa and row.get("seen") and "read" not in (wa[k]["notes"] or ""):   # blue ticks: they read it
                c.execute("update leads set notes=coalesce(notes,'')||' [WA read]' where id=?", (wa[k]["id"],)); c.commit()
    if ig:
        for row in browser.run(browser.ig_inbox, timeout=200):
            first = (row.get("text") or "").split("\n")[0].lower().strip()
            for h, r in ig.items():
                n = (r["name"] or "").lower().strip()
                if len(first) >= 4 and (first == h or (len(n) >= 4 and (first.startswith(n[:14]) or n.startswith(first[:14])))) and not row.get("own"):
                    found.append((r, "instagram"))
    if em:
        got = {e.lower() for e in browser.run(browser.gmail_inbox_from, list(em), timeout=150)}
        found += [(em[e], "email") for e in got if e in em]
    seen = set()
    for r, ch in found:
        if r["id"] in seen: continue
        seen.add(r["id"])
        c.execute("update leads set status='replied', replied_at=? where id=? and status='sent'", (time.strftime("%Y-%m-%d %H:%M"), r["id"]))
        c.execute("insert into touches values(?,?,?,?,?)", (r["id"], time.strftime("%Y-%m-%d %H:%M"), ch, None, "reply"))
        c.commit(); log(c, "💬 reply received: %s (%s)" % (r["name"], ch)); wadd("warn", "💬 Reply received: %s (%s)" % (r["name"], ch), notify=True)
    return [r["name"] for r, _ in found]

def backfill_touches(c):
    """Sends made before the touches table existed: rebuilt from the log, follow-up dates from sent_at."""
    if c.execute("select count(*) from touches").fetchone()[0]: return
    from datetime import datetime, timedelta
    for r in c.execute("select * from leads where sent_at is not null").fetchall():
        m = c.execute("select ts, what from log where what like ? order by rowid limit 1", ("% → " + r["name"] + "%",)).fetchone()
        ch = "email" if m and m["what"].startswith("email") else (m["what"].split(" →")[0] if m else "whatsapp")
        ts = m["ts"][:16] if m else r["sent_at"]
        c.execute("insert into touches values(?,?,?,?,?)", (r["id"], ts, ch, 0, "send"))
        nxt = (datetime.strptime(r["sent_at"][:10], "%Y-%m-%d") + timedelta(days=3)).date().isoformat() if r["status"] == "sent" else None
        c.execute("update leads set last_ch=coalesce(last_ch,?), fu_step=coalesce(fu_step,0), next_fu=coalesce(next_fu,?) where id=?", (ch, nxt, r["id"]))
    c.commit()

def analytics(c):
    q = lambda sql, *a: [dict(x) for x in c.execute(sql, a)]
    replied = "('replied','interested','meeting','won')"
    st = {r["status"]: r["n"] for r in q("select status, count(*) n from leads group by status")}
    sent = c.execute("select count(*) from leads where sent_at is not null").fetchone()[0]   # "rejected" without a send is not a send
    funnel = [("Found", sum(st.values())), ("Prepared", sent + st.get("ready", 0)), ("Sent", sent),
              ("Replied", sum(st.get(k, 0) for k in ("replied", "interested", "meeting", "won"))),
              ("Interested", sum(st.get(k, 0) for k in ("interested", "meeting", "won"))), ("Won", st.get("won", 0))]
    grp = lambda col: q("select %s k, count(*) sent, sum(status in %s) rep from leads where sent_at is not null group by %s order by sent desc" % (col, replied, col))
    daily = q("select substr(ts,1,10) d, count(*) n from touches where kind='send' group by d order by d desc limit 14")
    return {"funnel": funnel, "by_channel": grp("coalesce(last_ch,'?')"), "by_country": grp("country"), "by_category": grp("category"),
            "daily": list(reversed(daily)), "due": len(followups_due(c)), "status": st}

# ---------- background jobs ----------
JOB = {"run": False, "text": "idle", "stop": False}

def job_prepare(ids):
    c = db(); JOB.update(run=True, stop=False)
    try:
        for i, lid in enumerate(ids, 1):
            if JOB["stop"]: break
            JOB["text"] = "preparing %d/%d" % (i, len(ids))
            try: prepare(c, lid)
            except Exception as ex: c.execute("update leads set notes=coalesce(notes,'')||? where id=?", (" ERROR: %s" % ex, lid)); c.commit()
        JOB["text"] = "done: %d" % len(ids)
    finally:
        JOB["run"] = False

def job_auto(iso, cats, ncities, target, per=15):
    """The "robot": walks the biggest cities of one country, finds businesses, checks each for a website,
    builds demo + message for those without one, until `target` leads are ready. Sends nothing."""
    c = db(); JOB.update(run=True, stop=False); ready = 0
    try:
        for cy in cities(c, iso)[:ncities]:
            for cat in cats:
                if JOB["stop"] or ready >= target: break
                JOB["text"] = "radar: searching %s / %s (ready %d/%d)" % (cy["name"], CATEGORIES[cat][0], ready, target)
                try: find_leads(c, iso, cy["name"], cat, 8, per)
                except Exception as ex: log(c, "search error %s/%s: %s" % (cy["name"], cat, ex)); continue
                for r in c.execute("select id from leads where country=? and city=? and category=? and status='new' and site='unchecked'",
                                   (iso, cy["name"], cat)).fetchall():
                    if JOB["stop"] or ready >= target: break
                    JOB["text"] = "radar: checking %s / %s (ready %d/%d)" % (cy["name"], CATEGORIES[cat][0], ready, target)
                    log(c, "🔎 checking: %s (%s)" % (c.execute("select name from leads where id=?", (r["id"],)).fetchone()[0], cy["name"]))
                    try:
                        if prepare(c, r["id"]) == "ready": ready += 1
                    except Exception as ex:
                        c.execute("update leads set notes=coalesce(notes,'')||? where id=?", (" ERROR: %s" % ex, r["id"])); c.commit()
                        if "captcha" in str(ex): JOB["text"] = "stopped: Google captcha, confirm it in the Radar Chrome"; return
            if JOB["stop"] or ready >= target: break
        JOB["text"] = "radar finished: %d leads ready" % ready
    finally:
        JOB["run"] = False

def job_send(ids):
    c = db(); JOB.update(run=True, stop=False); ok = bad = 0
    try:
        for i, lid in enumerate(ids, 1):
            if JOB["stop"]: break
            JOB["text"] = "sending %d/%d" % (i, len(ids))
            try: send_email(c, lid); ok += 1
            except Exception as ex:
                bad += 1; c.execute("update leads set notes=coalesce(notes,'')||? where id=?", (" ERROR: %s" % ex, lid)); c.commit()
                if "limit" in str(ex): break
            if i < len(ids): time.sleep(random.uniform(60, 150))   # human pace, protects the Gmail account
        JOB["text"] = "sent %d, errors %d" % (ok, bad)
    finally:
        JOB["run"] = False

def channels(r):
    """Best channel first: WhatsApp (read most), then Instagram, then e-mail where the law allows."""
    out = []
    if len(re.sub(r"\D", "", r["whatsapp"] or r["phone"] or "")) >= 8: out.append("whatsapp")
    if r["instagram"]: out.append("instagram")
    if r["email"] and r["country"] not in EMAIL_BLOCKED and not (r["country"] == "GB" and FREEMAIL.search(r["email"])): out.append("email")
    return out

def job_outreach(ids, limit=40, cap=None):   # cap: one-off daily limit for this run only
    """Send to the chosen leads, best score first, one channel each (fallback when a channel fails),
    only in the business's 9:00-19:00, 2-5 minutes apart. Daily caps per channel."""
    c = db(); JOB.update(run=True, stop=False); ok = bad = later = 0
    try:
        q = "select * from leads where id in (%s) and status='ready' order by score desc" % ",".join("?" * len(ids))
        rows = c.execute(q, ids).fetchall()
        for i, r in enumerate(rows, 1):
            if JOB["stop"] or ok >= limit: break
            if not in_window(r):
                later += 1; log(c, "⏸ %s (%s): local time %d:00, outside business hours, postponed" % (r["name"], r["country"], local_hour(r))); continue
            JOB["text"] = "sending %d/%d: %s" % (i, len(rows), r["name"])
            log(c, "▶ %d/%d %s · %s, %s · score %s · channels: %s" % (i, len(rows), r["name"], r["city"], r["country"], r["score"], ", ".join(channels(r)) or "none"))
            sent, errs = False, []
            for ch in channels(r):
                if (sent_today(c) if ch == "email" else dm_today(c, ch)) >= (cap or (DAILY_EMAIL_CAP if ch == "email" else DM_CAP[ch])): errs.append(ch + " limit"); continue
                try:
                    send_email(c, r["id"]) if ch == "email" else send_dm(c, r["id"], ch, cap); sent = True; break
                except Exception as ex:
                    errs.append("%s: %s" % (ch, str(ex)[:120])); log(c, "✗ %s failed: %s" % (ch, str(ex)[:140]))
                    if "QR" in str(ex) or "not logged in" in str(ex) or "captcha" in str(ex): JOB["text"] = "stopped: " + str(ex); return
            if sent: ok += 1; log(c, "✓ sent: %s · %s" % (r["name"], {"whatsapp": "WhatsApp, with PDF", "instagram": "Instagram, 5-picture album", "email": "e-mail, with PDF"}[ch]))
            else:
                bad += 1; c.execute("update leads set notes=coalesce(notes,'')||? where id=?", (" ERROR: " + "; ".join(errs), r["id"])); c.commit()
            if sent and i < len(rows):
                w = random.uniform(120, 300); log(c, "... pause %d min %d s before the next message" % (w // 60, w % 60))
                for _ in range(int(w)):
                    if JOB["stop"]: break
                    time.sleep(1)
        JOB["text"] = "sent %d, failed %d, outside business hours (later) %d" % (ok, bad, later); log(c, "■ " + JOB["text"])
    finally:
        JOB["run"] = False

# ---------- watcher ----------
WATCH = []   # newest last: {i, t, level: info|warn|bad, msg}
_wseen = {}

def wadd(level, msg, key=None, every=900, notify=False):
    """One alert; the same key is not repeated within `every` seconds. Serious ones also pop a macOS notice."""
    if key and time.time() - _wseen.get(key, 0) < every: return
    if key: _wseen[key] = time.time()
    WATCH.append({"i": (WATCH[-1]["i"] + 1) if WATCH else 1, "t": time.strftime("%H:%M:%S"), "level": level, "msg": msg}); del WATCH[:-200]
    if level == "bad" or notify:
        subprocess.run(["osascript", "-e", 'display notification %s with title "Lead Radar - Watcher"' % json.dumps(msg)], capture_output=True)

BLOCK = re.compile(r"action blocked|try again later|we restrict certain activity|temporarily blocked|spam|banned|captcha", re.I)

def watcher():
    """Every 20 s: stuck job (log silent), failures in a row, blocks/bans, Radar Chrome gone, near the daily caps."""
    c = db(); last_rid = c.execute("select max(rowid) from log").fetchone()[0] or 0; fails = 0
    wadd("info", "Watcher started: checks every 20 seconds")
    while True:
        time.sleep(20)
        try:
            rows = c.execute("select rowid, ts, what from log where rowid>? order by rowid", (last_rid,)).fetchall()
            for r in rows:
                w = r["what"]; last_rid = r["rowid"]
                if w.startswith("✗"):
                    fails += 1
                    if BLOCK.search(w):
                        wadd("bad", "Block signal: " + w[2:160] + ". Sending stopped, check the account."); JOB["stop"] = True
                elif w.startswith("✓"): fails = 0
                elif w.startswith("■"): wadd("info", "Job finished: " + w[2:])
            if fails >= 5:
                wadd("warn", "%d sends failed in a row: the numbers may be landlines, or the account is restricted" % fails, "fails", 600)
            if JOB["run"]:
                lt = c.execute("select max(ts) from log").fetchone()[0] or ""
                silent = time.time() - time.mktime(time.strptime(lt, "%Y-%m-%d %H:%M:%S")) if lt else 0
                if silent > 720:
                    wadd("bad", "Job silent for %d minutes: restarting the Radar Chrome" % (silent // 60), "stuck2", 600)
                    import browser; browser.reset()
                elif silent > 480: wadd("warn", "Job silent for %d minutes (may be stuck)" % (silent // 60), "stuck", 600)
                if not subprocess.run(["pgrep", "-f", "user-data-dir=" + os.path.join(DATA, "chrome-profile")], capture_output=True).stdout:
                    wadd("warn", "Radar Chrome is closed: it will reopen on the next step", "nochrome", 600)
            if not JOB["run"] and 8 <= time.localtime().tm_hour < 24 and time.time() - _wseen.get("_replies", 0) > 1800:
                _wseen["_replies"] = time.time()
                try: check_replies(c)
                except Exception as ex: wadd("warn", "Reply check failed: %s" % str(ex)[:100], "repl", 3600)
            for ch in ("whatsapp", "instagram"):
                n = dm_today(c, ch)
                if n >= DM_CAP[ch] - 5: wadd("info", "%s: %d messages today, close to the limit" % (ch, n), "cap" + ch, 3600)
        except Exception as ex:
            wadd("warn", "Watcher error: %s" % str(ex)[:120], "werr", 600)

# ---------- web ----------
class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def out(self, code, body, ctype="application/json; charset=utf-8"):
        b = body if isinstance(body, bytes) else (json.dumps(body, ensure_ascii=False) if not isinstance(body, str) else body).encode()
        self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        u = urllib.parse.urlparse(self.path); q = dict(urllib.parse.parse_qsl(u.query)); c = db()
        try:
            if u.path == "/":
                return self.out(200, open(os.path.join(HERE, "ui.html"), encoding="utf-8").read(), "text/html; charset=utf-8")
            if u.path == "/api/meta":
                return self.out(200, {"countries": {k: v[0] for k, v in COUNTRIES.items()}, "categories": {k: v[0] for k, v in CATEGORIES.items()},
                                      "settings": {k: setting(c, k) for k in ("sender", "contact", "price", "gmail", "postal")},
                                      "has_pw": bool(smtp_password()), "job": JOB, "sent_today": sent_today(c), "cap": DAILY_EMAIL_CAP})
            if u.path == "/api/watch":
                return self.out(200, WATCH[-int(q.get("n") or 80):])
            if u.path == "/api/log":
                rows = c.execute("select rowid id, ts, what from log where rowid>? order by rowid desc limit 200", (int(q.get("after") or 0),)).fetchall()
                return self.out(200, [dict(x) for x in reversed(rows)])
            if u.path == "/api/cities":
                return self.out(200, cities(c, q["c"]))
            if u.path == "/api/leads":
                w, a = ["1=1"], []
                for k in ("country", "city", "category", "status"):
                    if q.get(k): w.append("%s=?" % k); a.append(q[k])
                if q.get("status") == "follow-up":   # sent 3+ days ago, no answer yet
                    w = [x for x in w if not x.startswith("status")]; a = [x for x in a if x != "follow-up"]
                    w.append("status='sent' and sent_at <= ?"); a.append(time.strftime("%Y-%m-%d", time.localtime(time.time() - 3 * 86400)) + " 99")
                rows = c.execute("select * from leads where %s order by case status when 'replied' then 0 when 'interested' then 1 when 'meeting' then 2 "
                                 "when 'ready' then 3 when 'sent' then 4 when 'new' then 5 else 6 end, coalesce(score,0) desc, created desc limit 1000" % " and ".join(w), a).fetchall()
                return self.out(200, [dict(r) for r in rows])
            if u.path == "/api/analytics":
                return self.out(200, analytics(c))
            if u.path == "/api/followups":
                return self.out(200, [dict(id=r["id"], name=r["name"], country=r["country"], ch=r["last_ch"], step=(r["fu_step"] or 0) + 1,
                                           text=fu_text(r, (r["fu_step"] or 0) + 1, setting(c, "sender", "—"))) for r in followups_due(c)])
            if u.path == "/api/touches":
                return self.out(200, [dict(x) for x in c.execute("select * from touches where lead_id=? order by ts", (q.get("id", ""),))])
            if u.path == "/api/stats":
                return self.out(200, [dict(r) for r in c.execute("select status, count(*) n from leads group by status")])
            if u.path == "/demo":
                r = c.execute("select demo,png from leads where id=?", (q["id"],)).fetchone()
                p = r["png"] if q.get("png") else r["demo"]
                return self.out(200, open(p, "rb").read(), "image/png" if q.get("png") else "text/html; charset=utf-8")
            self.out(404, {"err": "not found"})
        except Exception as ex:
            self.out(500, {"err": str(ex)})
    def do_POST(self):
        c = db(); n = int(self.headers.get("Content-Length", 0)); b = json.loads(self.rfile.read(n) or b"{}")
        try:
            p = self.path
            if p == "/api/search":
                return self.out(200, {"new": find_leads(c, b["country"], b["city"], b["category"], int(b.get("radius", 8)), int(b.get("limit", 40)), bool(b.get("all")))})
            if p == "/api/prepare":
                if JOB["run"]: raise RuntimeError("Another job is running: " + JOB["text"])
                threading.Thread(target=job_prepare, args=(b["ids"],), daemon=True).start(); return self.out(200, {"ok": True})
            if p == "/api/outreach":
                if JOB["run"]: raise RuntimeError("Another job is running: " + JOB["text"])
                threading.Thread(target=job_outreach, args=(b["ids"], int(b.get("limit", 40)), int(b["cap"]) if b.get("cap") else None), daemon=True).start(); return self.out(200, {"ok": True})
            if p == "/api/followup":
                if JOB["run"]: raise RuntimeError("Another job is running: " + JOB["text"])
                threading.Thread(target=job_followup, args=(int(b.get("limit", 40)),), daemon=True).start(); return self.out(200, {"ok": True})
            if p == "/api/check_replies":
                if JOB["run"]: raise RuntimeError("Another job is running: " + JOB["text"])
                return self.out(200, {"found": check_replies(c)})
            if p == "/api/send":
                if JOB["run"]: raise RuntimeError("Another job is running: " + JOB["text"])
                threading.Thread(target=job_send, args=(b["ids"],), daemon=True).start(); return self.out(200, {"ok": True})
            if p == "/api/auto":
                if JOB["run"]: raise RuntimeError("Another job is running: " + JOB["text"])
                cats = [k for k in b["cats"] if k in CATEGORIES] or ["restaurant"]
                threading.Thread(target=job_auto, args=(b["country"], cats, int(b.get("ncities", 5)), int(b.get("target", 30))), daemon=True).start()
                return self.out(200, {"ok": True})
            if p == "/api/stop":
                JOB["stop"] = True; return self.out(200, {"ok": True})
            if p == "/api/mark":
                mark(c, b["id"], b["status"], b.get("channel", "")); return self.out(200, {"ok": True})
            if p == "/api/save_msg":
                c.execute("update leads set msg_subject=?, msg_body=?, msg_short=?, email=? where id=?",
                          (b["subject"], b["body"], b["short"], b.get("email", ""), b["id"])); c.commit(); return self.out(200, {"ok": True})
            if p == "/api/settings":
                for k in ("sender", "contact", "price", "gmail", "postal"):
                    if k in b: c.execute("insert or replace into settings values(?,?)", (k, b[k].strip()))
                c.commit()
                return self.out(200, {"ok": True})
            if p == "/api/copyimg":   # demo PNG to clipboard, to paste into WhatsApp Web / Instagram DM
                r = c.execute("select png from leads where id=?", (b["id"],)).fetchone()
                if not (r and r["png"] and os.path.exists(r["png"])): raise RuntimeError("No demo picture")
                subprocess.run(["osascript", "-e", 'set the clipboard to (read (POSIX file "%s") as «class PNGf»)' % r["png"]], check=True, capture_output=True)
                return self.out(200, {"ok": True})
            if p == "/api/accounts":
                import browser; browser.run(browser.open_accounts); return self.out(200, {"ok": True})
            if p == "/api/acct_status":
                import browser; return self.out(200, browser.run(browser.status, timeout=120))
            if p == "/api/test_google":   # diagnostic: what the Radar Chrome sees for one query
                import browser
                def t(q):
                    pg = browser._ctx(); err = ""
                    try: j = browser.google(q)
                    except Exception as ex: j, err = {}, str(ex)
                    pg.screenshot(path=os.path.join(DATA, "google_test.png"))
                    dbg = pg.evaluate("() => ({h3: document.querySelectorAll('h3').length, ah3: document.querySelectorAll('a:has(h3)').length, sample: [...document.querySelectorAll('h3')].slice(0,3).map(h => (h.closest('a')||{}).href || 'no-a')})")
                    return {"res": j, "err": err, "url": pg.url, "title": pg.title(), "dbg": dbg}
                return self.out(200, browser.run(t, b.get("q", "test"), timeout=120))
            if p == "/api/test_gmail_sent":
                import browser; return self.out(200, browser.run(browser.gmail_sent_top, 3, timeout=120))
            if p == "/api/dm":
                send_dm(c, b["id"], b["channel"]); return self.out(200, {"ok": True})
            if p == "/api/open":   # opens WhatsApp / Instagram in the normal Chrome (logins stay there)
                subprocess.run(["open", "-a", "Google Chrome", b["url"]]); return self.out(200, {"ok": True})
            self.out(404, {"err": "not found"})
        except Exception as ex:
            self.out(500, {"err": str(ex)})

def selftest():
    global DB, DEMO
    import tempfile
    t = tempfile.mkdtemp(); DB = os.path.join(t, "t.db"); DEMO = os.path.join(t, "demo")
    c = db()
    assert insta_handle("https://www.instagram.com/abc.def/") == "abc.def" and insta_handle("@x_y") == "x_y"
    assert generic_name("Nails Design") and generic_name("Q & L") and not generic_name("Sample Beauty Center")
    assert norm("Chamberí Peluquería Café Façade São Straße Ñúñez Brûlé") == "chamberipeluqueriacafefacadesaostrassenunezbrule"
    w = lambda n: [norm(x) for x in n.split() if len(norm(x)) >= 4 and norm(x) not in STOP]
    A = lambda n: [norm(x) for x in re.split(r"[\s&'’.,-]+", n) if norm(x)]
    assert not own_domain("mrbarbers", "barbersdesign", w("Barber’s Design"), "London", A("Barber’s Design"))
    assert own_domain("acmehairandbeauty", "acmehairbeauty", w("Acme Hair & Beauty"), "London", A("Acme Hair & Beauty"))
    assert own_domain("acmesalon", "acmehairbeauty", w("Acme Hair & Beauty"), "London", A("Acme Hair & Beauty"))
    assert own_domain("samplenails", "samplesnailspa", w("Sample's Nail Spa"), "London", A("Sample's Nail Spa"))
    assert not weak_match("example-salon.example", A("Face and Body Treatments"))
    assert SOCIAL_OR_DIRECTORY.search("https://example-barbers.wheree.com/") and SOCIAL_OR_DIRECTORY.search("https://booksy.com/x")
    assert own_domain("lagranexample", "lagranexample", w("La Gran Example"), "Madrid")
    assert own_domain("exampleroommadrid", "exampleroom", w("Exampleroom"), "Madrid")
    assert not own_domain("zoneonelyceum", "zoneone", w("Zone One"), "Madrid")
    assert own_domain("luma", "luma", [], "Madrid")
    assert own_domain("barberiaexamplest5", "examplest5", w("Example St 5"), "Madrid", A("Example St 5"))
    c.execute("insert into leads(id,country,city,category,name,phone,lat,lon,lang,address,hours,email) values('node/1','GB','London','barber','Test Barber','+44 20 0000 0000',51.5,-0.12,'en','1 Example St','Mo-Sa 09:00-20:00','a@example.com')")
    c.execute("update leads set site='none' where id='node/1'"); c.commit()
    h = demo_html(c.execute("select * from leads").fetchone(), c)
    assert "Test Barber" in h and "wa.me/442000000000" in h and "tel:+44 20 0000 0000" in h
    for k in ("sender", "contact"): c.execute("insert or replace into settings values(?,?)", (k, "Test"))
    c.execute("insert or replace into settings values('price','150 USD')"); c.commit()
    draft(c, "node/1"); r = c.execute("select * from leads").fetchone()
    assert "Test Barber" in r["msg_subject"] and "for 150 USD" in r["msg_body"] and r["status"] == "ready"
    assert set(v[1] for v in COUNTRIES.values()) <= set(T), "language pack missing"
    for lang in T:  # every language has every category and every key formats
        assert set(T[lang]["cat"]) == set(CATEGORIES) and set(T[lang]["services"]) == set(CATEGORIES), lang
        assert len(T[lang]["why"]) == 3 and T[lang]["why_title"] and T[lang]["visit"], lang
        for k in ("hero", "about_t", "demo", "subject"): T[lang][k].format(name="n", city="c", cat="k")
        T[lang]["email"].format(name="n", sender="s", contact="c", price=""); T[lang]["short"].format(name="n", sender="s")
    c.execute("update leads set rating=4.7, reviews=189, platforms='Fresha, Facebook', instagram='acme.cuts', status='new' where id='node/1'"); c.commit()
    draft(c, "node/1"); r = c.execute("select * from leads").fetchone()
    assert r["msg_short"].startswith("Hi Test Barber") and "4.7★" in r["msg_short"] and "won't write again" in r["msg_short"], r["msg_short"]
    assert lang_for("CA", "Montréal") == "fr" and lang_for("CA", "Toronto") == "en" and lang_for("BE", "Gent") == "nl" and lang_for("CH", "Genève") == "fr"
    k = lambda n, cat: kind({"name": n, "category": cat})
    assert k("Acme Coiffure", "barber") == "hair" and k("Acme Barber Shop", "barber") == "barber" and k("Barbearía Example", "barber") == "barber"
    assert k("Acme Nails", "beauty") == "nails" and k("Sample Beauty Center", "beauty") == "beauty"
    for lg in set(v[1] for v in COUNTRIES.values()):
        assert set(T[lg]["cat_x"]) == {"hair", "nails"} and all(len(v) == 3 for v in T[lg]["services_x"].values()), lg
        for k in ("dm", "dm_reviews", "dm_platform", "dm_insta", "dm_none", "gain_platform", "gain_default"): assert k in T[lg], (lg, k)
    fake = {"whatsapp": "", "phone": "+44 7700 900123", "instagram": "x", "email": "a@hotmail.example", "country": "GB", "lon": -1.9}
    assert channels(fake) == ["whatsapp", "instagram"], channels(fake)   # UK free-mail never by e-mail (PECR)
    assert channels(dict(fake, country="DE", phone="", instagram="")) == [] and 0 <= local_hour(fake) < 24
    assert "4.7★" in r["msg_body"] and "189" in r["msg_body"] and "Fresha" in r["msg_body"] and "4.7★" in r["msg_short"], r["msg_body"]
    sc, why = score_lead(r, 4.7, 189, ["Fresha"]); assert sc >= 60 and "Fresha" in why, (sc, why)
    assert to_int("1.2K") == 1200 and to_int("189") == 189
    for lang in T:
        for k in ("hook_reviews", "hook_platform", "hook_instagram", "hook_offer", "short_reviews", "short_platform", "booking", "menu"): assert T[lang][k], (lang, k)
    mark(c, "node/1", "sent", "whatsapp"); assert c.execute("select status from leads").fetchone()[0] == "sent"
    try: send_email(c, "node/1"); assert False
    except RuntimeError as ex: assert "Already" in str(ex)
    # follow-up / pipeline / analytics
    from datetime import date, timedelta
    c.execute("insert into leads(id,country,city,category,name,phone,lang,status,sent_at) values('node/9','IT','Roma','beauty','Prova','+39 333 1234567','it','sent',?)",
              ((date.today() - timedelta(days=4)).isoformat() + " 10:00",)); c.commit()
    record_send(c, "node/9", "whatsapp", 0)
    assert c.execute("select next_fu from leads where id='node/9'").fetchone()[0] == (date.today() + timedelta(days=3)).isoformat()
    c.execute("update leads set next_fu=? where id='node/9'", (date.today().isoformat(),)); c.commit()
    assert [r["id"] for r in followups_due(c)] == ["node/9"]
    r9 = c.execute("select * from leads where id='node/9'").fetchone()
    assert fu_text(r9, 1, "M").startswith("Buongiorno, Prova!") and "cattiva idea" in fu_text(r9, 2, "M")
    for lg in set(v[1] for v in COUNTRIES.values()):
        assert "{name}" in T[lg]["fu1"] and "{sender}" in T[lg]["fu2"], lg
    record_send(c, "node/9", "whatsapp", 2); assert c.execute("select next_fu from leads where id='node/9'").fetchone()[0] is None
    c.execute("update leads set fu_step=0, next_fu=? where id='node/9'", (date.today().isoformat(),)); c.commit()
    mark(c, "node/9", "replied"); assert followups_due(c) == [] and c.execute("select replied_at from leads where id='node/9'").fetchone()[0]
    assert digits_tail("+39 333 123 4567") == digits_tail("393331234567") == "331234567" and digits_tail("abc") == ""
    an = analytics(c); assert an["funnel"][0][0] == "Found" and "by_channel" in an and an["due"] == 0
    print("selftest OK")

if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest(); sys.exit()
    db().close()
    backfill_touches(db())
    threading.Thread(target=watcher, daemon=True).start()
    print("Lead Radar: http://127.0.0.1:%d" % PORT)
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
