# -*- coding: utf-8 -*-
"""
CampusBridge — платформа студентських челенджів та хакатонів
Один файл, Python + Streamlit + SQLite.

Запуск:
    pip install streamlit pandas openpyxl
    streamlit run campusbridge.py

Дефолтний адмін: логін "admin", пароль "admin123"
"""

import streamlit as st
import sqlite3
import pandas as pd
import hashlib
import datetime
from datetime import timedelta
import io
import random
import string
import statistics
import uuid
import os

try:
    from streamlit_calendar import calendar as st_calendar
    CALENDAR_AVAILABLE = True
except ImportError:
    CALENDAR_AVAILABLE = False

try:
    import reportlab  # noqa: F401
    PDF_LIB_AVAILABLE = True
except ImportError:
    PDF_LIB_AVAILABLE = False

# ============================================================
# КОНСТАНТИ
# ============================================================

DB_PATH = "campusbridge.db"

MAIN_UNIVERSITY = "Вінницький державний педагогічний університет ім. М. Коцюбинського"
MAIN_FACULTY = "Факультет математики, фізики і комп'ютерних наук"

ALLOWED_EMAIL_DOMAINS = [
    "@vspu.edu.ua", "@vspu.net", "@kpi.ua", "@lnu.edu.ua", "@knu.ua",
]

CATEGORIES = ["IT", "Наука", "Спорт", "Волонтерство", "Бізнес/Кейси"]
FORMATS = ["Онлайн", "Офлайн", "Гібридний"]
EVENT_STATUSES = ["Чернетка", "Реєстрація відкрита", "Триває подія", "Архів"]
TEAM_STATUSES = ["На розгляді", "Прийнято", "Потребує доопрацювання", "Відхилено"]
MAX_PDF_MB = 50

st.set_page_config(page_title="CampusBridge", page_icon="🎓", layout="wide")

# ============================================================
# ШАР ДОСТУПУ ДО БАЗИ ДАНИХ
# ============================================================

def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def execute(sql, params=()):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(sql, params)
    conn.commit()
    last_id = cur.lastrowid
    conn.close()
    return last_id


def query_df(sql, params=()):
    conn = get_conn()
    df = pd.read_sql_query(sql, conn, params=params)
    conn.close()
    return df


def query_one(sql, params=()):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(sql, params)
    row = cur.fetchone()
    conn.close()
    return row


def hash_pw(pw):
    return hashlib.sha256(pw.encode("utf-8")).hexdigest()


def gen_code(n=6):
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=n))


def now():
    return str(datetime.datetime.now())


