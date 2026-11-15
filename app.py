import os, sqlite3, secrets, time
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, flash, g, abort
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from content import SITE
from seed_events import init_event_tables

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-only-change-me")
app.permanent_session_lifetime = 60*60*24*30
os.makedirs(app.instance_path, exist_ok=True)
DB = os.path.join(app.instance_path, "hackathon.db")
ALLOWED_DOMAIN = os.environ.get("ALLOWED_EMAIL_DOMAIN", "")

UPLOAD_FOLDER = os.path.join(app.root_path, "static", "uploads", "payments")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
SUBMISSION_FOLDER = os.path.join(app.root_path, "static", "uploads", "submissions")
os.makedirs(SUBMISSION_FOLDER, exist_ok=True)

try:
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
    c.executescript("""
    CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY,
        name TEXT,
        email TEXT UNIQUE,
        pw TEXT,
        role TEXT DEFAULT 'participant'
    );
    CREATE TABLE IF NOT EXISTS teams(
        id INTEGER PRIMARY KEY,
        team_id TEXT UNIQUE,
        team_pw TEXT,
        owner INTEGER UNIQUE,
        name TEXT,
        domain TEXT,
        payment_screenshot TEXT,
        payment_status TEXT DEFAULT 'Pending Verification',
        terms_agreed INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS members(
        id INTEGER PRIMARY KEY,
        team INTEGER,
        is_leader INTEGER DEFAULT 0,
        fname TEXT,
        lname TEXT,
        email TEXT,
        phone TEXT,
        gender TEXT,
        college TEXT,
        course TEXT,
        branch TEXT,
        duration TEXT,
        year TEXT,
        grad_year TEXT,
        enrollment TEXT,
        FOREIGN KEY(team) REFERENCES teams(id) ON DELETE CASCADE
    );
    """)
init_event_tables(DB)

def generate_team_credentials():
    with sqlite3.connect(DB) as c:
        row = c.execute("SELECT count(*) FROM teams").fetchone()
        num = 1001 + (row[0] if row else 0)
        while c.execute("SELECT 1 FROM teams WHERE team_id=?", (f"CN-{num}",)).fetchone():
            num += 1
        tid = f"CN-{num}"
    chars = "abcdefghjkmnpqrstuvwxyz23456789"
    tpw = "CN" + "".join(secrets.choice(chars) for _ in range(6))
    return tid, tpw

def user():
    return db().execute("SELECT * FROM users WHERE id=?", (session.get("uid"),)).fetchone() if session.get("uid") else None

def current_team():
    if session.get("team_id"):
        t = db().execute("SELECT * FROM teams WHERE id=?", (session["team_id"],)).fetchone()
        if t: return t
    if session.get("uid"):
        return db().execute("SELECT * FROM teams WHERE owner=?", (session["uid"],)).fetchone()
    return None

@app.context_processor
def inject():
    return dict(C=SITE, me=user(), my_team=current_team(), csrf=lambda: session.setdefault("csrf", secrets.token_hex(16)))

@app.before_request
def check_csrf():
    if request.method == "POST":
        token = request.form.get("csrf")
        sess_token = session.get("csrf")
        if not sess_token or token != sess_token:
            abort(400)

def login_required(f):
    @wraps(f)
    def w(*a, **k):
        if not session.get("uid") and not session.get("team_id"):
            flash("Please log in first.")
            return redirect(url_for("login"))
        return f(*a, **k)
    return w

def valid_email(e):
    return "@" in e and (not ALLOWED_DOMAIN or e.endswith("@" + ALLOWED_DOMAIN))

