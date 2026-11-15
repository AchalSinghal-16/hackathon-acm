import sqlite3, os

def init_event_tables(db_path):
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        c = conn.cursor()
        c.executescript("""
        CREATE TABLE IF NOT EXISTS event_info(
            id INTEGER PRIMARY KEY,
            key TEXT UNIQUE,
            value TEXT
        );
        CREATE TABLE IF NOT EXISTS event_schedule(
            id INTEGER PRIMARY KEY,
            day_title TEXT,
            time_slot TEXT,
            title TEXT,
            description TEXT,
            badge TEXT,
            order_idx INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS event_tracks(
            id INTEGER PRIMARY KEY,
            title TEXT,
            tagline TEXT,
            description TEXT,
            icon TEXT,
            color_accent TEXT,
            order_idx INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS event_problems(
            id INTEGER PRIMARY KEY,
            track_id INTEGER,
            code TEXT,
            title TEXT,
            description TEXT,
            pdf_url TEXT,
            FOREIGN KEY(track_id) REFERENCES event_tracks(id)
        );
        CREATE TABLE IF NOT EXISTS event_rules(
            id INTEGER PRIMARY KEY,
            category TEXT,
            rule_text TEXT,
            order_idx INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS event_judging(
            id INTEGER PRIMARY KEY,
            criterion TEXT,
            weightage TEXT,
            description TEXT,
            order_idx INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS event_rounds(
            id INTEGER PRIMARY KEY,
            round_num INTEGER,
            title TEXT,
            stage_name TEXT,
            deadline TEXT,
            status_label TEXT,
            description TEXT,
            submission_type TEXT,
            order_idx INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS team_submissions(
            id INTEGER PRIMARY KEY,
            team_id INTEGER,
            round_id INTEGER,
            project_title TEXT,
            project_summary TEXT,
            file_path TEXT,
            drive_link TEXT,
            github_link TEXT,
            demo_link TEXT,
            submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            status TEXT DEFAULT 'Submitted',
            remarks TEXT,
            FOREIGN KEY(team_id) REFERENCES teams(id) ON DELETE CASCADE,
            FOREIGN KEY(round_id) REFERENCES event_rounds(id) ON DELETE CASCADE,
            UNIQUE(team_id, round_id)
        );
        """)

        # Check if tracks already exist
        row = c.execute("SELECT COUNT(*) FROM event_tracks").fetchone()
        if not row or row[0] == 0:
            # 1. event_info
            info_items = [
                ("tagline", "Central India's Premier 36-Hour National Hackathon"),
                ("dates", "March 20 – 22, 2027"),
                ("mode", "In-Person / Offline Hackathon"),
                ("venue", "MITS Campus & Innovation Center, Gwalior (M.P.)"),
                ("duration", "36 Continuous Hours"),
                ("team_size", "4 to 6 Participants"),
                ("prize_pool", "₹2,00,000+"),
                ("about_p1", "ACM CodeNite 2027 is a high-octane 36-hour offline hackathon hosted by the ACM Student Chapter at Madhav Institute of Technology & Science (MITS). Bringing together passionate developers, designers, and innovators from across India, CodeNite provides the ultimate stage to solve pressing real-world challenges through code."),
                ("about_p2", "Participants collaborate overnight with access to round-the-clock mentorship from top industry leaders, high-speed campus infrastructure, interactive workshops, delicious meals, midnight hack jams, and massive cash prizes.")
            ]
            c.executemany("INSERT OR REPLACE INTO event_info(key, value) VALUES(?, ?)", info_items)

            # 2. event_tracks
            tracks = [
                ("AI & Machine Learning", "Autonomous systems, foundation models & computer vision", "Harness next-generation LLMs, generative media, edge AI, computer vision, and autonomous agentic workflows to create transformative automated solutions.", "cpu", "#8b5cf6", 1),
                ("Web3 & Blockchain", "Smart contracts, DeFi, decentralized identities & zk-Proofs", "Architect trustless platforms, transparent financial primitives, zero-knowledge verifiable credentials, and decentralized governance systems.", "lock", "#3b82f6", 2),
                ("Web & Mobile App Innovation", "Hyper-scalable apps, real-time collaboration & intuitive UX", "Craft blazing-fast, accessible, responsive full-stack applications with state-of-the-art UI/UX, PWAs, real-time sync, and consumer tech innovation.", "globe", "#10b981", 3),
                ("Cloud, DevOps & Cybersecurity", "Zero-trust architectures, security pipelines & infrastructure resilience", "Tackle cyber threat mitigation, cloud security monitoring, automated CI/CD pipelines, container orchestration, and serverless architectures.", "shield", "#f59e0b", 4),
                ("Open Innovation & Social Impact", "Disruptive interdisciplinary solutions for sustainability and society", "Cross-boundary solutions targeting clean energy, smart cities, accessible healthcare diagnostics, digital agriculture, and assistive civic technologies.", "bulb", "#ec4899", 5)
            ]
            c.executemany("INSERT INTO event_tracks(title, tagline, description, icon, color_accent, order_idx) VALUES(?, ?, ?, ?, ?, ?)", tracks)

            # 3. event_problems
            problems = [
                (1, "PS-AI-01", "Multilingual Emergency Voice/Text Dispatcher", "Develop an intelligent offline-capable or low-latency agent that transcribes vernacular voice distress calls, classifies emergency severity, and automates resource routing.", "#"),
                (2, "PS-W3-02", "Zero-Knowledge Verifiable Academic Credential Ledger", "Build a tamper-proof decentralized credential issuance and verification platform using zk-SNARKs to guarantee student privacy and rapid institutional verification.", "#"),
                (3, "PS-WM-03", "Offline-First Collaborative Classroom for Remote Regions", "Create a low-bandwidth, peer-to-peer synced learning portal supporting collaborative whiteboards, audio snippets, and conflict-free replicated data types (CRDTs).", "#"),
                (4, "PS-CS-04", "Automated Cloud Identity & Misconfiguration Sentinel", "Design an automated security audit pipeline that detects IAM privilege escalation paths and misconfigured Kubernetes ingress controllers in real time.", "#"),
                (5, "PS-OI-05", "AI-Driven Solar Microgrid Energy Balancer", "Develop an IoT telemetry and predictive machine learning dashboard that forecasts local solar generation and optimizes battery discharge across rural microgrids.", "#")
            ]
            c.executemany("INSERT INTO event_problems(track_id, code, title, description, pdf_url) VALUES(?, ?, ?, ?, ?)", problems)

            # 4. event_schedule
            schedule = [
                ("Day 1 · Friday", "09:00 AM – 10:30 AM", "Reporting, Check-In & Welcome Breakfast", "Badge verification, hackathon swag distribution, desk allocation and hot breakfast.", "Check-In", 1),
                ("Day 1 · Friday", "10:30 AM – 11:30 AM", "Grand Inauguration & Keynote Briefing", "Opening ceremony, jury introductions, track walkthroughs and event guidelines.", "Ceremony", 2),
                ("Day 1 · Friday", "11:30 AM Sharp", "Hackathon Sprint Begins (Clock Starts)", "36-hour continuous build begins! High-speed Wi-Fi live, workspace access unlocked.", "Hacking Live", 3),
                ("Day 1 · Friday", "01:30 PM – 02:30 PM", "Networking Lunch Buffet", "Nutritious lunch served at the campus dining center.", "Meal", 4),
                ("Day 1 · Friday", "05:30 PM – 07:30 PM", "Mentorship Round 1 (Ideation & Design Review)", "Industry mentors visit every team to review approach, tech stack, and feasibility.", "Mentorship", 5),
                ("Day 1 · Friday", "08:30 PM – 09:30 PM", "Dinner & Coffee Refuel", "Dinner served with hot coffee and energy snacks.", "Meal", 6),
                ("Day 1 · Friday", "11:59 PM", "Milestone 1 Deadline: Idea Deck & PPT Submission", "All teams submit their solution synopsis and presentation deck via the portal.", "Submission", 7),
                ("Day 2 · Saturday", "01:30 AM – 02:30 AM", "Midnight Hack Jam & Fun Coding Challenges", "Music, midnight pizza, trivia games, and mental rejuvenation.", "Activity", 8),
                ("Day 2 · Saturday", "08:00 AM – 09:00 AM", "Morning Breakfast & Tea Bar", "Fresh breakfast, tea, and fruit juices.", "Meal", 9),
                ("Day 2 · Saturday", "11:30 AM – 01:30 PM", "Mentorship Round 2 (Technical Progress Review)", "Code-level review, API integration troubleshooting, and architecture validation.", "Mentorship", 10),
                ("Day 2 · Saturday", "02:00 PM", "Milestone 2 Deadline: Mid-Hack Progress & GitHub Checkpoint", "Teams push repository commits and submit current working progress link.", "Submission", 11),
                ("Day 2 · Saturday", "05:00 PM – 06:00 PM", "Evening High Tea & Snacks", "High tea and quick organizer standup.", "Meal", 12),
                ("Day 2 · Saturday", "08:30 PM – 09:30 PM", "Dinner & Final Sprint Preparation", "Energizing dinner for the home stretch.", "Meal", 13),
                ("Day 3 · Sunday", "06:00 AM – 07:00 AM", "Dawn Coffee & Final Touches", "Morning coffee, testing edge cases, and pitch preparation.", "Meal", 14),
                ("Day 3 · Sunday", "09:30 AM", "Hacking Ends! Code Freeze & Repository Lock", "Coding ends promptly. All repositories locked for final commits.", "Code Freeze", 15),
                ("Day 3 · Sunday", "10:00 AM", "Milestone 3 Deadline: Final Submission (Demo, Deck, Video)", "Final deployment URL, YouTube/Drive video demo link, and project description.", "Submission", 16),
                ("Day 3 · Sunday", "10:30 AM – 01:30 PM", "Grand Jury Pitches & Live Demonstrations", "5-minute live demo + 3-minute jury Q&A on stage before evaluation committee.", "Judging", 17),
                ("Day 3 · Sunday", "01:30 PM – 02:30 PM", "Buffet Lunch & Project Showcase Expo", "Project exhibition open to students, faculty, and industry guests.", "Exhibition", 18),
                ("Day 3 · Sunday", "03:00 PM – 04:30 PM", "Closing Ceremony, Winner Announcement & Felicitation", "Trophy handover, cash prize awards, certificate distribution, and photo session.", "Ceremony", 19)
            ]
            c.executemany("INSERT INTO event_schedule(day_title, time_slot, title, description, badge, order_idx) VALUES(?, ?, ?, ?, ?, ?)", schedule)

            # 5. event_rules
            rules = [
                ("Eligibility & Composition", "Teams must consist of 4 to 6 members. Cross-college, cross-department, and cross-year teams are eligible and encouraged.", 1),
                ("Code Authenticity", "All code and design assets must be created during the official 36-hour hackathon period. Open-source libraries and public frameworks are permitted, but pre-built closed proprietary code is strictly prohibited.", 2),
                ("Mentorship & Attendance", "At least 3 team members must be physically present at their allocated station during all official mentorship and evaluation rounds.", 3),
                ("Submissions & Deadlines", "All milestones (Round 1 PPT, Round 2 GitHub checkpoint, Round 3 Final demo) must be submitted via this portal prior to the deadline timestamps.", 4),
                ("Decorum & Ethics", "Participants must maintain professionalism and adhere to the ACM Code of Conduct. Any plagiarism or harassment will lead to immediate disqualification.", 5)
            ]
            c.executemany("INSERT INTO event_rules(category, rule_text, order_idx) VALUES(?, ?, ?)", rules)

            # 6. event_judging
            judging = [
                ("Innovation & Novelty", "25%", "Uniqueness of the concept, creative problem solving, and novel approach to the domain challenge.", 1),
                ("Technical Complexity & Architecture", "25%", "Code quality, technical depth, robust backend/frontend design, and seamless API integrations.", 2),
                ("Practical Impact & Feasibility", "20%", "Real-world usability, target audience value proposition, market viability, and deployment potential.", 3),
                ("User Experience & Accessibility", "15%", "Clean visual design, intuitive interface navigation, responsiveness, and inclusive UX.", 4),
                ("Pitch Clarity & Live Demo", "15%", "Effectiveness of the pitch, live functioning demonstration, teamwork, and crisp defense during jury Q&A.", 5)
            ]
            c.executemany("INSERT INTO event_judging(criterion, weightage, description, order_idx) VALUES(?, ?, ?, ?)", judging)

            # 7. event_rounds
            rounds = [
                (1, "Round 1: Idea Synopsis & Presentation Deck", "Stage 1 · Ideation", "March 20, 2027 · 11:59 PM", "Open Now", "Submit your team's project title, domain problem statement, proposed solution architecture, and upload your PPT/PDF pitch deck (or provide a shareable Google Drive link).", "deck", 1),
                (2, "Round 2: Mid-Hack Progress & GitHub Checkpoint", "Stage 2 · Code In Progress", "March 21, 2027 · 02:00 PM", "Upcoming", "Share your public GitHub repository URL, key modules implemented so far, and any technical blockers for mentor review.", "progress", 2),
                (3, "Round 3: Final Project Submission & Video Demo", "Stage 3 · Final Delivery", "March 22, 2027 · 10:00 AM", "Upcoming", "Final repository lock, deployed live URL (e.g., Vercel, Netlify, Render), 2-minute demo video link (YouTube / Drive), and project summary.", "final", 3)
            ]
            c.executemany("INSERT INTO event_rounds(round_num, title, stage_name, deadline, status_label, description, submission_type, order_idx) VALUES(?, ?, ?, ?, ?, ?, ?, ?)", rounds)

            conn.commit()
            print("Successfully initialized and seeded event data!")
        else:
            print("Event data already exists.")

if __name__ == "__main__":
    init_event_tables(os.path.join("instance", "hackathon.db"))