def init_db():
    conn = get_conn()
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE,
        password TEXT,
        role TEXT,
        full_name TEXT,
        email TEXT,
        university TEXT,
        faculty TEXT,
        created_at TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT, category TEXT, format TEXT,
        description TEXT, regulations TEXT,
        reg_start TEXT, reg_end TEXT, event_start TEXT, pitch_deadline TEXT,
        min_team INTEGER, max_team INTEGER, prize_fund TEXT,
        status TEXT, leaderboard_live INTEGER DEFAULT 0,
        avoid_conflict INTEGER DEFAULT 1,
        university TEXT, faculty TEXT,
        created_by INTEGER, created_at TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS nominations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_id INTEGER, name TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS criteria (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_id INTEGER, name TEXT, weight REAL, max_score REAL
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS teams (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_id INTEGER, nomination_id INTEGER,
        name TEXT, captain_id INTEGER, invite_code TEXT,
        faculty TEXT, status TEXT, status_comment TEXT,
        created_at TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS team_members (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        team_id INTEGER, user_id INTEGER
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS submissions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        team_id INTEGER, repo_link TEXT, presentation_link TEXT, video_link TEXT,
        description TEXT, version INTEGER, updated_at TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS files (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        submission_id INTEGER, filename TEXT, mimetype TEXT,
        data BLOB, uploaded_at TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS jury_assignments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_id INTEGER, jury_id INTEGER, nomination_id INTEGER
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS scores (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        team_id INTEGER, jury_id INTEGER, criterion_id INTEGER,
        score REAL, feedback TEXT, created_at TEXT,
        UNIQUE(team_id, jury_id, criterion_id)
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS announcements (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_id INTEGER, title TEXT, body TEXT,
        target_team_id INTEGER, created_at TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS mentor_slots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        mentor_id INTEGER, event_id INTEGER,
        slot_date TEXT, start_time TEXT, end_time TEXT,
        location TEXT, is_booked INTEGER DEFAULT 0,
        team_id INTEGER, notes TEXT, created_at TEXT
    )""")
    conn.commit()

    # м'які міграції: додаємо нові колонки, якщо їх ще немає
    c.execute("PRAGMA table_info(events)")
    existing_cols = [row[1] for row in c.fetchall()]
    if "double_blind" not in existing_cols:
        c.execute("ALTER TABLE events ADD COLUMN double_blind INTEGER DEFAULT 0")
    if "banner_url" not in existing_cols:
        c.execute("ALTER TABLE events ADD COLUMN banner_url TEXT")
    if "video_url" not in existing_cols:
        c.execute("ALTER TABLE events ADD COLUMN video_url TEXT")
    conn.commit()

    c.execute("SELECT COUNT(*) FROM users WHERE role='admin'")
    if c.fetchone()[0] == 0:
        c.execute("""INSERT INTO users
            (username,password,role,full_name,email,university,faculty,created_at)
            VALUES (?,?,?,?,?,?,?,?)""",
            ("admin", hash_pw("admin123"), "admin", "Адміністратор системи",
             "admin@vspu.edu.ua", MAIN_UNIVERSITY, MAIN_FACULTY, now()))
        conn.commit()

    # демо-акаунти для тестування ролей журі, ментора та учасника
    demo_accounts = [
        ("jury_demo", "jury123", "jury", "Ірина Оцінювачева (демо-журі)",
         "jury_demo@vspu.edu.ua", MAIN_FACULTY),
        ("mentor_demo", "mentor123", "mentor", "Олег Ментор (демо-ментор)",
         "mentor_demo@vspu.edu.ua", "IT-індустрія / ФМФКН"),
        ("participant_demo", "part123", "participant", "Марія Учасниця (демо-учасник)",
         "participant_demo@vspu.edu.ua", MAIN_FACULTY),
    ]
    for username, pw, role, full_name, email, faculty in demo_accounts:
        c.execute("SELECT id FROM users WHERE username=?", (username,))
        if c.fetchone() is None:
            c.execute("""INSERT INTO users (username,password,role,full_name,email,university,faculty,created_at)
                         VALUES (?,?,?,?,?,?,?,?)""",
                      (username, hash_pw(pw), role, full_name, email, MAIN_UNIVERSITY, faculty, now()))
    conn.commit()

    # демо-подія, щоб календар і лідерборд не виглядали порожніми "з коробки"
    c.execute("SELECT COUNT(*) FROM events")
    if c.fetchone()[0] == 0:
        c.execute("SELECT id FROM users WHERE username='admin'")
        admin_id = c.fetchone()[0]
        c.execute("""INSERT INTO events (title,category,format,description,regulations,reg_start,reg_end,
            event_start,pitch_deadline,min_team,max_team,prize_fund,status,leaderboard_live,avoid_conflict,
            university,faculty,created_by,created_at,double_blind,banner_url,video_url)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            ("CampusBridge Demo Hack 2026", "IT", "Гібридний",
             "Демонстраційний хакатон для тестування платформи CampusBridge: подача проєктів, "
             "оцінювання журі, office hours з менторами та лідерборд у реальному часі.",
             "Регламент: команди 2-5 осіб, дедлайн подачі — 20.09.2026, фінальний пітчинг — 25.09.2026.",
             "2026-09-01", "2026-09-20", "2026-09-22", "2026-09-25",
             2, 5, "50 000 грн", "Реєстрація відкрита", 1, 1,
             MAIN_UNIVERSITY, MAIN_FACULTY, admin_id, now(), 0,
             "https://images.unsplash.com/photo-1504384308090-c894fdcc538d?w=800",
             "https://www.youtube.com/watch?v=dQw4w9WgXcQ"))
        demo_event_id = c.lastrowid
        c.execute("INSERT INTO nominations (event_id, name) VALUES (?,?)", (demo_event_id, "AI / Machine Learning"))
        nom1_id = c.lastrowid
        c.execute("INSERT INTO nominations (event_id, name) VALUES (?,?)", (demo_event_id, "Web / Mobile розробка"))
        crit_ids = []
        for crit_name, weight, max_score in [("Інноваційність", 30, 10), ("Технічна реалізація", 40, 10),
                                              ("Презентація", 30, 10)]:
            c.execute("INSERT INTO criteria (event_id,name,weight,max_score) VALUES (?,?,?,?)",
                      (demo_event_id, crit_name, weight, max_score))
            crit_ids.append(c.lastrowid)
        conn.commit()

        # демо-команда всередині демо-події — щоб лідерборд і деталізація балів
        # одразу мали приклад для перегляду, а не порожній екран
        c.execute("SELECT id FROM users WHERE username='participant_demo'")
        participant_demo_id = c.fetchone()[0]
        c.execute("SELECT id FROM users WHERE username='jury_demo'")
        jury_demo_id = c.fetchone()[0]

        c.execute("""INSERT INTO teams (event_id,nomination_id,name,captain_id,invite_code,faculty,status,
            status_comment,created_at) VALUES (?,?,?,?,?,?,?,?,?)""",
            (demo_event_id, nom1_id, "AI Вінничани", participant_demo_id, gen_code(), MAIN_FACULTY,
             "Прийнято", "", now()))
        demo_team_id = c.lastrowid
        c.execute("INSERT INTO team_members (team_id,user_id) VALUES (?,?)", (demo_team_id, participant_demo_id))
        c.execute("""INSERT INTO submissions (team_id,repo_link,presentation_link,video_link,description,
            version,updated_at) VALUES (?,?,?,?,?,?,?)""",
            (demo_team_id, "https://github.com/campusbridge/demo-ai-assistant", "",
             "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
             "Демонстраційний проєкт: інтелектуальний асистент, що підбирає студентам хакатони "
             "та челенджі за їхніми навичками й інтересами.", 1, now()))
        for cid in crit_ids:
            c.execute("""INSERT INTO scores (team_id,jury_id,criterion_id,score,feedback,created_at)
                VALUES (?,?,?,?,?,?)""",
                (demo_team_id, jury_demo_id, cid, 8.0,
                 "Сильна ідея та якісна технічна реалізація, продовжуйте розвивати проєкт!", now()))

        # архівна подія минулого року — щоб публічне портфоліо (Showcase) теж не було порожнім
        c.execute("""INSERT INTO events (title,category,format,description,regulations,reg_start,reg_end,
            event_start,pitch_deadline,min_team,max_team,prize_fund,status,leaderboard_live,avoid_conflict,
            university,faculty,created_by,created_at,double_blind,banner_url,video_url)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            ("CampusBridge Hack 2025", "IT", "Офлайн",
             "Архівна подія минулого року — приклад завершеного хакатону з опублікованим портфоліо проєктів.",
             "", "2025-09-01", "2025-09-15", "2025-09-20", "2025-09-21", 2, 5, "30 000 грн",
             "Архів", 1, 1, MAIN_UNIVERSITY, MAIN_FACULTY, admin_id, now(), 0,
             "https://images.unsplash.com/photo-1517245386807-bb43f82c33c4?w=800", ""))
        archive_event_id = c.lastrowid
        archive_crit_ids = []
        for crit_name, weight, max_score in [("Інноваційність", 30, 10), ("Технічна реалізація", 40, 10),
                                              ("Презентація", 30, 10)]:
            c.execute("INSERT INTO criteria (event_id,name,weight,max_score) VALUES (?,?,?,?)",
                      (archive_event_id, crit_name, weight, max_score))
            archive_crit_ids.append(c.lastrowid)
        c.execute("""INSERT INTO teams (event_id,nomination_id,name,captain_id,invite_code,faculty,status,
            status_comment,created_at) VALUES (?,?,?,?,?,?,?,?,?)""",
            (archive_event_id, None, "Смарт Кампус", None, gen_code(), MAIN_FACULTY, "Прийнято", "", now()))
        archive_team_id = c.lastrowid
        c.execute("""INSERT INTO submissions (team_id,repo_link,presentation_link,video_link,description,
            version,updated_at) VALUES (?,?,?,?,?,?,?)""",
            (archive_team_id, "https://github.com/campusbridge/smart-campus", "", "",
             "Переможець хакатону 2025 року: система розумного кампусу з керуванням аудиторіями "
             "та розкладом у реальному часі.", 1, now()))
        for cid in archive_crit_ids:
            c.execute("""INSERT INTO scores (team_id,jury_id,criterion_id,score,feedback,created_at)
                VALUES (?,?,?,?,?,?)""", (archive_team_id, jury_demo_id, cid, 9.0, "Відмінна робота!", now()))

        conn.commit()

    conn.close()


init_db()

# ============================================================
# АВТЕНТИФІКАЦІЯ
# ============================================================

def authenticate(username, password):
    row = query_one("SELECT * FROM users WHERE username=? AND password=?",
                     (username, hash_pw(password)))
    if row:
        cols = ["id", "username", "password", "role", "full_name", "email",
                "university", "faculty", "created_at"]
        return dict(zip(cols, row))
    return None


def email_domain_ok(email):
    email = email.lower().strip()
    return any(email.endswith(d) for d in ALLOWED_EMAIL_DOMAINS)


def register_participant(username, password, full_name, email, faculty):
    if not email_domain_ok(email):
        return False, "Пошта не належить жодному із зареєстрованих закладів освіти. Реєстрація можлива лише за корпоративною поштою (наприклад, @vspu.edu.ua)."
    existing = query_one("SELECT id FROM users WHERE username=?", (username,))
    if existing:
        return False, "Такий логін вже зайнятий."
    execute("""INSERT INTO users (username,password,role,full_name,email,university,faculty,created_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (username, hash_pw(password), "participant", full_name, email,
             MAIN_UNIVERSITY, faculty, now()))
    return True, "Реєстрацію завершено! Студентський статус підтверджено автоматично за поштою. Тепер увійдіть у систему."


# ============================================================
# ДОПОМІЖНІ ФУНКЦІЇ БІЗНЕС-ЛОГІКИ
# ============================================================

def get_events(status_filter=None, category_filter=None, format_filter=None):
    sql = "SELECT * FROM events WHERE 1=1"
    params = []
    if status_filter and status_filter != "Усі":
        sql += " AND status=?"
        params.append(status_filter)
    if category_filter and category_filter != "Усі":
        sql += " AND category=?"
        params.append(category_filter)
    if format_filter and format_filter != "Усі":
        sql += " AND format=?"
        params.append(format_filter)
    sql += " ORDER BY event_start"
    return query_df(sql, params)


def compute_team_score(team_id):
    """Зважений бал команди на основі критеріїв та середніх оцінок журі."""
    scores_df = query_df("""SELECT s.criterion_id, s.score, c.weight, c.max_score
                             FROM scores s JOIN criteria c ON s.criterion_id=c.id
                             WHERE s.team_id=?""", (team_id,))
    if scores_df.empty:
        return None
    grouped = scores_df.groupby("criterion_id").agg(
        avg_score=("score", "mean"), weight=("weight", "first"),
        max_score=("max_score", "first"))
    grouped["norm"] = grouped["avg_score"] / grouped["max_score"] * 100
    total_weight = grouped["weight"].sum()
    if total_weight == 0:
        return None
    weighted = (grouped["norm"] * grouped["weight"]).sum() / total_weight
    return round(weighted, 2)


def detect_anomalies(event_id):
    """Знаходить оцінки журі, що суттєво відхиляються від середнього по команді/критерію."""
    df = query_df("""SELECT s.id, s.team_id, s.jury_id, s.criterion_id, s.score,
                             u.full_name AS jury_name, t.name AS team_name, c.name AS crit_name
                      FROM scores s
                      JOIN teams t ON s.team_id=t.id
                      JOIN users u ON s.jury_id=u.id
                      JOIN criteria c ON s.criterion_id=c.id
                      WHERE t.event_id=?""", (event_id,))
    anomalies = []
    if df.empty:
        return pd.DataFrame(anomalies)
    for (team_id, crit_id), sub in df.groupby(["team_id", "criterion_id"]):
        if len(sub) < 2:
            continue
        vals = sub["score"].tolist()
        mean = statistics.mean(vals)
        std = statistics.pstdev(vals)
        if std == 0:
            continue
        for _, row in sub.iterrows():
            if abs(row["score"] - mean) > 1.5 * std:
                anomalies.append({
                    "Команда": row["team_name"], "Критерій": row["crit_name"],
                    "Журі": row["jury_name"], "Оцінка": row["score"],
                    "Середнє": round(mean, 2), "Відхилення": round(row["score"] - mean, 2)
                })
    return pd.DataFrame(anomalies)


def parse_date_flexible(text):
    """Намагається розпізнати дату/час у кількох поширених форматах."""
    if not text or not isinstance(text, str) or not text.strip():
        return None
    text = text.strip()
    formats = ["%Y-%m-%d %H:%M", "%Y-%m-%d", "%d.%m.%Y %H:%M", "%d.%m.%Y",
               "%Y-%m-%dT%H:%M", "%d/%m/%Y %H:%M", "%d/%m/%Y"]
    for fmt in formats:
        try:
            return datetime.datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def parse_prize_fund(text):
    """Витягує число із рядка призового фонду для сортування (наприклад, '50 000 грн' -> 50000)."""
    if not text:
        return None
    digits = "".join(ch for ch in str(text) if ch.isdigit())
    return int(digits) if digits else None


def _escape_ics(text):
    if not text:
        return ""
    return (str(text).replace("\\", "\\\\").replace(";", "\\;")
            .replace(",", "\\,").replace("\n", "\\n"))


def build_ics_for_event(ev):
    """Формує вміст .ics файлу з усіма ключовими дедлайнами події."""
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//CampusBridge//UA//"]
    stamp = datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")

    milestones = [
        ("Старт реєстрації", ev.get("reg_start")),
        ("Дедлайн подачі заявок", ev.get("reg_end")),
        ("Старт хакатону/події", ev.get("event_start")),
        ("Дедлайн пітчингу", ev.get("pitch_deadline")),
    ]
    added_any = False
    for label, date_str in milestones:
        dt = parse_date_flexible(date_str)
        if not dt:
            continue
        added_any = True
        has_time = ":" in (date_str or "") and dt.hour + dt.minute > 0
        summary = f"{label}: {ev.get('title', '')}"
        description = ev.get("description") or ""
        if has_time:
            dtstart = dt.strftime("%Y%m%dT%H%M%S")
            dtend = (dt + timedelta(hours=1)).strftime("%Y%m%dT%H%M%S")
            lines += [
                "BEGIN:VEVENT",
                f"UID:{uuid.uuid4()}@campusbridge",
                f"DTSTAMP:{stamp}",
                f"DTSTART:{dtstart}",
                f"DTEND:{dtend}",
                f"SUMMARY:{_escape_ics(summary)}",
                f"DESCRIPTION:{_escape_ics(description)}",
                "END:VEVENT",
            ]
        else:
            dtstart = dt.strftime("%Y%m%d")
            dtend = (dt + timedelta(days=1)).strftime("%Y%m%d")
            lines += [
                "BEGIN:VEVENT",
                f"UID:{uuid.uuid4()}@campusbridge",
                f"DTSTAMP:{stamp}",
                f"DTSTART;VALUE=DATE:{dtstart}",
                f"DTEND;VALUE=DATE:{dtend}",
                f"SUMMARY:{_escape_ics(summary)}",
                f"DESCRIPTION:{_escape_ics(description)}",
                "END:VEVENT",
            ]
    lines.append("END:VCALENDAR")
    if not added_any:
        return None
    return "\r\n".join(lines)


def youtube_embed_url(url):
    """Приймає посилання на YouTube у різних форматах і повертає його як є (st.video сам розпізнає)."""
    return url.strip() if url else None


UA_TRANSLIT = {
    'а': 'a', 'б': 'b', 'в': 'v', 'г': 'h', 'ґ': 'g', 'д': 'd', 'е': 'e', 'є': 'ye',
    'ж': 'zh', 'з': 'z', 'и': 'y', 'і': 'i', 'ї': 'yi', 'й': 'y', 'к': 'k', 'л': 'l',
    'м': 'm', 'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u',
    'ф': 'f', 'х': 'kh', 'ц': 'ts', 'ч': 'ch', 'ш': 'sh', 'щ': 'shch', 'ь': '',
    'ю': 'yu', 'я': 'ya', "'": '',
    'А': 'A', 'Б': 'B', 'В': 'V', 'Г': 'H', 'Ґ': 'G', 'Д': 'D', 'Е': 'E', 'Є': 'Ye',
    'Ж': 'Zh', 'З': 'Z', 'И': 'Y', 'І': 'I', 'Ї': 'Yi', 'Й': 'Y', 'К': 'K', 'Л': 'L',
    'М': 'M', 'Н': 'N', 'О': 'O', 'П': 'P', 'Р': 'R', 'С': 'S', 'Т': 'T', 'У': 'U',
    'Ф': 'F', 'Х': 'Kh', 'Ц': 'Ts', 'Ч': 'Ch', 'Ш': 'Sh', 'Щ': 'Shch', 'Ь': '',
    'Ю': 'Yu', 'Я': 'Ya',
}


def transliterate_ua(text):
    """Резервна транслітерація кирилиці латиницею для PDF, якщо на сервері немає шрифту з кирилицею."""
    if not text:
        return ""
    return "".join(UA_TRANSLIT.get(ch, ch) for ch in str(text))


_PDF_CYRILLIC_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
]
_PDF_CYRILLIC_BOLD_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
]


def _register_pdf_fonts():
    """Реєструє TTF-шрифт з підтримкою кирилиці для reportlab, якщо він є на сервері."""
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    regular_path = next((p for p in _PDF_CYRILLIC_FONT_CANDIDATES if os.path.exists(p)), None)
    if not regular_path:
        return None, None
    bold_path = next((p for p in _PDF_CYRILLIC_BOLD_CANDIDATES if os.path.exists(p)), regular_path)
    try:
        pdfmetrics.registerFont(TTFont("CBSans", regular_path))
        pdfmetrics.registerFont(TTFont("CBSans-Bold", bold_path))
        return "CBSans", "CBSans-Bold"
    except Exception:
        return None, None


def generate_jury_protocol_pdf(event_id):
    """Формує офіційний протокол засідання журі у форматі PDF."""
    if not PDF_LIB_AVAILABLE:
        return None
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.units import cm
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_CENTER

    ev = query_one("SELECT title, university, faculty, event_start FROM events WHERE id=?", (event_id,))
    if not ev:
        return None
    ev_title, university, faculty, event_start = ev

    teams = query_df("SELECT * FROM teams WHERE event_id=? AND status='Прийнято'", (event_id,))
    criteria = query_df("SELECT * FROM criteria WHERE event_id=?", (event_id,))
    jury_list = query_df("""SELECT DISTINCT u.full_name FROM jury_assignments ja
                             JOIN users u ON ja.jury_id = u.id WHERE ja.event_id=?""", (event_id,))
    if teams.empty or criteria.empty:
        return None

    font_regular, font_bold = _register_pdf_fonts()
    use_translit = font_regular is None
    font_regular = font_regular or "Helvetica"
    font_bold = font_bold or "Helvetica-Bold"

    def T(text):
        return transliterate_ua(text) if use_translit else (text or "")

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=1.5 * cm, bottomMargin=1.5 * cm,
                             leftMargin=1.5 * cm, rightMargin=1.5 * cm)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("CBTitle", parent=styles["Title"], fontName=font_bold,
                                  alignment=TA_CENTER, fontSize=15)
    normal_style = ParagraphStyle("CBNormal", parent=styles["Normal"], fontName=font_regular, fontSize=10,
                                   spaceAfter=4)
    small_style = ParagraphStyle("CBSmall", parent=styles["Normal"], fontName=font_regular, fontSize=9,
                                  spaceAfter=10)

    elements = [
        Paragraph(T(university), normal_style),
        Paragraph(T(faculty), normal_style),
        Spacer(1, 10),
        Paragraph(T("ПРОТОКОЛ засідання журі"), title_style),
        Spacer(1, 6),
        Paragraph(T(f"Подія: {ev_title}"), normal_style),
        Paragraph(T(f"Дата проведення: {event_start or '—'}"), normal_style),
        Paragraph(T(f"Дата формування протоколу: {now()[:16]}"), normal_style),
        Spacer(1, 14),
    ]

    crit_names = criteria["name"].tolist()
    header = [T("№"), T("Команда"), T("Факультет")] + [T(cn) for cn in crit_names] + [T("Підсумковий бал")]
    scored_rows = []
    for _, t in teams.iterrows():
        row_scores = []
        for _, crit in criteria.iterrows():
            avg_row = query_one("SELECT AVG(score) FROM scores WHERE team_id=? AND criterion_id=?",
                                 (t["id"], crit["id"]))
            avg = avg_row[0] if avg_row else None
            row_scores.append(round(avg, 1) if avg is not None else None)
        total = compute_team_score(t["id"])
        scored_rows.append((t, row_scores, total))
    scored_rows.sort(key=lambda x: x[2] if x[2] is not None else -1, reverse=True)

    table_data = [header]
    for i, (t, row_scores, total) in enumerate(scored_rows, start=1):
        table_data.append(
            [str(i), T(t["name"]), T(t["faculty"])] +
            [(str(v) if v is not None else "—") for v in row_scores] +
            [str(total) if total is not None else "—"]
        )

    tbl = Table(table_data, repeatRows=1)
    tbl.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), font_regular),
        ("FONTNAME", (0, 0), (-1, 0), font_bold),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#4F8BF9")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F5F7FA")]),
    ]))
    elements.append(tbl)
    elements.append(Spacer(1, 24))

    if not jury_list.empty:
        elements.append(Paragraph(T("Склад журі:"), normal_style))
        elements.append(Spacer(1, 4))
        for jname in jury_list["full_name"]:
            elements.append(Paragraph(T(f"________________________________   {jname}   (підпис)"), small_style))
        elements.append(Spacer(1, 10))

    elements.append(Paragraph(T("Голова журі: ____________________________   (ПІБ, підпис)"), normal_style))
    elements.append(Spacer(1, 20))
    elements.append(Paragraph(T("М.П."), normal_style))

    doc.build(elements)
    return buf.getvalue()