@app.route("/", methods=["GET", "POST"])
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        identifier = (request.form.get("team_id") or request.form.get("email") or "").strip()
        pwd = request.form.get("password", "")

        # 1. Try logging in via Team ID & auto-generated Team Password
        t = db().execute("SELECT * FROM teams WHERE UPPER(team_id)=UPPER(?)", (identifier,)).fetchone()
        if t and (t["team_pw"] == pwd or check_password_hash(t["team_pw"], pwd)):
            session.clear()
            session["team_id"] = t["id"]
            session["uid"] = t["owner"]
            session.permanent = bool(request.form.get("remember"))
            return redirect(url_for("dashboard"))

        # 2. Try logging in via Leader Email & Password
        u = db().execute("SELECT * FROM users WHERE LOWER(email)=LOWER(?)", (identifier,)).fetchone()
        if u and check_password_hash(u["pw"], pwd):
            session.clear()
            session["uid"] = u["id"]
            session.permanent = bool(request.form.get("remember"))
            t_user = db().execute("SELECT id FROM teams WHERE owner=?", (u["id"],)).fetchone()
            if t_user:
                session["team_id"] = t_user["id"]
            return redirect(url_for("dashboard"))

        flash("Incorrect Team ID or password.")
    return render_template("login.html", body="login-page home")

@app.route("/register", methods=["GET", "POST"])
def register():
    return redirect(url_for("team"))

@app.route("/login/google")
def login_google():
    if not google:
        flash("Google login isn’t set up yet. Add GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET to enable.")
        return redirect(url_for("login"))
    return google.authorize_redirect(url_for("google_cb", _external=True))

@app.route("/auth/google/callback")
def google_cb():
    if not google:
        return redirect(url_for("login"))
    info = google.authorize_access_token().get("userinfo")
    e = info["email"].lower()
    if not valid_email(e):
        flash("Use your college email ID.")
        return redirect(url_for("login"))
    u = db().execute("SELECT * FROM users WHERE email=?", (e,)).fetchone()
    if not u:
        cur = db().execute("INSERT INTO users(name,email,pw) VALUES(?,?,?)",
                          (info.get("name", e), e, generate_password_hash(secrets.token_hex(16))))
        db().commit()
        uid = cur.lastrowid
    else:
        uid = u["id"]
    session.clear()
    session["uid"] = uid

    t = db().execute("SELECT id FROM teams WHERE owner=?", (uid,)).fetchone()
    if t:
        session["team_id"] = t["id"]
        return redirect(url_for("dashboard"))
    return redirect(url_for("team"))

