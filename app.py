import os, re, io, csv, json, copy, uuid, time, shutil, sqlite3, secrets, tempfile, zipfile
from datetime import timedelta, datetime
from flask import Flask, render_template, request, redirect, session, g, flash, abort, Response
from markupsafe import Markup, escape
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.middleware.proxy_fix import ProxyFix

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.environ.get("DB_PATH", os.path.join(BASE, "proteinveda.db"))
UP = os.path.join(BASE, "static", "uploads"); os.makedirs(UP, exist_ok=True)
BK = os.path.join(BASE, "backups"); os.makedirs(BK, exist_ok=True)
IMGRE = r"[0-9a-f]{32}\.(?:jpg|jpeg|png|webp|gif|ico)"

def secret():
    if os.environ.get("SECRET_KEY"): return os.environ["SECRET_KEY"]
    p = os.path.join(BASE, ".secret_key")
    if not os.path.exists(p):
        open(p, "w").write(secrets.token_hex(32))
        try: os.chmod(p, 0o600)
        except OSError: pass
    return open(p).read().strip()

app = Flask(__name__)
if os.environ.get("BEHIND_PROXY") == "1": app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)
app.secret_key = secret()
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax", SESSION_COOKIE_SECURE=os.environ.get("HTTPS") == "1",
                  PERMANENT_SESSION_LIFETIME=timedelta(hours=8), MAX_CONTENT_LENGTH=200 * 1024 * 1024)

PART = ("Dealer", "Distributor")
KINDS = ["Farmer", "Dairy Owner", "Dealer", "Distributor"]
AVAIL = ["In Stock", "Limited Stock", "Out of Stock"]
ST_C = ["New", "In Progress", "Contacted", "Closed"]
ST_P = ["New", "Under Review", "Contacted", "Approved", "Rejected"]
BAD_IMG = "Only JPG, PNG, WEBP or GIF images up to 8 MB are allowed."
DEMO_NAMES = ["Dudh Shakti Pellet", "Pashu Aahar Mash", "Bachda Starter", "Bypass Fat Supplement"]
# Educational guidance only: not a formulation, guaranteed analysis, or feeding prescription.
PRODUCT_EDUCATION = {
    "dudh-shakti-pellet": {
        "what": "Pelleted feed is compressed into uniform pieces. It is commonly used as one part of a dairy animal's overall ration.",
        "check": ["Confirm whether this specific product is intended for cows, buffaloes or both.", "Ask for the verified ingredient list and guaranteed nutrient analysis.", "Confirm how it fits with the animal's roughage, water access and existing ration."],
        "questions": ["Which lactation stages is this formulation suitable for?", "What is the verified feeding recommendation for my animal?", "What are the storage conditions and shelf life?"]},
    "pashu-aahar-mash": {
        "what": "Mash feed is a loose, mixed feed rather than a pellet. Its suitability depends on its actual ingredients and nutrient composition.",
        "check": ["Request the complete ingredient and nutrient information.", "Ask whether it is a complete feed or a supplement to the existing ration.", "Keep feed clean and dry, and check the label for storage guidance."],
        "questions": ["For which animal types and production stages is it designed?", "How should it be introduced into the current ration?", "Is a verified batch specification available?"]},
    "bachda-starter": {
        "what": "Calf starter is a feed category intended to support young calves as they develop the ability to consume solid feed. The correct starting age depends on the actual product formulation and veterinary guidance.",
        "check": ["Confirm the labelled age range and intended species.", "Request the verified formulation and feeding directions.", "Ensure clean water and appropriate milk or milk-replacer feeding as advised by a qualified professional."],
        "questions": ["At what age can this exact product be introduced?", "What feeding amounts and transition schedule are recommended?", "Is it appropriate for my calf's current health and diet?"]},
    "bypass-fat-supplement": {
        "what": "Bypass fat is a category of energy supplement formulated to reduce breakdown in the rumen. Actual composition, suitability and use vary by product.",
        "check": ["Confirm that this is an actual bypass-fat formulation, not a generic energy feed.", "Request the fat composition and verified technical specification.", "Use only with ration advice from a qualified animal nutrition professional or veterinarian."],
        "questions": ["What is the verified fat content and ingredient source?", "For which dairy animals and stages is this product suitable?", "What is the recommended inclusion rate for my ration?"]},
}

SEED_DESC = {"Dudh Shakti Pellet": "Pelleted cattle feed for dairy animals. Contact us for detailed product information.",
    "Pashu Aahar Mash": "Mash-form cattle feed for daily feeding. Contact us for detailed product information.",
    "Bachda Starter": "Feed range for calves. Contact us for detailed product information.",
    "Bypass Fat Supplement": "Supplementary feed for dairy cattle. Contact us for detailed product information."}

# ---------------- editable content definitions ----------------
def mk(names, rows):
    names = names.split(); out = []
    for r in rows:
        d = {}
        for n, v in zip(names, r): d[n] = v
        out.append(d)
    return out
SC_TT = [("title", "Heading", "text"), ("text", "Description", "textarea")]
SC_MFG = [("title", "Step heading", "text"), ("text", "Description", "textarea"), ("image", "Photograph", "image")]
SC_PART = [("kind", "Visitor type", "kind"), ("eyebrow", "Small label (also homepage heading)", "text"), ("title", "Section heading", "text"), ("short", "Short text for homepage", "textarea"),
           ("text", "Description (blank line = new paragraph)", "textarea"), ("benefits", "Benefits", "lines"), ("button", "Button label", "text")]
SC_GAL = [("title", "Section name", "text"), ("key", "", "key")]
def norm(schema, rows):
    return [{n: str(r.get(n, "")) for n, _, _ in schema} for r in rows]
