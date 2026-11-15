import os, sqlite3, secrets, time
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, flash, g, abort, Response
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from content import SITE
from seed_events import init_event_tables
from seed_prizes import init_prize_tables
from seed_about_faq import init_about_faq_tables
from admin_core import (
    init_admin_tables,
    admin_required,
    log_admin_action,
    generate_teams_csv,
    ADMIN_SECRET_SLUG
)

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
init_prize_tables(DB)
init_about_faq_tables(DB)
init_admin_tables(DB)

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

@app.route("/prizes")
def prizes():
    overview_rows = db().execute("SELECT key, value FROM prize_overview").fetchall()
    overview = {r["key"]: r["value"] for r in overview_rows}
    podium_rows = db().execute("SELECT * FROM prize_podium ORDER BY order_idx, id").fetchall()
    podium = []
    for r in podium_rows:
        d = dict(r)
        d["perks_list"] = [p.strip() for p in (r["perks"] or "").split("\n") if p.strip()]
        podium.append(d)
    categories = db().execute("SELECT * FROM prize_categories ORDER BY order_idx, id").fetchall()
    perks = db().execute("SELECT * FROM prize_perks ORDER BY order_idx, id").fetchall()
    rules = db().execute("SELECT * FROM prize_rules ORDER BY order_idx, id").fetchall()

    t = current_team()
    return render_template("prizes.html",
                           overview=overview,
                           podium=podium,
                           categories=[dict(x) for x in categories],
                           perks=[dict(x) for x in perks],
                           rules=[dict(x) for x in rules],
                           team=t,
                           body="inner")

@app.route("/about")
def about():
    about_rows = db().execute("SELECT key, value FROM about_info").fetchall()
    info = {r["key"]: r["value"] for r in about_rows}
    pillars = db().execute("SELECT * FROM about_pillars ORDER BY order_idx, id").fetchall()
    facilities = db().execute("SELECT * FROM about_facilities ORDER BY order_idx, id").fetchall()
    t = current_team()
    return render_template("about.html",
                           info=info,
                           pillars=[dict(x) for x in pillars],
                           facilities=[dict(x) for x in facilities],
                           team=t,
                           body="inner")

@app.route("/faq")
def faq():
    categories = db().execute("SELECT * FROM faq_categories ORDER BY order_idx, id").fetchall()
    items = db().execute("SELECT * FROM faq_items ORDER BY order_idx, id").fetchall()
    faqs_by_cat = {}
    for item in items:
        faqs_by_cat.setdefault(item["category_slug"], []).append(dict(item))
    t = current_team()
    return render_template("faq.html",
                           categories=[dict(x) for x in categories],
                           faqs_by_cat=faqs_by_cat,
                           all_faqs=[dict(x) for x in items],
                           team=t,
                           body="inner")

# ==========================================
# STEALTH ADMIN OPS GATEWAY & AUDIT SYSTEM
# ==========================================

@app.route("/admin")
@app.route("/admin/<path:subpath>")
def trap_admin(subpath=None):
    """Trap route: completely hides the existence of the admin panel from ordinary users and attackers."""
    abort(404)

@app.route(f"/{ADMIN_SECRET_SLUG}", methods=["GET", "POST"])
def admin_login():
    if session.get("is_admin"):
        return redirect(f"/{ADMIN_SECRET_SLUG}/dashboard")
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        row = db().execute("SELECT * FROM admins WHERE username=?", (username,)).fetchone()
        if row and check_password_hash(row["pw"], password):
            session.clear()  # Clear existing user/team session to avoid state bleed
            session["is_admin"] = True
            session["admin_id"] = row["id"]
            session["admin_user"] = row["username"]
            session["admin_role"] = row["role"]
            db().execute("UPDATE admins SET last_login=CURRENT_TIMESTAMP WHERE id=?", (row["id"],))
            db().commit()
            log_admin_action(db(), row["username"], "LOGIN", "SYSTEM", "0", "Admin authenticated via ops gateway")
            return redirect(f"/{ADMIN_SECRET_SLUG}/dashboard")
        flash("Invalid security key or passphrase.")
    return render_template("admin_login.html", slug=ADMIN_SECRET_SLUG)

@app.route(f"/{ADMIN_SECRET_SLUG}/logout")
def admin_logout():
    if session.get("is_admin"):
        log_admin_action(db(), session.get("admin_user", "unknown"), "LOGOUT", "SYSTEM", "0")
    session.pop("is_admin", None)
    session.pop("admin_id", None)
    session.pop("admin_user", None)
    session.pop("admin_role", None)
    flash("Signed out of Organizer Ops Center.")
    return redirect("/")

