#!/usr/bin/env python3
"""Fill a throw-away data directory with ~25 FICTIONAL leads (used for the README screenshots).
Usage: LEAD_RADAR_DATA=/tmp/lead-radar-demo python3 scripts/seed_demo_data.py
Needs Chrome (CHROME_BIN) for the demo-site screenshots; no Playwright, no network except map tiles."""
import os, sys, random, time
if not os.environ.get("LEAD_RADAR_DATA"):
    sys.exit("set LEAD_RADAR_DATA to an empty temp directory first")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import radar
radar.build_pdf = lambda *a, **k: None   # the PDF brochure needs Playwright; not needed for screenshots
random.seed(7)

CITIES = {"London": ("GB", "en", 51.5074, -0.1278, "+44 20 7946 0"), "Lyon": ("FR", "fr", 45.7640, 4.8357, "+33 4 78 00 00 "),
          "Madrid": ("ES", "es", 40.4168, -3.7038, "+34 910 00 00 ")}
# (name, category, city, status, rating, reviews, platforms, instagram)
LEADS = [
 ("Acme Barbers", "barber", "London", "won", 4.8, 212, "Fresha", "acme.barbers"),
 ("Example Cafe", "cafe", "London", "meeting", 4.6, 134, "", "example.cafe"),
 ("Sample Dental Care", "dentist", "London", "interested", 4.7, 88, "", ""),
 ("Demo Bakery", "bakery", "London", "replied", 4.5, 61, "Just Eat", "demo.bakery"),
 ("Fictional Florist", "florist", "London", "sent", 4.4, 37, "", "fictional.florist"),
 ("Placeholder Garage", "car_repair", "London", "ready", 4.2, 29, "", ""),
 ("Test Nails Studio", "beauty", "London", "ready", 4.9, 156, "Treatwell", "test.nails"),
 ("Northside Gym", "gym", "London", "new", 0, 0, "", ""),
 ("Barbier Exemple", "barber", "Lyon", "replied", 4.7, 96, "Planity", "barbier.exemple"),
 ("Boulangerie Modele", "bakery", "Lyon", "sent", 4.6, 78, "", ""),
 ("Cafe de Demo", "cafe", "Lyon", "sent", 4.3, 54, "", "cafedemo"),
 ("Dentiste Fictif", "dentist", "Lyon", "ready", 4.8, 41, "", ""),
 ("Salon Exemple", "beauty", "Lyon", "ready", 4.5, 112, "Planity", "salon.exemple"),
 ("Garage Test", "car_repair", "Lyon", "rejected", 3.9, 22, "", ""),
 ("Fleuriste Modele", "florist", "Lyon", "new", 0, 0, "", ""),
 ("Barberia Ejemplo", "barber", "Madrid", "interested", 4.9, 187, "Booksy", "barberia.ejemplo"),
 ("Cafeteria Demo", "cafe", "Madrid", "sent", 4.4, 65, "", "cafeteria.demo"),
 ("Panaderia Muestra", "bakery", "Madrid", "sent", 4.6, 49, "", ""),
 ("Clinica Dental Ficticia", "dentist", "Madrid", "replied", 4.7, 73, "", ""),
 ("Gimnasio Prueba", "gym", "Madrid", "ready", 4.3, 58, "", "gimnasio.prueba"),
 ("Floristeria Ejemplo", "florist", "Madrid", "ready", 4.5, 33, "", ""),
 ("Taller Modelo", "car_repair", "Madrid", "ready", 4.1, 26, "", ""),
 ("Peluqueria Imaginaria", "beauty", "Madrid", "new", 0, 0, "", ""),
 ("Restaurante Ficticio", "restaurant", "Madrid", "new", 0, 0, "", ""),
 ("Sample Pizzeria", "restaurant", "London", "sent", 4.2, 102, "Deliveroo", ""),
]
HOURS = "Mo-Sa 09:00-19:00"
c = radar.db()
for k, v in (("sender", "Your Name"), ("contact", "you@example.com"), ("price", "300 USD"), ("gmail", "you@example.com"), ("postal", "1 Example Street, Sampletown")):
    c.execute("insert or replace into settings values(?,?)", (k, v))
for i, (name, cat, city, status, rating, reviews, plats, ig) in enumerate(LEADS, 1):
    iso, lang, lat, lon, ph = CITIES[city]
    phone = ph + "%03d" % (100 + i) if iso == "GB" else ph + "%02d" % (10 + i)
    lat += random.uniform(-.01, .01); lon += random.uniform(-.01, .01)
    c.execute("insert into leads(id,country,city,category,name,phone,email,instagram,address,lat,lon,hours,lang,site,created) values(?,?,?,?,?,?,?,?,?,?,?,?,?,'none',?)",
              ("node/%d" % (1000 + i), iso, city, cat, name, phone, ("hello@%s.example.com" % name.split()[0].lower()) if i % 3 == 0 else "",
               ig, "%d Example Street, %s" % (i, city), lat, lon, HOURS, lang, time.strftime("%Y-%m-%d")))
    lid = "node/%d" % (1000 + i)
    pl = [p for p in plats.split(", ") if p]
    r = c.execute("select * from leads where id=?", (lid,)).fetchone()
    sc, why = radar.score_lead(r, rating, reviews, pl) if reviews else (None, "")
    c.execute("update leads set rating=?, reviews=?, platforms=?, score=?, reasons=? where id=?", (rating or None, reviews or None, plats, sc, why, lid)); c.commit()
    if status == "new":
        continue
    radar.build_demo(c, lid); radar.draft(c, lid)
    if status == "ready":
        continue
    ch = "whatsapp" if i % 2 else "instagram" if ig else "email"
    radar.mark(c, lid, "sent", ch); radar.record_send(c, lid, ch, 0)
    day = time.strftime("%Y-%m-%d", time.localtime(time.time() - random.randint(0, 6) * 86400))
    c.execute("update touches set ts=? where lead_id=?", (day + " 11:%02d" % random.randint(0, 59), lid))
    c.execute("update leads set sent_at=? where id=?", (day + " 11:00", lid)); c.commit()
    if status != "sent":
        radar.mark(c, lid, status, ch)
c.execute("update leads set next_fu=date('now','-1 day') where status='sent' and id in ('node/1005','node/1010')"); c.commit()
print("seeded", c.execute("select count(*) from leads").fetchone()[0], "fictional leads into", radar.DATA)