DEF_LISTS = {
 "why_items": norm(SC_TT, mk("title text", [("Feed for every stage", "Products planned for dairy cattle, calves and supplementary feeding needs."),
   ("Factory-direct supply", "Manufactured in Buxar and supplied directly to dealers, distributors and farmers."),
   ("Consistent product", "Controlled mixing and batch checking so every bag performs like the last."),
   ("Straight business dealings", "Clear communication on pricing, availability and dispatch through our team.")])),
 "philosophy_items": norm(SC_TT, mk("title text", [("Nutrition first", "Feed is the foundation of cattle health and dairy output, so nutrition guides every product decision we make."),
   ("Consistency", "A farmer should get the same dependable feed every time. We plan our production and checking around that."),
   ("Lasting relationships", "We want long-term trust with farmers, dealers and distributors, built on clear communication.")])),
 "mfg_steps": norm(SC_MFG, mk("title text", [("Raw Material Sourcing", "Ingredients are sourced from suppliers for use in our feed formulations."),
   ("Ingredient Inspection", "Incoming materials are inspected before they are accepted for production."),
   ("Processing & Mixing", "Ingredients are processed and mixed according to each product's formulation."),
   ("Feed Manufacturing", "Mixed feed is manufactured in batches into the finished product form."),
   ("Quality Checking", "Finished feed is checked before it moves on to packing."),
   ("Packaging & Dispatch", "Feed is packed and dispatched to dealers, distributors and farmers.")])),
 "quality_items": norm(SC_TT, mk("title text", [("Quality Control", "Quality is checked at each stage of production, from incoming materials to finished feed."),
   ("Raw Material Inspection", "Ingredients are inspected on arrival, and only accepted materials go into production."),
   ("Manufacturing Hygiene", "We keep the production area and equipment clean so feed is made in a hygienic environment."),
   ("Product Consistency", "Batch-wise checking helps keep the feed the same from one batch to the next.")])),
 "partner_sections": norm(SC_PART, mk("kind eyebrow title short text benefits button", [
   ("Farmer", "Farmers & Dairy Owners", "Feed for your animals", "Looking for dependable feed for your cattle? Tell us your requirement and we will guide you.", "If you keep cattle or run a dairy, tell us about your herd and feeding requirement. Our team will help you find the right Protein Veda feed.\n\nPlease mention the type of cattle, your location and your requirement.", "", "Farmer Enquiry"),
   ("Dealer", "Dealers", "Stock Protein Veda feed", "Stock Protein Veda feed in your area. Contact us for dealer terms and availability.", "Dealers can contact us for product availability, supply and terms. Tell us about your shop and the area you serve.", "", "Dealer Enquiry"),
   ("Distributor", "Distributors", "Partner with us", "Interested in a distribution partnership for your region? Let us discuss it.", "If you are interested in distributing our cattle feed in your region, share your business details and we will get in touch to discuss a partnership.", "", "Distributor Enquiry")])),
 "gallery_sections": norm(SC_GAL, mk("title key", [("Factory", "factory"), ("Manufacturing", "manufacturing"), ("Products", "products"), ("Packaging", "packaging")])),
}
LIST_SCHEMA = {"why_items": SC_TT, "philosophy_items": SC_TT, "mfg_steps": SC_MFG, "quality_items": SC_TT, "partner_sections": SC_PART, "gallery_sections": SC_GAL}
DEFAULTS = {
 "hero_eyebrow": "Cattle Feed Manufacturer · Buxar, Bihar", "hero_title": "Better Nutrition. Healthier Cattle. Stronger Dairy.",
 "hero_text": "Protein Veda manufactures cattle feed for farmers, dairy owners, dealers and distributors who depend on consistent nutrition for their animals.",
 "strip_items": "Manufactured in Buxar, Bihar\nFeed for dairy cattle and calves\nSupply to dealers and distributors\nDirect enquiries from farmers",
 "about_eyebrow": "About Protein Veda", "about_title": "Feed made with the farmer's daily work in mind", "intro": "Protein Veda is a cattle feed manufacturing company based in Buxar, Bihar, India.",
 "products_eyebrow": "Featured Products", "products_title": "Our cattle feed range", "products_text": "Feed for different cattle and production stages. Detailed specifications and pack sizes are shared on request.",
 "why_eyebrow": "Why Protein Veda", "why_title": "What you can expect from us",
 "process_eyebrow": "Manufacturing Process", "process_title": "From raw material to dispatch", "process_text": "Each stage is handled and checked before the next begins.",
 "quality_eyebrow": "Quality Assurance", "quality_title": "Quality is checked at every step", "quality_text": "Our quality practices will be described here in detail once finalised with our production team.",
 "home_quality_points": "Inspection of incoming raw materials\nClean and hygienic manufacturing area\nBatch-wise checking of finished feed\nConsistency from one batch to the next",
 "partners_eyebrow": "Farmers & Business Partners", "partners_title": "Work with Protein Veda",
 "contact_eyebrow": "Contact Us", "contact_title": "Send us your enquiry", "contact_text": "Farmers, dairy owners, dealers and distributors are all welcome to get in touch.",
 "about_sub": "A cattle feed manufacturing company based in Buxar, Bihar, India.", "about_intro_eyebrow": "Company Introduction", "about_intro_title": "Protein Veda",
 "about_intro_text2": "We work with farmers, dairy owners, dealers and distributors.", "founder_name": "Parmar Gupt Raj",
 "vision_eyebrow": "Our Vision", "vision_title": "Where we are headed", "vision": "To be a cattle feed brand that farmers and dairy owners can depend on for their animals' daily nutrition.",
 "mission_eyebrow": "Our Mission", "mission_title": "How we work", "mission": "To manufacture consistent, carefully checked cattle feed and to deal with farmers, dealers and distributors clearly and honestly.",
 "philosophy_eyebrow": "Company Philosophy", "philosophy_title": "What guides our work",
 "approach_eyebrow": "Manufacturing Approach", "approach_title": "Controlled, batch-wise production", "approach_text": "From sourcing to dispatch, each stage is handled and checked before the next begins.",
 "commit_eyebrow": "Quality Commitment", "commit_title": "Checked at every step", "commit_text": "We inspect what comes in, keep production clean, and check finished feed before it leaves.",
 "about_cta": "Want to know more about our feed?",
 "mfg_sub": "How Protein Veda cattle feed is made, from raw material to dispatch.", "mfg_cta": "Want to supply or stock our feed?",
 "quality_sub": "Our approach to keeping every batch of feed dependable.", "quality_cta": "Questions about our quality practices?",
 "partners_sub": "Feed for your cattle, or a business partnership with Protein Veda.", "enquiry_eyebrow": "Business Enquiry", "enquiry_title": "Tell us about yourself", "enquiry_text": "Fill in the form and our team will contact you.",
 "gallery_sub": "Factory, manufacturing, product and packaging photographs.", "gallery_cta": "Want to visit or know more?", "gallery_empty": "Photographs will be added soon.",
 "contact_sub": "Farmers, dairy owners, dealers and distributors are all welcome to get in touch.", "contact_page_eyebrow": "Get in touch", "contact_page_title": "Protein Veda",
 "phone": "7493966862",
 "whatsapp": "917493966862",
 "email": "info@proteinveda.co.in",
 "wa_message": "Hello Protein Veda, I would like to make an enquiry.",
}
def FLD(k, l, t="text", h=""): return ("f", k, l, t, h)
def HD(t): return ("h", t)
def LST(k, l, item): return ("l", k, l, LIST_SCHEMA[k], item)
TOG = [(f"show_{k}", f"Show {l} section", "toggle") for k, l in [("about", "About"), ("products", "Products"), ("why", "Why Protein Veda"), ("process", "Manufacturing process"), ("quality", "Quality"), ("partners", "Farmers & distributors"), ("contact", "Contact")]]
SEO_PAGES = [("about", "About"), ("products", "Products"), ("manufacturing", "Manufacturing"), ("quality", "Quality"), ("partners", "Farmers & Distributors"), ("gallery", "Gallery"), ("contact", "Contact"), ("blog_list", "Blog")]
ED = {
 "homepage": ("Homepage", "/", [HD("Hero section"), FLD("hero_eyebrow", "Small label above heading"), FLD("hero_title", "Hero heading"), FLD("hero_text", "Hero description", "textarea"),
   FLD("hero_image", "Hero background photograph", "image", "Wide photograph, at least 1600 px wide."), FLD("strip_items", "Highlight strip below hero", "lines"),
   HD("Company introduction"), FLD("about_eyebrow", "Small label"), FLD("about_title", "Heading"), FLD("intro", "Company introduction", "textarea"), FLD("about_image", "Introduction photograph", "image"),
   HD("Products section"), FLD("products_eyebrow", "Small label"), FLD("products_title", "Heading"), FLD("products_text", "Text", "textarea"),
   HD("Manufacturing process section (the steps themselves are edited in the Manufacturing page)"), FLD("process_eyebrow", "Small label"), FLD("process_title", "Heading"), FLD("process_text", "Text", "textarea"),
   HD("Quality section"), FLD("quality_eyebrow", "Small label"), FLD("quality_title", "Heading"), FLD("quality_text", "Text", "textarea"), FLD("home_quality_points", "Quality points", "lines"),
   HD("Farmers & distributors section (the boxes are edited in the Farmers & Distributors page)"), FLD("partners_eyebrow", "Small label"), FLD("partners_title", "Heading"),
   HD("Contact section"), FLD("contact_eyebrow", "Small label"), FLD("contact_title", "Heading"), FLD("contact_text", "Text", "textarea"),
   HD("Show or hide sections")] + [FLD(*t) for t in TOG] + [("featured",)]),
 "about": ("About Us Page", "/about", [HD("Page header"), FLD("about_sub", "Header subtitle", "textarea"),
   HD("Company introduction"), FLD("about_intro_eyebrow", "Small label"), FLD("about_intro_title", "Heading"), FLD("intro", "Introduction paragraph (also used on homepage)", "textarea"), FLD("about_intro_text2", "Second paragraph", "textarea"), FLD("about_image", "Photograph (also used on homepage)", "image"),
   HD("Founder"), FLD("founder_name", "Founder name"),
   HD("Vision and mission"), FLD("vision_eyebrow", "Vision label"), FLD("vision_title", "Vision heading"), FLD("vision", "Vision", "textarea"), FLD("mission_eyebrow", "Mission label"), FLD("mission_title", "Mission heading"), FLD("mission", "Mission", "textarea"),
   HD("Company philosophy"), FLD("philosophy_eyebrow", "Small label"), FLD("philosophy_title", "Heading"), LST("philosophy_items", "Philosophy points", "Point"),
   HD("Manufacturing approach"), FLD("approach_eyebrow", "Small label"), FLD("approach_title", "Heading"), FLD("approach_text", "Text", "textarea"),
   HD("Quality commitment"), FLD("commit_eyebrow", "Small label"), FLD("commit_title", "Heading"), FLD("commit_text", "Text", "textarea"), FLD("about_cta", "Bottom banner heading")]),
 "why": ("Why Protein Veda", "/#why", [HD("Homepage section: Why Protein Veda"), FLD("why_eyebrow", "Small label"), FLD("why_title", "Heading"), LST("why_items", "Points", "Point")]),
 "manufacturing": ("Manufacturing Page", "/manufacturing", [HD("Page header"), FLD("mfg_sub", "Header subtitle", "textarea"), HD("Manufacturing steps (also shown on the homepage)"), LST("mfg_steps", "Steps", "Step"), FLD("mfg_cta", "Bottom banner heading")]),
 "quality": ("Quality Assurance Page", "/quality", [HD("Page header"), FLD("quality_sub", "Header subtitle", "textarea"), HD("Quality topics"), LST("quality_items", "Topics", "Topic"), FLD("quality_image", "Side photograph (also used on homepage Quality section)", "image"), FLD("quality_cta", "Bottom banner heading")]),
 "partners": ("Farmers & Distributors Page", "/farmers-distributors", [HD("Page header"), FLD("partners_sub", "Header subtitle", "textarea"), HD("Sections (farmers, dealers, distributors)"), LST("partner_sections", "Sections", "Section"),
   HD("Enquiry form area"), FLD("enquiry_eyebrow", "Small label"), FLD("enquiry_title", "Heading"), FLD("enquiry_text", "Text", "textarea")]),
 "gallery": ("Gallery Sections", "/gallery", [HD("Page header"), FLD("gallery_sub", "Header subtitle", "textarea"), HD("Gallery sections (rename, add, delete, reorder). Upload the photographs in Gallery Photos."), LST("gallery_sections", "Sections", "Section"),
   FLD("gallery_empty", "Text shown when there are no photos"), FLD("gallery_cta", "Bottom banner heading")]),
 "contact": ("Contact Page", "/contact", [HD("Page header"), FLD("contact_sub", "Header subtitle", "textarea"), FLD("contact_page_eyebrow", "Small label"), FLD("contact_page_title", "Heading"),
   HD("Contact information (used across the whole website)"), FLD("phone", "Phone number"), FLD("whatsapp", "WhatsApp number", "text", "Country code + number, digits only. Example: 919876543210"), FLD("email", "Email address"),
   FLD("address", "Complete factory address", "textarea", "Shown on the Contact page and used for the map if no map location is set."), FLD("map_query", "Google Maps location", "text", "Type an address or place name, or paste a Google Maps 'Embed a map' link (https://www.google.com/maps/embed...)."),
   FLD("contact_hours", "Working hours (optional)"), FLD("wa_message", "Default WhatsApp message", "textarea")]),
 "company": ("Company Details", "/contact", [FLD("company_name", "Company name"), FLD("logo", "Logo", "image", "Used in the website header. PNG with transparent background works best."), FLD("phone", "Phone number"),
   FLD("whatsapp", "WhatsApp number", "text", "Country code + number, digits only. Example: 919876543210"), FLD("email", "Email address"), FLD("address", "Complete factory address", "textarea"), FLD("map_query", "Google Maps location"),
   FLD("facebook", "Facebook link"), FLD("instagram", "Instagram link"), FLD("youtube", "YouTube link"), FLD("description", "Company description (footer and search engines)", "textarea")]),
 "website": ("Website Settings & SEO", "/", [FLD("logo", "Website logo", "image"), FLD("favicon", "Favicon", "image", "Small square icon (PNG or ICO) shown in the browser tab."), FLD("seo_home_title", "Home page title", "text", "Shown in Google results and the browser tab."),
   FLD("seo_home_desc", "Home page meta description", "textarea"), FLD("seo_desc", "Default meta description (all other pages)", "textarea")] + [FLD(f"seo_{k}_title", f"{l} page title") for k, l in SEO_PAGES] + [FLD("footer_text", "Footer text")]),
}
ADMIN_ONLY = ("company", "website")