@app.route(f"/{ADMIN_SECRET_SLUG}/dashboard")
@admin_required
def admin_dashboard():
    total_teams = db().execute("SELECT count(*) FROM teams").fetchone()[0]
    pending_payments = db().execute("SELECT count(*) FROM teams WHERE payment_status='Pending Verification'").fetchone()[0]
    verified_teams = db().execute("SELECT count(*) FROM teams WHERE payment_status='Verified'").fetchone()[0]
    total_members = db().execute("SELECT count(*) FROM members").fetchone()[0]
    
    stats = {
        "total_teams": total_teams,
        "pending_payments": pending_payments,
        "verified_teams": verified_teams,
        "total_members": total_members
    }
    
    tracks = db().execute("SELECT title FROM event_tracks ORDER BY order_idx ASC").fetchall()
    track_counts = {}
    for trk in tracks:
        cnt = db().execute("SELECT count(*) FROM teams WHERE domain=?", (trk["title"],)).fetchone()[0]
        track_counts[trk["title"]] = cnt
        
    pending_teams = db().execute("""
        SELECT t.*, 
               m.fname || ' ' || m.lname as leader_name,
               m.email as leader_email,
               m.phone as leader_phone,
               m.college as leader_college
        FROM teams t
        LEFT JOIN members m ON m.team = t.id AND m.is_leader = 1
        WHERE t.payment_status = 'Pending Verification'
        ORDER BY t.id DESC
    """).fetchall()
    
    recent_teams = db().execute("""
        SELECT t.*, 
               m.fname || ' ' || m.lname as leader_name,
               m.college as leader_college
        FROM teams t
        LEFT JOIN members m ON m.team = t.id AND m.is_leader = 1
        ORDER BY t.id DESC LIMIT 8
    """).fetchall()
    
    return render_template(
        "admin_dashboard.html",
        slug=ADMIN_SECRET_SLUG,
        active_tab="dashboard",
        pending_payments_count=pending_payments,
        stats=stats,
        track_counts=track_counts,
        pending_teams=pending_teams,
        recent_teams=recent_teams
    )

@app.route(f"/{ADMIN_SECRET_SLUG}/payments")
@admin_required
def admin_payments():
    status_filter = request.args.get("status", "all").lower()
    q = request.args.get("q", "").strip()
    
    c_all = db().execute("SELECT count(*) FROM teams").fetchone()[0]
    c_pending = db().execute("SELECT count(*) FROM teams WHERE payment_status='Pending Verification'").fetchone()[0]
    c_verified = db().execute("SELECT count(*) FROM teams WHERE payment_status='Verified'").fetchone()[0]
    c_rejected = db().execute("SELECT count(*) FROM teams WHERE payment_status='Rejected'").fetchone()[0]
    counts = {"all": c_all, "pending": c_pending, "verified": c_verified, "rejected": c_rejected}
    
    query_sql = """
        SELECT t.*,
               m.fname || ' ' || m.lname as leader_name,
               m.email as leader_email,
               m.phone as leader_phone,
               m.college as leader_college
        FROM teams t
        LEFT JOIN members m ON m.team = t.id AND m.is_leader = 1
        WHERE 1=1
    """
    params = []
    if status_filter == "pending":
        query_sql += " AND t.payment_status = 'Pending Verification'"
    elif status_filter == "verified":
        query_sql += " AND t.payment_status = 'Verified'"
    elif status_filter == "rejected":
        query_sql += " AND t.payment_status = 'Rejected'"
        
    if q:
        query_sql += " AND (t.team_id LIKE ? OR t.name LIKE ? OR m.fname LIKE ? OR m.lname LIKE ? OR m.email LIKE ? OR m.phone LIKE ?)"
        like_q = f"%{q}%"
        params.extend([like_q, like_q, like_q, like_q, like_q, like_q])
        
    query_sql += " ORDER BY t.id DESC"
    teams = db().execute(query_sql, params).fetchall()
    
    return render_template(
        "admin_payments.html",
        slug=ADMIN_SECRET_SLUG,
        active_tab="payments",
        pending_payments_count=c_pending,
        counts=counts,
        teams=teams,
        current_status=status_filter,
        query=q
    )