def anon_code(team_id):
    """Детермінований анонімний код команди для сліпого оцінювання."""
    h = hashlib.md5(f"team-anon-{team_id}".encode("utf-8")).hexdigest()[:5].upper()
    return f"Команда №{h}"


def has_conflict(event_id, team_id, jury_user):
    ev = query_one("SELECT avoid_conflict FROM events WHERE id=?", (event_id,))
    if not ev or not ev[0]:
        return False
    team = query_one("SELECT faculty FROM teams WHERE id=?", (team_id,))
    if not team:
        return False
    return team[0] == jury_user.get("faculty")


# ============================================================
# СТАН СЕСІЇ
# ============================================================

if "user" not in st.session_state:
    st.session_state.user = None
if "page" not in st.session_state:
    st.session_state.page = "public"


def logout():
    st.session_state.user = None
    st.rerun()


# ============================================================
# ПУБЛІЧНІ СТОРІНКИ (без входу)
# ============================================================

def page_calendar():
    st.subheader("📅 Календар подій")

    f1, f2, f3 = st.columns(3)
    with f1:
        status_f = st.selectbox("Статус", ["Усі"] + EVENT_STATUSES)
    with f2:
        cat_f = st.selectbox("Категорія", ["Усі"] + CATEGORIES)
    with f3:
        format_f = st.selectbox("Формат", ["Усі"] + FORMATS)

    f4, f5 = st.columns([2, 1])
    with f4:
        search_q = st.text_input("🔎 Пошук за назвою або ключовими словами в описі")
    with f5:
        sort_by = st.selectbox("Сортувати", ["За датою старту (найближчі)", "За призовим фондом (спадання)"])

    events = get_events(status_f, cat_f, format_f)

    if search_q.strip():
        q = search_q.strip().lower()
        mask = events["title"].fillna("").str.lower().str.contains(q) | \
               events["description"].fillna("").str.lower().str.contains(q) | \
               events["regulations"].fillna("").str.lower().str.contains(q)
        events = events[mask]

    if events.empty:
        st.info("Подій за обраними фільтрами не знайдено.")
        return

    events = events.copy()
    if sort_by == "За датою старту (найближчі)":
        events["_sort_dt"] = events["event_start"].apply(lambda x: parse_date_flexible(x) or datetime.datetime.max)
        events = events.sort_values("_sort_dt")
    else:
        events["_sort_prize"] = events["prize_fund"].apply(lambda x: parse_prize_fund(x) or -1)
        events = events.sort_values("_sort_prize", ascending=False)

    tab_list, tab_calendar = st.tabs(["📋 Список подій", "🗓️ Календарна сітка"])

    with tab_list:
        for _, ev in events.iterrows():
            with st.container(border=True):
                if ev.get("banner_url"):
                    st.image(ev["banner_url"], use_container_width=True)

                c1, c2 = st.columns([3, 1])
                with c1:
                    st.markdown(f"### {ev['title']}")
                    st.caption(f"{ev['category']} · {ev['format']} · {ev['status']}")
                    st.write(ev["description"] or "")
                    st.write(f"🗓️ Реєстрація: {ev['reg_start']} → {ev['reg_end']} | Старт: {ev['event_start']}")
                with c2:
                    if ev["prize_fund"]:
                        st.metric("Призовий фонд", ev["prize_fund"])
                    teams_count = query_one("SELECT COUNT(*) FROM teams WHERE event_id=?", (ev["id"],))[0]
                    st.metric("Команд подано", teams_count)

                if ev.get("video_url"):
                    with st.expander("🎬 Промо-відео"):
                        st.video(youtube_embed_url(ev["video_url"]))

                ics_content = build_ics_for_event(ev)
                if ics_content:
                    st.download_button(
                        "📆 Додати дедлайни в календар (.ics)",
                        data=ics_content,
                        file_name=f"{ev['title'][:40].replace(' ', '_')}.ics",
                        mime="text/calendar",
                        key=f"ics_{ev['id']}",
                    )
                else:
                    st.caption("Дати події ще не вказані у форматі, придатному для експорту в календар.")

                with st.expander("Регламент і деталі"):
                    st.write(ev["regulations"] or "Регламент не завантажено.")
                    noms = query_df("SELECT name FROM nominations WHERE event_id=?", (ev["id"],))
                    if not noms.empty:
                        st.write("**Номінації:** " + ", ".join(noms["name"].tolist()))

    with tab_calendar:
        if not CALENDAR_AVAILABLE:
            st.warning("Для інтерактивного календаря встановіть пакет: `pip install streamlit-calendar`")
        else:
            category_colors = {
                "IT": "#4F8BF9", "Наука": "#8E44AD", "Спорт": "#27AE60",
                "Волонтерство": "#E67E22", "Бізнес/Кейси": "#E74C3C",
            }
            cal_events = []
            for _, ev in events.iterrows():
                start_dt = parse_date_flexible(ev["event_start"]) or parse_date_flexible(ev["reg_start"])
                if not start_dt:
                    continue
                cal_events.append({
                    "title": ev["title"],
                    "start": start_dt.strftime("%Y-%m-%d"),
                    "end": start_dt.strftime("%Y-%m-%d"),
                    "color": category_colors.get(ev["category"], "#4F8BF9"),
                })
                reg_start_dt = parse_date_flexible(ev["reg_start"])
                if reg_start_dt:
                    cal_events.append({
                        "title": f"🟢 Старт реєстрації: {ev['title']}",
                        "start": reg_start_dt.strftime("%Y-%m-%d"),
                        "end": reg_start_dt.strftime("%Y-%m-%d"),
                        "color": "#95A5A6",
                    })
                pitch_dt = parse_date_flexible(ev["pitch_deadline"])
                if pitch_dt:
                    cal_events.append({
                        "title": f"🏁 Пітчинг: {ev['title']}",
                        "start": pitch_dt.strftime("%Y-%m-%d"),
                        "end": pitch_dt.strftime("%Y-%m-%d"),
                        "color": "#F1C40F",
                    })

            if not cal_events:
                st.info("Немає подій із розпізнаваними датами (очікуваний формат: ГГГГ-ММ-ДД).")
            else:
                cal_options = {
                    "initialView": "dayGridMonth",
                    "headerToolbar": {
                        "left": "prev,next today",
                        "center": "title",
                        "right": "dayGridMonth,timeGridWeek,listMonth",
                    },
                    "locale": "uk",
                    "height": 650,
                }
                st_calendar(events=cal_events, options=cal_options, key="campusbridge_calendar")


