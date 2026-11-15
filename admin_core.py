import sqlite3, os, csv, io
from functools import wraps
from flask import session, abort, Response
from werkzeug.security import generate_password_hash, check_password_hash

ADMIN_SECRET_SLUG = os.environ.get("ADMIN_SECRET_SLUG", "ops-gateway-2027")

def init_admin_tables(db_path):
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        c = conn.cursor()
        c.executescript("""
        CREATE TABLE IF NOT EXISTS admins(
            id INTEGER PRIMARY KEY,
            username TEXT UNIQUE,
            pw TEXT,
            full_name TEXT,
            role TEXT DEFAULT 'SuperAdmin',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_login TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS admin_audit_log(
            id INTEGER PRIMARY KEY,
            admin_user TEXT,
            action TEXT,
            target_type TEXT,
            target_id TEXT,
            details TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)
        
        # Check if master admin exists
        row = c.execute("SELECT COUNT(*) FROM admins").fetchone()
        if not row or row[0] == 0:
            default_user = os.environ.get("ADMIN_USERNAME", "admin")
            default_pass = os.environ.get("ADMIN_PASSWORD", "CodeNite2027@MITS")
            hashed_pw = generate_password_hash(default_pass)
            c.execute("""
                INSERT INTO admins(username, pw, full_name, role)
                VALUES(?, ?, 'ACM MITS Head Organizer', 'SuperAdmin')
            """, (default_user, hashed_pw))
            conn.commit()
            print(f"Master admin initialized: {default_user}")

def log_admin_action(conn, admin_user, action, target_type, target_id, details=""):
    try:
        conn.execute("""
            INSERT INTO admin_audit_log(admin_user, action, target_type, target_id, details)
            VALUES(?, ?, ?, ?, ?)
        """, (admin_user, action, target_type, str(target_id), details))
        conn.commit()
    except Exception as e:
        print("Audit log error:", e)

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("is_admin"):
            abort(404)  # Return 404 to hide admin route existence completely from regular users
        return f(*args, **kwargs)
    return decorated_function

def generate_teams_csv(conn):
    conn.row_factory = sqlite3.Row
    teams = conn.execute("SELECT * FROM teams ORDER BY id ASC").fetchall()
    
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Headers
    headers = [
        "Team ID", "Team Name", "Track / Domain", "Payment Status", "Registration Time",
        "Leader Name", "Leader Email", "Leader Phone", "Leader College", "Leader Branch", "Leader Year", "Leader Enrollment",
        "Member 2 Name", "Member 2 Email", "Member 2 Phone", "Member 2 College",
        "Member 3 Name", "Member 3 Email", "Member 3 Phone", "Member 3 College",
        "Member 4 Name", "Member 4 Email", "Member 4 Phone", "Member 4 College",
        "Member 5 Name", "Member 5 Email", "Member 5 Phone", "Member 5 College",
        "Member 6 Name", "Member 6 Email", "Member 6 Phone", "Member 6 College"
    ]
    writer.writerow(headers)
    
    for t in teams:
        members = conn.execute("SELECT * FROM members WHERE team=? ORDER BY is_leader DESC, id ASC", (t["id"],)).fetchall()
        leader = members[0] if members else None
        
        row = [
            t["team_id"],
            t["name"],
            t["domain"],
            t["payment_status"],
            t["created_at"],
            f"{leader['fname']} {leader['lname']}" if leader else "",
            leader["email"] if leader else "",
            leader["phone"] if leader else "",
            leader["college"] if leader else "",
            leader["branch"] if leader else "",
            leader["year"] if leader else "",
            leader["enrollment"] if leader else ""
        ]
        
        # Teammates 2 to 6
        teammates = members[1:] if len(members) > 1 else []
        for i in range(5):
            if i < len(teammates):
                m = teammates[i]
                row.extend([
                    f"{m['fname']} {m['lname']}".strip(),
                    m["email"],
                    m["phone"],
                    m["college"]
                ])
            else:
                row.extend(["", "", "", ""])
                
        writer.writerow(row)
        
    return output.getvalue()