@app.route(f"/{ADMIN_SECRET_SLUG}/payment/<int:team_id>/<action>", methods=["POST"])
@admin_required
def admin_payment_action(team_id, action):
    team = db().execute("SELECT * FROM teams WHERE id=?", (team_id,)).fetchone()
    if not team:
        flash("Team not found.")
        return redirect(f"/{ADMIN_SECRET_SLUG}/payments")
        
    if action == "approve":
        db().execute("UPDATE teams SET payment_status='Verified' WHERE id=?", (team_id,))
        db().commit()
        log_admin_action(db(), session.get("admin_user"), "PAYMENT_APPROVE", "TEAM", team_id, f"Approved ₹50 payment for team {team['team_id']}")
        flash(f"Payment approved for Team {team['team_id']} ({team['name']}).")
    elif action == "reject":
        db().execute("UPDATE teams SET payment_status='Rejected' WHERE id=?", (team_id,))
        db().commit()
        log_admin_action(db(), session.get("admin_user"), "PAYMENT_REJECT", "TEAM", team_id, f"Rejected ₹50 payment for team {team['team_id']}")
        flash(f"Payment rejected for Team {team['team_id']} ({team['name']}).")
    elif action == "revert":
        db().execute("UPDATE teams SET payment_status='Pending Verification' WHERE id=?", (team_id,))
        db().commit()
        log_admin_action(db(), session.get("admin_user"), "PAYMENT_REVERT", "TEAM", team_id, f"Reverted payment status for team {team['team_id']}")
        flash(f"Team {team['team_id']} reverted to Pending Verification.")
        
    ref = request.referrer
    if ref and ADMIN_SECRET_SLUG in ref:
        return redirect(ref)
    return redirect(f"/{ADMIN_SECRET_SLUG}/payments")

@app.route(f"/{ADMIN_SECRET_SLUG}/teams")
@admin_required
def admin_teams():
    q = request.args.get("q", "").strip()
    track = request.args.get("track", "").strip()
    
    pending_payments = db().execute("SELECT count(*) FROM teams WHERE payment_status='Pending Verification'").fetchone()[0]
    tracks = [r["title"] for r in db().execute("SELECT title FROM event_tracks ORDER BY order_idx ASC").fetchall()]
    
    sql = """
        SELECT t.*, 
               m.fname || ' ' || m.lname as leader_name,
               m.college as leader_college
        FROM teams t
        LEFT JOIN members m ON m.team = t.id AND m.is_leader = 1
        WHERE 1=1
    """
    params = []
    if track:
        sql += " AND t.domain = ?"
        params.append(track)
    if q:
        sql += " AND (t.team_id LIKE ? OR t.name LIKE ? OR m.fname LIKE ? OR m.lname LIKE ? OR m.college LIKE ?)"
        like_q = f"%{q}%"
        params.extend([like_q, like_q, like_q, like_q, like_q])
        
    sql += " ORDER BY t.id DESC"
    raw_teams = db().execute(sql, params).fetchall()
    
    teams = []
    for rt in raw_teams:
        t_dict = dict(rt)
        members = db().execute("SELECT * FROM members WHERE team=? ORDER BY is_leader DESC, id ASC", (rt["id"],)).fetchall()
        t_dict["members"] = members
        teams.append(t_dict)
        
    return render_template(
        "admin_teams.html",
        slug=ADMIN_SECRET_SLUG,
        active_tab="teams",
        pending_payments_count=pending_payments,
        teams=teams,
        tracks=tracks,
        current_track=track,
        query=q
    )

@app.route(f"/{ADMIN_SECRET_SLUG}/submissions")
@admin_required
def admin_submissions():
    round_filter = request.args.get("round", "all")
    pending_payments = db().execute("SELECT count(*) FROM teams WHERE payment_status='Pending Verification'").fetchone()[0]
    
    rounds = db().execute("SELECT * FROM event_rounds ORDER BY round_num ASC").fetchall()
    
    sql = """
        SELECT s.*, 
               t.team_id as team_code,
               t.name as team_name,
               t.domain,
               r.round_num,
               r.title as round_title,
               r.stage_name
        FROM team_submissions s
        JOIN teams t ON t.id = s.team_id
        JOIN event_rounds r ON r.id = s.round_id
        WHERE 1=1
    """
    params = []
    if round_filter != "all" and round_filter.isdigit():
        sql += " AND r.round_num = ?"
        params.append(int(round_filter))
        
    sql += " ORDER BY s.submitted_at DESC"
    submissions = db().execute(sql, params).fetchall()
    total_submissions = db().execute("SELECT count(*) FROM team_submissions").fetchone()[0]
    
    return render_template(
        "admin_submissions.html",
        slug=ADMIN_SECRET_SLUG,
        active_tab="submissions",
        pending_payments_count=pending_payments,
        submissions=submissions,
        rounds=rounds,
        current_round=round_filter,
        total_submissions=total_submissions
    )

@app.route(f"/{ADMIN_SECRET_SLUG}/submissions/<int:sub_id>/evaluate", methods=["POST"])
@admin_required
def admin_evaluate_submission(sub_id):
    new_status = request.form.get("status", "Submitted")
    remarks = request.form.get("remarks", "").strip()
    db().execute("UPDATE team_submissions SET status=?, remarks=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", (new_status, remarks, sub_id))
    db().commit()
    log_admin_action(db(), session.get("admin_user"), "EVALUATE_SUBMISSION", "SUBMISSION", sub_id, f"Set status to {new_status}")
    flash(f"Submission #{sub_id} evaluation updated successfully.")
    return redirect(f"/{ADMIN_SECRET_SLUG}/submissions")

