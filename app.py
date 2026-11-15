import os, sqlite3, secrets
from flask import Flask, render_template, request, redirect, url_for, session, flash, g, abort
from werkzeug.security import generate_password_hash, check_password_hash
from content import SITE

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-only-change-me")
app.permanent_session_lifetime = 60*60*24*30
os.makedirs(app.instance_path, exist_ok=True)
DB = os.path.join(app.instance_path, "hackathon.db")
ALLOWED_DOMAIN = os.environ.get("ALLOWED_EMAIL_DOMAIN", "")   # e.g. "college.edu" (blank = any email)

try:  # Google OAuth is optional; set GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET to enable
    from authlib.integrations.flask_client import OAuth
    google = OAuth(app).register("google", client_id=os.environ.get("GOOGLE_CLIENT_ID"),
        client_secret=os.environ.get("GOOGLE_CLIENT_SECRET"),
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"}) if os.environ.get("GOOGLE_CLIENT_ID") else None
except ImportError:
    google = None

def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB); g.db.row_factory = sqlite3.Row
    return g.db
@app.teardown_appcontext
def close(_): 
    d = g.pop("db", None)
    if d: d.close()
with sqlite3.connect(DB) as c:
    c.executescript("""CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, name TEXT, email TEXT UNIQUE, pw TEXT);
    CREATE TABLE IF NOT EXISTS teams(id INTEGER PRIMARY KEY, owner INTEGER UNIQUE, name TEXT, college TEXT, idea TEXT);
    CREATE TABLE IF NOT EXISTS members(id INTEGER PRIMARY KEY, team INTEGER, name TEXT, email TEXT);""")

def user():
    return db().execute("SELECT * FROM users WHERE id=?", (session.get("uid"),)).fetchone() if session.get("uid") else None
@app.context_processor
def inject():
    return dict(C=SITE, me=user(), csrf=lambda: session.setdefault("csrf", secrets.token_hex(16)))
@app.before_request
def check_csrf():
    if request.method == "POST" and request.form.get("csrf") != session.get("csrf"): abort(400)
def login_required(f):
    from functools import wraps
    @wraps(f)
    def w(*a, **k):
        if not session.get("uid"): flash("Please log in first."); return redirect(url_for("login"))
        return f(*a, **k)
    return w
def valid_email(e): return "@" in e and (not ALLOWED_DOMAIN or e.endswith("@"+ALLOWED_DOMAIN))

@app.route("/", methods=["GET","POST"])
@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email","").strip().lower()
        u = db().execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        if u and check_password_hash(u["pw"], request.form.get("password","")):
            session.clear(); session["uid"] = u["id"]; session.permanent = bool(request.form.get("remember"))
            return redirect(url_for("dashboard"))
        flash("Incorrect email or password.")
    return render_template("login.html", body="login-page home")

@app.route("/register", methods=["GET","POST"])
def register():
    if request.method == "POST":
        n, e, p = request.form.get("name","").strip(), request.form.get("email","").strip().lower(), request.form.get("password","")
        if not n or not valid_email(e): flash("Enter your name and a valid college email ID.")
        elif len(p) < 8: flash("Password must be at least 8 characters.")
        elif db().execute("SELECT 1 FROM users WHERE email=?", (e,)).fetchone(): flash("That email is already registered. Log in instead.")
        else:
            cur = db().execute("INSERT INTO users(name,email,pw) VALUES(?,?,?)", (n,e,generate_password_hash(p))); db().commit()
            session.clear(); session["uid"] = cur.lastrowid; return redirect(url_for("team"))
    return render_template("register.html", body="login-page")

@app.route("/login/google")
def login_google():
    if not google: flash("Google login isn’t set up yet. Add GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET."); return redirect(url_for("login"))
    return google.authorize_redirect(url_for("google_cb", _external=True))
@app.route("/auth/google/callback")
def google_cb():
    info = google.authorize_access_token().get("userinfo")
    e = info["email"].lower()
    if not valid_email(e): flash("Use your college email ID."); return redirect(url_for("login"))
    u = db().execute("SELECT * FROM users WHERE email=?", (e,)).fetchone()
    if not u:
        cur = db().execute("INSERT INTO users(name,email,pw) VALUES(?,?,?)", (info.get("name",e),e,generate_password_hash(secrets.token_hex(16)))); db().commit(); uid = cur.lastrowid
    else: uid = u["id"]
    session.clear(); session["uid"] = uid; return redirect(url_for("dashboard"))

@app.route("/forgot-password")
def forgot():
    flash("Password reset by email isn’t configured yet. Please contact the organisers."); return redirect(url_for("login"))
@app.route("/logout")
def logout(): session.clear(); return redirect(url_for("login"))

@app.route("/dashboard")
@login_required
def dashboard():
    t = db().execute("SELECT * FROM teams WHERE owner=?", (session["uid"],)).fetchone()
    m = db().execute("SELECT * FROM members WHERE team=?", (t["id"],)).fetchall() if t else []
    return render_template("dashboard.html", team=t, members=m)

@app.route("/team-registration", methods=["GET","POST"])
@login_required
def team():
    if request.method == "POST":
        f = request.form; name = f.get("team_name","").strip()
        names, emails = f.getlist("m_name"), f.getlist("m_email")
        rows = [(a.strip(), b.strip().lower()) for a, b in zip(names, emails) if a.strip()]
        if not name or not (2 <= len(rows) <= 4): flash("Add a team name and 2 to 4 members.")
        else:
            d = db(); d.execute("DELETE FROM members WHERE team IN (SELECT id FROM teams WHERE owner=?)", (session["uid"],))
            d.execute("DELETE FROM teams WHERE owner=?", (session["uid"],))
            cur = d.execute("INSERT INTO teams(owner,name,college,idea) VALUES(?,?,?,?)", (session["uid"], name, f.get("college","").strip(), f.get("idea","").strip()))
            d.executemany("INSERT INTO members(team,name,email) VALUES(?,?,?)", [(cur.lastrowid,a,b) for a,b in rows]); d.commit()
            flash("Team registered."); return redirect(url_for("dashboard"))
    return render_template("team_registration.html", body="inner")

@app.route("/<page>")
def info(page):
    if page not in ("events","prizes","about","faq"): abort(404)
    return render_template("info.html", page=page, body="inner")

if __name__ == "__main__":
    app.run(debug=True)