# ---------------- db & helpers ----------------
def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB); g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close(e=None):
    d = g.pop("db", None)
    if d: d.close()

def slugify(n): return re.sub(r"[^a-z0-9]+", "-", (n or "").lower()).strip("-") or "item"
def unique_slug(c, name, table="products"):
    base = slug = slugify(name); k = 2
    while c.execute(f"SELECT 1 FROM {table} WHERE slug=?", (slug,)).fetchone(): slug = f"{base}-{k}"; k += 1
    return slug
def addcols(c, table, cols):
    have = [r[1] for r in c.execute(f"PRAGMA table_info({table})")]
    for n, d in cols.items():
        if n not in have: c.execute(f"ALTER TABLE {table} ADD COLUMN {n} {d}")

def init_db():
    c = sqlite3.connect(DB)
    c.executescript("""
    CREATE TABLE IF NOT EXISTS products(id INTEGER PRIMARY KEY, name TEXT, category TEXT, protein TEXT, description TEXT);
    CREATE TABLE IF NOT EXISTS inquiries(id INTEGER PRIMARY KEY, name TEXT, phone TEXT, kind TEXT, message TEXT, created TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS settings(k TEXT PRIMARY KEY, v TEXT);
    CREATE TABLE IF NOT EXISTS admin(id INTEGER PRIMARY KEY, username TEXT UNIQUE, pw TEXT);
    CREATE TABLE IF NOT EXISTS gallery(id INTEGER PRIMARY KEY, category TEXT, image TEXT, caption TEXT DEFAULT '', pos INTEGER DEFAULT 0);
    CREATE TABLE IF NOT EXISTS posts(id INTEGER PRIMARY KEY, title TEXT, slug TEXT, excerpt TEXT DEFAULT '', body TEXT DEFAULT '', cover TEXT DEFAULT '', published INTEGER DEFAULT 0, created TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS activity(id INTEGER PRIMARY KEY, who TEXT, what TEXT, created TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS login_attempts(key TEXT PRIMARY KEY, attempts INTEGER NOT NULL DEFAULT 0, last_at REAL NOT NULL DEFAULT 0);
    """)
    addcols(c, "products", {"slug": "TEXT DEFAULT ''", "packaging": "TEXT DEFAULT ''", "specs": "TEXT DEFAULT ''", "active": "INTEGER DEFAULT 1", "featured": "INTEGER DEFAULT 0", "availability": "TEXT DEFAULT 'In Stock'", "image": "TEXT DEFAULT ''", "is_demo": "INTEGER DEFAULT 0"})
    addcols(c, "inquiries", {"status": "TEXT DEFAULT 'New'", "notes": "TEXT DEFAULT ''", "business": "TEXT DEFAULT ''", "city": "TEXT DEFAULT ''"})
    addcols(c, "admin", {"role": "TEXT DEFAULT 'admin'"})
    addcols(c, "settings", {"draft": "TEXT"})
    if not c.execute("SELECT 1 FROM admin").fetchone():
        c.execute("INSERT INTO admin(username,pw,role) VALUES(?,?,'admin')", (os.environ.get("ADMIN_USER", "admin"), generate_password_hash(os.environ.get("ADMIN_PASS", "ChangeMe@123"))))
    fresh = not c.execute("SELECT 1 FROM products").fetchone()
    if fresh:
        c.executemany("INSERT INTO products(name,category,protein,description,is_demo) VALUES(?,?,?,?,1)", [("Dudh Shakti Pellet", "Dairy Cattle", "", SEED_DESC["Dudh Shakti Pellet"]), ("Pashu Aahar Mash", "Cattle", "", SEED_DESC["Pashu Aahar Mash"]), ("Bachda Starter", "Calf", "", SEED_DESC["Bachda Starter"]), ("Bypass Fat Supplement", "Supplement", "", SEED_DESC["Bypass Fat Supplement"])])
        c.execute("INSERT OR REPLACE INTO settings(k,v) VALUES('demo_marked','1')")
    if not c.execute("SELECT 1 FROM settings WHERE k='demo_marked'").fetchone():   # one-time: flag the original sample products on existing databases
        for n, d in SEED_DESC.items(): c.execute("UPDATE products SET is_demo=1 WHERE name=? AND (description=? OR description='' OR description IS NULL)", (n, d))
        c.execute("INSERT OR REPLACE INTO settings(k,v) VALUES('demo_marked','1')")
    for n, d in SEED_DESC.items(): c.execute("UPDATE products SET description=?, protein='' WHERE name=? AND (description IS NULL OR description='' OR protein IN ('20% Protein','18% Protein','22% Protein','High Energy'))", (n, d))
    # Only fill packaging for original sample products; never override real product data.
    c.execute("UPDATE products SET packaging='50 KG' WHERE is_demo=1 AND (packaging IS NULL OR TRIM(packaging)='')")
    for i, n in c.execute("SELECT id,name FROM products WHERE slug IS NULL OR slug=''").fetchall(): c.execute("UPDATE products SET slug=? WHERE id=?", (unique_slug(c, n), i))
    c.commit(); c.close()
    try: os.chmod(DB, 0o600)
    except OSError: pass

def is_preview():
    if not session.get("uid") or not session.get("preview"):
        return False
    user = db().execute("SELECT role FROM admin WHERE id=?", (session["uid"],)).fetchone()
    if user is None:
        session.clear()
        return False
    return True