@app.route(f"/{ADMIN_SECRET_SLUG}/content")
@admin_required
def admin_content():
    pending_payments = db().execute("SELECT count(*) FROM teams WHERE payment_status='Pending Verification'").fetchone()[0]
    
    event_info_rows = db().execute("SELECT key, value FROM event_info").fetchall()
    event_info = {r["key"]: r["value"] for r in event_info_rows}
    
    prize_ov_rows = db().execute("SELECT key, value FROM prize_overview").fetchall()
    prize_overview = {r["key"]: r["value"] for r in prize_ov_rows}
    podium = db().execute("SELECT * FROM prize_podium ORDER BY order_idx ASC").fetchall()
    
    faqs = db().execute("SELECT * FROM faq_items ORDER BY order_idx ASC, id ASC").fetchall()
    
    return render_template(
        "admin_content.html",
        slug=ADMIN_SECRET_SLUG,
        active_tab="content",
        pending_payments_count=pending_payments,
        event_info=event_info,
        prize_overview=prize_overview,
        podium=podium,
        faqs=faqs
    )

@app.route(f"/{ADMIN_SECRET_SLUG}/content/event-info", methods=["POST"])
@admin_required
def admin_save_event_info():
    keys = ["tagline", "dates", "venue", "prize_pool", "team_size", "mode", "about_p1"]
    for k in keys:
        if k in request.form:
            val = request.form.get(k, "").strip()
            db().execute("INSERT OR REPLACE INTO event_info(key, value) VALUES(?, ?)", (k, val))
    db().commit()
    log_admin_action(db(), session.get("admin_user"), "UPDATE_CONTENT", "EVENT_INFO", "0")
    flash("Event details saved and updated live on the site.")
    return redirect(f"/{ADMIN_SECRET_SLUG}/content")

@app.route(f"/{ADMIN_SECRET_SLUG}/content/prizes", methods=["POST"])
@admin_required
def admin_save_prizes():
    keys = ["total_pool", "cash_pool", "perks_val"]
    for k in keys:
        if k in request.form:
            val = request.form.get(k, "").strip()
            db().execute("INSERT OR REPLACE INTO prize_overview(key, value) VALUES(?, ?)", (k, val))
    
    podium_rows = db().execute("SELECT id FROM prize_podium").fetchall()
    for p in podium_rows:
        f_key = f"podium_{p['id']}"
        if f_key in request.form:
            val = request.form.get(f_key, "").strip()
            db().execute("UPDATE prize_podium SET amount=? WHERE id=?", (val, p["id"]))
            
    db().commit()
    log_admin_action(db(), session.get("admin_user"), "UPDATE_CONTENT", "PRIZES", "0")
    flash("Prize pool amounts saved and updated live on /prizes.")
    return redirect(f"/{ADMIN_SECRET_SLUG}/content")

@app.route(f"/{ADMIN_SECRET_SLUG}/content/faq/add", methods=["POST"])
@admin_required
def admin_add_faq():
    cat = request.form.get("category_slug", "general").strip()
    q = request.form.get("question", "").strip()
    a = request.form.get("answer", "").strip()
    if q and a:
        db().execute("INSERT INTO faq_items(category_slug, question, answer, order_idx) VALUES(?, ?, ?, 99)", (cat, q, a))
        db().commit()
        log_admin_action(db(), session.get("admin_user"), "ADD_FAQ", "FAQ", "0", q)
        flash("New FAQ item added successfully.")
    return redirect(f"/{ADMIN_SECRET_SLUG}/content")

@app.route(f"/{ADMIN_SECRET_SLUG}/content/faq/delete/<int:faq_id>", methods=["POST"])
@admin_required
def admin_delete_faq(faq_id):
    db().execute("DELETE FROM faq_items WHERE id=?", (faq_id,))
    db().commit()
    log_admin_action(db(), session.get("admin_user"), "DELETE_FAQ", "FAQ", faq_id)
    flash("FAQ item deleted.")
    return redirect(f"/{ADMIN_SECRET_SLUG}/content")

@app.route(f"/{ADMIN_SECRET_SLUG}/export/teams")
@admin_required
def admin_export_teams():
    csv_data = generate_teams_csv(db())
    log_admin_action(db(), session.get("admin_user"), "EXPORT_CSV", "TEAMS", "0", "Exported all teams to CSV")
    filename = f"CodeNite2027_Teams_Roster_{int(time.time())}.csv"
    return Response(
        csv_data,
        mimetype="text/csv",
        headers={"Content-disposition": f"attachment; filename={filename}"}
    )

@app.route("/<page>")
def info(page):
    abort(404)

if __name__ == "__main__":
    app.run(debug=True)
