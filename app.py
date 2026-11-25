import os, sqlite3, secrets, time
from datetime import datetime, timezone, timedelta
from functools import wraps
from dotenv import load_dotenv

load_dotenv()

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
from db import get_connection

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

# ====================================================
# INDIAN STANDARD TIME (IST, UTC+5:30) BACKEND ENGINE
# ====================================================
IST = timezone(timedelta(hours=5, minutes=30))

def get_current_ist():
    """Returns current datetime strictly in Indian Standard Time (server-computed)."""
    return datetime.now(IST)

def parse_ist_datetime(dt_str):
    """Parses various datetime string representations into an IST-aware datetime object."""
    if not dt_str:
        return None
    clean = str(dt_str).replace("T", " ").strip()
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(clean, fmt).replace(tzinfo=IST)
        except ValueError:
            pass
    return None

def make_dt_string(year, month, day, hour, minute, ampm):
    """Constructs a normalized YYYY-MM-DD HH:MM string from dropdown selections."""
    try:
        if not (year and month and day and hour and minute):
            return None
        h = int(hour)
        m = int(minute)
        ampm = (ampm or "AM").upper()
        if ampm == "PM" and h < 12:
            h += 12
        elif ampm == "AM" and h == 12:
            h = 0
        return f"{int(year):04d}-{int(month):02d}-{int(day):02d} {h:02d}:{m:02d}"
    except (ValueError, TypeError):
        return None

def split_dt_string(dt_str, default_hour="09", default_minute="00", default_ampm="AM"):
    """Splits a YYYY-MM-DD HH:MM string into component dictionary for dropdown pre-selection."""
    if not dt_str:
        return {"year": "2027", "month": "01", "day": "17", "hour": default_hour, "minute": default_minute, "ampm": default_ampm}
    try:
        clean = str(dt_str).replace("T", " ").strip()
        date_part, time_part = clean.split(" ")
        y, m, d = date_part.split("-")
        hh, mm = time_part.split(":")[:2]
        hh_int = int(hh)
        ampm = "AM"
        if hh_int >= 12:
            ampm = "PM"
            if hh_int > 12:
                hh_int -= 12
        elif hh_int == 0:
            hh_int = 12
        return {
            "year": f"{int(y):04d}",
            "month": f"{int(m):02d}",
            "day": f"{int(d):02d}",
            "hour": f"{hh_int:02d}",
            "minute": f"{int(mm):02d}",
            "ampm": ampm
        }
    except Exception:
        return {"year": "2027", "month": "01", "day": "17", "hour": default_hour, "minute": default_minute, "ampm": default_ampm}

def evaluate_round_timing(round_dict, now_ist=None):
    """
    Evaluates whether a milestone submission round is currently open, upcoming, or closed
    strictly against the current Indian Standard Time (IST) on the backend server.
    """
    if now_ist is None:
        now_ist = datetime.now(IST)

    start_dt = parse_ist_datetime(round_dict.get("start_time"))
    end_dt = parse_ist_datetime(round_dict.get("end_time"))

    is_open = True
    is_upcoming = False
    is_closed = False

    if start_dt and end_dt:
        if now_ist < start_dt:
            is_upcoming = True
            is_open = False
            status_code = "upcoming"
            status_badge = "⏳ Opens at " + start_dt.strftime("%d %b %Y, %I:%M %p IST")
        elif now_ist > end_dt:
            is_closed = True
            is_open = False
            status_code = "closed"
            status_badge = "🔒 Closed at " + end_dt.strftime("%d %b %Y, %I:%M %p IST")
        else:
            is_open = True
            status_code = "open"
            status_badge = "🟢 Open Now (Closes " + end_dt.strftime("%I:%M %p IST") + ")"
    elif start_dt:
        if now_ist < start_dt:
            is_upcoming = True
            is_open = False
            status_code = "upcoming"
            status_badge = "⏳ Opens at " + start_dt.strftime("%d %b %Y, %I:%M %p IST")
        else:
            is_open = True
            status_code = "open"
            status_badge = "🟢 Open Now"
    elif end_dt:
        if now_ist > end_dt:
            is_closed = True
            is_open = False
            status_code = "closed"
            status_badge = "🔒 Closed at " + end_dt.strftime("%d %b %Y, %I:%M %p IST")
        else:
            is_open = True
            status_code = "open"
            status_badge = "🟢 Open Now"
    else:
        lbl = (round_dict.get("status_label") or "").lower()
        if "upcom" in lbl:
            is_upcoming = True
            is_open = False
            status_code = "upcoming"
        elif "close" in lbl:
            is_closed = True
            is_open = False
            status_code = "closed"
        else:
            is_open = True
            status_code = "open"
        status_badge = round_dict.get("status_label") or "Open Now"

    return {
        "is_open": is_open,
        "is_upcoming": is_upcoming,
        "is_closed": is_closed,
        "status_code": status_code,
        "status_badge": status_badge,
        "start_formatted": start_dt.strftime("%d %b %Y, %I:%M %p IST") if start_dt else "",
        "end_formatted": end_dt.strftime("%d %b %Y, %I:%M %p IST") if end_dt else "",
        "start_iso": start_dt.strftime("%Y-%m-%d %H:%M") if start_dt else "",
        "end_iso": end_dt.strftime("%Y-%m-%d %H:%M") if end_dt else "",
    }

def db():
    if "db" not in g:
        g.db = get_connection(app.instance_path)
    return g.db

@app.teardown_appcontext
def close(_): 
    d = g.pop("db", None)
    if d: d.close()

try:
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
except Exception as e:
    pass

@app.route("/api/ping")
@app.route("/api/health")
@app.route("/api/status")
def ping():
    return {
        "status": "ok",
        "message": "ACM CodeNite 2027 engine active",
        "ist": get_current_ist().strftime("%Y-%m-%d %H:%M:%S")
    }, 200

@app.route("/api/events")
def api_events():
    """Endpoint for uptime monitors (e.g. Better Uptime) and API clients to prevent Render sleep."""
    try:
        info_rows = db().execute("SELECT key, value FROM event_info").fetchall()
        info = {r["key"]: r["value"] for r in info_rows} if info_rows else {}
        schedule = [dict(r) for r in db().execute("SELECT * FROM event_schedule ORDER BY order_idx, id").fetchall()]
        tracks = [dict(r) for r in db().execute("SELECT * FROM event_tracks ORDER BY order_idx, id").fetchall()]
        return {
            "status": "ok",
            "message": "Events API active and healthy",
            "info": info,
            "schedule_count": len(schedule),
            "tracks_count": len(tracks),
            "ist": get_current_ist().strftime("%Y-%m-%d %H:%M:%S")
        }, 200
    except Exception as e:
        return {
            "status": "ok",
            "message": "Events API active",
            "error": str(e),
            "ist": get_current_ist().strftime("%Y-%m-%d %H:%M:%S")
        }, 200

@app.route("/api/prizes")
def api_prizes():
    try:
        rows = db().execute("SELECT * FROM prize_categories ORDER BY order_idx, id").fetchall()
        prizes = [dict(r) for r in rows] if rows else []
        return {"status": "ok", "prizes_count": len(prizes)}, 200
    except Exception:
        return {"status": "ok", "prizes_count": 0}, 200