def get_score_breakdown(team_id):
    """Деталізація оцінок команди: кожен критерій і кожен голос журі окремо."""
    return query_df("""SELECT c.name AS criterion, c.weight, c.max_score,
                               u.full_name AS jury, s.score, s.feedback
                        FROM scores s
                        JOIN criteria c ON s.criterion_id = c.id
                        JOIN users u ON s.jury_id = u.id
                        WHERE s.team_id = ?
                        ORDER BY c.id, u.full_name""", (team_id,))


def render_score_breakdown(team_id):
    df = get_score_breakdown(team_id)
    if df.empty:
        st.info("Оцінок ще немає.")
        return
    st.markdown("**Середній бал за критеріями (з урахуванням ваги):**")
    summary = df.groupby(["criterion", "weight", "max_score"], as_index=False)["score"].mean()
    summary["Внесок у підсумок, %"] = (summary["score"] / summary["max_score"] * summary["weight"]).round(1)
    summary = summary.rename(columns={"criterion": "Критерій", "weight": "Вага, %",
                                       "max_score": "Максимум", "score": "Середня оцінка"})
    summary["Середня оцінка"] = summary["Середня оцінка"].round(2)
    st.dataframe(summary[["Критерій", "Вага, %", "Максимум", "Середня оцінка", "Внесок у підсумок, %"]],
                 use_container_width=True, hide_index=True)

    st.markdown("**Оцінки кожного члена журі (з фідбеком):**")
    detail = df.rename(columns={"criterion": "Критерій", "jury": "Журі", "score": "Оцінка",
                                 "max_score": "Максимум", "feedback": "Фідбек"})
    st.dataframe(detail[["Критерій", "Журі", "Оцінка", "Максимум", "Фідбек"]],
                 use_container_width=True, hide_index=True)


def page_leaderboard():
    st.subheader("🏆 Публічна таблиця результатів")
    events = get_events()
    if events.empty:
        st.info("Подій ще немає.")
        return
    ev_map = dict(zip(events["title"], events["id"]))
    ev_title = st.selectbox("Оберіть подію", list(ev_map.keys()))
    ev_id = ev_map[ev_title]
    ev_row = query_one("SELECT leaderboard_live FROM events WHERE id=?", (ev_id,))
    if not ev_row or not ev_row[0]:
        st.warning("Лідерборд для цієї події ще не опубліковано адміністратором.")
        return
    teams = query_df("SELECT * FROM teams WHERE event_id=? AND status='Прийнято'", (ev_id,))
    if teams.empty:
        st.info("Прийнятих команд поки немає.")
        return

    ranked = []
    for _, t in teams.iterrows():
        score = compute_team_score(t["id"])
        ranked.append((t, score if score is not None else -1, score))
    ranked.sort(key=lambda x: x[1], reverse=True)

    board_rows = []
    medals = ["🥇", "🥈", "🥉"]
    for i, (t, sort_score, score) in enumerate(ranked):
        place = medals[i] if i < 3 and score is not None else str(i + 1)
        board_rows.append({"Місце": place, "Команда": t["name"], "Факультет": t["faculty"],
                            "Бал": score if score is not None else "—"})
    st.dataframe(pd.DataFrame(board_rows), use_container_width=True, hide_index=True)

    user = st.session_state.user
    if user and user["role"] in ("admin", "jury"):
        st.markdown("#### 📄 Офіційний протокол журі")
        if not PDF_LIB_AVAILABLE:
            st.caption("Для експорту в PDF на сервері потрібен пакет `reportlab` (додайте його в requirements.txt).")
        else:
            pdf_bytes = generate_jury_protocol_pdf(ev_id)
            if pdf_bytes:
                st.download_button(
                    "📄 Завантажити офіційний протокол журі (PDF)",
                    data=pdf_bytes,
                    file_name=f"protocol_{ev_id}.pdf",
                    mime="application/pdf",
                )
            else:
                st.caption("Ще недостатньо даних для формування протоколу (немає критеріїв або команд).")

    st.markdown("#### Портфоліо та деталізація оцінок команд")
    for i, (t, sort_score, score) in enumerate(ranked):
        place_label = f"{medals[i]} " if i < 3 and score is not None else ""
        with st.expander(f"{place_label}{t['name']} ({t['faculty']}) — {score if score is not None else '—'} балів"):
            tab_portfolio, tab_breakdown = st.tabs(["📦 Портфоліо проєкту", "🔍 Деталізація балу"])
            with tab_portfolio:
                sub = query_one("""SELECT repo_link, presentation_link, video_link, description
                                    FROM submissions WHERE team_id=? ORDER BY version DESC LIMIT 1""", (t["id"],))
                if sub:
                    st.write(sub[3] or "")
                    if sub[0]:
                        st.write(f"🔗 Репозиторій: {sub[0]}")
                    if sub[2]:
                        st.video(youtube_embed_url(sub[2]))
                else:
                    st.write("Подача ще не завантажена.")
            with tab_breakdown:
                render_score_breakdown(t["id"])


# ============================================================
# ЛОГІН / РЕЄСТРАЦІЯ
# ============================================================

def page_showcase():
    st.subheader("🖼️ Портфоліо проєктів (Showcase)")
    st.caption("Галерея найкращих студентських проєктів: репозиторії, демо-відео та презентації "
               "з поточних і минулих подій.")

    only_archived = st.checkbox("Показувати лише завершені події (архів)", value=True)
    search_q = st.text_input("🔎 Пошук за назвою команди або описом проєкту")

    events = get_events("Архів") if only_archived else get_events()
    if events.empty:
        st.info("Завершених подій ще немає. Зніміть позначку вище, щоб побачити проєкти поточних подій.")
        return

    found_any = False
    for _, ev in events.iterrows():
        teams = query_df("SELECT * FROM teams WHERE event_id=? AND status='Прийнято'", (ev["id"],))
        if teams.empty:
            continue

        scored = []
        for _, t in teams.iterrows():
            sub = query_one("""SELECT repo_link, presentation_link, video_link, description
                                FROM submissions WHERE team_id=? ORDER BY version DESC LIMIT 1""", (t["id"],))
            if not sub:
                continue
            desc = sub[3] or ""
            if search_q.strip():
                q = search_q.strip().lower()
                if q not in t["name"].lower() and q not in desc.lower():
                    continue
            scored.append((t, sub, compute_team_score(t["id"])))
        if not scored:
            continue

        scored.sort(key=lambda x: x[2] if x[2] is not None else -1, reverse=True)
        found_any = True
        st.markdown(f"### {ev['title']}")
        st.caption(f"{ev['category']} · {ev['format']} · {ev['event_start'] or 'дата не вказана'}")

        cols = st.columns(2)
        for idx, (t, sub, score) in enumerate(scored):
            with cols[idx % 2]:
                with st.container(border=True):
                    badge = " 🏆" if idx == 0 and score is not None else ""
                    st.markdown(f"**{t['name']}**{badge}")
                    st.caption(f"{t['faculty']}" + (f" · ⭐ {score} балів" if score is not None else ""))
                    if sub[3]:
                        preview = sub[3][:220] + ("…" if len(sub[3]) > 220 else "")
                        st.write(preview)
                    if sub[2]:
                        st.video(youtube_embed_url(sub[2]))
                    if sub[0]:
                        st.write(f"🔗 [Репозиторій проєкту]({sub[0]})")
                    files = query_df("""SELECT f.id, f.filename FROM files f
                                         JOIN submissions s ON f.submission_id = s.id
                                         WHERE s.team_id=? ORDER BY f.uploaded_at DESC LIMIT 1""", (t["id"],))
                    if not files.empty:
                        file_id = int(files.iloc[0]["id"])
                        file_name = files.iloc[0]["filename"]
                        blob_row = query_one("SELECT data, mimetype FROM files WHERE id=?", (file_id,))
                        if blob_row:
                            st.download_button(f"📄 Завантажити презентацію ({file_name})",
                                                data=blob_row[0], file_name=file_name,
                                                mime=blob_row[1] or "application/pdf",
                                                key=f"showcase_file_{t['id']}")
        st.markdown("---")

    if not found_any:
        st.info("За обраними фільтрами проєктів не знайдено.")


def page_login():
    tab1, tab2 = st.tabs(["Вхід", "Реєстрація учасника"])
    with tab1:
        with st.form("login_form"):
            u = st.text_input("Логін")
            p = st.text_input("Пароль", type="password")
            submitted = st.form_submit_button("Увійти")
            if submitted:
                user = authenticate(u, p)
                if user:
                    st.session_state.user = user
                    st.success(f"Вітаємо, {user['full_name']}!")
                    st.rerun()
                else:
                    st.error("Невірний логін або пароль.")
        st.caption("Нові облікові записи журі та менторів створює адміністратор системи "
                   "(розділи «⚖️ Журі» та «🧑‍🏫 Ментори»).")
        with st.expander("🔑 Демо-облікові записи для тестування всіх ролей"):
            st.markdown(
                "| Роль | Логін | Пароль |\n"
                "|---|---|---|\n"
                "| Адміністратор | `admin` | `admin123` |\n"
                "| Журі | `jury_demo` | `jury123` |\n"
                "| Ментор | `mentor_demo` | `mentor123` |\n"
                "| Учасник | `participant_demo` | `part123` |"
            )

    with tab2:
        st.write(f"Реєстрація доступна для студентів **{MAIN_UNIVERSITY}**, {MAIN_FACULTY}, а також партнерських закладів.")
        with st.form("register_form"):
            full_name = st.text_input("Повне ім'я")
            username = st.text_input("Бажаний логін")
            email = st.text_input("Корпоративна пошта (наприклад, name@vspu.edu.ua)")
            faculty = st.text_input("Факультет / кафедра", value=MAIN_FACULTY)
            pw1 = st.text_input("Пароль", type="password")
            pw2 = st.text_input("Повторіть пароль", type="password")
            submitted2 = st.form_submit_button("Зареєструватися")
            if submitted2:
                if not full_name or not username or not email or not pw1:
                    st.error("Заповніть усі поля.")
                elif pw1 != pw2:
                    st.error("Паролі не збігаються.")
                else:
                    ok, msg = register_participant(username, pw1, full_name, email, faculty)
                    if ok:
                        st.success(msg)
                    else:
                        st.error(msg)


# ============================================================
# АДМІНІСТРАТОР
# ============================================================