@app.route("/forgot-password")
def forgot():
    flash("Password reset is managed by organizers. Please contact ACM CodeNite support.")
    return redirect(url_for("login"))

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/team-registration", methods=["GET", "POST"])
def team():
    if request.method == "POST":
        f = request.form
        if not f.get("terms_agreed"):
            flash("Please accept the Terms & Conditions to proceed.")
            return redirect(url_for("team"))

        team_name = f.get("team_name", "").strip()
        domain = f.get("domain", "").strip()
        if not team_name or not domain:
            flash("Please provide your team name and preferred track.")
            return redirect(url_for("team"))

        # Payment screenshot upload
        file = request.files.get("payment_screenshot")
        screenshot_path = ""
        if file and file.filename:
            fn = secure_filename(file.filename)
            ext = os.path.splitext(fn)[1].lower()
            if ext in (".jpg", ".jpeg", ".png", ".webp"):
                unique_fn = f"{int(time.time())}_{secrets.token_hex(4)}{ext}"
                file.save(os.path.join(UPLOAD_FOLDER, unique_fn))
                screenshot_path = f"uploads/payments/{unique_fn}"
            else:
                flash("Invalid payment screenshot file format. Please upload JPG, PNG, or WEBP.")
                return redirect(url_for("team"))
        else:
            flash("Please upload your ₹50 payment screenshot.")
            return redirect(url_for("team"))

        # Team Leader
        leader_fname = f.get("leader_fname", "").strip()
        leader_lname = f.get("leader_lname", "").strip()
        leader_email = f.get("leader_email", "").strip().lower()
        if not leader_fname or not leader_email:
            flash("Please enter team leader name and college email.")
            return redirect(url_for("team"))

        members_data = [{
            "is_leader": 1,
            "fname": leader_fname,
            "lname": leader_lname,
            "email": leader_email,
            "phone": f.get("leader_phone", "").strip(),
            "gender": f.get("leader_gender", "").strip(),
            "college": f.get("leader_college", "").strip(),
            "course": f.get("leader_course", "").strip(),
            "branch": f.get("leader_branch", "").strip(),
            "duration": f.get("leader_duration", "4 Years").strip(),
            "year": f.get("leader_year", "").strip(),
            "grad_year": f.get("leader_grad_year", "").strip(),
            "enrollment": f.get("leader_enrollment", "").strip()
        }]

        # Members 2 to 6
        for num in range(2, 7):
            mfname = f.get(f"m{num}_fname", "").strip()
            if mfname:
                members_data.append({
                    "is_leader": 0,
                    "fname": mfname,
                    "lname": f.get(f"m{num}_lname", "").strip(),
                    "email": f.get(f"m{num}_email", "").strip().lower(),
                    "phone": f.get(f"m{num}_phone", "").strip(),
                    "gender": f.get(f"m{num}_gender", "").strip(),
                    "college": f.get(f"m{num}_college", "").strip(),
                    "course": f.get(f"m{num}_course", "").strip(),
                    "branch": f.get(f"m{num}_branch", "").strip(),
                    "duration": f.get(f"m{num}_duration", "4 Years").strip(),
                    "year": f.get(f"m{num}_year", "").strip(),
                    "grad_year": f.get(f"m{num}_grad_year", "").strip(),
                    "enrollment": f.get(f"m{num}_enrollment", "").strip()
                })

        if not (4 <= len(members_data) <= 6):
            flash("Teams must have a minimum of 4 members and a maximum of 6 members.")
            return redirect(url_for("team"))

        d = db()
        u = d.execute("SELECT * FROM users WHERE email=?", (leader_email,)).fetchone()
        if not u:
            cur = d.execute("INSERT INTO users(name,email,pw) VALUES(?,?,?)",
                            (f"{leader_fname} {leader_lname}".strip(), leader_email, generate_password_hash(secrets.token_hex(16))))
            uid = cur.lastrowid
        else:
            uid = u["id"]

        session["uid"] = uid

        # Check existing team
        prev_t = d.execute("SELECT id FROM teams WHERE owner=?", (uid,)).fetchone()
        if prev_t:
            d.execute("DELETE FROM members WHERE team=?", (prev_t["id"],))
            d.execute("DELETE FROM teams WHERE id=?", (prev_t["id"],))

        tid, tpw = generate_team_credentials()

        cur = d.execute("""INSERT INTO teams(team_id, team_pw, owner, name, domain, payment_screenshot, payment_status, terms_agreed)
                           VALUES(?,?,?,?,?,?,?,1)""",
                        (tid, tpw, uid, team_name, domain, screenshot_path, 'Pending Verification'))
        new_team_pk = cur.lastrowid
        session["team_id"] = new_team_pk

        for m in members_data:
            d.execute("""INSERT INTO members(team, is_leader, fname, lname, email, phone, gender, college, course, branch, duration, year, grad_year, enrollment)
                         VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                      (new_team_pk, m["is_leader"], m["fname"], m["lname"], m["email"], m["phone"], m["gender"], m["college"],
                       m["course"], m["branch"], m["duration"], m["year"], m["grad_year"], m["enrollment"]))
        d.commit()

        return render_template("team_success.html", team_id=tid, team_pw=tpw, team_name=team_name, body="inner")

    return render_template("team_registration.html", body="inner")

@app.route("/dashboard")
@login_required
def dashboard():
    t = current_team()
    m = db().execute("SELECT * FROM members WHERE team=? ORDER BY is_leader DESC, id ASC", (t["id"],)).fetchall() if t else []
    return render_template("dashboard.html", team=t, members=m, body="inner")

@app.route("/team/edit", methods=["POST"])
@login_required
def edit_team():
    t = current_team()
    if not t:
        abort(403)
    new_name = request.form.get("team_name", "").strip()
    new_domain = request.form.get("domain", "").strip()
    if new_name and new_domain:
        db().execute("UPDATE teams SET name=?, domain=? WHERE id=?", (new_name, new_domain, t["id"]))
        db().commit()
        flash("Team information updated successfully.")
    return redirect(url_for("dashboard"))

@app.route("/member/edit/<int:mid>", methods=["POST"])
@login_required
def edit_member(mid):
    t = current_team()
    if not t:
        abort(403)
    m = db().execute("SELECT * FROM members WHERE id=? AND team=?", (mid, t["id"])).fetchone()
    if not m:
        abort(404)
    f = request.form
    # Leader's primary email cannot be changed; teammates' email CAN be changed
    new_email = m["email"] if m["is_leader"] else f.get("email", m["email"]).strip().lower()

    db().execute("""UPDATE members SET
        fname=?, lname=?, email=?, phone=?, gender=?, college=?,
        course=?, branch=?, duration=?, year=?, grad_year=?, enrollment=?
        WHERE id=? AND team=?""",
        (f.get("fname", m["fname"]).strip(),
         f.get("lname", m["lname"]).strip(),
         new_email,
         f.get("phone", m["phone"]).strip(),
         f.get("gender", m["gender"]).strip(),
         f.get("college", m["college"]).strip(),
         f.get("course", m["course"]).strip(),
         f.get("branch", m["branch"]).strip(),
         f.get("duration", m["duration"]).strip(),
         f.get("year", m["year"]).strip(),
         f.get("grad_year", m["grad_year"]).strip(),
         f.get("enrollment", m["enrollment"]).strip(),
         mid, t["id"]))
    db().commit()
    flash(f"Details updated for {f.get('fname', 'member')}.")
    return redirect(url_for("dashboard"))

@app.route("/member/delete/<int:mid>", methods=["POST"])
@login_required
def delete_member(mid):
    t = current_team()
    if not t:
        abort(403)
    count = db().execute("SELECT count(*) FROM members WHERE team=?", (t["id"],)).fetchone()[0]
    if count <= 4:
        flash("Cannot remove member: Teams must have at least 4 members.")
        return redirect(url_for("dashboard"))
    m = db().execute("SELECT * FROM members WHERE id=? AND team=?", (mid, t["id"])).fetchone()
    if not m:
        abort(404)
    if m["is_leader"]:
        flash("Cannot remove the Team Leader.")
        return redirect(url_for("dashboard"))
    db().execute("DELETE FROM members WHERE id=? AND team=?", (mid, t["id"]))
    db().commit()
    flash("Member removed from team.")
    return redirect(url_for("dashboard"))

@app.route("/member/add", methods=["POST"])
@login_required
def add_member():
    t = current_team()
    if not t:
        abort(403)
    count = db().execute("SELECT count(*) FROM members WHERE team=?", (t["id"],)).fetchone()[0]
    if count >= 6:
        flash("Cannot add more members: Maximum 6 members allowed.")
        return redirect(url_for("dashboard"))
    f = request.form
    fname = f.get("fname", "").strip()
    email = f.get("email", "").strip().lower()
    if not fname or not email:
        flash("Please provide member name and college email.")
        return redirect(url_for("dashboard"))
    db().execute("""INSERT INTO members(team, is_leader, fname, lname, email, phone, gender, college, course, branch, duration, year, grad_year, enrollment)
                    VALUES(?,0,?,?,?,?,?,?,?,?,?,?,?,?)""",
                 (t["id"], fname, f.get("lname", "").strip(), email, f.get("phone", "").strip(),
                  f.get("gender", "").strip(), f.get("college", "").strip(), f.get("course", "").strip(),
                  f.get("branch", "").strip(), f.get("duration", "4 Years").strip(),
                  f.get("year", "").strip(), f.get("grad_year", "").strip(), f.get("enrollment", "").strip()))
    db().commit()
    flash(f"Added {fname} to the team roster.")
    return redirect(url_for("dashboard"))

@app.route("/events")
def events():
    info_rows = db().execute("SELECT key, value FROM event_info").fetchall()
    info = {r["key"]: r["value"] for r in info_rows}
    schedule = db().execute("SELECT * FROM event_schedule ORDER BY order_idx, id").fetchall()
    tracks = db().execute("SELECT * FROM event_tracks ORDER BY order_idx, id").fetchall()
    problems = db().execute("SELECT * FROM event_problems ORDER BY id").fetchall()
    rules = db().execute("SELECT * FROM event_rules ORDER BY order_idx, id").fetchall()
    judging = db().execute("SELECT * FROM event_judging ORDER BY order_idx, id").fetchall()
    rounds = db().execute("SELECT * FROM event_rounds ORDER BY order_idx, id").fetchall()

    t = current_team()
    submissions = {}
    if t:
        sub_rows = db().execute("SELECT * FROM team_submissions WHERE team_id=?", (t["id"],)).fetchall()
        submissions = {r["round_id"]: dict(r) for r in sub_rows}

    schedule_by_day = {}
    for item in schedule:
        schedule_by_day.setdefault(item["day_title"], []).append(dict(item))

    problems_by_track = {}
    for prob in problems:
        problems_by_track.setdefault(prob["track_id"], []).append(dict(prob))

    rules_by_category = {}
    for r in rules:
        rules_by_category.setdefault(r["category"], []).append(r["rule_text"])

    return render_template("events.html",
                           info=info,
                           schedule_by_day=schedule_by_day,
                           tracks=[dict(x) for x in tracks],
                           problems_by_track=problems_by_track,
                           rules_by_category=rules_by_category,
                           judging=[dict(x) for x in judging],
                           rounds=[dict(x) for x in rounds],
                           submissions=submissions,
                           team=t,
                           body="inner")

@app.route("/events/submit/<int:round_id>", methods=["POST"])
def submit_round(round_id):
    t = current_team()
    if not t:
        flash("Please log in with your Team credentials to make a submission.")
        return redirect(url_for("login"))

    round_data = db().execute("SELECT * FROM event_rounds WHERE id=?", (round_id,)).fetchone()
    if not round_data:
        abort(404)

    project_title = request.form.get("project_title", "").strip()
    project_summary = request.form.get("project_summary", "").strip()
    drive_link = request.form.get("drive_link", "").strip()
    github_link = request.form.get("github_link", "").strip()
    demo_link = request.form.get("demo_link", "").strip()

    file_path = None
    if "submission_file" in request.files:
        file = request.files["submission_file"]
        if file and file.filename:
            ext = os.path.splitext(file.filename)[1].lower()
            if ext not in (".pdf", ".ppt", ".pptx", ".zip", ".rar"):
                flash("Allowed file types: .pdf, .ppt, .pptx, .zip, .rar")
                return redirect(url_for("events"))
            filename = f"team_{t['team_id']}_r{round_id}_{secrets.token_hex(4)}{ext}"
            file.save(os.path.join(SUBMISSION_FOLDER, filename))
            file_path = filename

    existing = db().execute("SELECT id, file_path FROM team_submissions WHERE team_id=? AND round_id=?", (t["id"], round_id)).fetchone()
    if existing:
        saved_file = file_path if file_path else existing["file_path"]
        db().execute("""
            UPDATE team_submissions
            SET project_title=?, project_summary=?, file_path=?, drive_link=?, github_link=?, demo_link=?, updated_at=CURRENT_TIMESTAMP, status='Submitted'
            WHERE id=?
        """, (project_title, project_summary, saved_file, drive_link, github_link, demo_link, existing["id"]))
    else:
        db().execute("""
            INSERT INTO team_submissions(team_id, round_id, project_title, project_summary, file_path, drive_link, github_link, demo_link, status)
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, 'Submitted')
        """, (t["id"], round_id, project_title, project_summary, file_path, drive_link, github_link, demo_link))

    db().commit()
    flash(f"Submission for {round_data['title']} saved successfully!")
    return redirect(url_for("events"))

@app.route("/<page>")
def info(page):
    if page not in ("prizes", "about", "faq"):
        abort(404)
    return render_template("info.html", page=page, body="inner")

if __name__ == "__main__":
    app.run(debug=True)