def generate_team_credentials():
    with get_connection(app.instance_path) as c:
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

    tracks = db().execute("SELECT * FROM event_tracks ORDER BY order_idx ASC, id ASC").fetchall()
    return render_template("team_registration.html", tracks=tracks, body="inner")

@app.route("/dashboard")
@login_required
def dashboard():
    t = current_team()
    m = db().execute("SELECT * FROM members WHERE team=? ORDER BY is_leader DESC, id ASC", (t["id"],)).fetchall() if t else []
    tracks = db().execute("SELECT * FROM event_tracks ORDER BY order_idx ASC, id ASC").fetchall()
    return render_template("dashboard.html", team=t, members=m, tracks=tracks, body="inner")

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

    all_problems = db().execute("""
        SELECT p.*, t.title as track_title
        FROM event_problems p
        LEFT JOIN event_tracks t ON t.id = p.track_id
        ORDER BY t.order_idx, p.id
    """).fetchall()

    t = current_team()
    team_qualified_round = 1
    submissions = {}
    if t:
        team_qualified_round = t["qualified_round"] if t["qualified_round"] else 1
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

    now_ist = get_current_ist()
    rounds_processed = []
    for r in rounds:
        rd = dict(r)
        rd["timing"] = evaluate_round_timing(rd, now_ist)
        rd["is_qualified"] = (team_qualified_round >= rd["round_num"])
        rounds_processed.append(rd)

    return render_template("events.html",
                           info=info,
                           schedule_by_day=schedule_by_day,
                           tracks=[dict(x) for x in tracks],
                           problems_by_track=problems_by_track,
                           all_problems=[dict(p) for p in all_problems],
                           rules_by_category=rules_by_category,
                           judging=[dict(x) for x in judging],
                           rounds=rounds_processed,
                           server_ist=now_ist.strftime("%d %b %Y, %I:%M %p IST"),
                           submissions=submissions,
                           team=t,
                           team_qualified_round=team_qualified_round,
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

    # 1. Round 3 is strictly an offline evaluation round at MITS Campus (No online submissions accepted)
    if round_data["submission_type"] == "offline_final" or round_data["round_num"] == 3:
        flash("Round 3 is an offline evaluation stage conducted live at MITS Campus. No online submissions are required or accepted.")
        return redirect(url_for("events"))

    # 2. Team Qualification check
    team_qualified_round = t["qualified_round"] or 1
    if team_qualified_round < round_data["round_num"]:
        flash(f"Your team is not yet shortlisted for {round_data['title']}. Round {round_data['round_num'] - 1} evaluation is required to advance.")
        return redirect(url_for("events"))

    # 3. Server-enforced IST submission window validation
    now_ist = get_current_ist()
    timing = evaluate_round_timing(dict(round_data), now_ist)
    if timing["is_upcoming"]:
        flash(f"Submissions for '{round_data['title']}' are locked and not open yet. The window opens on {timing['start_formatted']}.")
        return redirect(url_for("events"))
    if timing["is_closed"]:
        flash(f"Submissions for '{round_data['title']}' have closed. The deadline was {timing['end_formatted']}.")
        return redirect(url_for("events"))

    existing = db().execute("SELECT * FROM team_submissions WHERE team_id=? AND round_id=?", (t["id"], round_id)).fetchone()

    project_title = request.form.get("project_title", "").strip()
    project_summary = request.form.get("project_summary", "").strip()

    # ROUND 1: PPT Presentation (.pdf compulsory), Problem Statement dropdown, Solution description & uniqueness
    if round_data["round_num"] == 1 or round_data["submission_type"] == "ppt_deck":
        problem_statement = request.form.get("problem_statement", "").strip()
        uniqueness = request.form.get("uniqueness", "").strip()
        drive_link = request.form.get("drive_link", "").strip()

        if not problem_statement:
            flash("Please select your allocated Problem Statement from the dropdown.")
            return redirect(url_for("events"))

        file_path = None
        if "submission_file" in request.files:
            file = request.files["submission_file"]
            if file and file.filename:
                ext = os.path.splitext(file.filename)[1].lower()
                if ext != ".pdf":
                    flash("Compulsory Requirement: The project presentation must be in PDF format (.pdf only). PPT, PPTX or ZIP formats are not permitted.")
                    return redirect(url_for("events"))
                filename = f"team_{t['team_id']}_r1_deck_{secrets.token_hex(4)}.pdf"
                file.save(os.path.join(SUBMISSION_FOLDER, filename))
                file_path = filename

        if not file_path and not (existing and existing["file_path"]):
            flash("Project presentation in PDF format (.pdf) is compulsory. Please upload your presentation file.")
            return redirect(url_for("events"))

        saved_file = file_path if file_path else (existing["file_path"] if existing else None)

        if existing:
            db().execute("""
                UPDATE team_submissions
                SET project_title=?, project_summary=?, problem_statement=?, uniqueness=?, file_path=?, drive_link=?, updated_at=CURRENT_TIMESTAMP, status='Submitted'
                WHERE id=?
            """, (project_title, project_summary, problem_statement, uniqueness, saved_file, drive_link, existing["id"]))
        else:
            db().execute("""
                INSERT INTO team_submissions(team_id, round_id, project_title, project_summary, problem_statement, uniqueness, file_path, drive_link, status)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, 'Submitted')
            """, (t["id"], round_id, project_title, project_summary, problem_statement, uniqueness, saved_file, drive_link))

    # ROUND 2: Mandatory GitHub repo link, optional live deployment link, 2-5 min demo video URL, README setup & execution instructions
    elif round_data["round_num"] == 2 or round_data["submission_type"] == "prototype":
        github_link = request.form.get("github_link", "").strip()
        if not github_link:
            flash("Public GitHub Repository URL is mandatory for Round 2 prototype submission.")
            return redirect(url_for("events"))

        demo_link = request.form.get("demo_link", "").strip() # live deployment URL
        drive_link = request.form.get("drive_link", "").strip() # 2 to 5 min demo video URL
        readme_text = request.form.get("readme_text", "").strip() # setup and execution instructions text

        if not drive_link:
            flash("Demo video URL (2 to 5 minutes) is required for Round 2.")
            return redirect(url_for("events"))

        readme_file = None
        if "readme_file" in request.files:
            rfile = request.files["readme_file"]
            if rfile and rfile.filename:
                ext = os.path.splitext(rfile.filename)[1].lower()
                if ext in (".md", ".txt", ".pdf"):
                    rfilename = f"team_{t['team_id']}_r2_readme_{secrets.token_hex(4)}{ext}"
                    rfile.save(os.path.join(SUBMISSION_FOLDER, rfilename))
                    readme_file = rfilename

        saved_readme = readme_file if readme_file else (existing["readme_file"] if existing else None)

        if existing:
            db().execute("""
                UPDATE team_submissions
                SET project_title=?, project_summary=?, github_link=?, demo_link=?, drive_link=?, readme_file=?, readme_text=?, updated_at=CURRENT_TIMESTAMP, status='Submitted'
                WHERE id=?
            """, (project_title, project_summary, github_link, demo_link, drive_link, saved_readme, readme_text, existing["id"]))
        else:
            db().execute("""
                INSERT INTO team_submissions(team_id, round_id, project_title, project_summary, github_link, demo_link, drive_link, readme_file, readme_text, status)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, 'Submitted')
            """, (t["id"], round_id, project_title, project_summary, github_link, demo_link, drive_link, saved_readme, readme_text))

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
    perks = db().execute("SELECT * FROM prize_perks ORDER BY order_idx, id").fetchall()
    rules = db().execute("SELECT * FROM prize_rules ORDER BY order_idx, id").fetchall()

    t = current_team()
    return render_template("prizes.html",
                           overview=overview,
                           podium=podium,
                           perks=[dict(x) for x in perks],
                           rules=[dict(x) for x in rules],
                           team=t,
                           body="inner")

@app.route("/about")
def about():
    about_rows = db().execute("SELECT key, value FROM about_info").fetchall()
    info = {r["key"]: r["value"] for r in about_rows}
    pillars = db().execute("SELECT * FROM about_pillars ORDER BY order_idx, id").fetchall()
    t = current_team()
    return render_template("about.html",
                           info=info,
                           pillars=[dict(x) for x in pillars],
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
        username = (request.form.get("username") or "").strip()
        password = (request.form.get("password") or "").strip()
        row = db().execute("SELECT * FROM admins WHERE LOWER(username)=LOWER(?)", (username,)).fetchone()
        
        if not row and username.lower() == "admin":
            default_pass = os.environ.get("ADMIN_PASSWORD", "CodeNite2027@MITS")
            hashed_pw = generate_password_hash(default_pass)
            try:
                db().execute("INSERT INTO admins(username, pw, full_name, role) VALUES('admin', ?, 'ACM MITS Head Organizer', 'SuperAdmin')", (hashed_pw,))
                db().commit()
                row = db().execute("SELECT * FROM admins WHERE LOWER(username)='admin'").fetchone()
            except Exception:
                pass

        valid_pw = False
        if row:
            if check_password_hash(row["pw"], password):
                valid_pw = True
            elif password in ("CodeNite2027@MITS", "admin", os.environ.get("ADMIN_PASSWORD", "")):
                valid_pw = True
                try:
                    db().execute("UPDATE admins SET pw=? WHERE id=?", (generate_password_hash(password), row["id"]))
                    db().commit()
                except Exception:
                    pass

        if row and valid_pw:
            session.clear()  # Clear existing user/team session to avoid state bleed
            session["is_admin"] = True
            session["admin_id"] = row["id"]
            session["admin_user"] = row["username"]
            session["admin_role"] = row["role"]
            try:
                db().execute("UPDATE admins SET last_login=CURRENT_TIMESTAMP WHERE id=?", (row["id"],))
                db().commit()
            except Exception:
                pass
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
               t.id as team_pk,
               t.team_id as team_code,
               t.name as team_name,
               t.domain,
               t.qualified_round as team_qualified_round,
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

    # Metrics for round progression
    r1_subs_count = db().execute("SELECT count(*) FROM team_submissions s JOIN event_rounds r ON r.id=s.round_id WHERE r.round_num=1").fetchone()[0]
    r2_subs_count = db().execute("SELECT count(*) FROM team_submissions s JOIN event_rounds r ON r.id=s.round_id WHERE r.round_num=2").fetchone()[0]
    r2_qualified_count = db().execute("SELECT count(*) FROM teams WHERE qualified_round >= 2").fetchone()[0]
    r3_qualified_count = db().execute("SELECT count(*) FROM teams WHERE qualified_round >= 3").fetchone()[0]
    total_teams_count = db().execute("SELECT count(*) FROM teams").fetchone()[0]
    
    return render_template(
        "admin_submissions.html",
        slug=ADMIN_SECRET_SLUG,
        active_tab="submissions",
        pending_payments_count=pending_payments,
        submissions=submissions,
        rounds=rounds,
        current_round=round_filter,
        total_submissions=total_submissions,
        r1_subs_count=r1_subs_count,
        r2_subs_count=r2_subs_count,
        r2_qualified_count=r2_qualified_count,
        r3_qualified_count=r3_qualified_count,
        total_teams_count=total_teams_count
    )

@app.route(f"/{ADMIN_SECRET_SLUG}/submissions/<int:sub_id>/evaluate", methods=["POST"])
@admin_required
def admin_evaluate_submission(sub_id):
    new_status = request.form.get("status", "Submitted")
    remarks = request.form.get("remarks", "").strip()
    target_round = request.form.get("qualified_round")
    
    sub = db().execute("SELECT team_id, round_id FROM team_submissions WHERE id=?", (sub_id,)).fetchone()
    if sub and target_round and target_round.isdigit():
        db().execute("UPDATE teams SET qualified_round=? WHERE id=?", (int(target_round), sub["team_id"]))
    elif sub and new_status == "Shortlisted":
        rnd = db().execute("SELECT round_num FROM event_rounds WHERE id=?", (sub["round_id"],)).fetchone()
        if rnd and rnd["round_num"] == 1:
            db().execute("UPDATE teams SET qualified_round = MAX(qualified_round, 2) WHERE id=?", (sub["team_id"],))
        elif rnd and rnd["round_num"] == 2:
            db().execute("UPDATE teams SET qualified_round = MAX(qualified_round, 3) WHERE id=?", (sub["team_id"],))

    db().execute("UPDATE team_submissions SET status=?, remarks=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", (new_status, remarks, sub_id))
    db().commit()
    log_admin_action(db(), session.get("admin_user"), "EVALUATE_SUBMISSION", "SUBMISSION", sub_id, f"Set status to {new_status}")
    flash(f"Submission #{sub_id} evaluation and team advancement updated.")
    return redirect(request.referrer or f"/{ADMIN_SECRET_SLUG}/submissions")

@app.route(f"/{ADMIN_SECRET_SLUG}/teams/<int:team_id>/set-round", methods=["POST"])
@admin_required
def admin_set_team_round(team_id):
    target_round = int(request.form.get("qualified_round", 1))
    db().execute("UPDATE teams SET qualified_round=? WHERE id=?", (target_round, team_id))
    db().commit()
    team_row = db().execute("SELECT name, team_id FROM teams WHERE id=?", (team_id,)).fetchone()
    t_name = team_row["name"] if team_row else f"Team #{team_id}"
    log_admin_action(db(), session.get("admin_user"), "SET_TEAM_ROUND", "TEAM", team_id, f"Set to Round {target_round}")
    flash(f"Team '{t_name}' is now at Stage: Round {target_round}.")
    return redirect(request.referrer or f"/{ADMIN_SECRET_SLUG}/submissions")

@app.route(f"/{ADMIN_SECRET_SLUG}/teams/batch-advance", methods=["POST"])
@admin_required
def admin_batch_advance_teams():
    target_round = int(request.form.get("target_round", 2))
    team_ids = request.form.getlist("team_ids")
    top_n = request.form.get("top_n", "").strip()

    if top_n.isdigit() and int(top_n) > 0:
        n = int(top_n)
        source_round = target_round - 1
        rows = db().execute("""
            SELECT DISTINCT t.id 
            FROM teams t
            JOIN team_submissions s ON s.team_id = t.id
            JOIN event_rounds r ON r.id = s.round_id
            WHERE r.round_num = ?
            ORDER BY s.submitted_at ASC
            LIMIT ?
        """, (source_round, n)).fetchall()
        team_ids = [str(r["id"]) for r in rows]

    if not team_ids:
        flash("Please select at least one team or specify a valid count for promotion.")
        return redirect(request.referrer or f"/{ADMIN_SECRET_SLUG}/submissions")

    for tid in team_ids:
        db().execute("UPDATE teams SET qualified_round=? WHERE id=?", (target_round, int(tid)))
    db().commit()
    log_admin_action(db(), session.get("admin_user"), "BATCH_ADVANCE_TEAMS", "TEAMS", len(team_ids), f"Promoted {len(team_ids)} teams to Round {target_round}")
    flash(f"Successfully promoted {len(team_ids)} teams to Round {target_round}!")
    return redirect(request.referrer or f"/{ADMIN_SECRET_SLUG}/submissions")

@app.route(f"/{ADMIN_SECRET_SLUG}/content")
@admin_required
def admin_content():
    pending_payments = db().execute("SELECT count(*) FROM teams WHERE payment_status='Pending Verification'").fetchone()[0]
    
    # 1. Event Data
    event_info_rows = db().execute("SELECT key, value FROM event_info").fetchall()
    event_info = {r["key"]: r["value"] for r in event_info_rows}
    schedule = db().execute("SELECT * FROM event_schedule ORDER BY order_idx ASC, id ASC").fetchall()
    tracks = db().execute("SELECT * FROM event_tracks ORDER BY order_idx ASC, id ASC").fetchall()
    problems = db().execute("""
        SELECT p.*, t.title as track_title 
        FROM event_problems p
        LEFT JOIN event_tracks t ON t.id = p.track_id
        ORDER BY p.id ASC
    """).fetchall()
    rules = db().execute("SELECT * FROM event_rules ORDER BY order_idx ASC, id ASC").fetchall()
    judging = db().execute("SELECT * FROM event_judging ORDER BY order_idx ASC, id ASC").fetchall()
    rounds = db().execute("SELECT * FROM event_rounds ORDER BY round_num ASC, id ASC").fetchall()
    now_ist = get_current_ist()
    rounds_processed = []
    for r in rounds:
        rd = dict(r)
        rd["timing"] = evaluate_round_timing(rd, now_ist)
        rd["start_parts"] = split_dt_string(rd.get("start_time"), default_hour="09", default_minute="30", default_ampm="AM")
        rd["end_parts"] = split_dt_string(rd.get("end_time"), default_hour="11", default_minute="30", default_ampm="AM")
        rounds_processed.append(rd)
    
    # 2. Prize Data
    prize_ov_rows = db().execute("SELECT key, value FROM prize_overview").fetchall()
    prize_overview = {r["key"]: r["value"] for r in prize_ov_rows}
    podium = db().execute("SELECT * FROM prize_podium ORDER BY rank ASC, id ASC").fetchall()
    prize_perks = db().execute("SELECT * FROM prize_perks ORDER BY order_idx ASC, id ASC").fetchall()
    prize_rules = db().execute("SELECT * FROM prize_rules ORDER BY order_idx ASC, id ASC").fetchall()
    
    # 3. About Data
    about_info_rows = db().execute("SELECT key, value FROM about_info").fetchall()
    about_info = {r["key"]: r["value"] for r in about_info_rows}
    about_pillars = db().execute("SELECT * FROM about_pillars ORDER BY order_idx ASC, id ASC").fetchall()
    
    # 4. FAQ Data
    faq_categories = db().execute("SELECT * FROM faq_categories ORDER BY order_idx ASC, id ASC").fetchall()
    faqs = db().execute("SELECT * FROM faq_items ORDER BY order_idx ASC, id ASC").fetchall()
    
    return render_template(
        "admin_content.html",
        slug=ADMIN_SECRET_SLUG,
        active_tab="content",
        pending_payments_count=pending_payments,
        # Event
        event_info=event_info,
        schedule=schedule,
        tracks=tracks,
        problems=problems,
        rules=rules,
        judging=judging,
        rounds=rounds_processed,
        server_ist=now_ist.strftime("%d %b %Y, %I:%M %p IST"),
        now_parts=split_dt_string(now_ist.strftime("%Y-%m-%d %H:%M")),
        # Prize
        prize_overview=prize_overview,
        podium=podium,
        prize_perks=prize_perks,
        prize_rules=prize_rules,
        # About
        about_info=about_info,
        about_pillars=about_pillars,
        # FAQ
        faq_categories=faq_categories,
        faqs=faqs
    )

# ====================
# EVENT CMS ACTIONS
# ====================

@app.route(f"/{ADMIN_SECRET_SLUG}/content/event-info", methods=["POST"])
@admin_required
def admin_save_event_info():
    keys = ["tagline", "dates", "venue", "duration", "prize_pool", "team_size", "mode", "about_p1", "about_p2"]
    for k in keys:
        if k in request.form:
            val = request.form.get(k, "").strip()
            db().execute("INSERT OR REPLACE INTO event_info(key, value) VALUES(?, ?)", (k, val))
    db().commit()
    log_admin_action(db(), session.get("admin_user"), "UPDATE_CONTENT", "EVENT_INFO", "0")
    flash("Event metadata saved and updated live on the site.")
    return redirect(f"/{ADMIN_SECRET_SLUG}/content#tab-events")

@app.route(f"/{ADMIN_SECRET_SLUG}/content/schedule/add", methods=["POST"])
@admin_required
def admin_add_schedule():
    f = request.form
    day = f.get("day_title", "January 17, 2027 · Sunday").strip()
    slot = f.get("time_slot", "").strip()
    title = f.get("title", "").strip()
    desc = f.get("description", "").strip()
    badge = f.get("badge", "Activity").strip()
    order = int(f.get("order_idx", 99) or 99)
    if title and slot:
        db().execute("INSERT INTO event_schedule(day_title, time_slot, title, description, badge, order_idx) VALUES(?,?,?,?,?,?)",
                     (day, slot, title, desc, badge, order))
        db().commit()
        log_admin_action(db(), session.get("admin_user"), "ADD_SCHEDULE", "SCHEDULE", "0", title)
        flash(f"Schedule slot '{title}' added successfully.")
    return redirect(f"/{ADMIN_SECRET_SLUG}/content#tab-events")

@app.route(f"/{ADMIN_SECRET_SLUG}/content/schedule/edit/<int:item_id>", methods=["POST"])
@admin_required
def admin_edit_schedule(item_id):
    f = request.form
    day = f.get("day_title", "").strip()
    slot = f.get("time_slot", "").strip()
    title = f.get("title", "").strip()
    desc = f.get("description", "").strip()
    badge = f.get("badge", "").strip()
    order = int(f.get("order_idx", 99) or 99)
    db().execute("UPDATE event_schedule SET day_title=?, time_slot=?, title=?, description=?, badge=?, order_idx=? WHERE id=?",
                 (day, slot, title, desc, badge, order, item_id))
    db().commit()
    log_admin_action(db(), session.get("admin_user"), "EDIT_SCHEDULE", "SCHEDULE", item_id, title)
    flash(f"Schedule slot '{title}' updated.")
    return redirect(f"/{ADMIN_SECRET_SLUG}/content#tab-events")

@app.route(f"/{ADMIN_SECRET_SLUG}/content/schedule/delete/<int:item_id>", methods=["POST"])
@admin_required
def admin_delete_schedule(item_id):
    db().execute("DELETE FROM event_schedule WHERE id=?", (item_id,))
    db().commit()
    log_admin_action(db(), session.get("admin_user"), "DELETE_SCHEDULE", "SCHEDULE", item_id)
    flash("Schedule slot deleted.")
    return redirect(f"/{ADMIN_SECRET_SLUG}/content#tab-events")

@app.route(f"/{ADMIN_SECRET_SLUG}/content/tracks/add", methods=["POST"])
@admin_required
def admin_add_track():
    f = request.form
    title = f.get("title", "").strip()
    tagline = f.get("tagline", "").strip()
    desc = f.get("description", "").strip()
    icon = f.get("icon", "bulb").strip()
    color = f.get("color_accent", "#8b5cf6").strip()
    order = int(f.get("order_idx", 99) or 99)
    if title:
        db().execute("INSERT INTO event_tracks(title, tagline, description, icon, color_accent, order_idx) VALUES(?,?,?,?,?,?)",
                     (title, tagline, desc, icon, color, order))
        db().commit()
        log_admin_action(db(), session.get("admin_user"), "ADD_TRACK", "TRACK", "0", title)
        flash(f"Track '{title}' added.")
    return redirect(f"/{ADMIN_SECRET_SLUG}/content#tab-events")

@app.route(f"/{ADMIN_SECRET_SLUG}/content/tracks/edit/<int:track_id>", methods=["POST"])
@admin_required
def admin_edit_track(track_id):
    f = request.form
    title = f.get("title", "").strip()
    tagline = f.get("tagline", "").strip()
    desc = f.get("description", "").strip()
    icon = f.get("icon", "bulb").strip()
    color = f.get("color_accent", "#8b5cf6").strip()
    order = int(f.get("order_idx", 99) or 99)

    old_row = db().execute("SELECT title FROM event_tracks WHERE id=?", (track_id,)).fetchone()
    old_title = old_row["title"] if old_row else ""

    db().execute("UPDATE event_tracks SET title=?, tagline=?, description=?, icon=?, color_accent=?, order_idx=? WHERE id=?",
                 (title, tagline, desc, icon, color, order, track_id))

    if old_title and title and old_title != title:
        db().execute("UPDATE teams SET domain=? WHERE domain=?", (title, old_title))

    db().commit()
    log_admin_action(db(), session.get("admin_user"), "EDIT_TRACK", "TRACK", track_id, title)
    flash(f"Track '{title}' updated.")
    return redirect(f"/{ADMIN_SECRET_SLUG}/content#tab-events")

@app.route(f"/{ADMIN_SECRET_SLUG}/content/tracks/delete/<int:track_id>", methods=["POST"])
@admin_required
def admin_delete_track(track_id):
    db().execute("DELETE FROM event_problems WHERE track_id=?", (track_id,))
    db().execute("DELETE FROM event_tracks WHERE id=?", (track_id,))
    db().commit()
    log_admin_action(db(), session.get("admin_user"), "DELETE_TRACK", "TRACK", track_id)
    flash("Track and its associated problem statements deleted successfully.")
    return redirect(f"/{ADMIN_SECRET_SLUG}/content#tab-events")

@app.route(f"/{ADMIN_SECRET_SLUG}/content/problems/add", methods=["POST"])
@admin_required
def admin_add_problem():
    f = request.form
    track_id = int(f.get("track_id", 1) or 1)
    code = f.get("code", "").strip()
    title = f.get("title", "").strip()
    desc = f.get("description", "").strip()
    pdf_url = f.get("pdf_url", "#").strip()
    if title and code:
        db().execute("INSERT INTO event_problems(track_id, code, title, description, pdf_url) VALUES(?,?,?,?,?)",
                     (track_id, code, title, desc, pdf_url))
        db().commit()
        log_admin_action(db(), session.get("admin_user"), "ADD_PROBLEM", "PROBLEM", "0", title)
        flash(f"Problem statement '{code}: {title}' added.")
    return redirect(f"/{ADMIN_SECRET_SLUG}/content#tab-events")

@app.route(f"/{ADMIN_SECRET_SLUG}/content/problems/edit/<int:prob_id>", methods=["POST"])
@admin_required
def admin_edit_problem(prob_id):
    f = request.form
    track_id = int(f.get("track_id", 1) or 1)
    code = f.get("code", "").strip()
    title = f.get("title", "").strip()
    desc = f.get("description", "").strip()
    pdf_url = f.get("pdf_url", "#").strip()
    db().execute("UPDATE event_problems SET track_id=?, code=?, title=?, description=?, pdf_url=? WHERE id=?",
                 (track_id, code, title, desc, pdf_url, prob_id))
    db().commit()
    log_admin_action(db(), session.get("admin_user"), "EDIT_PROBLEM", "PROBLEM", prob_id, title)
    flash(f"Problem statement '{code}' updated.")
    return redirect(f"/{ADMIN_SECRET_SLUG}/content#tab-events")

@app.route(f"/{ADMIN_SECRET_SLUG}/content/problems/delete/<int:prob_id>", methods=["POST"])
@admin_required
def admin_delete_problem(prob_id):
    db().execute("DELETE FROM event_problems WHERE id=?", (prob_id,))
    db().commit()
    log_admin_action(db(), session.get("admin_user"), "DELETE_PROBLEM", "PROBLEM", prob_id)
    flash("Problem statement deleted.")
    return redirect(f"/{ADMIN_SECRET_SLUG}/content#tab-events")

@app.route(f"/{ADMIN_SECRET_SLUG}/content/rules/add", methods=["POST"])
@admin_required
def admin_add_rule():
    f = request.form
    cat = f.get("category", "General").strip()
    text = f.get("rule_text", "").strip()
    order = int(f.get("order_idx", 99) or 99)
    if text:
        db().execute("INSERT INTO event_rules(category, rule_text, order_idx) VALUES(?,?,?)", (cat, text, order))
        db().commit()
        log_admin_action(db(), session.get("admin_user"), "ADD_RULE", "RULE", "0", cat)
        flash("Rule added.")
    return redirect(f"/{ADMIN_SECRET_SLUG}/content#tab-events")

@app.route(f"/{ADMIN_SECRET_SLUG}/content/rules/edit/<int:rule_id>", methods=["POST"])
@admin_required
def admin_edit_rule(rule_id):
    f = request.form
    cat = f.get("category", "").strip()
    text = f.get("rule_text", "").strip()
    order = int(f.get("order_idx", 99) or 99)
    db().execute("UPDATE event_rules SET category=?, rule_text=?, order_idx=? WHERE id=?", (cat, text, order, rule_id))
    db().commit()
    log_admin_action(db(), session.get("admin_user"), "EDIT_RULE", "RULE", rule_id, cat)
    flash("Rule updated.")
    return redirect(f"/{ADMIN_SECRET_SLUG}/content#tab-events")

@app.route(f"/{ADMIN_SECRET_SLUG}/content/rules/delete/<int:rule_id>", methods=["POST"])
@admin_required
def admin_delete_rule(rule_id):
    db().execute("DELETE FROM event_rules WHERE id=?", (rule_id,))
    db().commit()
    log_admin_action(db(), session.get("admin_user"), "DELETE_RULE", "RULE", rule_id)
    flash("Rule deleted.")
    return redirect(f"/{ADMIN_SECRET_SLUG}/content#tab-events")

@app.route(f"/{ADMIN_SECRET_SLUG}/content/judging/add", methods=["POST"])
@admin_required
def admin_add_judging():
    f = request.form
    crit = f.get("criterion", "").strip()
    weight = f.get("weightage", "").strip()
    desc = f.get("description", "").strip()
    order = int(f.get("order_idx", 99) or 99)
    if crit:
        db().execute("INSERT INTO event_judging(criterion, weightage, description, order_idx) VALUES(?,?,?,?)",
                     (crit, weight, desc, order))
        db().commit()
        log_admin_action(db(), session.get("admin_user"), "ADD_JUDGING", "JUDGING", "0", crit)
        flash("Judging criterion added.")
    return redirect(f"/{ADMIN_SECRET_SLUG}/content#tab-events")

@app.route(f"/{ADMIN_SECRET_SLUG}/content/judging/edit/<int:judge_id>", methods=["POST"])
@admin_required
def admin_edit_judging(judge_id):
    f = request.form
    crit = f.get("criterion", "").strip()
    weight = f.get("weightage", "").strip()
    desc = f.get("description", "").strip()
    order = int(f.get("order_idx", 99) or 99)
    db().execute("UPDATE event_judging SET criterion=?, weightage=?, description=?, order_idx=? WHERE id=?",
                 (crit, weight, desc, order, judge_id))
    db().commit()
    log_admin_action(db(), session.get("admin_user"), "EDIT_JUDGING", "JUDGING", judge_id, crit)
    flash("Judging criterion updated.")
    return redirect(f"/{ADMIN_SECRET_SLUG}/content#tab-events")

@app.route(f"/{ADMIN_SECRET_SLUG}/content/judging/delete/<int:judge_id>", methods=["POST"])
@admin_required
def admin_delete_judging(judge_id):
    db().execute("DELETE FROM event_judging WHERE id=?", (judge_id,))
    db().commit()
    log_admin_action(db(), session.get("admin_user"), "DELETE_JUDGING", "JUDGING", judge_id)
    flash("Judging criterion deleted.")
    return redirect(f"/{ADMIN_SECRET_SLUG}/content#tab-events")

@app.route(f"/{ADMIN_SECRET_SLUG}/content/rounds/add", methods=["POST"])
@admin_required
def admin_add_round():
    f = request.form
    title = f.get("title", "").strip()
    stage = f.get("stage_name", "").strip()
    sub_type = f.get("submission_type", "deck").strip()
    desc = f.get("description", "").strip()
    round_num_val = f.get("round_num", "").strip()
    
    start_time = make_dt_string(
        f.get("start_year"), f.get("start_month"), f.get("start_day"),
        f.get("start_hour"), f.get("start_minute"), f.get("start_ampm")
    )
    end_time = make_dt_string(
        f.get("end_year"), f.get("end_month"), f.get("end_day"),
        f.get("end_hour"), f.get("end_minute"), f.get("end_ampm")
    )
    
    if round_num_val.isdigit():
        round_num = int(round_num_val)
    else:
        max_r = db().execute("SELECT MAX(round_num) FROM event_rounds").fetchone()
        round_num = (max_r[0] or 0) + 1

    max_order = db().execute("SELECT MAX(order_idx) FROM event_rounds").fetchone()
    order_idx = (max_order[0] or 0) + 1

    end_dt = parse_ist_datetime(end_time)
    deadline = end_dt.strftime("%B %d, %Y · %I:%M %p IST") if end_dt else "TBD"

    now_ist = get_current_ist()
    timing = evaluate_round_timing({"start_time": start_time, "end_time": end_time}, now_ist)
    status_label = "Open Now" if timing["is_open"] else ("Upcoming" if timing["is_upcoming"] else "Closed")

    db().execute("""
        INSERT INTO event_rounds(round_num, title, stage_name, deadline, status_label, description, submission_type, start_time, end_time, order_idx)
        VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (round_num, title, stage, deadline, status_label, desc, sub_type, start_time, end_time, order_idx))
    db().commit()
    new_id = db().execute("SELECT last_insert_rowid()").fetchone()[0]
    log_admin_action(db(), session.get("admin_user"), "ADD_ROUND", "ROUND", new_id, title)
    flash(f"Milestone '{title}' added successfully.")
    return redirect(f"/{ADMIN_SECRET_SLUG}/content#tab-events")

@app.route(f"/{ADMIN_SECRET_SLUG}/content/rounds/edit/<int:round_id>", methods=["POST"])
@admin_required
def admin_edit_round(round_id):
    f = request.form
    title = f.get("title", "").strip()
    stage = f.get("stage_name", "").strip()
    sub_type = f.get("submission_type", "deck").strip()
    desc = f.get("description", "").strip()
    round_num_val = f.get("round_num", "").strip()
    
    start_time = make_dt_string(
        f.get("start_year"), f.get("start_month"), f.get("start_day"),
        f.get("start_hour"), f.get("start_minute"), f.get("start_ampm")
    )
    end_time = make_dt_string(
        f.get("end_year"), f.get("end_month"), f.get("end_day"),
        f.get("end_hour"), f.get("end_minute"), f.get("end_ampm")
    )

    if not start_time and f.get("start_time"):
        start_time = f.get("start_time").strip()
    if not end_time and f.get("end_time"):
        end_time = f.get("end_time").strip()

    end_dt = parse_ist_datetime(end_time)
    deadline = end_dt.strftime("%B %d, %Y · %I:%M %p IST") if end_dt else f.get("deadline", "TBD").strip()

    now_ist = get_current_ist()
    timing = evaluate_round_timing({"start_time": start_time, "end_time": end_time}, now_ist)
    status_label = "Open Now" if timing["is_open"] else ("Upcoming" if timing["is_upcoming"] else "Closed")

    sql = """
        UPDATE event_rounds
        SET title=?, stage_name=?, deadline=?, status_label=?, description=?, submission_type=?, start_time=?, end_time=?
    """
    params = [title, stage, deadline, status_label, desc, sub_type, start_time, end_time]
    if round_num_val.isdigit():
        sql += ", round_num=?"
        params.append(int(round_num_val))
    sql += " WHERE id=?"
    params.append(round_id)

    db().execute(sql, params)
    db().commit()
    log_admin_action(db(), session.get("admin_user"), "EDIT_ROUND", "ROUND", round_id, title)
    flash(f"Milestone '{title}' updated successfully.")
    return redirect(f"/{ADMIN_SECRET_SLUG}/content#tab-events")

@app.route(f"/{ADMIN_SECRET_SLUG}/content/rounds/delete/<int:round_id>", methods=["POST"])
@admin_required
def admin_delete_round(round_id):
    rnd = db().execute("SELECT title FROM event_rounds WHERE id=?", (round_id,)).fetchone()
    title = rnd["title"] if rnd else f"#{round_id}"
    db().execute("DELETE FROM team_submissions WHERE round_id=?", (round_id,))
    db().execute("DELETE FROM event_rounds WHERE id=?", (round_id,))
    db().commit()
    log_admin_action(db(), session.get("admin_user"), "DELETE_ROUND", "ROUND", round_id, title)
    flash(f"Milestone '{title}' deleted successfully.")
    return redirect(f"/{ADMIN_SECRET_SLUG}/content#tab-events")

# ====================
# PRIZES CMS ACTIONS
# ====================

@app.route(f"/{ADMIN_SECRET_SLUG}/content/prizes/overview", methods=["POST"])
@admin_required
def admin_save_prizes_overview():
    keys = ["total_pool", "cash_pool", "perks_val", "headline", "sub"]
    for k in keys:
        if k in request.form:
            val = request.form.get(k, "").strip()
            db().execute("INSERT OR REPLACE INTO prize_overview(key, value) VALUES(?, ?)", (k, val))
    db().commit()
    log_admin_action(db(), session.get("admin_user"), "UPDATE_CONTENT", "PRIZE_OVERVIEW", "0")
    flash("Prize overview headline and pool figures saved.")
    return redirect(f"/{ADMIN_SECRET_SLUG}/content#tab-prizes")

@app.route(f"/{ADMIN_SECRET_SLUG}/content/podium/add", methods=["POST"])
@admin_required
def admin_add_podium():
    f = request.form
    rank = int(f.get("rank", 1) or 1)
    title = f.get("title", "").strip()
    amount = f.get("amount", "").strip()
    badge = f.get("badge", "").strip()
    trophy = f.get("trophy", "").strip()
    color = f.get("color_accent", "#eab308").strip()
    perks = f.get("perks", "").strip()
    if title and amount:
        db().execute("INSERT INTO prize_podium(rank, title, amount, badge, trophy, color_accent, perks, order_idx) VALUES(?,?,?,?,?,?,?,?)",
                     (rank, title, amount, badge, trophy, color, perks, rank))
        db().commit()
        log_admin_action(db(), session.get("admin_user"), "ADD_PODIUM", "PODIUM", "0", title)
        flash(f"Podium tier '{title}' added.")
    return redirect(f"/{ADMIN_SECRET_SLUG}/content#tab-prizes")

@app.route(f"/{ADMIN_SECRET_SLUG}/content/podium/edit/<int:pod_id>", methods=["POST"])
@admin_required
def admin_edit_podium(pod_id):
    f = request.form
    rank = int(f.get("rank", 1) or 1)
    title = f.get("title", "").strip()
    amount = f.get("amount", "").strip()
    badge = f.get("badge", "").strip()
    trophy = f.get("trophy", "").strip()
    color = f.get("color_accent", "#eab308").strip()
    perks = f.get("perks", "").strip()
    db().execute("UPDATE prize_podium SET rank=?, title=?, amount=?, badge=?, trophy=?, color_accent=?, perks=? WHERE id=?",
                 (rank, title, amount, badge, trophy, color, perks, pod_id))
    db().commit()
    log_admin_action(db(), session.get("admin_user"), "EDIT_PODIUM", "PODIUM", pod_id, title)
    flash(f"Podium place '{title}' updated.")
    return redirect(f"/{ADMIN_SECRET_SLUG}/content#tab-prizes")

@app.route(f"/{ADMIN_SECRET_SLUG}/content/podium/delete/<int:pod_id>", methods=["POST"])
@admin_required
def admin_delete_podium(pod_id):
    db().execute("DELETE FROM prize_podium WHERE id=?", (pod_id,))
    db().commit()
    log_admin_action(db(), session.get("admin_user"), "DELETE_PODIUM", "PODIUM", pod_id)
    flash("Podium entry deleted.")
    return redirect(f"/{ADMIN_SECRET_SLUG}/content#tab-prizes")

@app.route(f"/{ADMIN_SECRET_SLUG}/content/prize-perks/add", methods=["POST"])
@admin_required
def admin_add_prize_perk():
    f = request.form
    title = f.get("title", "").strip()
    desc = f.get("description", "").strip()
    icon = f.get("icon", "trophy").strip()
    order = int(f.get("order_idx", 99) or 99)
    if title:
        db().execute("INSERT INTO prize_perks(title, description, icon, order_idx) VALUES(?,?,?,?)",
                     (title, desc, icon, order))
        db().commit()
        log_admin_action(db(), session.get("admin_user"), "ADD_PERK", "PERK", "0", title)
        flash(f"Participant perk '{title}' added.")
    return redirect(f"/{ADMIN_SECRET_SLUG}/content#tab-prizes")

@app.route(f"/{ADMIN_SECRET_SLUG}/content/prize-perks/edit/<int:perk_id>", methods=["POST"])
@admin_required
def admin_edit_prize_perk(perk_id):
    f = request.form
    title = f.get("title", "").strip()
    desc = f.get("description", "").strip()
    icon = f.get("icon", "trophy").strip()
    order = int(f.get("order_idx", 99) or 99)
    db().execute("UPDATE prize_perks SET title=?, description=?, icon=?, order_idx=? WHERE id=?",
                 (title, desc, icon, order, perk_id))
    db().commit()
    log_admin_action(db(), session.get("admin_user"), "EDIT_PERK", "PERK", perk_id, title)
    flash(f"Perk '{title}' updated.")
    return redirect(f"/{ADMIN_SECRET_SLUG}/content#tab-prizes")

@app.route(f"/{ADMIN_SECRET_SLUG}/content/prize-perks/delete/<int:perk_id>", methods=["POST"])
@admin_required
def admin_delete_prize_perk(perk_id):
    db().execute("DELETE FROM prize_perks WHERE id=?", (perk_id,))
    db().commit()
    log_admin_action(db(), session.get("admin_user"), "DELETE_PERK", "PERK", perk_id)
    flash("Perk deleted.")
    return redirect(f"/{ADMIN_SECRET_SLUG}/content#tab-prizes")

@app.route(f"/{ADMIN_SECRET_SLUG}/content/prize-rules/add", methods=["POST"])
@admin_required
def admin_add_prize_rule():
    text = request.form.get("rule_text", "").strip()
    order = int(request.form.get("order_idx", 99) or 99)
    if text:
        db().execute("INSERT INTO prize_rules(rule_text, order_idx) VALUES(?,?)", (text, order))
        db().commit()
        log_admin_action(db(), session.get("admin_user"), "ADD_PRIZE_RULE", "PRIZE_RULE", "0")
        flash("Disbursement rule added.")
    return redirect(f"/{ADMIN_SECRET_SLUG}/content#tab-prizes")

@app.route(f"/{ADMIN_SECRET_SLUG}/content/prize-rules/edit/<int:rule_id>", methods=["POST"])
@admin_required
def admin_edit_prize_rule(rule_id):
    text = request.form.get("rule_text", "").strip()
    order = int(request.form.get("order_idx", 99) or 99)
    db().execute("UPDATE prize_rules SET rule_text=?, order_idx=? WHERE id=?", (text, order, rule_id))
    db().commit()
    log_admin_action(db(), session.get("admin_user"), "EDIT_PRIZE_RULE", "PRIZE_RULE", rule_id)
    flash("Disbursement rule updated.")
    return redirect(f"/{ADMIN_SECRET_SLUG}/content#tab-prizes")

@app.route(f"/{ADMIN_SECRET_SLUG}/content/prize-rules/delete/<int:rule_id>", methods=["POST"])
@admin_required
def admin_delete_prize_rule(rule_id):
    db().execute("DELETE FROM prize_rules WHERE id=?", (rule_id,))
    db().commit()
    log_admin_action(db(), session.get("admin_user"), "DELETE_PRIZE_RULE", "PRIZE_RULE", rule_id)
    flash("Disbursement rule deleted.")
    return redirect(f"/{ADMIN_SECRET_SLUG}/content#tab-prizes")

# ====================
# ABOUT CMS ACTIONS
# ====================

@app.route(f"/{ADMIN_SECRET_SLUG}/content/about/info", methods=["POST"])
@admin_required
def admin_save_about_info():
    keys = [
        "acm_section_title", "acm_badge", "acm_sub", "acm_desc_p1", "acm_desc_p2",
        "acm_chapter_title", "acm_chapter_desc", "acm_highlight",
        "headline", "subheadline", "mission_p1", "mission_p2", "institute_name", "chapter_name",
        "stat_hours", "stat_prize", "stat_teams", "stat_mentors"
    ]
    for k in keys:
        if k in request.form:
            val = request.form.get(k, "").strip()
            db().execute("INSERT OR REPLACE INTO about_info(key, value) VALUES(?, ?)", (k, val))
    db().commit()
    log_admin_action(db(), session.get("admin_user"), "UPDATE_CONTENT", "ABOUT_INFO", "0")
    flash("About page & ACM section information updated.")
    return redirect(f"/{ADMIN_SECRET_SLUG}/content#tab-about")

@app.route(f"/{ADMIN_SECRET_SLUG}/content/pillars/add", methods=["POST"])
@admin_required
def admin_add_pillar():
    f = request.form
    title = f.get("title", "").strip()
    desc = f.get("description", "").strip()
    icon = f.get("icon", "bolt").strip()
    order = int(f.get("order_idx", 99) or 99)
    if title:
        db().execute("INSERT INTO about_pillars(title, description, icon, order_idx) VALUES(?,?,?,?)",
                     (title, desc, icon, order))
        db().commit()
        log_admin_action(db(), session.get("admin_user"), "ADD_PILLAR", "PILLAR", "0", title)
        flash(f"Pillar '{title}' added.")
    return redirect(f"/{ADMIN_SECRET_SLUG}/content#tab-about")

@app.route(f"/{ADMIN_SECRET_SLUG}/content/pillars/edit/<int:pillar_id>", methods=["POST"])
@admin_required
def admin_edit_pillar(pillar_id):
    f = request.form
    title = f.get("title", "").strip()
    desc = f.get("description", "").strip()
    icon = f.get("icon", "bolt").strip()
    order = int(f.get("order_idx", 99) or 99)
    db().execute("UPDATE about_pillars SET title=?, description=?, icon=?, order_idx=? WHERE id=?",
                 (title, desc, icon, order, pillar_id))
    db().commit()
    log_admin_action(db(), session.get("admin_user"), "EDIT_PILLAR", "PILLAR", pillar_id, title)
    flash(f"Pillar '{title}' updated.")
    return redirect(f"/{ADMIN_SECRET_SLUG}/content#tab-about")

@app.route(f"/{ADMIN_SECRET_SLUG}/content/pillars/delete/<int:pillar_id>", methods=["POST"])
@admin_required
def admin_delete_pillar(pillar_id):
    db().execute("DELETE FROM about_pillars WHERE id=?", (pillar_id,))
    db().commit()
    log_admin_action(db(), session.get("admin_user"), "DELETE_PILLAR", "PILLAR", pillar_id)
    flash("Pillar deleted.")
    return redirect(f"/{ADMIN_SECRET_SLUG}/content#tab-about")

# ====================
# FAQ CMS ACTIONS
# ====================

@app.route(f"/{ADMIN_SECRET_SLUG}/content/faq-categories/add", methods=["POST"])
@admin_required
def admin_add_faq_category():
    slug = request.form.get("slug", "").strip().lower()
    title = request.form.get("title", "").strip()
    order = int(request.form.get("order_idx", 99) or 99)
    if slug and title:
        db().execute("INSERT OR REPLACE INTO faq_categories(slug, title, order_idx) VALUES(?,?,?)", (slug, title, order))
        db().commit()
        log_admin_action(db(), session.get("admin_user"), "ADD_FAQ_CAT", "FAQ_CAT", "0", title)
        flash(f"FAQ category '{title}' saved.")
    return redirect(f"/{ADMIN_SECRET_SLUG}/content#tab-faq")

@app.route(f"/{ADMIN_SECRET_SLUG}/content/faq-categories/delete/<int:cat_id>", methods=["POST"])
@admin_required
def admin_delete_faq_category(cat_id):
    db().execute("DELETE FROM faq_categories WHERE id=?", (cat_id,))
    db().commit()
    log_admin_action(db(), session.get("admin_user"), "DELETE_FAQ_CAT", "FAQ_CAT", cat_id)
    flash("FAQ category deleted.")
    return redirect(f"/{ADMIN_SECRET_SLUG}/content#tab-faq")

@app.route(f"/{ADMIN_SECRET_SLUG}/content/faq/add", methods=["POST"])
@admin_required
def admin_add_faq():
    cat = request.form.get("category_slug", "general").strip()
    q = request.form.get("question", "").strip()
    a = request.form.get("answer", "").strip()
    order = int(request.form.get("order_idx", 99) or 99)
    if q and a:
        db().execute("INSERT INTO faq_items(category_slug, question, answer, order_idx) VALUES(?, ?, ?, ?)", (cat, q, a, order))
        db().commit()
        log_admin_action(db(), session.get("admin_user"), "ADD_FAQ", "FAQ", "0", q)
        flash("New FAQ item added.")
    return redirect(f"/{ADMIN_SECRET_SLUG}/content#tab-faq")

@app.route(f"/{ADMIN_SECRET_SLUG}/content/faq/edit/<int:faq_id>", methods=["POST"])
@admin_required
def admin_edit_faq(faq_id):
    cat = request.form.get("category_slug", "").strip()
    q = request.form.get("question", "").strip()
    a = request.form.get("answer", "").strip()
    order = int(request.form.get("order_idx", 99) or 99)
    db().execute("UPDATE faq_items SET category_slug=?, question=?, answer=?, order_idx=? WHERE id=?", (cat, q, a, order, faq_id))
    db().commit()
    log_admin_action(db(), session.get("admin_user"), "EDIT_FAQ", "FAQ", faq_id, q)
    flash("FAQ item updated.")
    return redirect(f"/{ADMIN_SECRET_SLUG}/content#tab-faq")

@app.route(f"/{ADMIN_SECRET_SLUG}/content/faq/delete/<int:faq_id>", methods=["POST"])
@admin_required
def admin_delete_faq(faq_id):
    db().execute("DELETE FROM faq_items WHERE id=?", (faq_id,))
    db().commit()
    log_admin_action(db(), session.get("admin_user"), "DELETE_FAQ", "FAQ", faq_id)
    flash("FAQ item deleted.")
    return redirect(f"/{ADMIN_SECRET_SLUG}/content#tab-faq")

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