def admin_event_builder():
    st.subheader("🛠️ Конструктор подій")
    events = get_events()
    options = ["➕ Створити нову подію"] + [
        f"{(row['title'] if row['title'] else '(без назви)')} (#{row['id']})"
        for _, row in events.iterrows()
    ]
    choice = st.selectbox("Подія", options)

    editing_id = None
    if choice != "➕ Створити нову подію":
        editing_id = int(choice.split("#")[-1].rstrip(")"))
        ev = query_one("SELECT * FROM events WHERE id=?", (editing_id,))
        cols = ["id","title","category","format","description","regulations","reg_start","reg_end",
                "event_start","pitch_deadline","min_team","max_team","prize_fund","status",
                "leaderboard_live","avoid_conflict","university","faculty","created_by","created_at",
                "double_blind","banner_url","video_url"]
        ev = dict(zip(cols, ev))
    else:
        ev = {c: "" for c in ["title","category","format","description","regulations",
                               "prize_fund","banner_url","video_url"]}
        ev.update({"status": "Чернетка", "min_team": 2, "max_team": 5,
                   "leaderboard_live": 0, "avoid_conflict": 1, "double_blind": 0,
                   "university": MAIN_UNIVERSITY, "faculty": MAIN_FACULTY})

    with st.form("event_form"):
        title = st.text_input("Назва події", value=ev.get("title", ""))
        c1, c2 = st.columns(2)
        with c1:
            category = st.selectbox("Тип/категорія", CATEGORIES,
                                     index=CATEGORIES.index(ev["category"]) if ev.get("category") in CATEGORIES else 0)
            fmt = st.selectbox("Формат", FORMATS,
                                index=FORMATS.index(ev["format"]) if ev.get("format") in FORMATS else 0)
            status = st.selectbox("Статус", EVENT_STATUSES,
                                   index=EVENT_STATUSES.index(ev["status"]) if ev.get("status") in EVENT_STATUSES else 0)
        with c2:
            min_team = st.number_input("Мін. учасників у команді", min_value=1, max_value=20, value=int(ev.get("min_team") or 2))
            max_team = st.number_input("Макс. учасників у команді", min_value=1, max_value=20, value=int(ev.get("max_team") or 5))
            prize = st.text_input("Призовий фонд", value=ev.get("prize_fund") or "")

        description = st.text_area("Опис (текстовий блок)", value=ev.get("description") or "")
        regulations = st.text_area("Положення / регламент (текстовий блок)", value=ev.get("regulations") or "")

        st.markdown("**Таймлайн етапів (дедлайни)**")
        d1, d2, d3, d4 = st.columns(4)
        with d1:
            reg_start = st.text_input("Старт реєстрації (ГГГГ-ММ-ДД)", value=ev.get("reg_start") or "")
        with d2:
            reg_end = st.text_input("Кінець подачі заявок", value=ev.get("reg_end") or "")
        with d3:
            event_start = st.text_input("Старт хакатону/події", value=ev.get("event_start") or "")
        with d4:
            pitch_deadline = st.text_input("Дедлайн пітчингу", value=ev.get("pitch_deadline") or "")

        c3, c4 = st.columns(2)
        with c3:
            leaderboard_live = st.checkbox("Транслювати лідерборд у реальному часі", value=bool(ev.get("leaderboard_live")))
        with c4:
            avoid_conflict = st.checkbox("Забороняти журі оцінювати команди свого факультету (конфлікт інтересів)",
                                          value=bool(ev.get("avoid_conflict", 1)))

        double_blind = st.checkbox(
            "🕶️ Сліпе оцінювання (double-blind): журі не бачить назву команди та факультет під час оцінювання",
            value=bool(ev.get("double_blind", 0)),
            help="Команди відображатимуться журі під анонімним кодом (наприклад, «Команда №A1B2»). "
                 "Захист від конфлікту інтересів за факультетом продовжує діяти автоматично, навіть якщо факультет прихований.")

        st.markdown("**Медіа**")
        m1, m2 = st.columns(2)
        with m1:
            banner_url = st.text_input("Посилання на банер (URL зображення)", value=ev.get("banner_url") or "")
        with m2:
            video_url = st.text_input("Посилання на промо-відео (YouTube)", value=ev.get("video_url") or "")

        submitted = st.form_submit_button("💾 Зберегти подію")
        if submitted:
            if not title:
                st.error("Вкажіть назву події.")
            else:
                if editing_id:
                    execute("""UPDATE events SET title=?, category=?, format=?, description=?, regulations=?,
                               reg_start=?, reg_end=?, event_start=?, pitch_deadline=?, min_team=?, max_team=?,
                               prize_fund=?, status=?, leaderboard_live=?, avoid_conflict=?, double_blind=?,
                               banner_url=?, video_url=? WHERE id=?""",
                            (title, category, fmt, description, regulations, reg_start, reg_end, event_start,
                             pitch_deadline, min_team, max_team, prize, status, int(leaderboard_live),
                             int(avoid_conflict), int(double_blind), banner_url, video_url, editing_id))
                    st.success("Подію оновлено.")
                else:
                    new_id = execute("""INSERT INTO events (title,category,format,description,regulations,
                                        reg_start,reg_end,event_start,pitch_deadline,min_team,max_team,prize_fund,
                                        status,leaderboard_live,avoid_conflict,university,faculty,created_by,created_at,
                                        double_blind,banner_url,video_url)
                                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                                     (title, category, fmt, description, regulations, reg_start, reg_end,
                                      event_start, pitch_deadline, min_team, max_team, prize, status,
                                      int(leaderboard_live), int(avoid_conflict), MAIN_UNIVERSITY, MAIN_FACULTY,
                                      st.session_state.user["id"], now(), int(double_blind), banner_url, video_url))
                    st.success(f"Подію створено (ID {new_id}).")
                st.rerun()

    if editing_id:
        st.markdown("---")
        st.markdown("#### Номінації")
        noms = query_df("SELECT * FROM nominations WHERE event_id=?", (editing_id,))
        st.dataframe(noms[["id", "name"]] if not noms.empty else noms, use_container_width=True, hide_index=True)
        with st.form("nom_form"):
            nom_name = st.text_input("Нова номінація (наприклад, AI-трек, Бізнес-трек)")
            if st.form_submit_button("Додати номінацію") and nom_name:
                execute("INSERT INTO nominations (event_id, name) VALUES (?,?)", (editing_id, nom_name))
                st.rerun()

        st.markdown("#### Критерії оцінювання")
        crit = query_df("SELECT * FROM criteria WHERE event_id=?", (editing_id,))
        st.dataframe(crit[["id", "name", "weight", "max_score"]] if not crit.empty else crit,
                     use_container_width=True, hide_index=True)
        with st.form("crit_form"):
            cc1, cc2, cc3 = st.columns(3)
            with cc1:
                cname = st.text_input("Назва критерію (наприклад, Інноваційність)")
            with cc2:
                cweight = st.number_input("Вага, %", min_value=1, max_value=100, value=25)
            with cc3:
                cmax = st.number_input("Макс. бал", min_value=1, max_value=100, value=10)
            if st.form_submit_button("Додати критерій") and cname:
                execute("INSERT INTO criteria (event_id,name,weight,max_score) VALUES (?,?,?,?)",
                        (editing_id, cname, cweight, cmax))
                st.rerun()


def admin_team_moderation():
    st.subheader("📥 Модерація заявок команд")
    events = get_events()
    if events.empty:
        st.info("Спочатку створіть подію.")
        return
    ev_map = dict(zip(events["title"], events["id"]))
    ev_title = st.selectbox("Подія", list(ev_map.keys()), key="mod_event")
    ev_id = ev_map[ev_title]

    teams = query_df("SELECT * FROM teams WHERE event_id=?", (ev_id,))
    if teams.empty:
        st.info("Заявок ще немає.")
        return

    status_filter = st.multiselect("Фільтр за статусом", TEAM_STATUSES, default=TEAM_STATUSES)
    teams = teams[teams["status"].isin(status_filter)]

    st.dataframe(teams[["id", "name", "faculty", "status", "status_comment"]],
                 use_container_width=True, hide_index=True)

    st.markdown("#### Масові дії")
    ids = st.multiselect("Оберіть ID команд", teams["id"].tolist())
    bulk_status = st.selectbox("Новий статус", TEAM_STATUSES, key="bulk_status")
    bulk_comment = st.text_input("Коментар (за потреби, наприклад причина доопрацювання)")
    if st.button("Застосувати до обраних") and ids:
        for tid in ids:
            execute("UPDATE teams SET status=?, status_comment=? WHERE id=?", (bulk_status, bulk_comment, tid))
        st.success(f"Оновлено {len(ids)} команд(и).")
        st.rerun()

    st.markdown("#### Індивідуальна зміна статусу")
    for _, t in teams.iterrows():
        with st.expander(f"#{t['id']} · {t['name']} — {t['status']}"):
            members = query_df("""SELECT u.full_name, u.email FROM team_members tm
                                   JOIN users u ON tm.user_id=u.id WHERE tm.team_id=?""", (t["id"],))
            st.write("**Учасники:**")
            st.dataframe(members, use_container_width=True, hide_index=True)
            new_status = st.selectbox("Статус", TEAM_STATUSES,
                                       index=TEAM_STATUSES.index(t["status"]) if t["status"] in TEAM_STATUSES else 0,
                                       key=f"st_{t['id']}")
            comment = st.text_input("Коментар для команди", value=t["status_comment"] or "", key=f"cm_{t['id']}")
            if st.button("Зберегти", key=f"save_{t['id']}"):
                execute("UPDATE teams SET status=?, status_comment=? WHERE id=?", (new_status, comment, t["id"]))
                st.success("Статус оновлено.")
                st.rerun()


def admin_jury():
    st.subheader("⚖️ Керування журі")
    st.markdown("#### Створити обліковий запис журі/експерта")
    with st.form("jury_create"):
        full_name = st.text_input("ПІБ експерта")
        username = st.text_input("Логін")
        email = st.text_input("Пошта")
        faculty = st.text_input("Факультет/кафедра (для перевірки конфлікту інтересів)")
        temp_pw = st.text_input("Тимчасовий пароль", value=gen_code(8))
        if st.form_submit_button("Створити") and full_name and username:
            existing = query_one("SELECT id FROM users WHERE username=?", (username,))
            if existing:
                st.error("Такий логін вже існує.")
            else:
                execute("""INSERT INTO users (username,password,role,full_name,email,university,faculty,created_at)
                           VALUES (?,?,?,?,?,?,?,?)""",
                        (username, hash_pw(temp_pw), "jury", full_name, email, MAIN_UNIVERSITY, faculty, now()))
                st.success(f"Журі створено. Логін: {username} / Пароль: {temp_pw}")

    st.markdown("#### Розподіл журі за номінаціями")
    events = get_events()
    if events.empty:
        return
    ev_map = dict(zip(events["title"], events["id"]))
    ev_title = st.selectbox("Подія", list(ev_map.keys()), key="jury_event")
    ev_id = ev_map[ev_title]

    jury_list = query_df("SELECT id, full_name, faculty FROM users WHERE role='jury'")
    noms = query_df("SELECT id, name FROM nominations WHERE event_id=?", (ev_id,))
    if jury_list.empty:
        st.info("Спершу створіть облікові записи журі.")
        return

    with st.form("assign_form"):
        jmap = dict(zip(jury_list["full_name"], jury_list["id"]))
        jname = st.selectbox("Журі", list(jmap.keys()))
        nmap = {"— вся подія —": None}
        nmap.update(dict(zip(noms["name"], noms["id"])))
        nname = st.selectbox("Номінація", list(nmap.keys()))
        if st.form_submit_button("Призначити"):
            execute("INSERT INTO jury_assignments (event_id,jury_id,nomination_id) VALUES (?,?,?)",
                    (ev_id, jmap[jname], nmap[nname]))
            st.success("Журі призначено.")

    st.markdown("#### Поточні призначення")
    assign_df = query_df("""SELECT ja.id, u.full_name AS jury, COALESCE(n.name,'вся подія') AS nomination
                             FROM jury_assignments ja
                             JOIN users u ON ja.jury_id=u.id
                             LEFT JOIN nominations n ON ja.nomination_id=n.id
                             WHERE ja.event_id=?""", (ev_id,))
    st.dataframe(assign_df, use_container_width=True, hide_index=True)


def admin_mentors():
    st.subheader("🧑‍🏫 Ментори (Office Hours)")
    st.markdown("#### Створити обліковий запис ментора")
    with st.form("mentor_create"):
        full_name = st.text_input("ПІБ ментора")
        username = st.text_input("Логін")
        email = st.text_input("Пошта")
        faculty = st.text_input("Факультет / компанія / спеціалізація")
        temp_pw = st.text_input("Тимчасовий пароль", value=gen_code(8))
        if st.form_submit_button("Створити") and full_name and username:
            existing = query_one("SELECT id FROM users WHERE username=?", (username,))
            if existing:
                st.error("Такий логін вже існує.")
            else:
                execute("""INSERT INTO users (username,password,role,full_name,email,university,faculty,created_at)
                           VALUES (?,?,?,?,?,?,?,?)""",
                        (username, hash_pw(temp_pw), "mentor", full_name, email, MAIN_UNIVERSITY, faculty, now()))
                st.success(f"Ментора створено. Логін: {username} / Пароль: {temp_pw}")

    st.markdown("#### Список менторів")
    mentors = query_df("SELECT id, full_name, email, faculty FROM users WHERE role='mentor'")
    st.dataframe(mentors, use_container_width=True, hide_index=True)

    st.markdown("---")
    st.markdown("#### Огляд усіх слотів Office Hours")
    events = get_events()
    if events.empty:
        return
    ev_map = dict(zip(events["title"], events["id"]))
    ev_title = st.selectbox("Подія", list(ev_map.keys()), key="mentor_overview_event")
    ev_id = ev_map[ev_title]
    slots = query_df("""SELECT ms.id, u.full_name AS mentor, ms.slot_date, ms.start_time, ms.end_time,
                                ms.location, COALESCE(t.name,'—') AS team,
                                CASE WHEN ms.is_booked=1 THEN 'заброньовано' ELSE 'вільно' END AS status
                         FROM mentor_slots ms
                         JOIN users u ON ms.mentor_id=u.id
                         LEFT JOIN teams t ON ms.team_id=t.id
                         WHERE ms.event_id=? ORDER BY ms.slot_date, ms.start_time""", (ev_id,))
    if slots.empty:
        st.info("Слотів для консультацій ще не створено.")
    else:
        st.dataframe(slots, use_container_width=True, hide_index=True)


def admin_analytics():
    st.subheader("📊 Аналітика та звіти")
    events = get_events()
    if events.empty:
        st.info("Немає даних для аналітики.")
        return

    total_teams = query_one("SELECT COUNT(*) FROM teams")[0]
    total_members = query_one("SELECT COUNT(*) FROM team_members")[0]
    total_events = len(events)
    c1, c2, c3 = st.columns(3)
    c1.metric("Всього подій", total_events)
    c2.metric("Всього команд", total_teams)
    c3.metric("Всього учасників", total_members)

    teams_all = query_df("""SELECT t.*, e.title AS event_title FROM teams t
                             JOIN events e ON t.event_id=e.id""")
    if not teams_all.empty:
        st.markdown("#### Розподіл команд за подіями")
        st.bar_chart(teams_all.groupby("event_title").size())

        st.markdown("#### Розподіл за факультетами")
        st.bar_chart(teams_all.groupby("faculty").size())

        st.markdown("#### Розподіл за статусами заявок")
        st.bar_chart(teams_all.groupby("status").size())

    st.markdown("#### Виявлені аномалії в оцінюванні")
    ev_map = dict(zip(events["title"], events["id"]))
    ev_title = st.selectbox("Подія для перевірки аномалій", list(ev_map.keys()), key="anomaly_event")
    anomalies = detect_anomalies(ev_map[ev_title])
    if anomalies.empty:
        st.success("Аномалій не виявлено.")
    else:
        st.warning("Знайдено оцінки з суттєвим відхиленням від середнього — рекомендується перегляд.")
        st.dataframe(anomalies, use_container_width=True, hide_index=True)

    st.markdown("#### Вивантаження звітів")
    export_format = st.radio("Формат", ["CSV", "Excel"], horizontal=True)
    if st.button("Сформувати звіт"):
        events_df = query_df("SELECT * FROM events")
        teams_df = query_df("SELECT * FROM teams")
        scores_df = query_df("SELECT * FROM scores")
        if export_format == "CSV":
            buf = io.StringIO()
            teams_df.to_csv(buf, index=False)
            st.download_button("⬇️ Завантажити teams.csv", buf.getvalue(), file_name="teams.csv", mime="text/csv")
        else:
            buf = io.BytesIO()
            with pd.ExcelWriter(buf, engine="openpyxl") as writer:
                events_df.to_excel(writer, sheet_name="Events", index=False)
                teams_df.to_excel(writer, sheet_name="Teams", index=False)
                scores_df.to_excel(writer, sheet_name="Scores", index=False)
            st.download_button("⬇️ Завантажити CampusBridge_report.xlsx", buf.getvalue(),
                                file_name="CampusBridge_report.xlsx",
                                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


def admin_announcements():
    st.subheader("📢 Сповіщення та розсилки")
    events = get_events()
    ev_map = {"— глобальне (усі учасники) —": None}
    ev_map.update(dict(zip(events["title"], events["id"])) if not events.empty else {})

    with st.form("announce_form"):
        ev_title = st.selectbox("Подія", list(ev_map.keys()))
        ev_id = ev_map[ev_title]
        target_team_id = None
        if ev_id:
            teams = query_df("SELECT id, name FROM teams WHERE event_id=?", (ev_id,))
            tmap = {"— всі команди події —": None}
            tmap.update(dict(zip(teams["name"], teams["id"])) if not teams.empty else {})
            tname = st.selectbox("Отримувач", list(tmap.keys()))
            target_team_id = tmap[tname]
        title = st.text_input("Заголовок")
        body = st.text_area("Текст повідомлення")
        if st.form_submit_button("Надіслати") and title:
            execute("INSERT INTO announcements (event_id,title,body,target_team_id,created_at) VALUES (?,?,?,?,?)",
                    (ev_id, title, body, target_team_id, now()))
            st.success("Оголошення опубліковано.")

    st.markdown("#### Історія оголошень")
    hist = query_df("""SELECT a.created_at, COALESCE(e.title,'Глобальне') AS event,
                               COALESCE(t.name,'Усі команди') AS target, a.title, a.body
                        FROM announcements a
                        LEFT JOIN events e ON a.event_id=e.id
                        LEFT JOIN teams t ON a.target_team_id=t.id
                        ORDER BY a.created_at DESC""")
    st.dataframe(hist, use_container_width=True, hide_index=True)


def admin_import_export():
    st.subheader("📤 Імпорт / Експорт даних")

    st.markdown("#### Експорт")
    table_choice = st.selectbox("Таблиця для експорту", ["events", "teams", "users", "scores", "submissions"])
    df = query_df(f"SELECT * FROM {table_choice}")
    st.dataframe(df, use_container_width=True, hide_index=True)
    col1, col2 = st.columns(2)
    with col1:
        buf_csv = io.StringIO()
        df.to_csv(buf_csv, index=False)
        st.download_button(f"⬇️ {table_choice}.csv", buf_csv.getvalue(), file_name=f"{table_choice}.csv", mime="text/csv")
    with col2:
        buf_xlsx = io.BytesIO()
        with pd.ExcelWriter(buf_xlsx, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name=table_choice[:31])
        st.download_button(f"⬇️ {table_choice}.xlsx", buf_xlsx.getvalue(), file_name=f"{table_choice}.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    st.markdown("---")
    st.markdown("#### Імпорт команд (масове попереднє додавання)")
    st.caption("Очікувані колонки: event_id, name, faculty, status (необов'язково)")
    up = st.file_uploader("Завантажте CSV або Excel файл із командами", type=["csv", "xlsx"], key="import_teams")
    if up is not None:
        try:
            if up.name.endswith(".csv"):
                imp_df = pd.read_csv(up)
            else:
                imp_df = pd.read_excel(up)
            st.dataframe(imp_df, use_container_width=True, hide_index=True)
            if st.button("Підтвердити імпорт команд"):
                count = 0
                for _, r in imp_df.iterrows():
                    execute("""INSERT INTO teams (event_id,nomination_id,name,captain_id,invite_code,
                               faculty,status,status_comment,created_at) VALUES (?,?,?,?,?,?,?,?,?)""",
                            (int(r.get("event_id")), None, r.get("name"), None, gen_code(),
                             r.get("faculty", ""), r.get("status", "На розгляді"), "", now()))
                    count += 1
                st.success(f"Імпортовано {count} команд(и).")
        except Exception as e:
            st.error(f"Помилка обробки файлу: {e}")

    st.markdown("#### Імпорт подій (масове створення)")
    st.caption("Очікувані колонки: title, category, format, description, status, "
               "reg_start, reg_end, event_start, pitch_deadline, prize_fund, banner_url, video_url (необов'язково)")
    up2 = st.file_uploader("Завантажте CSV або Excel файл із подіями", type=["csv", "xlsx"], key="import_events")
    if up2 is not None:
        try:
            if up2.name.endswith(".csv"):
                imp_df2 = pd.read_csv(up2)
            else:
                imp_df2 = pd.read_excel(up2)
            st.dataframe(imp_df2, use_container_width=True, hide_index=True)
            if st.button("Підтвердити імпорт подій"):
                count = 0
                for _, r in imp_df2.iterrows():
                    execute("""INSERT INTO events (title,category,format,description,regulations,reg_start,reg_end,
                               event_start,pitch_deadline,min_team,max_team,prize_fund,status,leaderboard_live,
                               avoid_conflict,university,faculty,created_by,created_at,double_blind,banner_url,video_url)
                               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                            (r.get("title"), r.get("category", "IT"), r.get("format", "Онлайн"),
                             r.get("description", ""), "", r.get("reg_start", ""), r.get("reg_end", ""),
                             r.get("event_start", ""), r.get("pitch_deadline", ""), 2, 5,
                             r.get("prize_fund", ""), r.get("status", "Чернетка"),
                             0, 1, MAIN_UNIVERSITY, MAIN_FACULTY, st.session_state.user["id"], now(), 0,
                             r.get("banner_url", ""), r.get("video_url", "")))
                    count += 1
                st.success(f"Імпортовано {count} подій(ї).")
        except Exception as e:
            st.error(f"Помилка обробки файлу: {e}")