def act(col="active"): return "1=1" if is_preview() else f"{col}=1"
def S(draft=None):
    d = is_preview() if draft is None else draft; key = "S1" if d else "S0"
    if not hasattr(g, key):
        setattr(g, key, {r["k"]: ((r["draft"] if d and r["draft"] is not None else r["v"]) or "") for r in db().execute("SELECT k,v,draft FROM settings")})
    return getattr(g, key)

def L(d, k):
    raw = d.get(k)
    if raw is not None:
        try:
            v = json.loads(raw)
            if isinstance(v, list): return norm(LIST_SCHEMA[k], [x for x in v if isinstance(x, dict)])
        except ValueError: pass
    return copy.deepcopy(DEF_LISTS.get(k, []))

class SP:
    def __init__(self, d): self._d = d
    def __getattr__(self, k): return self._d[k] if k in self._d else DEFAULTS.get(k, "")
    def L(self, k): return L(self._d, k)

def sigok(h, ico=True):
    return h[:2] == b"\xff\xd8" or h[:4] == b"\x89PNG" or h[:4] == b"GIF8" or (h[:4] == b"RIFF" and h[8:12] == b"WEBP") or (ico and h[:4] == b"\x00\x00\x01\x00")

def save_img(f, ico=False):
    if not f or not f.filename: return ""
    ext = f.filename.rsplit(".", 1)[-1].lower() if "." in f.filename else ""
    if ext not in {"jpg", "jpeg", "png", "webp", "gif"} | ({"ico"} if ico else set()): return None
    f.stream.seek(0, 2); size = f.stream.tell(); f.stream.seek(0)
    h = f.stream.read(12); f.stream.seek(0)
    matching = ((ext in ("jpg", "jpeg") and h[:2] == b"\xff\xd8") or
                (ext == "png" and h[:8] == b"\x89PNG\r\n\x1a\n") or
                (ext == "gif" and h[:6] in (b"GIF87a", b"GIF89a")) or
                (ext == "webp" and h[:4] == b"RIFF" and h[8:12] == b"WEBP") or
                (ext == "ico" and ico and h[:4] == b"\x00\x00\x01\x00"))
    if size > 8 * 1024 * 1024 or size < 16 or not matching: return None
    name = uuid.uuid4().hex + "." + ext
    f.save(os.path.join(UP, name)); return name

def rm_img(name):
    if name and re.fullmatch(IMGRE, name):
        try: os.remove(os.path.join(UP, name))
        except OSError: pass

def need(*roles):
    uid = session.get("uid")
    u = db().execute("SELECT id,username,role FROM admin WHERE id=?", (uid,)).fetchone() if uid else None
    if not u: session.clear(); abort(redirect("/admin/login"))
    session["role"] = u["role"] or "admin"; session["user"] = u["username"]
    if roles and session["role"] not in roles: abort(403)

def log(what):
    db().execute("INSERT INTO activity(who,what) VALUES(?,?)", (session.get("user", "visitor"), what)); db().commit()
def back(default):
    n = request.form.get("next", ""); return redirect(n if n.startswith("/admin") else default)
def cnt(q, a=()): return db().execute(q, a).fetchone()[0]
def pw_ok(p): return len(p) >= 8 and re.search(r"[A-Za-z]", p) and re.search(r"\d", p)

@app.template_filter("paras")
def paras(t):
    return Markup("".join(f"<p>{escape(p).replace(chr(10), Markup('<br>'))}</p>" for p in re.split(r"\n\s*\n", t or "") if p.strip()))

@app.before_request
def csrf():
    if "t" not in session: session["t"] = secrets.token_hex(16)
    if request.method == "POST" and request.form.get("t") != session["t"]: abort(400)

@app.after_request
def hdr(r):
    r.headers.update({"X-Content-Type-Options": "nosniff", "X-Frame-Options": "SAMEORIGIN", "Referrer-Policy": "strict-origin-when-cross-origin", "Permissions-Policy": "camera=(), microphone=(), geolocation=()"})
    if request.path.startswith("/admin") or is_preview(): r.headers["Cache-Control"] = "no-store"
    if os.environ.get("HTTPS") == "1": r.headers["Strict-Transport-Security"] = "max-age=31536000"
    return r

@app.context_processor
def inject():
    try: st = S()
    except Exception: st = {}
    ep = request.endpoint or ""; pend = 0
    try:
        if session.get("uid"): pend = cnt("SELECT COUNT(*) FROM settings WHERE draft IS NOT NULL")
    except Exception: pass
    return {"token": session.get("t", ""), "s": SP(st), "pt": st.get(f"seo_{ep}_title", ""), "pd": st.get(f"seo_{ep}_desc", "") or st.get("seo_desc", ""), "preview": is_preview(), "pending": pend, "canonical": "https://proteinveda.co.in" + request.path}

@app.errorhandler(404)
def nf(e): return render_template("404.html"), 404
@app.errorhandler(403)
def forbidden(e): return "Access denied: your account does not have permission for this page. <a href='/admin'>Back</a>", 403
@app.errorhandler(413)
def toolarge(e): return "Upload too large. <a href='/admin'>Back</a>", 413

# ---------------- public site ----------------
@app.route("/")
def home():
    c = db()
    selected = S().get("featured_product_ids")
    if selected is not None:
        try: ids = json.loads(selected)
        except (ValueError, TypeError): ids = []
        items = [r for r in c.execute(f"SELECT * FROM products WHERE {act()} ORDER BY id") if r["id"] in ids][:8]
    else:
        items = c.execute(f"SELECT * FROM products WHERE {act()} AND featured=1 ORDER BY id LIMIT 8").fetchall()
    if not items: items = c.execute(f"SELECT * FROM products WHERE {act()} ORDER BY id LIMIT 5").fetchall()
    return render_template("home.html", products=items)

for _path, _tpl in {"about": "about", "manufacturing": "manufacturing", "quality": "quality", "farmers-distributors": "partners", "contact": "contact"}.items():
    app.add_url_rule("/" + _path, endpoint=_tpl, view_func=(lambda t=_tpl: render_template(t + ".html")))

@app.route("/products")
def products():
    cat = request.args.get("cat", "")[:100]
    term = request.args.get("q", "").strip()[:100]
    cats = [r[0] for r in db().execute(f"SELECT DISTINCT category FROM products WHERE category!='' AND {act()} ORDER BY category")]
    clauses, args = [act()], []
    if cat:
        clauses.append("category=?"); args.append(cat)
    if term:
        clauses.append("(name LIKE ? OR category LIKE ? OR description LIKE ?)")
        pattern = "%" + term + "%"
        # SQL LIKE wildcards are permitted in user search terms.
        args.extend([pattern] * 3)
    sql = "SELECT * FROM products WHERE " + " AND ".join(clauses) + " ORDER BY id DESC"
    return render_template("products.html", items=db().execute(sql, args).fetchall(), cats=cats, cat=cat, term=term)

@app.route("/products/<slug>")
def product(slug):
    p = db().execute(f"SELECT * FROM products WHERE slug=? AND {act()}", (slug,)).fetchone() or abort(404)
    rel = db().execute(f"SELECT * FROM products WHERE category=? AND id!=? AND {act()} ORDER BY id LIMIT 3", (p["category"], p["id"])).fetchall()
    return render_template("product.html", p=p, related=rel, education=PRODUCT_EDUCATION.get(p["slug"]) if p["is_demo"] else None)

@app.get("/robots.txt")
def robots_txt():
    return Response("User-agent: *\nDisallow: /admin\nSitemap: https://proteinveda.co.in/sitemap.xml\n", mimetype="text/plain")

@app.get("/sitemap.xml")
def sitemap_xml():
    from xml.sax.saxutils import escape as xml_escape
    paths = ["/", "/about", "/products", "/manufacturing", "/quality", "/farmers-distributors", "/gallery", "/blog", "/contact"]
    paths += ["/products/" + r[0] for r in db().execute("SELECT slug FROM products WHERE active=1 AND slug!=''")]
    paths += ["/blog/" + r[0] for r in db().execute("SELECT slug FROM posts WHERE published=1 AND slug!=''")]
    body = '<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + "".join("<url><loc>" + xml_escape("https://proteinveda.co.in" + p) + "</loc></url>" for p in paths) + "</urlset>"
    return Response(body, mimetype="application/xml")

@app.route("/gallery")
def gallery():
    rows = db().execute("SELECT * FROM gallery ORDER BY pos,id").fetchall()
    secs = [x for x in L(S(), "gallery_sections") if x["key"]]
    return render_template("gallery.html", sections=secs, groups={x["key"]: [r for r in rows if r["category"] == x["key"]] for x in secs})

