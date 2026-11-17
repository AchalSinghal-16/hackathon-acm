import sqlite3, os

def init_about_faq_tables(db_path):
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        c = conn.cursor()
        c.executescript("""
        CREATE TABLE IF NOT EXISTS about_info(
            id INTEGER PRIMARY KEY,
            key TEXT UNIQUE,
            value TEXT
        );

        CREATE TABLE IF NOT EXISTS about_pillars(
            id INTEGER PRIMARY KEY,
            title TEXT,
            description TEXT,
            icon TEXT,
            order_idx INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS about_facilities(
            id INTEGER PRIMARY KEY,
            title TEXT,
            description TEXT,
            icon TEXT,
            order_idx INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS faq_categories(
            id INTEGER PRIMARY KEY,
            slug TEXT UNIQUE,
            title TEXT,
            order_idx INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS faq_items(
            id INTEGER PRIMARY KEY,
            category_slug TEXT,
            question TEXT,
            answer TEXT,
            order_idx INTEGER DEFAULT 0
        );
        """)

        # Check if about data exists
        row = c.execute("SELECT COUNT(*) FROM about_pillars").fetchone()
        if not row or row[0] == 0:
            # 1. about_info
            about_meta = [
                ("headline", "Empowering Innovators. Building the Future."),
                ("subheadline", "Central India's flagship 12-hour offline hackathon on January 17, 2027 hosted by the ACM Student Chapter at Madhav Institute of Technology & Science (MITS), Gwalior."),
                ("acm_section_title", "What is ACM?"),
                ("acm_badge", "The Global Computing Society"),
                ("acm_sub", "Association for Computing Machinery · Advancing Computing as a Science & Profession"),
                ("acm_desc_p1", "The Association for Computing Machinery (ACM) is the world's largest educational and scientific computing society, delivering resources that advance computing as a science and a profession. ACM brings together computing educators, researchers, and professionals to inspire dialogue, share technical resources, and address the grand challenges of the computing field."),
                ("acm_desc_p2", "ACM provides the computing field's premier digital library, publishes leading journals and magazines, organizes top-tier international computing conferences, and awards the prestigious A.M. Turing Award — universally recognized as the 'Nobel Prize of Computing'."),
                ("acm_chapter_title", "ACM Student Chapter @ MITS Gwalior"),
                ("acm_chapter_desc", "Established at Madhav Institute of Technology & Science (MITS Gwalior, est. 1957), the ACM Student Chapter is a vibrant student-driven developer community dedicated to technical excellence. We empower student builders through high-velocity hackathons like CodeNite, open-source cohorts, algorithmic contests, and mentorship programs."),
                ("acm_highlight", "A worldwide network uniting over 100,000+ computing professionals, researchers, and student builders across 190+ countries."),
                ("mission_p1", "ACM CodeNite 2027 is a high-octane 12-hour offline hackathon engineered to bring India's sharpest student developers, designers, and innovators under one roof on January 17, 2027. Our mission is to transform theoretical academic knowledge into tangible, deployable real-world software solutions."),
                ("mission_p2", "Hosted at the state-of-the-art campus of Madhav Institute of Technology & Science (MITS Gwalior, est. 1957), CodeNite is supported by leading industry partners, top technical mentors, and angel investors dedicated to fostering the next wave of tech founders."),
                ("institute_name", "Madhav Institute of Technology & Science (MITS), Gwalior"),
                ("chapter_name", "ACM Student Chapter, MITS Gwalior"),
                ("stat_hours", "12"),
                ("stat_prize", "₹50,000+"),
                ("stat_teams", "100+"),
                ("stat_mentors", "20+")
            ]
            c.executemany("INSERT OR REPLACE INTO about_info(key, value) VALUES(?, ?)", about_meta)

            # 2. about_pillars
            pillars = [
                ("12 Hours of Pure Innovation", "A high-intensity sprint where teams conceptualize, architect, code, and deploy functional prototypes from scratch.", "bolt", 1),
                ("Round-the-Clock Mentorship", "Experienced engineers, tech leads, and startup founders on the floor 24/7 to help untangle bugs, architecture, and pitch decks.", "users", 2),
                ("Zero-Cost Campus Hospitality", "Completely covered hospitality including buffet meals, midnight pizza, energy bars, and continuous tea and coffee stations.", "trophy", 3),
                ("Industry & Investor Exposure", "Showcase your project directly before tech leaders, startup incubators, and corporate hiring managers for career-defining opportunities.", "globe", 4),
                ("Transparent Double-Stage Judging", "Rigorous and objective evaluation combining technical architecture audits and live 5-minute onstage grand jury demos.", "check", 5),
                ("Inclusive Builder Community", "An open, respectful, and vibrant community bringing together coders, designers, hardware hackers, and domain researchers.", "sparkles", 6)
            ]
            c.executemany("INSERT INTO about_pillars(title, description, icon, order_idx) VALUES(?, ?, ?, ?)", pillars)

        # Check if faq data exists
        row_faq = c.execute("SELECT COUNT(*) FROM faq_items").fetchone()
        if not row_faq or row_faq[0] == 0:
            # 4. faq_categories
            categories = [
                ("general", "General & Format", 1),
                ("eligibility", "Team & Eligibility", 2),
                ("rules", "Code & Guidelines", 3),
                ("submissions", "Submissions & Judging", 4),
                ("logistics", "Venue & Hospitality", 5)
            ]
            c.executemany("INSERT OR REPLACE INTO faq_categories(slug, title, order_idx) VALUES(?, ?, ?)", categories)

            # 5. faq_items
            faqs = [
                # General
                ("general", "What is ACM CodeNite 2027?",
                 "ACM CodeNite 2027 is Central India's premier 12-hour national offline hackathon organized by the ACM Student Chapter at Madhav Institute of Technology & Science (MITS), Gwalior. Teams of 4 to 6 students build working prototypes over 12 hours on January 17, 2027 to solve real-world problems.", 1),
                ("general", "When and where is the hackathon taking place?",
                 "The hackathon will take place offline on Sunday, January 17, 2027 at the MITS Campus and Innovation Labs, Gwalior (Madhya Pradesh).", 2),
                ("general", "Is the hackathon completely offline / in-person?",
                 "Yes! ACM CodeNite 2027 is a 100% in-person, on-campus hackathon. Teams must be physically present at MITS Gwalior for check-in, build sprint, mentorship rounds, and final jury presentations.", 3),
                ("general", "Is there a registration fee to participate?",
                 "A nominal initial fee of ₹50 per team is collected during registration for team verification and confirmation. Once registered, full participation, food, midnight pizza, Wi-Fi, mentorship, and swag are completely free for all team members.", 4),

                # Eligibility
                ("eligibility", "Who is eligible to participate in ACM CodeNite?",
                 "Any currently enrolled undergraduate or postgraduate student from any recognized college, university, or institute in India with a valid college ID card is eligible to participate.", 5),
                ("eligibility", "What is the team size requirement?",
                 "Teams must have a minimum of 4 members and can have up to a maximum of 6 members. Individual participation or teams with fewer than 4 members are strictly not permitted.", 6),
                ("eligibility", "Can teammates be from different colleges or different years?",
                 "Yes, absolutely! Cross-college, cross-department, and multi-year teams are highly encouraged. Every member can specify their own college and academic year during registration.", 7),
                ("eligibility", "Can we change team members after registering?",
                 "Yes. The Team Leader can log into the Team Dashboard anytime before the event to update teammate details, add new members (up to 6), or remove members (provided the team does not drop below the mandatory 4 members).", 8),

                # Rules
                ("rules", "Can we use pre-built or existing projects?",
                 "No. All project code and core implementation must be written fresh during the official 36-hour hackathon duration. You are free to use open-source libraries, public frameworks, APIs, and UI component kits, but pre-built proprietary software will lead to immediate disqualification.", 9),
                ("rules", "What should we bring with us to the venue?",
                 "Every participant must bring their personal laptop, charger, valid college ID card, government photo ID (Aadhaar/Driver's License), and any specific hardware or IoT development kits required for their project.", 10),
                ("rules", "Will the problem statements be provided beforehand?",
                 "The 5 broad innovation tracks (AI/ML, Web3, Web/Mobile, Cloud/Cyber, Open Innovation) and sample challenge briefs are available on the Events page. Detailed specific problem statements will be officially unlocked during the Grand Opening Ceremony on Day 1.", 11),

                # Submissions
                ("submissions", "What deliverables are required during the hackathon?",
                 "Teams submit 3 key milestones via their online portal: Round 1 (Idea synopsis & PPT presentation deck), Round 2 (Mid-hack GitHub progress checkpoint), and Round 3 (Final GitHub repository, deployed live URL, and 2-minute video demo).", 12),
                ("submissions", "How will the projects be evaluated?",
                 "Projects are evaluated by industry judges and academic experts across 5 criteria: Innovation & Novelty (25%), Technical Complexity & Architecture (25%), Practical Impact & Feasibility (20%), UI/UX & Accessibility (15%), and Live Demo & Pitch Presentation (15%).", 13),
                ("submissions", "How and when are cash prizes disbursed?",
                 "All prize money is disbursed directly to the designated Team Leader's verified bank account or UPI within 7 to 10 working days following the closing ceremony, subject to statutory tax guidelines.", 14),

                # Logistics
                ("logistics", "What hospitality and food arrangements are provided?",
                 "All meals—including buffet breakfast, hot lunch, high tea, evening dinner, midnight snacks, pizza, and 24/7 tea/coffee stations—are provided completely free of charge to all verified participants.", 15),
                ("logistics", "Are there rest zones and sleeping arrangements?",
                 "Yes. MITS provides dedicated gender-separated air-conditioned resting halls with mattresses and blankets for participants wishing to take power naps during the overnight build.", 16),
                ("logistics", "Whom should we contact in case of queries?",
                 "You can reach out to the ACM CodeNite organizing committee via the official email support desk or approach the on-ground Helpdesk counters on campus throughout the event.", 17)
            ]
            c.executemany("INSERT INTO faq_items(category_slug, question, answer, order_idx) VALUES(?, ?, ?, ?)", faqs)

        conn.commit()
        print("Successfully initialized and seeded About & FAQ data!")

if __name__ == "__main__":
    init_about_faq_tables(os.path.join("instance", "hackathon.db"))