def page_admin():
    st.sidebar.markdown("### 👑 Меню адміністратора")
    menu = st.sidebar.radio("Розділ", [
        "🛠️ Конструктор подій", "📥 Модерація заявок", "⚖️ Журі", "🧑‍🏫 Ментори",
        "📊 Аналітика та звіти", "📢 Сповіщення", "📤 Імпорт/Експорт", "🏆 Лідерборд", "🖼️ Портфоліо проєктів"
    ])
    if menu == "🛠️ Конструктор подій":
        admin_event_builder()
    elif menu == "📥 Модерація заявок":
        admin_team_moderation()
    elif menu == "⚖️ Журі":
        admin_jury()
    elif menu == "🧑‍🏫 Ментори":
        admin_mentors()
    elif menu == "📊 Аналітика та звіти":
        admin_analytics()
    elif menu == "📢 Сповіщення":
        admin_announcements()
    elif menu == "📤 Імпорт/Експорт":
        admin_import_export()
    elif menu == "🏆 Лідерборд":
        page_leaderboard()
    elif menu == "🖼️ Портфоліо проєктів":
        page_showcase()


# ============================================================
# УЧАСНИК / КАПІТАН КОМАНДИ
# ============================================================

def participant_my_team():
    st.subheader("🚀 Моя команда")
    user = st.session_state.user
    my_teams = query_df("""SELECT t.* FROM teams t JOIN team_members tm ON t.id=tm.team_id
                            WHERE tm.user_id=?""", (user["id"],))

    tab1, tab2 = st.tabs(["Моя поточна команда", "Створити / приєднатись"])

    with tab2:
        st.markdown("##### Створити нову команду (я — капітан)")
        events = get_events("Реєстрація відкрита")
        if events.empty:
            st.info("Наразі немає подій з відкритою реєстрацією.")
        else:
            with st.form("create_team_form"):
                ev_map = dict(zip(events["title"], events["id"]))
                ev_title = st.selectbox("Подія", list(ev_map.keys()))
                ev_id = ev_map[ev_title]
                noms = query_df("SELECT id, name FROM nominations WHERE event_id=?", (ev_id,))
                nom_id = None
                if not noms.empty:
                    nmap = dict(zip(noms["name"], noms["id"]))
                    nom_name = st.selectbox("Номінація", list(nmap.keys()))
                    nom_id = nmap[nom_name]
                team_name = st.text_input("Назва команди")
                faculty = st.text_input("Факультет", value=user.get("faculty") or MAIN_FACULTY)
                if st.form_submit_button("Створити команду") and team_name:
                    code = gen_code()
                    tid = execute("""INSERT INTO teams (event_id,nomination_id,name,captain_id,invite_code,
                                     faculty,status,status_comment,created_at) VALUES (?,?,?,?,?,?,?,?,?)""",
                                  (ev_id, nom_id, team_name, user["id"], code, faculty, "На розгляді", "", now()))
                    execute("INSERT INTO team_members (team_id,user_id) VALUES (?,?)", (tid, user["id"]))
                    st.success(f"Команду створено! Інвайт-код для запрошення учасників: **{code}**")
                    st.rerun()

        st.markdown("##### Приєднатись за інвайт-кодом")
        with st.form("join_team_form"):
            code_in = st.text_input("Інвайт-код команди")
            if st.form_submit_button("Приєднатись") and code_in:
                team = query_one("SELECT id, event_id FROM teams WHERE invite_code=?", (code_in.strip().upper(),))
                if not team:
                    st.error("Команду з таким кодом не знайдено.")
                else:
                    tid, ev_id = team
                    already = query_one("SELECT id FROM team_members WHERE team_id=? AND user_id=?", (tid, user["id"]))
                    if already:
                        st.warning("Ви вже у цій команді.")
                    else:
                        ev = query_one("SELECT max_team FROM events WHERE id=?", (ev_id,))
                        current_count = query_one("SELECT COUNT(*) FROM team_members WHERE team_id=?", (tid,))[0]
                        if ev and current_count >= ev[0]:
                            st.error("Команда вже заповнена (досягнуто максимальної кількості учасників).")
                        else:
                            execute("INSERT INTO team_members (team_id,user_id) VALUES (?,?)", (tid, user["id"]))
                            st.success("Ви приєдналися до команди!")
                            st.rerun()

    with tab1:
        if my_teams.empty:
            st.info("Ви ще не в жодній команді.")
            return
        for _, t in my_teams.iterrows():
            with st.container(border=True):
                st.markdown(f"### {t['name']}")
                status_colors = {"Прийнято": "green", "Відхилено": "red",
                                  "Потребує доопрацювання": "orange", "На розгляді": "blue"}
                st.markdown(f":{status_colors.get(t['status'],'gray')}[**Статус: {t['status']}**]")
                if t["status_comment"]:
                    st.caption(f"Коментар журі/адміністратора: {t['status_comment']}")
                st.write(f"Інвайт-код для запрошення: `{t['invite_code']}`")

                members = query_df("""SELECT u.full_name, u.email FROM team_members tm
                                       JOIN users u ON tm.user_id=u.id WHERE tm.team_id=?""", (t["id"],))
                st.write("**Учасники команди:**")
                st.dataframe(members, use_container_width=True, hide_index=True)

                st.markdown("#### 📦 Подача проєкту")
                last_sub = query_one("""SELECT repo_link, presentation_link, video_link, description, version
                                         FROM submissions WHERE team_id=? ORDER BY version DESC LIMIT 1""", (t["id"],))
                with st.form(f"submit_form_{t['id']}"):
                    repo_link = st.text_input("Посилання на репозиторій (GitHub)",
                                               value=last_sub[0] if last_sub else "")
                    video_link = st.text_input("Посилання на відео (YouTube/Google Drive)",
                                                value=last_sub[2] if last_sub else "")
                    description = st.text_area("Опис проєкту",
                                                value=last_sub[3] if last_sub else "")
                    pdf_file = st.file_uploader("Презентація (PDF, до 50 МБ)", type=["pdf"], key=f"pdf_{t['id']}")
                    if st.form_submit_button("Зберегти / оновити подачу"):
                        new_version = (last_sub[4] + 1) if last_sub else 1
                        pres_link = last_sub[1] if last_sub else ""
                        sub_id = execute("""INSERT INTO submissions (team_id,repo_link,presentation_link,video_link,
                                           description,version,updated_at) VALUES (?,?,?,?,?,?,?)""",
                                        (t["id"], repo_link, pres_link, video_link, description, new_version, now()))
                        if pdf_file is not None:
                            size_mb = pdf_file.size / (1024 * 1024)
                            if size_mb > MAX_PDF_MB:
                                st.error(f"Файл завеликий ({size_mb:.1f} МБ). Максимум {MAX_PDF_MB} МБ.")
                            else:
                                execute("""INSERT INTO files (submission_id,filename,mimetype,data,uploaded_at)
                                           VALUES (?,?,?,?,?)""",
                                        (sub_id, pdf_file.name, pdf_file.type, pdf_file.getvalue(), now()))
                        st.success(f"Подачу збережено (версія {new_version}).")
                        st.rerun()

                if last_sub:
                    st.caption(f"Поточна версія подачі: v{last_sub[4]}")