@app.route("/blog")
def blog_list(): return render_template("blog.html", posts=db().execute(f"SELECT * FROM posts WHERE {act('published')} ORDER BY id DESC").fetchall())
@app.route("/blog/<slug>")
def blog_post(slug): return render_template("post.html", p=db().execute(f"SELECT * FROM posts WHERE slug=? AND {act('published')}", (slug,)).fetchone() or abort(404))

@app.post("/inquiry")
def inquiry():
    f = request.form
    # Hidden honeypot: ordinary visitors never fill this field.
    if f.get("website", "").strip():
        flash("Thank you! Your enquiry has been received.")
        return redirect("/#contact")
    # Per-IP, shared SQLite throttle. 5 submissions per rolling 10-minute window.
    ip = request.remote_addr or "unknown"
    key = "enquiry:" + ip
    now = time.time()
    prior = db().execute("SELECT attempts,last_at FROM login_attempts WHERE key=?", (key,)).fetchone()
    if prior and prior["attempts"] >= 5 and now - prior["last_at"] < 600:
        flash("Too many enquiries. Please try again later or contact us by phone.")
        return redirect("/#contact")
    n, p, k, m, b, ct = (f.get(x, "").strip()[:500] for x in ("name", "phone", "kind", "message", "business", "city"))
    if n and 10 <= len(re.sub(r"\D", "", p)) <= 15:
        db().execute("""INSERT INTO login_attempts(key,attempts,last_at) VALUES(?,1,?)
            ON CONFLICT(key) DO UPDATE SET attempts=CASE WHEN ?-last_at>=600 THEN 1 ELSE attempts+1 END,last_at=?""",
            (key, now, now, now))
        db().execute("INSERT INTO inquiries(name,phone,kind,message,business,city) VALUES(?,?,?,?,?,?)", (n, p, k if k in KINDS else "Farmer", m, b, ct)); db().commit()
        flash("Thank you! Our team will contact you soon.")
    else: flash("Please enter your name and a valid 10-digit phone number.")
    nxt = f.get("next", "")
    return redirect(nxt.split("#")[0] + "#enquiry" if nxt.startswith("/") and not nxt.startswith("//") else "/#contact")

# ---------------- admin: auth, dashboard, account ----------------
def login_blocked(keys):
    now = time.time()
    for key in keys:
        row = db().execute("SELECT attempts,last_at FROM login_attempts WHERE key=?", (key,)).fetchone()
        if row and row["attempts"] >= 5 and now - row["last_at"] < 300:
            return True
    return False

def record_login_attempt(keys, success=False):
    c = db(); now = time.time()
    for key in keys:
        if success:
            c.execute("DELETE FROM login_attempts WHERE key=?", (key,))
        else:
            c.execute("""INSERT INTO login_attempts(key,attempts,last_at) VALUES(?,1,?)
                ON CONFLICT(key) DO UPDATE SET
                attempts=CASE WHEN ?-last_at>=300 THEN 1 ELSE attempts+1 END,
                last_at=?""", (key, now, now, now))
    c.commit()

@app.route("/admin/login", methods=["GET", "POST"])
def login():
    ip = request.remote_addr or "unknown"
    if request.method == "POST":
        u = request.form.get("u", "").strip(); keys = (ip, "u:" + u.lower())
        if login_blocked(keys): flash("Too many failed attempts. Please wait 5 minutes.")
        else:
            r = db().execute("SELECT * FROM admin WHERE username=?", (u,)).fetchone()
            if r and check_password_hash(r["pw"], request.form.get("p", "")):
                record_login_attempt(keys, success=True)
                session.clear(); session.update(uid=r["id"], user=r["username"], role=r["role"] or "admin", t=secrets.token_hex(16)); session.permanent = True
                log("Logged in")
                if check_password_hash(r["pw"], "ChangeMe@123"): flash("Please change the default password now."); return redirect("/admin/account")
                return redirect("/admin")
            record_login_attempt(keys)
            flash("Wrong username or password.")
    return render_template("admin/login.html")

@app.post("/admin/logout")
def logout(): session.clear(); return redirect("/admin/login")

@app.route("/admin")
def dash():
    need(); ph = ",".join("?" * len(PART))
    d = dict(total=cnt("SELECT COUNT(*) FROM products"), active=cnt("SELECT COUNT(*) FROM products WHERE active=1"), demo=cnt("SELECT COUNT(*) FROM products WHERE is_demo=1"), demo_live=cnt("SELECT COUNT(*) FROM products WHERE is_demo=1 AND active=1"),
        cust=cnt(f"SELECT COUNT(*) FROM inquiries WHERE kind NOT IN ({ph})", PART), cust_new=cnt(f"SELECT COUNT(*) FROM inquiries WHERE status='New' AND kind NOT IN ({ph})", PART),
        part=cnt(f"SELECT COUNT(*) FROM inquiries WHERE kind IN ({ph})", PART), part_new=cnt(f"SELECT COUNT(*) FROM inquiries WHERE status='New' AND kind IN ({ph})", PART))
    me = db().execute("SELECT pw FROM admin WHERE id=?", (session["uid"],)).fetchone()
    return render_template("admin/dashboard.html", d=d, last_backup=S(False).get("last_backup", ""), acts=db().execute("SELECT * FROM activity ORDER BY id DESC LIMIT 12").fetchall(),
        recent=db().execute("SELECT * FROM inquiries ORDER BY id DESC LIMIT 6").fetchall(), default_pw=bool(me and check_password_hash(me["pw"], "ChangeMe@123")))

@app.route("/admin/account")
def a_account(): need(); return render_template("admin/account.html", users=db().execute("SELECT * FROM admin ORDER BY id").fetchall())

@app.post("/admin/account/password")
def a_pw():
    need(); f = request.form; r = db().execute("SELECT * FROM admin WHERE id=?", (session["uid"],)).fetchone()
    if not check_password_hash(r["pw"], f.get("old", "")): flash("Current password is wrong.")
    elif not pw_ok(f.get("new", "")): flash("New password must be at least 8 characters and contain both letters and numbers.")
    elif f.get("new") != f.get("new2"): flash("New passwords do not match.")
    else: db().execute("UPDATE admin SET pw=? WHERE id=?", (generate_password_hash(f["new"]), r["id"])); db().commit(); log("Changed own password"); flash("Password changed.")
    return redirect("/admin/account")

@app.post("/admin/users/add")
def a_user_add():
    need("admin"); f = request.form; u = f.get("username", "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_.-]{3,30}", u) or not pw_ok(f.get("password", "")): flash("Username: 3-30 letters/numbers. Password: at least 8 characters with letters and numbers.")
    elif db().execute("SELECT 1 FROM admin WHERE username=?", (u,)).fetchone(): flash("That username already exists.")
    else:
        db().execute("INSERT INTO admin(username,pw,role) VALUES(?,?,?)", (u, generate_password_hash(f["password"]), "admin" if f.get("role") == "admin" else "editor")); db().commit(); log(f"Added user {u}"); flash("User added.")
    return redirect("/admin/account")

@app.post("/admin/users/<int:i>/delete")
def a_user_del(i):
    need("admin"); r = db().execute("SELECT * FROM admin WHERE id=?", (i,)).fetchone() or abort(404)
    if i == session["uid"]: flash("You cannot delete your own account.")
    elif r["role"] == "admin" and cnt("SELECT COUNT(*) FROM admin WHERE role='admin'") < 2: flash("At least one admin must remain.")
    else: db().execute("DELETE FROM admin WHERE id=?", (i,)); db().commit(); log(f"Deleted user {r['username']}"); flash("User deleted.")
    return redirect("/admin/account")

# ---------------- admin: preview & publish ----------------
@app.route("/admin/preview")
def a_preview():
    need(); session["preview"] = True; go = request.args.get("go", "/")
    return redirect(go if go.startswith("/") and not go.startswith("//") else "/")

@app.route("/admin/preview/exit")
def a_preview_exit(): need(); session.pop("preview", None); return redirect("/admin")

@app.post("/admin/publish")
def a_publish():
    need("admin"); n = cnt("SELECT COUNT(*) FROM settings WHERE draft IS NOT NULL")
    c = db()
    pending = c.execute("SELECT draft FROM settings WHERE k='featured_product_ids' AND draft IS NOT NULL").fetchone()
    if pending:
        try: ids = json.loads(pending[0])
        except (ValueError, TypeError): ids = []
        c.execute("UPDATE products SET featured=0")
        for pid in ids:
            if isinstance(pid, int): c.execute("UPDATE products SET featured=1 WHERE id=?", (pid,))
    c.execute("UPDATE settings SET v=draft, draft=NULL WHERE draft IS NOT NULL"); c.commit()
    log(f"Published {n} content change(s)"); flash(f"Published {n} change(s). They are now live on the website."); return back("/admin")

