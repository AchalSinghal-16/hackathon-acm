import sqlite3, os

def init_prize_tables(db_path):
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        c = conn.cursor()
        c.executescript("""
        CREATE TABLE IF NOT EXISTS prize_overview(
            id INTEGER PRIMARY KEY,
            key TEXT UNIQUE,
            value TEXT
        );

        CREATE TABLE IF NOT EXISTS prize_podium(
            id INTEGER PRIMARY KEY,
            rank INTEGER,
            title TEXT,
            amount TEXT,
            badge TEXT,
            trophy TEXT,
            color_accent TEXT,
            gradient TEXT,
            perks TEXT,
            order_idx INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS prize_categories(
            id INTEGER PRIMARY KEY,
            title TEXT,
            amount TEXT,
            tag TEXT,
            description TEXT,
            icon TEXT,
            color_accent TEXT,
            order_idx INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS prize_perks(
            id INTEGER PRIMARY KEY,
            title TEXT,
            description TEXT,
            icon TEXT,
            order_idx INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS prize_rules(
            id INTEGER PRIMARY KEY,
            rule_text TEXT,
            order_idx INTEGER DEFAULT 0
        );
        """)

        row = c.execute("SELECT COUNT(*) FROM prize_podium").fetchone()
        if not row or row[0] == 0:
            # 1. prize_overview
            overview = [
                ("total_pool", "₹2,50,000+"),
                ("cash_pool", "₹2,00,000"),
                ("perks_val", "₹50,000+ in Cloud Credits & Swag"),
                ("headline", "Compete for Glory, Cash & Career-Defining Opportunities"),
                ("sub", "ACM CodeNite 2027 features a massive prize pool designed to reward technical depth, creative innovation, and tangible execution.")
            ]
            c.executemany("INSERT OR REPLACE INTO prize_overview(key, value) VALUES(?, ?)", overview)

            # 2. prize_podium
            podium = [
                (1, "Grand Champion (1st Place)", "₹1,00,000", "🥇 1st Place", "ACM CodeNite Winner Trophy & Gold Medals", "#eab308", "linear-gradient(135deg,#fffbeb,#fef3c7)",
                 "₹1,00,000 Direct Cash Award\nFast-track Direct Internship Interviews with Sponsor Companies\nACM CodeNite Grand Champion Trophy & Gold Medals\n₹50,000 AWS & Cloud Infrastructure Credits\nExclusive Winner Swag Kits & Framed Certificates of Grand Excellence", 1),
                (2, "1st Runner-Up (2nd Place)", "₹60,000", "🥈 2nd Place", "Runner-Up Trophy & Silver Medals", "#94a3b8", "linear-gradient(135deg,#f8fafc,#f1f5f9)",
                 "₹60,000 Direct Cash Award\nDirect Interviews for Paid Tech Internships\nOfficial Runner-Up Trophy & Silver Medals\n₹25,000 Cloud & Developer Tooling Credits\nPremium Runner-Up Swag Kits & Certificates of Excellence", 2),
                (3, "2nd Runner-Up (3rd Place)", "₹30,000", "🥉 3rd Place", "2nd Runner-Up Trophy & Bronze Medals", "#d97706", "linear-gradient(135deg,#fffbeb,#fed7aa)",
                 "₹30,000 Direct Cash Award\nCurated Career Mentorship & Network Access\nOfficial 2nd Runner-Up Trophy & Bronze Medals\n₹15,000 Cloud Tooling Credits\nOfficial Swag Box & Certificates of Excellence", 3)
            ]
            c.executemany("INSERT INTO prize_podium(rank, title, amount, badge, trophy, color_accent, gradient, perks, order_idx) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)", podium)

            # 3. prize_categories
            categories = [
                ("Best All-First-Year Team", "₹10,000", "Freshman Excellence", "Awarded to the top-scoring team composed entirely of 1st-year undergraduate students, accompanied by special campus incubator support.", "bolt", "#8b5cf6", 1),
                ("Best AI / Machine Learning Innovation", "₹10,000", "Track Award", "Recognizing the most innovative deployment of foundation models, computer vision, or autonomous agent workflows.", "cpu", "#3b82f6", 2),
                ("Best Web3 & Decentralized Platform", "₹10,000", "Track Award", "Awarded to the standout decentralized application showcasing novel smart contracts, zk-proofs, or verifiable credentials.", "lock", "#10b981", 3),
                ("Women in Tech / All-Women Squad", "₹10,000", "Diversity in Tech", "Dedicated prize celebrating exceptional engineering leadership from all-women participant squads, backed by 1-on-1 industry mentorship.", "sparkles", "#ec4899", 4),
                ("Best Social Impact & Civic Tech", "₹10,000", "Special Award", "Given to the project with the highest potential to create positive civic, environmental, or healthcare impact in rural or urban India.", "bulb", "#f59e0b", 5)
            ]
            c.executemany("INSERT INTO prize_categories(title, amount, tag, description, icon, color_accent, order_idx) VALUES(?, ?, ?, ?, ?, ?, ?)", categories)

            # 4. prize_perks
            perks = [
                ("Official ACM & MITS Certificates", "Nationally recognized verified Certificate of Participation for every attendee who builds and presents their solution.", "doc", 1),
                ("Free Cloud Credits & Developer Perks", "Free cloud computing credits, API keys, and premium developer tools from hackathon partners and sponsors.", "globe", 2),
                ("36-Hour Round-the-Clock Meals & Snacks", "Hot buffet breakfast, lunch, dinner, high tea, midnight pizza, energy drinks, and continuous tea/coffee bar.", "trophy", 3),
                ("Exclusive Swag & Merchandise", "CodeNite 2027 limited-edition T-shirts, premium laptop vinyl stickers, ID badges, and custom event lanyards.", "bolt", 4),
                ("Live Industry Mentorship & Networking", "Direct guidance on the floor from senior architects, startup founders, and engineers throughout the 36-hour sprint.", "users", 5),
                ("Internship & Recruitment Exposure", "Direct talent consideration and resume circulation to hiring managers and recruiters from partner companies.", "check", 6)
            ]
            c.executemany("INSERT INTO prize_perks(title, description, icon, order_idx) VALUES(?, ?, ?, ?)", perks)

            # 5. prize_rules
            rules = [
                ("All prize amounts are distributed on a per-team basis and will be disbursed directly to the designated Team Leader via bank wire / UPI within 7–10 working days after the closing ceremony.", 1),
                ("Taxes and statutory deductions (if applicable under Indian law) will be deducted at source (TDS) as per government guidelines.", 2),
                ("Teams must present a functioning live prototype during the Grand Jury evaluation round to be eligible for any podium or category prize.", 3),
                ("Special category prizes (e.g. Best All-First-Year Team) are stackable with podium awards if a team wins both on merit.", 4),
                ("All members of winning teams must be verified students with valid college ID cards presented during physical check-in.", 5)
            ]
            c.executemany("INSERT INTO prize_rules(rule_text, order_idx) VALUES(?, ?)", rules)

            conn.commit()
            print("Successfully initialized and seeded prize data!")
        else:
            print("Prize data already exists.")

if __name__ == "__main__":
    init_prize_tables(os.path.join("instance", "hackathon.db"))