def participant_office_hours():
    st.subheader("🗓️ Office Hours — консультації з менторами")
    user = st.session_state.user
    my_teams = query_df("""SELECT t.* FROM teams t JOIN team_members tm ON t.id=tm.team_id
                            WHERE tm.user_id=?""", (user["id"],))
    if my_teams.empty:
        st.info("Спочатку створіть або приєднайтесь до команди на вкладці «Моя команда».")
        return

    team_map = dict(zip(my_teams["name"] + " (#" + my_teams["id"].astype(str) + ")", my_teams["id"]))
    team_label = st.selectbox("Команда", list(team_map.keys()))
    team_id = int(team_map[team_label])
    team_row = my_teams[my_teams["id"] == team_id].iloc[0]
    event_id = int(team_row["event_id"])

    my_booking = query_df("""SELECT ms.id, u.full_name AS mentor, ms.slot_date, ms.start_time, ms.end_time,
                                     ms.location, ms.notes
                              FROM mentor_slots ms JOIN users u ON ms.mentor_id=u.id
                              WHERE ms.team_id=? AND ms.event_id=?""", (team_id, event_id))

    if not my_booking.empty:
        st.success("✅ У вашої команди вже є записана консультація:")
        st.dataframe(my_booking, use_container_width=True, hide_index=True)
        cancel_id = int(my_booking.iloc[0]["id"])
        if st.button("Скасувати запис"):
            execute("UPDATE mentor_slots SET is_booked=0, team_id=NULL WHERE id=?", (cancel_id,))
            st.success("Запис скасовано, слот знову вільний.")
            st.rerun()
        return

    st.markdown("#### Вільні слоти для консультацій перед пітчингом")
    free_slots = query_df("""SELECT ms.id, u.full_name AS mentor, ms.slot_date, ms.start_time, ms.end_time,
                                     ms.location
                              FROM mentor_slots ms JOIN users u ON ms.mentor_id=u.id
                              WHERE ms.event_id=? AND ms.is_booked=0
                              ORDER BY ms.slot_date, ms.start_time""", (event_id,))
    if free_slots.empty:
        st.info("Наразі немає вільних слотів для цієї події. Спробуйте пізніше.")
        return

    st.dataframe(free_slots, use_container_width=True, hide_index=True)
    slot_map = {
        f"{row['mentor']} · {row['slot_date']} {row['start_time']}–{row['end_time']} ({row['location'] or 'онлайн'})": row["id"]
        for _, row in free_slots.iterrows()
    }
    chosen = st.selectbox("Оберіть слот", list(slot_map.keys()))
    if st.button("📌 Записатись на консультацію"):
        slot_id = int(slot_map[chosen])
        current = query_one("SELECT is_booked FROM mentor_slots WHERE id=?", (slot_id,))
        if current and current[0] == 1:
            st.error("На жаль, цей слот щойно зайняли. Оберіть інший.")
        else:
            execute("UPDATE mentor_slots SET is_booked=1, team_id=? WHERE id=?", (team_id, slot_id))
            st.success("Вас записано на консультацію!")
            st.rerun()


def page_participant():
    st.sidebar.markdown("### 🎓 Меню учасника")
    menu = st.sidebar.radio("Розділ", ["📅 Календар подій", "🚀 Моя команда", "🗓️ Office Hours",
                                        "🏆 Лідерборд", "🖼️ Портфоліо проєктів", "📢 Оголошення"])
    if menu == "📅 Календар подій":
        page_calendar()
    elif menu == "🚀 Моя команда":
        participant_my_team()
    elif menu == "🗓️ Office Hours":
        participant_office_hours()
    elif menu == "🏆 Лідерборд":
        page_leaderboard()
    elif menu == "🖼️ Портфоліо проєктів":
        page_showcase()
    elif menu == "📢 Оголошення":
        page_announcements_view()