@app.post("/admin/discard")
def a_discard():
    need("admin"); db().execute("UPDATE settings SET draft=NULL"); db().commit(); log("Discarded unpublished changes"); flash("Unpublished changes discarded."); return back("/admin")

# ---------------- admin: page content editor (drafts) ----------------
def setdraft(c, k, val, base):
    c.execute("INSERT OR IGNORE INTO settings(k,v) VALUES(?, '')", (k,))
    c.execute("UPDATE settings SET draft=? WHERE k=?", (None if val == base else val, k))

def save_blocks(blocks):
    c = db(); live = S(False); fl = request.form; errs = []; act_ = fl.get("action", ""); anchor = ""
    for b in blocks:
        if b[0] == "f":
            _, k, l, t, h = b
            if t == "image":
                n = save_img(request.files.get(k), ico=(k == "favicon"))
                if n is None: errs.append(f"{l}: {BAD_IMG}"); continue
                if n: val = n
                elif fl.get("rm_" + k): val = ""
                else: continue
                base = live.get(k, "")
            elif t == "toggle": val = "1" if fl.get(k) else "0"; base = live.get(k) or "1"
            else:
                val = fl.get(k, "").replace("\r\n", "\n").strip()[:4000]
                if t == "lines": val = "\n".join(x.strip() for x in val.split("\n"))
                if k == "whatsapp": val = re.sub(r"\D", "", val)
                if k in ("facebook", "instagram", "youtube") and val and not val.startswith(("http://", "https://")): val = "https://" + val
                base = live[k] if k in live else DEFAULTS.get(k, "")
            setdraft(c, k, val, base)
        elif b[0] == "l":
            _, k, l, schema, item = b; n = min(int(fl.get(k + "__n", "0") or 0), 200); items = []
            for i in range(n):
                d = {}
                for name, lab, t in schema:
                    fn = f"{k}__{i}__{name}"; v = fl.get(fn, "")
                    if t == "image":
                        cu = fl.get(fn + "__cur", ""); cu = cu if re.fullmatch(IMGRE, cu) else ""; nn = save_img(request.files.get(fn))
                        if nn is None: errs.append(f"{item} {i+1} photo: {BAD_IMG}"); nn = ""
                        d[name] = nn or ("" if fl.get("rm_" + fn) else cu)
                    elif t == "key": d[name] = v if re.fullmatch(r"[a-z0-9-]{1,40}", v) else ""
                    elif t == "kind": d[name] = v if v in KINDS else "Farmer"
                    elif t == "lines": d[name] = "\n".join(x.strip() for x in v.replace("\r\n", "\n").split("\n")).strip()[:3000]
                    else: d[name] = v.replace("\r\n", "\n").strip()[:3000]
                items.append(d)
            a = act_.split(":")
            if len(a) == 3 and a[1] == k and a[2].isdigit() and int(a[2]) < len(items):
                i = int(a[2]); anchor = "list-" + k
                if a[0] == "del":
                    if k == "gallery_sections" and cnt("SELECT COUNT(*) FROM gallery WHERE category=?", (items[i].get("key", ""),)): errs.append("This gallery section still has photos. Delete or move its photos first.")
                    else: items.pop(i)
                elif a[0] == "up" and i > 0: items[i - 1], items[i] = items[i], items[i - 1]
                elif a[0] == "down" and i < len(items) - 1: items[i + 1], items[i] = items[i], items[i + 1]
            elif act_ == "add:" + k:
                anchor = "list-" + k; items.append({n_: ("Farmer" if t_ == "kind" else "") for n_, _, t_ in schema})
            if any(n_ == "key" for n_, _, _ in schema):
                used = {x["key"] for x in items if x.get("key")}
                for x in items:
                    if not x.get("key") and x.get("title", "").strip():
                        base_ = slug = slugify(x.get("title")); j = 2
                        while slug in used: slug = f"{base_}-{j}"; j += 1
                        x["key"] = slug; used.add(slug)
            setdraft(c, k, json.dumps(items, ensure_ascii=False), json.dumps(L(live, k), ensure_ascii=False))
    return errs, anchor

@app.route("/admin/site/<page>", methods=["GET", "POST"])
def a_site(page):
    if page not in ED: abort(404)
    need("admin") if page in ADMIN_ONLY else need()
    title, url, blocks = ED[page]; c = db()
    if request.method == "POST":
        errs, anchor = save_blocks(blocks)
        if page == "homepage":
            # Save selection as a draft; apply only after admin publishes.
            ids = [int(i) for i in request.form.getlist("featured") if i.isdigit()]
            setdraft(c, "featured_product_ids", json.dumps(ids),
                     json.dumps([r[0] for r in c.execute("SELECT id FROM products WHERE featured=1 ORDER BY id")]))
        c.commit(); log(f"Edited {title} (draft)")
        for e in errs: flash(e)
        if request.form.get("action") == "preview": return redirect("/admin/preview?go=" + url)
        flash("Saved as draft. Use Preview Website to check it, then Publish changes to make it live.")
        return redirect(request.path + ("#" + anchor if anchor else ""))
    cur = S(True); vals = {}; lists = {}
    for b in blocks:
        if b[0] == "f": vals[b[1]] = (cur.get(b[1]) != "0") if b[3] == "toggle" else (cur.get(b[1], "") if b[3] == "image" else (cur[b[1]] if b[1] in cur else DEFAULTS.get(b[1], "")))
        elif b[0] == "l": lists[b[1]] = L(cur, b[1])
    return render_template("admin/settings.html", page=page, title=title, url=url, blocks=blocks, vals=vals, lists=lists, kinds=KINDS, products=c.execute("SELECT * FROM products ORDER BY id").fetchall(), featured_ids=json.loads(cur.get("featured_product_ids") or "[]") if "featured_product_ids" in cur else [r[0] for r in c.execute("SELECT id FROM products WHERE featured=1")])

# ---------------- admin: products ----------------
@app.route("/admin/products")
def a_products():
    need(); c = db()
    return render_template("admin/products.html", items=c.execute("SELECT * FROM products ORDER BY id DESC").fetchall(), demo=cnt("SELECT COUNT(*) FROM products WHERE is_demo=1"),
        cats=c.execute("SELECT category, COUNT(*) n FROM products WHERE category!='' GROUP BY category ORDER BY category").fetchall())

@app.route("/admin/products/new", methods=["GET", "POST"])
@app.route("/admin/products/<int:pid>/edit", methods=["GET", "POST"])
def a_product(pid=None):
    need(); c = db()
    p = c.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone() if pid else None
    if pid and not p: abort(404)
    if request.method == "POST":
        f = request.form; name = f.get("name", "").strip(); img = save_img(request.files.get("image"))
        if not name: flash("Product name is required.")
        elif img is None: flash(BAD_IMG)
        else:
            specs = "\n".join(f"{l.strip()}: {v.strip()}" for l, v in zip(f.getlist("sl"), f.getlist("sv")) if l.strip() and v.strip())
            vals = [name, f.get("category", "").strip(), f.get("protein", "").strip(), f.get("description", "").strip(), f.get("packaging", "").strip(), specs,
                    f.get("availability") if f.get("availability") in AVAIL else AVAIL[0], 1 if f.get("active") else 0, 1 if f.get("featured") else 0]
            if p:
                image = p["image"]
                if img: rm_img(image); image = img
                elif f.get("remove_image"): rm_img(image); image = ""
                c.execute("UPDATE products SET name=?,category=?,protein=?,description=?,packaging=?,specs=?,availability=?,active=?,featured=?,image=?,is_demo=? WHERE id=?", vals + [image, 1 if (p["is_demo"] and f.get("is_demo")) else 0, pid]); log(f"Edited product: {name}")
            else:
                c.execute("INSERT INTO products(name,category,protein,description,packaging,specs,availability,active,featured,image,slug) VALUES(?,?,?,?,?,?,?,?,?,?,?)", vals + [img, unique_slug(c, name)]); log(f"Added product: {name}")
            c.commit(); flash("Product saved."); return redirect("/admin/products")
    specs = [l.split(":", 1) for l in (p["specs"] if p else "").splitlines() if ":" in l] + [["", ""]] * 3
    return render_template("admin/product_form.html", p=p, specs=specs, avail=AVAIL, cats=[r[0] for r in c.execute("SELECT DISTINCT category FROM products WHERE category!=''")])

