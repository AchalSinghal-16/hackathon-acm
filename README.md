# ACM CodeNite 2027 - Flask site

    pip install -r requirements.txt
    python app.py          # http://127.0.0.1:5000

## Edit the content
All visible text (headings, badge, features, events, prizes, FAQ) is in `content.py`.

## Edit the styling
Edit `static/css/style.src.css` and `static/css/responsive.src.css`, then run:

    cd static && python build.py

This regenerates `style.css` and `responsive.css` (it converts px to rem so the layouts scale with the screen).

## Layouts
- Laptop/desktop (>=1100px): fills the window, no scrolling. Background `images/background.jpg` + `background-wide.jpg`.
- Tablet (700-1099px): single column.
- Phone (<=699px): scaled phone design. Background `images/background-m.jpg`, character `images/character-m.png`.

## Settings (environment variables)
- `SECRET_KEY` - set this in production.
- `ALLOWED_EMAIL_DOMAIN` - optional, e.g. `yourcollege.edu`.
- Google login: create OAuth credentials, add redirect URI `http://127.0.0.1:5000/auth/google/callback`, then set `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`.