def page_announcements_view():
    st.subheader("📢 Оголошення")
    user = st.session_state.user
    my_team_ids = query_df("SELECT team_id FROM team_members WHERE user_id=?", (user["id"],))["team_id"].tolist()
    if my_team_ids:
        placeholders = ",".join(["?"] * len(my_team_ids))
        sql = f"""SELECT created_at, title, body FROM announcements
                  WHERE target_team_id IS NULL OR target_team_id IN ({placeholders})
                  ORDER BY created_at DESC"""
        anns = query_df(sql, my_team_ids)
    else:
        anns = query_df("SELECT created_at, title, body FROM announcements WHERE target_team_id IS NULL ORDER BY created_at DESC")
    if anns.empty:
        st.info("Оголошень поки немає.")
    else:
        for _, a in anns.iterrows():
            with st.container(border=True):
                st.markdown(f"**{a['title']}**")
                st.caption(a["created_at"])
                st.write(a["body"])


# ============================================================
# ЖУРІ / ЕКСПЕРТ
# ============================================================

def page_jury():
    st.sidebar.markdown("### ⚖️ Меню журі")
    menu = st.sidebar.radio("Розділ", ["📋 Оцінювання", "🏆 Лідерборд", "🖼️ Портфоліо проєктів", "📢 Оголошення"])
    if menu == "📋 Оцінювання":
        jury_evaluation()
    elif menu == "🏆 Лідерборд":
        page_leaderboard()
    elif menu == "🖼️ Портфоліо проєктів":
        page_showcase()
    elif menu == "📢 Оголошення":
        page_announcements_view()


def jury_evaluation():
    st.subheader("📋 Інтерфейс оцінювання")
    user = st.session_state.user
    assignments = query_df("""SELECT ja.event_id, ja.nomination_id, e.title AS event_title
                               FROM jury_assignments ja JOIN events e ON ja.event_id=e.id
                               WHERE ja.jury_id=?""", (user["id"],))
    if assignments.empty:
        st.info("Вам ще не призначено подій для оцінювання.")
        return

    ev_options = assignments["event_title"].unique().tolist()
    ev_title = st.selectbox("Подія", ev_options)
    ev_id = int(assignments[assignments["event_title"] == ev_title]["event_id"].iloc[0])
    nom_ids = assignments[assignments["event_title"] == ev_title]["nomination_id"].tolist()

    ev_row = query_one("SELECT double_blind FROM events WHERE id=?", (ev_id,))
    double_blind = bool(ev_row[0]) if ev_row else False
    if double_blind:
        st.info("🕶️ Для цієї події увімкнено **сліпе оцінювання** — назви команд і факультети приховано.")

    if any(pd.isna(n) for n in nom_ids):
        teams = query_df("SELECT * FROM teams WHERE event_id=? AND status='Прийнято'", (ev_id,))
    else:
        placeholders = ",".join(["?"] * len(nom_ids))
        teams = query_df(f"SELECT * FROM teams WHERE event_id=? AND status='Прийнято' AND nomination_id IN ({placeholders})",
                          [ev_id] + nom_ids)

    criteria = query_df("SELECT * FROM criteria WHERE event_id=?", (ev_id,))
    if criteria.empty:
        st.warning("Для цієї події ще не налаштовано критерії оцінювання.")
        return
    if teams.empty:
        st.info("Немає прийнятих команд для оцінювання.")
        return

    for _, t in teams.iterrows():
        display_name = anon_code(t["id"]) if double_blind else f"{t['name']} ({t['faculty']})"

        if has_conflict(ev_id, t["id"], user):
            with st.container(border=True):
                st.markdown(f"### {display_name if double_blind else t['name']}")
                st.warning("⛔ Оцінювання недоступне: команда належить до вашого факультету (конфлікт інтересів).")
            continue

        with st.container(border=True):
            st.markdown(f"### {display_name}")
            sub = query_one("""SELECT repo_link, presentation_link, video_link, description
                                FROM submissions WHERE team_id=? ORDER BY version DESC LIMIT 1""", (t["id"],))
            if sub:
                st.write(sub[3] or "_Опис відсутній_")
                if sub[0]:
                    st.write(f"🔗 Репозиторій: {sub[0]}")
                if sub[2]:
                    st.write(f"🎬 Відео: {sub[2]}")
                files = query_df("""SELECT f.filename, f.id FROM files f
                                     JOIN submissions s ON f.submission_id=s.id
                                     WHERE s.team_id=? ORDER BY f.uploaded_at DESC LIMIT 1""", (t["id"],))
                if not files.empty:
                    st.write(f"📄 Презентація: {files.iloc[0]['filename']}")
            else:
                st.warning("Команда ще не завантажила подачу.")

            with st.form(f"score_form_{t['id']}"):
                score_vals = {}
                for _, crit in criteria.iterrows():
                    existing = query_one("SELECT score FROM scores WHERE team_id=? AND jury_id=? AND criterion_id=?",
                                          (t["id"], user["id"], crit["id"]))
                    default_val = existing[0] if existing else 0.0
                    score_vals[crit["id"]] = st.slider(
                        f"{crit['name']} (вага {crit['weight']}%, макс {crit['max_score']})",
                        min_value=0.0, max_value=float(crit["max_score"]), value=float(default_val), step=0.5,
                        key=f"slider_{t['id']}_{crit['id']}")
                existing_fb = query_one("SELECT feedback FROM scores WHERE team_id=? AND jury_id=? LIMIT 1",
                                         (t["id"], user["id"]))
                feedback = st.text_area("Текстовий фідбек / менторський відгук",
                                         value=existing_fb[0] if existing_fb else "", key=f"fb_{t['id']}")
                if st.form_submit_button("💾 Зберегти оцінку"):
                    for crit_id, val in score_vals.items():
                        execute("""INSERT INTO scores (team_id,jury_id,criterion_id,score,feedback,created_at)
                                   VALUES (?,?,?,?,?,?)
                                   ON CONFLICT(team_id,jury_id,criterion_id)
                                   DO UPDATE SET score=excluded.score, feedback=excluded.feedback, created_at=excluded.created_at""",
                                (t["id"], user["id"], crit_id, val, feedback, now()))
                    st.success("Оцінку збережено.")
                    st.rerun()


# ============================================================
# МЕНТОР (OFFICE HOURS)
# ============================================================

def page_mentor():
    st.sidebar.markdown("### 🧑‍🏫 Меню ментора")
    menu = st.sidebar.radio("Розділ", ["🗓️ Мої слоти консультацій", "🏆 Лідерборд", "🖼️ Портфоліо проєктів", "📢 Оголошення"])
    if menu == "🗓️ Мої слоти консультацій":
        mentor_slots_manager()
    elif menu == "🏆 Лідерборд":
        page_leaderboard()
    elif menu == "🖼️ Портфоліо проєктів":
        page_showcase()
    elif menu == "📢 Оголошення":
        page_announcements_view()


def mentor_slots_manager():
    st.subheader("🗓️ Office Hours — мої слоти консультацій")
    user = st.session_state.user

    events = get_events()
    if events.empty:
        st.info("Подій ще немає.")
        return
    ev_map = dict(zip(events["title"], events["id"]))
    ev_title = st.selectbox("Подія", list(ev_map.keys()))
    ev_id = ev_map[ev_title]

    st.markdown("#### ➕ Додати новий слот")
    with st.form("add_slot_form"):
        c1, c2, c3 = st.columns(3)
        with c1:
            slot_date = st.text_input("Дата (ГГГГ-ММ-ДД)")
        with c2:
            start_time = st.text_input("Початок (ГГ:ХХ)", value="10:00")
        with c3:
            end_time = st.text_input("Кінець (ГГ:ХХ)", value="10:15")
        location = st.text_input("Місце проведення / посилання (Zoom, Meet тощо)", value="Онлайн")
        notes = st.text_input("Примітка (необов'язково)", value="")
        if st.form_submit_button("Додати слот") and slot_date and start_time and end_time:
            execute("""INSERT INTO mentor_slots (mentor_id,event_id,slot_date,start_time,end_time,
                       location,is_booked,team_id,notes,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (user["id"], ev_id, slot_date, start_time, end_time, location, 0, None, notes, now()))
            st.success("Слот додано до розкладу.")
            st.rerun()

    st.markdown("#### Мій розклад консультацій")
    my_slots = query_df("""SELECT ms.id, ms.slot_date, ms.start_time, ms.end_time, ms.location,
                                   COALESCE(t.name,'—') AS team,
                                   CASE WHEN ms.is_booked=1 THEN '🔴 заброньовано' ELSE '🟢 вільно' END AS status
                            FROM mentor_slots ms LEFT JOIN teams t ON ms.team_id=t.id
                            WHERE ms.mentor_id=? AND ms.event_id=?
                            ORDER BY ms.slot_date, ms.start_time""", (user["id"], ev_id))
    if my_slots.empty:
        st.info("Слотів ще не створено.")
        return

    st.dataframe(my_slots, use_container_width=True, hide_index=True)

    st.markdown("#### Керування слотами")
    for _, s in my_slots.iterrows():
        label = f"#{s['id']} · {s['slot_date']} {s['start_time']}–{s['end_time']} · {s['status']} · {s['team']}"
        c1, c2 = st.columns([4, 1])
        with c1:
            st.write(label)
        with c2:
            if st.button("🗑️ Видалити", key=f"del_slot_{s['id']}"):
                execute("DELETE FROM mentor_slots WHERE id=?", (int(s["id"]),))
                st.rerun()


# ============================================================
# ГОЛОВНИЙ МАРШРУТИЗАТОР
# ============================================================

def main():
    st.title("🎓 CampusBridge")
    st.caption(f"{MAIN_UNIVERSITY} · {MAIN_FACULTY}")

    user = st.session_state.user

    if user is None:
        st.sidebar.markdown("### Навігація")
        public_page = st.sidebar.radio("Розділ", ["📅 Календар подій", "🏆 Лідерборд",
                                                    "🖼️ Портфоліо проєктів", "🔐 Вхід / Реєстрація"])
        if public_page == "📅 Календар подій":
            page_calendar()
        elif public_page == "🏆 Лідерборд":
            page_leaderboard()
        elif public_page == "🖼️ Портфоліо проєктів":
            page_showcase()
        else:
            page_login()
        return

    st.sidebar.success(f"Ви увійшли як: {user['full_name']} ({user['role']})")
    if st.sidebar.button("Вийти"):
        logout()

    if user["role"] == "admin":
        page_admin()
    elif user["role"] == "participant":
        page_participant()
    elif user["role"] == "jury":
        page_jury()
    elif user["role"] == "mentor":
        page_mentor()


if __name__ == "__main__":
    main()