@app.post("/admin/products/<int:pid>/delete")
def a_p_del(pid):
    need(); p = db().execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone() or abort(404)
    rm_img(p["image"]); db().execute("DELETE FROM products WHERE id=?", (pid,)); db().commit(); log(f"Deleted product: {p['name']}"); flash("Product deleted."); return redirect("/admin/products")

@app.post("/admin/products/<int:pid>/toggle")
def a_p_toggle(pid):
    need(); p = db().execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone() or abort(404)
    db().execute("UPDATE products SET active=? WHERE id=?", (0 if p["active"] else 1, pid)); db().commit(); log(f"{'Hid' if p['active'] else 'Published'} product: {p['name']}"); return redirect("/admin/products")

@app.post("/admin/demo/<what>")
def a_demo(what):
    need()
    if what == "hide": db().execute("UPDATE products SET active=0 WHERE is_demo=1"); log("Hid all demo products"); flash("All demo products are now hidden from the website.")
    elif what == "delete":
        for r in db().execute("SELECT image FROM products WHERE is_demo=1").fetchall(): rm_img(r["image"])
        n = cnt("SELECT COUNT(*) FROM products WHERE is_demo=1"); db().execute("DELETE FROM products WHERE is_demo=1"); log(f"Deleted {n} demo products"); flash(f"{n} demo product(s) deleted.")
    else: abort(404)
    db().commit(); return redirect("/admin/products")

@app.post("/admin/categories/rename")
def a_cat_rename():
    need(); o, n = request.form.get("old", ""), request.form.get("new", "").strip()
    if n and o: db().execute("UPDATE products SET category=? WHERE category=?", (n, o)); db().commit(); log(f"Renamed category {o} to {n}"); flash("Category renamed.")
    return redirect("/admin/products")

# ---------------- admin: gallery photos ----------------
@app.route("/admin/gallery")
def a_gallery():
    need(); secs = [x for x in L(S(True), "gallery_sections") if x["key"]]; rows = db().execute("SELECT * FROM gallery ORDER BY pos,id").fetchall()
    return render_template("admin/gallery.html", cats=[(x["key"], x["title"]) for x in secs], groups={x["key"]: [r for r in rows if r["category"] == x["key"]] for x in secs})

@app.post("/admin/gallery/upload")
def a_g_up():
    need(); cat = request.form.get("category")
    if not cat or cat not in {x["key"] for x in L(S(True), "gallery_sections")}: abort(400)
    n = 0
    for f in request.files.getlist("files"):
        img = save_img(f)
        if img is None: flash(f"Skipped {f.filename}: {BAD_IMG}"); continue
        if img:
            db().execute("INSERT INTO gallery(category,image,caption,pos) VALUES(?,?,?,?)", (cat, img, request.form.get("caption", "").strip()[:200], cnt("SELECT COALESCE(MAX(pos),0)+1 FROM gallery WHERE category=?", (cat,)))); n += 1
    db().commit(); log(f"Uploaded {n} gallery photo(s) to {cat}"); flash(f"{n} photo(s) uploaded."); return redirect("/admin/gallery")

@app.post("/admin/gallery/<int:i>/caption")
def a_g_cap(i): need(); db().execute("UPDATE gallery SET caption=? WHERE id=?", (request.form.get("caption", "").strip()[:200], i)); db().commit(); flash("Caption saved."); return redirect("/admin/gallery")

@app.post("/admin/gallery/<int:i>/delete")
def a_g_del(i):
    need(); r = db().execute("SELECT * FROM gallery WHERE id=?", (i,)).fetchone() or abort(404)
    rm_img(r["image"]); db().execute("DELETE FROM gallery WHERE id=?", (i,)); db().commit(); log("Deleted a gallery photo"); flash("Photo deleted."); return redirect("/admin/gallery")

@app.post("/admin/gallery/<int:i>/move/<d>")
def a_g_move(i, d):
    need(); r = db().execute("SELECT * FROM gallery WHERE id=?", (i,)).fetchone() or abort(404)
    ids = [x["id"] for x in db().execute("SELECT id FROM gallery WHERE category=? ORDER BY pos,id", (r["category"],))]
    a = ids.index(i); b = a - 1 if d == "up" else a + 1
    if 0 <= b < len(ids):
        ids[a], ids[b] = ids[b], ids[a]
        for n, x in enumerate(ids, 1): db().execute("UPDATE gallery SET pos=? WHERE id=?", (n, x))
        db().commit()
    return redirect("/admin/gallery")

# ---------------- admin: enquiries ----------------
def inq_query(scope):
    ph = ",".join("?" * len(PART)); where = [f"kind {'IN' if scope == 'partners' else 'NOT IN'} ({ph})"]; args = list(PART)
    q, st = request.args.get("q", "").strip(), request.args.get("status", "")
    if q: where.append("(name LIKE ? OR phone LIKE ? OR message LIKE ? OR business LIKE ? OR city LIKE ? OR notes LIKE ?)"); args += [f"%{q}%"] * 6
    if st: where.append("status=?"); args.append(st)
    return "SELECT * FROM inquiries WHERE " + " AND ".join(where) + " ORDER BY id DESC LIMIT 1000", args

def inq_page(scope):
    need(); q, a = inq_query(scope)
    return render_template("admin/enquiries.html", scope=scope, rows=db().execute(q, a).fetchall(), q=request.args.get("q", ""), st=request.args.get("status", ""),
        title="Distributor Applications" if scope == "partners" else "Customer Enquiries", statuses=ST_P if scope == "partners" else ST_C)
app.add_url_rule("/admin/enquiries", "a_enq", lambda: inq_page("customers"))
app.add_url_rule("/admin/partners", "a_part", lambda: inq_page("partners"))

@app.post("/admin/inquiry/<int:i>/update")
def a_inq_up(i):
    need(); r = db().execute("SELECT * FROM inquiries WHERE id=?", (i,)).fetchone() or abort(404)
    st = request.form.get("status"); st = st if st in (ST_P if r["kind"] in PART else ST_C) else r["status"]
    db().execute("UPDATE inquiries SET status=?, notes=? WHERE id=?", (st, request.form.get("notes", "")[:2000], i)); db().commit(); log(f"Updated enquiry from {r['name']} ({st})"); flash("Saved.")
    return back("/admin/partners" if r["kind"] in PART else "/admin/enquiries")

@app.post("/admin/inquiry/<int:i>/delete")
def a_inq_del(i):
    need(); r = db().execute("SELECT * FROM inquiries WHERE id=?", (i,)).fetchone() or abort(404)
    db().execute("DELETE FROM inquiries WHERE id=?", (i,)); db().commit(); log(f"Deleted enquiry from {r['name']}"); flash("Enquiry deleted.")
    return redirect("/admin/partners" if r["kind"] in PART else "/admin/enquiries")

def safe(v):
    v = str(v or ""); return "'" + v if v and v[0] in "=+-@\t\r" else v

@app.route("/admin/export/<scope>")
def a_export(scope):
    need()
    if scope not in ("customers", "partners"): abort(404)
    q, a = inq_query(scope); out = io.StringIO(); w = csv.writer(out)
    w.writerow(["ID", "Date", "Name", "Phone", "Type", "Business", "City", "Message", "Status", "Notes"])
    for r in db().execute(q, a): w.writerow([r["id"], r["created"]] + [safe(r[k]) for k in ("name", "phone", "kind", "business", "city", "message", "status", "notes")])
    log(f"Exported {scope} to CSV")
    return Response("\ufeff" + out.getvalue(), mimetype="text/csv", headers={"Content-Disposition": f"attachment; filename=proteinveda-{scope}.csv"})

# ---------------- admin: blog ----------------
@app.route("/admin/blog")
def a_blog(): need(); return render_template("admin/blog.html", posts=db().execute("SELECT * FROM posts ORDER BY id DESC").fetchall())

@app.route("/admin/blog/new", methods=["GET", "POST"])
@app.route("/admin/blog/<int:bid>/edit", methods=["GET", "POST"])
def a_post(bid=None):
    need(); c = db(); p = c.execute("SELECT * FROM posts WHERE id=?", (bid,)).fetchone() if bid else None
    if bid and not p: abort(404)
    if request.method == "POST":
        f = request.form; t = f.get("title", "").strip(); img = save_img(request.files.get("cover"))
        if not t: flash("Title is required.")
        elif img is None: flash(BAD_IMG)
        else:
            vals = [t, f.get("excerpt", "").strip()[:400], f.get("body", "").strip(), 1 if f.get("published") else 0]
            if p:
                cover = p["cover"]
                if img: rm_img(cover); cover = img
                elif f.get("remove_cover"): rm_img(cover); cover = ""
                c.execute("UPDATE posts SET title=?,excerpt=?,body=?,published=?,cover=? WHERE id=?", vals + [cover, bid]); log(f"Edited article: {t}")
            else: c.execute("INSERT INTO posts(title,excerpt,body,published,cover,slug) VALUES(?,?,?,?,?,?)", vals + [img, unique_slug(c, t, "posts")]); log(f"Created article: {t}")
            c.commit(); flash("Article saved."); return redirect("/admin/blog")
    return render_template("admin/blog_form.html", p=p)

@app.post("/admin/blog/<int:bid>/delete")
def a_post_del(bid):
    need(); p = db().execute("SELECT * FROM posts WHERE id=?", (bid,)).fetchone() or abort(404)
    rm_img(p["cover"]); db().execute("DELETE FROM posts WHERE id=?", (bid,)); db().commit(); log(f"Deleted article: {p['title']}"); flash("Article deleted."); return redirect("/admin/blog")

@app.post("/admin/blog/<int:bid>/toggle")
def a_post_tg(bid):
    need(); p = db().execute("SELECT * FROM posts WHERE id=?", (bid,)).fetchone() or abort(404)
    db().execute("UPDATE posts SET published=? WHERE id=?", (0 if p["published"] else 1, bid)); db().commit(); log(f"{'Unpublished' if p['published'] else 'Published'} article: {p['title']}"); return redirect("/admin/blog")

# ---------------- admin: media library ----------------
def usage():
    u = {}
    def add(blob, label):
        for n in re.findall(r"[0-9a-f]{32}\.\w+", blob or ""): u.setdefault(n, set()).add(label)
    for r in db().execute("SELECT k,v,draft FROM settings"): add(r["v"], "Page content: " + r["k"]); add(r["draft"], "Unpublished draft: " + r["k"])
    for r in db().execute("SELECT name,image FROM products"): add(r["image"], "Product: " + (r["name"] or ""))
    for r in db().execute("SELECT category,image FROM gallery"): add(r["image"], "Gallery: " + (r["category"] or ""))
    for r in db().execute("SELECT title,cover FROM posts"): add(r["cover"], "Blog: " + (r["title"] or ""))
    return u

@app.route("/admin/media")
def a_media():
    need(); u = usage(); files = []
    for f in sorted(os.listdir(UP), key=lambda x: -os.path.getmtime(os.path.join(UP, x))):
        if re.fullmatch(IMGRE, f): files.append({"name": f, "size": os.path.getsize(os.path.join(UP, f)), "used": sorted(u.get(f, []))})
    return render_template("admin/media.html", files=files, unused=sum(1 for x in files if not x["used"]))

@app.post("/admin/media/delete")
def a_media_del():
    need("admin"); n = request.form.get("name", "")
    if re.fullmatch(IMGRE, n) and not usage().get(n): rm_img(n); log("Deleted unused image"); flash("Image deleted.")
    else: flash("That image is in use and cannot be deleted.")
    return redirect("/admin/media")

@app.post("/admin/media/clean")
def a_media_clean():
    need("admin"); u = usage(); n = 0
    for f in os.listdir(UP):
        if re.fullmatch(IMGRE, f) and not u.get(f): rm_img(f); n += 1
    log(f"Deleted {n} unused image(s)"); flash(f"{n} unused image(s) deleted."); return redirect("/admin/media")

# ---------------- admin: backup & restore ----------------
def make_backup_zip(fobj):
    tmp = tempfile.mktemp(suffix=".db"); src = sqlite3.connect(DB); dst = sqlite3.connect(tmp); src.backup(dst); dst.close(); src.close(); n = 0
    with zipfile.ZipFile(fobj, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(tmp, "proteinveda.db")
        for f in sorted(os.listdir(UP)):
            if re.fullmatch(IMGRE, f): z.write(os.path.join(UP, f), "uploads/" + f); n += 1
        z.writestr("backup-info.txt", f"Protein Veda backup\nCreated: {datetime.now():%Y-%m-%d %H:%M:%S}\nImages: {n}\n")
    os.remove(tmp); return n

def save_server_backup(prefix="backup"):
    p = os.path.join(BK, f"{prefix}-{datetime.now():%Y%m%d-%H%M%S}.zip")
    with open(p, "wb") as f: make_backup_zip(f)
    old = sorted(x for x in os.listdir(BK) if x.startswith(prefix + "-"))[:-14]
    for x in old: os.remove(os.path.join(BK, x))
    return p

def note_backup():
    db().execute("INSERT OR REPLACE INTO settings(k,v) VALUES('last_backup',?)", (datetime.now().strftime("%Y-%m-%d %H:%M"),)); db().commit()

def restore_zip(fobj):
    try: z = zipfile.ZipFile(fobj)
    except zipfile.BadZipFile: return "That file is not a valid backup zip."
    if "proteinveda.db" not in z.namelist(): return "This zip does not contain proteinveda.db, so it is not a Protein Veda backup."
    entries = z.infolist()
    if sum(i.file_size for i in entries) > 1_500_000_000: return "Backup is too large."
    if len(entries) > 10000: return "Backup contains too many files."
    for item in entries:
        if item.filename == "proteinveda.db":
            if item.file_size > 1_000_000_000: return "Database in backup is too large."
        elif re.fullmatch(r"uploads/(" + IMGRE + ")", item.filename):
            if item.file_size > 8 * 1024 * 1024: return "Backup contains an oversized image."
            with z.open(item) as stream:
                if not sigok(stream.read(12)): return "Backup contains an invalid image."
        elif item.filename != "backup-info.txt":
            return "Backup contains unexpected files."
    tmp = tempfile.mktemp(suffix=".db")
    with open(tmp, "wb") as f: f.write(z.read("proteinveda.db"))
    try:
        c = sqlite3.connect(tmp); okdb = c.execute("PRAGMA integrity_check").fetchone()[0] == "ok"; tabs = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}; c.close()
    except sqlite3.DatabaseError: os.remove(tmp); return "The database inside this backup is damaged."
    if not okdb or not {"products", "settings", "admin", "inquiries"} <= tabs: os.remove(tmp); return "The database inside this backup is damaged or incomplete."
    save_server_backup("pre-restore")
    src = sqlite3.connect(tmp); dst = sqlite3.connect(DB); src.backup(dst); src.close(); dst.close(); os.remove(tmp)
    n = 0
    for name in z.namelist():
        m = re.fullmatch(r"uploads/(" + IMGRE + ")", name)
        if m:
            data = z.read(name)
            if sigok(data[:12]): open(os.path.join(UP, m.group(1)), "wb").write(data); n += 1
    init_db(); return n

@app.route("/admin/backup")
def a_backup():
    need("admin"); files = []
    for f in sorted(os.listdir(BK), reverse=True):
        if f.endswith(".zip"): files.append({"name": f, "size": os.path.getsize(os.path.join(BK, f))})
    return render_template("admin/backup.html", files=files, imgs=len([f for f in os.listdir(UP) if re.fullmatch(IMGRE, f)]), dbsize=os.path.getsize(DB), last=S(False).get("last_backup", ""))

@app.post("/admin/backup/download")
def a_bk_dl():
    need("admin"); buf = io.BytesIO(); make_backup_zip(buf); note_backup(); log("Downloaded a backup")
    return Response(buf.getvalue(), mimetype="application/zip", headers={"Content-Disposition": f"attachment; filename=proteinveda-backup-{datetime.now():%Y%m%d-%H%M}.zip"})

@app.post("/admin/backup/save")
def a_bk_save(): need("admin"); save_server_backup(); note_backup(); log("Saved a backup on the server"); flash("Backup saved in the server's backups folder."); return redirect("/admin/backup")

@app.route("/admin/backup/file/<name>")
def a_bk_file(name):
    need("admin")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+\.zip", name) or not os.path.exists(os.path.join(BK, name)): abort(404)
    return Response(open(os.path.join(BK, name), "rb").read(), mimetype="application/zip", headers={"Content-Disposition": f"attachment; filename={name}"})

@app.post("/admin/backup/restore")
def a_bk_restore():
    need("admin"); f = request.files.get("backup")
    if request.form.get("confirm", "").strip() != "RESTORE": flash("Type RESTORE in the box to confirm."); return redirect("/admin/backup")
    if not f or not f.filename: flash("Please choose a backup .zip file."); return redirect("/admin/backup")
    r = restore_zip(f.stream)
    if isinstance(r, str): flash(r); return redirect("/admin/backup")
    session.clear(); flash(f"Restore complete ({r} images restored). Please log in again. A safety copy of the previous data was saved in the backups folder."); return redirect("/admin/login")

init_db()
if __name__ == "__main__": app.run(debug=False, port=5000)
