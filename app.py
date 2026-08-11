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
import base64
import smtplib
from email.mime.text import MIMEText
import altair as alt
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
EVENT_STATUSES = ["Чернетка", "Реєстрація відкрита", "Закрито", "Триває подія", "Архів"]
TEAM_STATUSES = ["На розгляді", "Прийнято", "Потребує доопрацювання", "Відхилено"]
MAX_PDF_MB = 50

EVENT_TEMPLATES = {
    "🏆 Класичний хакатон": {
        "category": "IT", "format": "Гібридний", "min_team": 2, "max_team": 5,
        "description": "Класичний хакатон: команди за обмежений час (24-48 годин) розробляють "
                       "робочий прототип проєкту від ідеї до демо.",
        "regulations": "Учасники формують команди 2-5 осіб. Час на розробку — 24-48 годин. "
                       "Фінал — пітчинг перед журі. Оцінюється інноваційність, технічна реалізація "
                       "та якість презентації.",
        "prize_fund": "50 000 грн", "max_teams": 20, "double_blind": 0, "jury_see_other_scores": 0,
        "nominations": ["AI / Machine Learning", "Web / Mobile розробка", "IoT / Hardware"],
        "criteria": [("Інноваційність", 30, 10), ("Технічна реалізація", 40, 10), ("Презентація", 30, 10)],
    },
    "💼 Кейс-чемпіонат": {
        "category": "Бізнес/Кейси", "format": "Офлайн", "min_team": 3, "max_team": 5,
        "description": "Кейс-чемпіонат: команди аналізують реальний бізнес-кейс від партнера "
                       "й презентують обґрунтоване рішення журі з індустрії.",
        "regulations": "Кейс видається на початку події. Час на підготовку рішення — 4-6 годин. "
                       "Оцінюється глибина аналізу, практична застосовність рішення та презентація.",
        "prize_fund": "30 000 грн", "max_teams": 15, "double_blind": 1, "jury_see_other_scores": 1,
        "nominations": ["Маркетингова стратегія", "Фінансова модель", "Операційна ефективність"],
        "criteria": [("Аналітична глибина", 35, 10), ("Практична застосовність", 35, 10),
                     ("Презентація рішення", 30, 10)],
    },
    "🏅 Спортивний челендж": {
        "category": "Спорт", "format": "Офлайн", "min_team": 1, "max_team": 10,
        "description": "Спортивний челендж/турнір між факультетами чи закладами освіти.",
        "regulations": "Змагання проходять за стандартними спортивними правилами обраної дисципліни. "
                       "Реєстрація команд/учасників — заздалегідь, за визначеним лімітом місць.",
        "prize_fund": "Кубок і грамоти переможцям", "max_teams": 12, "double_blind": 0,
        "jury_see_other_scores": 1, "nominations": [],
        "criteria": [("Результат/час", 60, 10), ("Командна взаємодія", 20, 10), ("Фейр-плей", 20, 10)],
    },
}

st.set_page_config(page_title="CampusBridge", page_icon="🎓", layout="wide")

# ============================================================
# ШАР ДОСТУПУ ДО БАЗИ ДАНИХ
# ============================================================

# pandas/numpy повертають numpy.int64/float64 для колонок id при ітерації DataFrame
# (наприклад, у циклах по критеріях/командах у лідерборді). Без цих адаптерів sqlite3
# мовчки не знаходить збігів по такому параметру (повертає None замість помилки),
# тому реєструємо конвертацію у звичайні Python int/float ще до першого запиту.
try:
    import numpy as _np
    for _int_type in (_np.int64, _np.int32, _np.intp):
        sqlite3.register_adapter(_int_type, lambda val: int(val))
    for _float_type in (_np.float64, _np.float32):
        sqlite3.register_adapter(_float_type, lambda val: float(val))
except ImportError:
    pass


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
    c.execute("""CREATE TABLE IF NOT EXISTS mentor_feedback (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        slot_id INTEGER, mentor_id INTEGER, team_id INTEGER,
        rating INTEGER, comment TEXT, created_at TEXT,
        UNIQUE(slot_id, team_id)
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS showcase_likes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        team_id INTEGER, voter_key TEXT, created_at TEXT,
        UNIQUE(team_id, voter_key)
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS team_status_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        team_id INTEGER, old_status TEXT, new_status TEXT,
        changed_by_id INTEGER, changed_by_name TEXT,
        comment TEXT, changed_at TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS email_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        team_id INTEGER, to_email TEXT, subject TEXT, body TEXT,
        status TEXT, created_at TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS team_questions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        team_id INTEGER, question TEXT, asked_by_id INTEGER, asked_by_name TEXT, asked_at TEXT,
        answer TEXT, answered_by_name TEXT, answered_at TEXT
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
    if "max_teams" not in existing_cols:
        c.execute("ALTER TABLE events ADD COLUMN max_teams INTEGER")
    if "jury_see_other_scores" not in existing_cols:
        c.execute("ALTER TABLE events ADD COLUMN jury_see_other_scores INTEGER DEFAULT 0")
    conn.commit()

    c.execute("PRAGMA table_info(submissions)")
    sub_cols = [row[1] for row in c.fetchall()]
    if "tags" not in sub_cols:
        c.execute("ALTER TABLE submissions ADD COLUMN tags TEXT")
    conn.commit()

    c.execute("PRAGMA table_info(announcements)")
    ann_cols = [row[1] for row in c.fetchall()]
    if "priority" not in ann_cols:
        c.execute("ALTER TABLE announcements ADD COLUMN priority TEXT DEFAULT 'Звичайне'")
    if "audience" not in ann_cols:
        c.execute("ALTER TABLE announcements ADD COLUMN audience TEXT DEFAULT 'Усі'")
    if "created_by_name" not in ann_cols:
        c.execute("ALTER TABLE announcements ADD COLUMN created_by_name TEXT")
    if "email_status" not in ann_cols:
        c.execute("ALTER TABLE announcements ADD COLUMN email_status TEXT")
    conn.commit()

    c.execute("PRAGMA table_info(users)")
    user_cols = [row[1] for row in c.fetchall()]
    if "email_opt_in" not in user_cols:
        c.execute("ALTER TABLE users ADD COLUMN email_opt_in INTEGER DEFAULT 1")
    conn.commit()

    c.execute("PRAGMA table_info(users)")
    user_cols = [row[1] for row in c.fetchall()]
    if "email_opt_in" not in user_cols:
        c.execute("ALTER TABLE users ADD COLUMN email_opt_in INTEGER DEFAULT 1")
    conn.commit()

    c.execute("PRAGMA table_info(team_members)")
    tm_cols = [row[1] for row in c.fetchall()]
    if "joined_at" not in tm_cols:
        c.execute("ALTER TABLE team_members ADD COLUMN joined_at TEXT")
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
        nom2_id = c.lastrowid
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
        c.execute("INSERT INTO team_members (team_id,user_id,joined_at) VALUES (?,?,?)",
                   (demo_team_id, participant_demo_id, now()))
        c.execute("""INSERT INTO submissions (team_id,repo_link,presentation_link,video_link,description,
            version,updated_at,tags) VALUES (?,?,?,?,?,?,?,?)""",
            (demo_team_id, "https://github.com/campusbridge/demo-ai-assistant", "",
             "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
             "Демонстраційний проєкт: інтелектуальний асистент, що підбирає студентам хакатони "
             "та челенджі за їхніми навичками й інтересами.", 1, now(),
             "Python, Machine Learning, NLP, FastAPI"))
        for cid in crit_ids:
            c.execute("""INSERT INTO scores (team_id,jury_id,criterion_id,score,feedback,created_at)
                VALUES (?,?,?,?,?,?)""",
                (demo_team_id, jury_demo_id, cid, 8.0,
                 "Сильна ідея та якісна технічна реалізація, продовжуйте розвивати проєкт!", now()))

        # друга демо-команда в іншій номінації — щоб фільтр за номінаціями та порівняння команд
        # у лідерборді одразу мали що показати
        c.execute("""INSERT INTO teams (event_id,nomination_id,name,captain_id,invite_code,faculty,status,
            status_comment,created_at) VALUES (?,?,?,?,?,?,?,?,?)""",
            (demo_event_id, nom2_id, "Web Titans", None, gen_code(), "ФІТ", "Прийнято", "", now()))
        demo_team2_id = c.lastrowid
        c.execute("""INSERT INTO submissions (team_id,repo_link,presentation_link,video_link,description,
            version,updated_at,tags) VALUES (?,?,?,?,?,?,?,?)""",
            (demo_team2_id, "https://github.com/campusbridge/demo-web-titans", "", "",
             "Демонстраційний проєкт: платформа для обміну конспектами між студентами факультету.",
             1, now(), "React, TypeScript, Node.js, PostgreSQL"))
        for cid, sc in zip(crit_ids, [6.0, 7.0, 6.5]):
            c.execute("""INSERT INTO scores (team_id,jury_id,criterion_id,score,feedback,created_at)
                VALUES (?,?,?,?,?,?)""",
                (demo_team2_id, jury_demo_id, cid, sc, "Непогана реалізація, варто доопрацювати UX.", now()))

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
            version,updated_at,tags) VALUES (?,?,?,?,?,?,?,?)""",
            (archive_team_id, "https://github.com/campusbridge/smart-campus", "", "",
             "Переможець хакатону 2025 року: система розумного кампусу з керуванням аудиторіями "
             "та розкладом у реальному часі.", 1, now(), "IoT, React, Node.js, MQTT"))
        for cid in archive_crit_ids:
            c.execute("""INSERT INTO scores (team_id,jury_id,criterion_id,score,feedback,created_at)
                VALUES (?,?,?,?,?,?)""", (archive_team_id, jury_demo_id, cid, 9.0, "Відмінна робота!", now()))

        # призначення демо-журі на демо-подію — без цього розділ "Оцінювання" для jury_demo
        # виглядав би порожнім, хоча оцінки вище вже виставлені
        c.execute("INSERT INTO jury_assignments (event_id,jury_id,nomination_id) VALUES (?,?,?)",
                  (demo_event_id, jury_demo_id, None))

        # демо-слоти ментора на демо-подію: один вільний і один заброньований демо-командою,
        # щоб розділ "Мої слоти консультацій" не був порожнім із коробки
        c.execute("SELECT id FROM users WHERE username='mentor_demo'")
        mentor_demo_id = c.fetchone()[0]
        c.execute("""INSERT INTO mentor_slots (mentor_id,event_id,slot_date,start_time,end_time,
            location,is_booked,team_id,notes,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (mentor_demo_id, demo_event_id, "2026-09-21", "11:00", "11:15",
             "Онлайн (Google Meet)", 1, demo_team_id, "Обговорення архітектури рекомендаційної моделі", now()))
        c.execute("""INSERT INTO mentor_slots (mentor_id,event_id,slot_date,start_time,end_time,
            location,is_booked,team_id,notes,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (mentor_demo_id, demo_event_id, "2026-09-21", "11:30", "11:45",
             "Онлайн (Google Meet)", 0, None, "", now()))

        # демо-оголошення: одне глобальне і одне по демо-події з різними пріоритетами,
        # щоб розділ "Оголошення" одразу мав приклад для всіх ролей
        c.execute("""INSERT INTO announcements (event_id,title,body,target_team_id,created_at,
            priority,audience,created_by_name,email_status) VALUES (?,?,?,?,?,?,?,?,?)""",
            (None, "Ласкаво просимо до CampusBridge!",
             "Це демонстраційна платформа студентських хакатонів. Тут ви можете переглядати події, "
             "подавати заявки, оцінювати проєкти та бронювати консультації з менторами.",
             None, now(), "Звичайне", "Усі", "Адміністратор системи", None))
        c.execute("""INSERT INTO announcements (event_id,title,body,target_team_id,created_at,
            priority,audience,created_by_name,email_status) VALUES (?,?,?,?,?,?,?,?,?)""",
            (demo_event_id, "Нагадування: дедлайн подачі проєктів наближається",
             "Не забудьте завантажити останню версію презентації та заповнити опис проєкту "
             "до дедлайну пітчингу. Консультації з менторами доступні в розділі Office Hours.",
             None, now(), "⭐ Важливе", "Усі команди", "Адміністратор системи", None))

        conn.commit()

    # ------------------------------------------------------------------
    # Самозцілення для вже розгорнутих інсталяцій платформи
    # ------------------------------------------------------------------
    # Демо-блок вище виконується лише один раз — коли в базі ще немає жодної події.
    # Якщо цей код платформи розгортається поверх уже наповненої бази (наприклад,
    # оновлення вже працюючого застосунку), демо-обліковий запис jury_demo міг
    # лишитися без жодного призначення на подію. Перевіряємо це щоразу при старті
    # й, за потреби, ідемпотентно призначаємо його на першу доступну подію, щоб
    # розділ «Оцінювання» не виглядав порожнім для демонстрації ролі журі.
    c.execute("SELECT id FROM users WHERE username='jury_demo'")
    jury_demo_row = c.fetchone()
    if jury_demo_row:
        jury_demo_id_heal = jury_demo_row[0]
        c.execute("SELECT COUNT(*) FROM jury_assignments WHERE jury_id=?", (jury_demo_id_heal,))
        if c.fetchone()[0] == 0:
            c.execute("SELECT id FROM events ORDER BY id LIMIT 1")
            first_event = c.fetchone()
            if first_event:
                c.execute("INSERT INTO jury_assignments (event_id,jury_id,nomination_id) VALUES (?,?,?)",
                          (first_event[0], jury_demo_id_heal, None))

    # Аналогічно для демо-ментора: якщо в нього ще немає жодного слоту консультацій,
    # створюємо один вільний слот на першій доступній події.
    c.execute("SELECT id FROM users WHERE username='mentor_demo'")
    mentor_demo_row = c.fetchone()
    if mentor_demo_row:
        mentor_demo_id_heal = mentor_demo_row[0]
        c.execute("SELECT COUNT(*) FROM mentor_slots WHERE mentor_id=?", (mentor_demo_id_heal,))
        if c.fetchone()[0] == 0:
            c.execute("SELECT id FROM events ORDER BY id LIMIT 1")
            first_event_m = c.fetchone()
            if first_event_m:
                c.execute("""INSERT INTO mentor_slots (mentor_id,event_id,slot_date,start_time,end_time,
                    location,is_booked,team_id,notes,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (mentor_demo_id_heal, first_event_m[0], str(datetime.date.today() + timedelta(days=14)),
                     "11:00", "11:15", "Онлайн", 0, None, "", now()))
    # Якщо на вже розгорнутій платформі ще жодного оголошення не публікували,
    # додаємо демонстраційне глобальне оголошення, щоб розділ не виглядав порожнім.
    c.execute("SELECT COUNT(*) FROM announcements")
    if c.fetchone()[0] == 0:
        c.execute("""INSERT INTO announcements (event_id,title,body,target_team_id,created_at,
            priority,audience,created_by_name,email_status) VALUES (?,?,?,?,?,?,?,?,?)""",
            (None, "Ласкаво просимо до CampusBridge!",
             "Це демонстраційна платформа студентських хакатонів. Тут ви можете переглядати події, "
             "подавати заявки, оцінювати проєкти та бронювати консультації з менторами.",
             None, now(), "Звичайне", "Усі", "Адміністратор системи", None))

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
                "university", "faculty", "created_at", "email_opt_in"]
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


def compute_team_score_for_jury(team_id, jury_id):
    """Зважений бал команди на основі оцінок лише ОДНОГО конкретного журі (без усереднення з іншими)."""
    scores_df = query_df("""SELECT s.criterion_id, s.score, c.weight, c.max_score
                             FROM scores s JOIN criteria c ON s.criterion_id=c.id
                             WHERE s.team_id=? AND s.jury_id=?""", (team_id, jury_id))
    if scores_df.empty:
        return None
    scores_df["norm"] = scores_df["score"] / scores_df["max_score"] * 100
    total_weight = scores_df["weight"].sum()
    if total_weight == 0:
        return None
    weighted = (scores_df["norm"] * scores_df["weight"]).sum() / total_weight
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


def compute_team_rank(team_id):
    """Повертає (місце, всього_команд) команди в її номінації/події за зваженим балом, або None якщо оцінок немає."""
    team = query_one("SELECT event_id, nomination_id FROM teams WHERE id=?", (team_id,))
    if not team:
        return None
    event_id, nomination_id = team
    if nomination_id is not None:
        teams_scope = query_df("SELECT id FROM teams WHERE event_id=? AND nomination_id=? AND status='Прийнято'",
                                (event_id, nomination_id))
    else:
        teams_scope = query_df("SELECT id FROM teams WHERE event_id=? AND status='Прийнято'", (event_id,))
    ranked = []
    for _, t in teams_scope.iterrows():
        score = compute_team_score(int(t["id"]))
        if score is not None:
            ranked.append((int(t["id"]), score))
    if not ranked:
        return None
    ranked.sort(key=lambda x: x[1], reverse=True)
    for i, (tid, _) in enumerate(ranked, start=1):
        if tid == team_id:
            return i, len(ranked)
    return None


def generate_team_certificate_pdf(team_id):
    """Формує PDF-сертифікат участі (або перемоги, якщо команда в топ-3) для команди."""
    if not PDF_LIB_AVAILABLE:
        return None
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib import colors
    from reportlab.lib.units import cm
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_CENTER

    team_row = query_one("""SELECT t.name, t.faculty, e.title, e.university, e.faculty, e.event_start
                             FROM teams t JOIN events e ON t.event_id=e.id WHERE t.id=?""", (team_id,))
    if not team_row:
        return None
    team_name, team_faculty, event_title, university, org_faculty, event_start = team_row

    members = query_df("""SELECT u.full_name FROM team_members tm JOIN users u ON tm.user_id=u.id
                           WHERE tm.team_id=?""", (team_id,))
    member_names = members["full_name"].tolist() if not members.empty else []

    rank_info = compute_team_rank(team_id)
    medal_labels = {1: "1 місце", 2: "2 місце", 3: "3 місце"}
    is_winner = rank_info is not None and rank_info[0] in (1, 2, 3)

    font_regular, font_bold = _register_pdf_fonts()
    use_translit = font_regular is None
    font_regular = font_regular or "Helvetica"
    font_bold = font_bold or "Helvetica-Bold"

    def T(text):
        return transliterate_ua(text) if use_translit else (text or "")

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), topMargin=2 * cm, bottomMargin=2 * cm,
                             leftMargin=2.5 * cm, rightMargin=2.5 * cm)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("CertTitle", parent=styles["Title"], fontName=font_bold,
                                  alignment=TA_CENTER, fontSize=30, textColor=colors.HexColor("#4F8BF9"))
    subtitle_style = ParagraphStyle("CertSubtitle", parent=styles["Normal"], fontName=font_regular,
                                     alignment=TA_CENTER, fontSize=12, spaceAfter=6)
    team_style = ParagraphStyle("CertTeam", parent=styles["Title"], fontName=font_bold,
                                 alignment=TA_CENTER, fontSize=22, spaceAfter=10)
    body_style = ParagraphStyle("CertBody", parent=styles["Normal"], fontName=font_regular,
                                 alignment=TA_CENTER, fontSize=13, spaceAfter=6)
    small_style = ParagraphStyle("CertSmall", parent=styles["Normal"], fontName=font_regular,
                                  alignment=TA_CENTER, fontSize=10, textColor=colors.grey)

    divider = Table([[""]], colWidths=[300], rowHeights=[3])
    divider.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#4F8BF9"))]))
    divider.hAlign = "CENTER"

    elements = [
        Spacer(1, 10),
        Paragraph(T(university), subtitle_style),
        Paragraph(T(org_faculty), subtitle_style),
        Spacer(1, 20),
        Paragraph(T("СЕРТИФІКАТ ПЕРЕМОЖЦЯ" if is_winner else "СЕРТИФІКАТ УЧАСНИКА"), title_style),
        Spacer(1, 8),
        divider,
        Spacer(1, 20),
        Paragraph(T("Видано команді"), body_style),
        Paragraph(T(team_name), team_style),
    ]
    if is_winner:
        medal_colors = {1: "#FFD700", 2: "#C0C0C0", 3: "#CD7F32"}
        medal_style = ParagraphStyle("CertMedal", parent=body_style, fontName=font_bold,
                                      textColor=colors.HexColor(medal_colors[rank_info[0]]), fontSize=15)
        elements.append(Paragraph(T(f"{medal_labels[rank_info[0]]} із {rank_info[1]} команд"), medal_style))
        elements.append(Spacer(1, 8))
    elements += [
        Paragraph(T(f"за участь у події «{event_title}»"), body_style),
        Spacer(1, 4),
        Paragraph(T(f"Факультет: {team_faculty or '—'}"), body_style),
    ]
    if member_names:
        elements.append(Spacer(1, 10))
        elements.append(Paragraph(T("Склад команди: " + ", ".join(member_names)), body_style))

    elements.append(Spacer(1, 30))
    sign_table = Table([[T("____________________________"), T("____________________________")],
                         [T("Голова організаційного комітету"), T(f"Дата: {event_start or now()[:10]}")]],
                        colWidths=[280, 280])
    sign_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), font_regular),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
    ]))
    elements.append(sign_table)
    elements.append(Spacer(1, 16))
    elements.append(Paragraph(T("CampusBridge — платформа студентських челенджів та хакатонів"), small_style))

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


def maybe_autoclose_registration(event_id):
    """Якщо кількість зареєстрованих команд досягла ліміту, автоматично закриває реєстрацію."""
    ev = query_one("SELECT max_teams, status FROM events WHERE id=?", (event_id,))
    if not ev:
        return False
    max_teams, status = ev
    if not max_teams or status != "Реєстрація відкрита":
        return False
    count = query_one("SELECT COUNT(*) FROM teams WHERE event_id=?", (event_id,))[0]
    if count >= max_teams:
        execute("UPDATE events SET status='Закрито' WHERE id=?", (event_id,))
        return True
    return False


# ------------------------------------------------------------
# Каскадне видалення: команда / подія
# ------------------------------------------------------------

def delete_team_cascade(team_id):
    """Остаточно видаляє команду разом з усіма пов'язаними даними: учасники, подачі, файли,
    оцінки, лайки, історія статусів, журнал email, питання до організаторів; звільняє слоти
    менторів і посилання оголошень."""
    subs = query_df("SELECT id FROM submissions WHERE team_id=?", (team_id,))
    for sid in subs["id"].tolist():
        execute("DELETE FROM files WHERE submission_id=?", (int(sid),))
    execute("DELETE FROM submissions WHERE team_id=?", (team_id,))
    execute("DELETE FROM scores WHERE team_id=?", (team_id,))
    execute("DELETE FROM team_members WHERE team_id=?", (team_id,))
    execute("DELETE FROM showcase_likes WHERE team_id=?", (team_id,))
    execute("DELETE FROM team_status_log WHERE team_id=?", (team_id,))
    execute("DELETE FROM email_log WHERE team_id=?", (team_id,))
    execute("DELETE FROM team_questions WHERE team_id=?", (team_id,))
    execute("UPDATE mentor_slots SET is_booked=0, team_id=NULL WHERE team_id=?", (team_id,))
    execute("UPDATE announcements SET target_team_id=NULL WHERE target_team_id=?", (team_id,))
    execute("DELETE FROM teams WHERE id=?", (team_id,))


def delete_event_cascade(event_id):
    """Остаточно видаляє подію разом з усіма її командами (каскадно) та іншими пов'язаними даними."""
    team_ids = query_df("SELECT id FROM teams WHERE event_id=?", (event_id,))["id"].tolist()
    for tid in team_ids:
        delete_team_cascade(int(tid))
    execute("DELETE FROM criteria WHERE event_id=?", (event_id,))
    execute("DELETE FROM nominations WHERE event_id=?", (event_id,))
    execute("DELETE FROM jury_assignments WHERE event_id=?", (event_id,))
    execute("DELETE FROM mentor_slots WHERE event_id=?", (event_id,))
    execute("DELETE FROM announcements WHERE event_id=?", (event_id,))
    execute("DELETE FROM events WHERE id=?", (event_id,))


# ------------------------------------------------------------
# Модерація заявок: унікальність учасників, історія статусів, email
# ------------------------------------------------------------

def get_user_team_for_event(user_id, event_id):
    """Повертає (team_id, team_name), якщо користувач уже в якійсь команді на цю подію, інакше None."""
    row = query_one("""SELECT t.id, t.name FROM team_members tm JOIN teams t ON tm.team_id = t.id
                        WHERE tm.user_id=? AND t.event_id=?""", (user_id, event_id))
    return row


def find_duplicate_participants(event_id):
    """Знаходить учасників, які одночасно записані у 2+ команди на цю саму подію."""
    df = query_df("""SELECT u.id AS user_id, u.full_name, u.email, t.id AS team_id, t.name AS team_name
                      FROM team_members tm
                      JOIN users u ON tm.user_id = u.id
                      JOIN teams t ON tm.team_id = t.id
                      WHERE t.event_id = ?
                      ORDER BY u.id""", (event_id,))
    if df.empty:
        return df
    dupes = df[df.duplicated(subset=["user_id"], keep=False)]
    return dupes


def log_status_change(team_id, old_status, new_status, comment):
    """Логує зміну статусу заявки команди: хто, коли, з якого статусу на який, з яким коментарем."""
    if old_status == new_status:
        return
    user = st.session_state.get("user") or {}
    execute("""INSERT INTO team_status_log (team_id,old_status,new_status,changed_by_id,changed_by_name,
               comment,changed_at) VALUES (?,?,?,?,?,?,?)""",
            (team_id, old_status, new_status, user.get("id"), user.get("full_name", "Система"), comment, now()))


def get_status_history(team_id):
    return query_df("""SELECT changed_at, old_status, new_status, changed_by_name, comment
                        FROM team_status_log WHERE team_id=? ORDER BY changed_at DESC""", (team_id,))


def get_smtp_config():
    """Читає налаштування SMTP із .streamlit/secrets.toml (секція [smtp]), якщо вони є."""
    try:
        if hasattr(st, "secrets") and "smtp" in st.secrets:
            return dict(st.secrets["smtp"])
    except Exception:
        pass
    return None


EMAIL_TEMPLATES_BY_STATUS = {
    "Прийнято": {
        "subject": "✅ Заявку команди «{team}» прийнято — {event}",
        "intro": "Вітаємо! Заявку вашої команди на подію «{event}» ПРИЙНЯТО.",
    },
    "Потребує доопрацювання": {
        "subject": "⚠️ Заявка команди «{team}» потребує доопрацювання — {event}",
        "intro": "Заявку вашої команди на подію «{event}» відправлено на доопрацювання.",
    },
}


def send_status_email(team_id, new_status, comment):
    """Надсилає (або симулює) email-сповіщення капітану команди при зміні статусу.
    Повертає 'sent' / 'simulated' / 'failed: ...' / None (якщо надсилання не потрібне)."""
    tmpl = EMAIL_TEMPLATES_BY_STATUS.get(new_status)
    if not tmpl:
        return None

    team = query_one("""SELECT t.name, t.captain_id, e.title FROM teams t
                         JOIN events e ON t.event_id = e.id WHERE t.id=?""", (team_id,))
    if not team:
        return None
    team_name, captain_id, event_title = team
    if not captain_id:
        return None  # команда без капітана (наприклад, імпортована вручну) — надсилати нікому

    captain = query_one("SELECT full_name, email, email_opt_in FROM users WHERE id=?", (captain_id,))
    if not captain or not captain[1]:
        return None
    captain_name, to_email, opt_in = captain
    if opt_in == 0:
        execute("""INSERT INTO email_log (team_id,to_email,subject,body,status,created_at)
                   VALUES (?,?,?,?,?,?)""",
                (team_id, to_email, tmpl["subject"].format(team=team_name, event=event_title),
                 "(лист не сформовано — отримувач вимкнув email-сповіщення у профілі)",
                 "skipped_opt_out", now()))
        return "skipped_opt_out"

    subject = tmpl["subject"].format(team=team_name, event=event_title)
    body_lines = [f"Вітаємо, {captain_name}!", "", tmpl["intro"].format(event=event_title)]
    if comment:
        body_lines += ["", f"Коментар організаторів: {comment}"]
    body_lines += ["", "Деталі можна переглянути в особистому кабінеті на платформі CampusBridge.",
                   "", f"— CampusBridge, {MAIN_UNIVERSITY}"]
    body = "\n".join(body_lines)

    status_result = "simulated"
    smtp_cfg = get_smtp_config()
    if smtp_cfg:
        try:
            msg = MIMEText(body, _charset="utf-8")
            msg["Subject"] = subject
            from_email = smtp_cfg.get("from_email") or smtp_cfg.get("username", "")
            msg["From"] = from_email
            msg["To"] = to_email
            host = smtp_cfg["host"]
            port = int(smtp_cfg.get("port", 587))
            use_tls = bool(smtp_cfg.get("use_tls", True))
            with smtplib.SMTP(host, port, timeout=10) as server:
                if use_tls:
                    server.starttls()
                if smtp_cfg.get("username"):
                    server.login(smtp_cfg["username"], smtp_cfg.get("password", ""))
                server.sendmail(from_email, [to_email], msg.as_string())
            status_result = "sent"
        except Exception as e:
            status_result = f"failed: {e}"

    execute("""INSERT INTO email_log (team_id,to_email,subject,body,status,created_at)
               VALUES (?,?,?,?,?,?)""", (team_id, to_email, subject, body, status_result, now()))
    return status_result


def apply_team_status_change(team_id, new_status, comment):
    """Єдина точка зміни статусу команди: оновлює запис, логує історію й надсилає email.
    Повертає (old_status, email_result)."""
    old_row = query_one("SELECT status FROM teams WHERE id=?", (team_id,))
    old_status = old_row[0] if old_row else None
    execute("UPDATE teams SET status=?, status_comment=? WHERE id=?", (new_status, comment, team_id))
    log_status_change(team_id, old_status, new_status, comment)
    email_result = None
    if old_status != new_status:
        email_result = send_status_email(team_id, new_status, comment)
    return old_status, email_result


def send_announcement_email(team_id, ann_title, ann_body):
    """Надсилає (або симулює) email-дублікат оголошення капітану команди.
    Повертає 'sent' / 'simulated' / 'failed: ...' / None (якщо надсилати нікому)."""
    team = query_one("""SELECT t.name, t.captain_id, e.title FROM teams t
                         JOIN events e ON t.event_id = e.id WHERE t.id=?""", (team_id,))
    if not team:
        return None
    team_name, captain_id, event_title = team
    if not captain_id:
        return None  # команда без капітана — надсилати нікому

    captain = query_one("SELECT full_name, email, email_opt_in FROM users WHERE id=?", (captain_id,))
    if not captain or not captain[1]:
        return None
    captain_name, to_email, opt_in = captain
    if opt_in == 0:
        execute("""INSERT INTO email_log (team_id,to_email,subject,body,status,created_at)
                   VALUES (?,?,?,?,?,?)""",
                (team_id, to_email, f"📢 {ann_title} — {event_title}",
                 "(лист не сформовано — отримувач вимкнув email-сповіщення у профілі)",
                 "skipped_opt_out", now()))
        return "skipped_opt_out"

    subject = f"📢 {ann_title} — {event_title}"
    body_lines = [f"Вітаємо, {captain_name}!", "", ann_body or "",
                  "", f"Команда: {team_name} · Подія: {event_title}",
                  "", "Це оголошення також опубліковано в особистому кабінеті на платформі CampusBridge.",
                  "", f"— CampusBridge, {MAIN_UNIVERSITY}"]
    body = "\n".join(body_lines)

    status_result = "simulated"
    smtp_cfg = get_smtp_config()
    if smtp_cfg:
        try:
            msg = MIMEText(body, _charset="utf-8")
            msg["Subject"] = subject
            from_email = smtp_cfg.get("from_email") or smtp_cfg.get("username", "")
            msg["From"] = from_email
            msg["To"] = to_email
            host = smtp_cfg["host"]
            port = int(smtp_cfg.get("port", 587))
            use_tls = bool(smtp_cfg.get("use_tls", True))
            with smtplib.SMTP(host, port, timeout=10) as server:
                if use_tls:
                    server.starttls()
                if smtp_cfg.get("username"):
                    server.login(smtp_cfg["username"], smtp_cfg.get("password", ""))
                server.sendmail(from_email, [to_email], msg.as_string())
            status_result = "sent"
        except Exception as e:
            status_result = f"failed: {e}"

    execute("""INSERT INTO email_log (team_id,to_email,subject,body,status,created_at)
               VALUES (?,?,?,?,?,?)""", (team_id, to_email, subject, body, status_result, now()))
    return status_result


def _deliver_generic_email(to_email, subject, body):
    """Спільна логіка надсилання (або симуляції) листа без прив'язки до команди. Повертає статус."""
    smtp_cfg = get_smtp_config()
    status_result = "simulated"
    if smtp_cfg:
        try:
            msg = MIMEText(body, _charset="utf-8")
            msg["Subject"] = subject
            from_email = smtp_cfg.get("from_email") or smtp_cfg.get("username", "")
            msg["From"] = from_email
            msg["To"] = to_email
            host = smtp_cfg["host"]
            port = int(smtp_cfg.get("port", 587))
            use_tls = bool(smtp_cfg.get("use_tls", True))
            with smtplib.SMTP(host, port, timeout=10) as server:
                if use_tls:
                    server.starttls()
                if smtp_cfg.get("username"):
                    server.login(smtp_cfg["username"], smtp_cfg.get("password", ""))
                server.sendmail(from_email, [to_email], msg.as_string())
            status_result = "sent"
        except Exception as e:
            status_result = f"failed: {e}"
    return status_result


def send_team_invite_email(team_id, to_email):
    """Надсилає (або симулює) запрошення приєднатися до команди за інвайт-кодом.
    Повертає 'sent' / 'simulated' / 'failed: ...' / None."""
    team = query_one("""SELECT t.name, t.invite_code, e.title FROM teams t
                         JOIN events e ON t.event_id = e.id WHERE t.id=?""", (team_id,))
    if not team:
        return None
    team_name, invite_code, event_title = team
    subject = f"Запрошення приєднатися до команди «{team_name}» — {event_title}"
    body = "\n".join([
        f"Вас запрошують приєднатися до команди «{team_name}» на подію «{event_title}» "
        "на платформі CampusBridge.", "",
        f"Інвайт-код команди: {invite_code}", "",
        "Увійдіть (або зареєструйтеся, якщо у вас ще немає акаунта) і скористайтесь опцією "
        "«Приєднатись за інвайт-кодом» у розділі «Моя команда».", "",
        f"— CampusBridge, {MAIN_UNIVERSITY}",
    ])
    status_result = _deliver_generic_email(to_email, subject, body)
    execute("""INSERT INTO email_log (team_id,to_email,subject,body,status,created_at)
               VALUES (?,?,?,?,?,?)""", (team_id, to_email, subject, body, status_result, now()))
    return status_result


def request_password_reset(username, email):
    """Якщо логін і пошта збігаються з обліковим записом, генерує й надсилає (або симулює)
    новий тимчасовий пароль. Завжди повертає generic-статус, щоб не розкривати існування акаунтів."""
    user = query_one("SELECT id, full_name, email FROM users WHERE username=? AND email=?",
                      (username.strip(), email.strip()))
    if not user:
        return "not_found"
    uid, full_name, to_email = user
    temp_pw = gen_code(10)
    execute("UPDATE users SET password=? WHERE id=?", (hash_pw(temp_pw), uid))
    subject = "🔑 Тимчасовий пароль для CampusBridge"
    body = "\n".join([
        f"Вітаємо, {full_name}!", "",
        f"Ваш тимчасовий пароль: {temp_pw}", "",
        "Увійдіть із цим паролем і одразу змініть його у розділі «👤 Профіль» → «🔑 Змінити пароль».", "",
        f"— CampusBridge, {MAIN_UNIVERSITY}",
    ])
    status_result = _deliver_generic_email(to_email, subject, body)
    execute("""INSERT INTO email_log (team_id,to_email,subject,body,status,created_at)
               VALUES (?,?,?,?,?,?)""", (None, to_email, subject, body, status_result, now()))
    return status_result


def get_email_log_for_event(event_id):
    return query_df("""SELECT el.created_at, t.name AS team, el.to_email, el.subject, el.status
                        FROM email_log el JOIN teams t ON el.team_id = t.id
                        WHERE t.event_id=? ORDER BY el.created_at DESC""", (event_id,))


# ------------------------------------------------------------
# Питання команд до організаторів (двосторонній зв'язок)
# ------------------------------------------------------------

def ask_team_question(team_id, question_text):
    user = st.session_state.get("user") or {}
    execute("""INSERT INTO team_questions (team_id,question,asked_by_id,asked_by_name,asked_at,
               answer,answered_by_name,answered_at) VALUES (?,?,?,?,?,?,?,?)""",
            (team_id, question_text, user.get("id"), user.get("full_name", "Учасник"), now(),
             None, None, None))


def answer_team_question(question_id, answer_text):
    user = st.session_state.get("user") or {}
    execute("UPDATE team_questions SET answer=?, answered_by_name=?, answered_at=? WHERE id=?",
            (answer_text, user.get("full_name", "Адміністратор"), now(), question_id))


def get_team_questions(team_id):
    return query_df("SELECT * FROM team_questions WHERE team_id=? ORDER BY asked_at DESC", (team_id,))


def get_unanswered_questions_count():
    return query_one("SELECT COUNT(*) FROM team_questions WHERE answer IS NULL")[0]


# ------------------------------------------------------------
# QR-код для швидкого приєднання до команди офлайн (наприклад, на реєстрації хакатону)
# ------------------------------------------------------------

def qr_code_url(data, size=180):
    """Публічний сервіс генерації QR-коду за URL-параметром — без потреби у сторонніх бібліотеках."""
    import urllib.parse
    return f"https://api.qrserver.com/v1/create-qr-code/?size={size}x{size}&data={urllib.parse.quote(data)}"


# ------------------------------------------------------------
# Лайки глядачів (Community Choice Award) для портфоліо
# ------------------------------------------------------------

def get_voter_key():
    """Повертає стабільний ідентифікатор голосуючого: користувача або анонімної сесії."""
    user = st.session_state.get("user")
    if user:
        return f"user:{user['id']}"
    if "_anon_voter_id" not in st.session_state:
        st.session_state["_anon_voter_id"] = f"anon:{uuid.uuid4()}"
    return st.session_state["_anon_voter_id"]


def has_liked(team_id):
    return query_one("SELECT id FROM showcase_likes WHERE team_id=? AND voter_key=?",
                      (team_id, get_voter_key())) is not None


def get_like_count(team_id):
    return query_one("SELECT COUNT(*) FROM showcase_likes WHERE team_id=?", (team_id,))[0]


def toggle_like(team_id):
    voter = get_voter_key()
    existing = query_one("SELECT id FROM showcase_likes WHERE team_id=? AND voter_key=?", (team_id, voter))
    if existing:
        execute("DELETE FROM showcase_likes WHERE id=?", (existing[0],))
        return False
    execute("INSERT INTO showcase_likes (team_id, voter_key, created_at) VALUES (?,?,?)", (team_id, voter, now()))
    return True


def parse_tags(tags_text):
    if not tags_text:
        return []
    return [t.strip() for t in str(tags_text).split(",") if t.strip()]


def render_pdf_inline(file_bytes, height=520):
    """Вбудовує PDF просто в інтерфейс через base64 iframe — без обов'язкового завантаження."""
    b64 = base64.b64encode(file_bytes).decode("utf-8")
    st.markdown(
        f'<iframe src="data:application/pdf;base64,{b64}" width="100%" height="{height}" '
        f'style="border:1px solid #444; border-radius:8px;"></iframe>',
        unsafe_allow_html=True,
    )


def get_latest_submission_with_file(team_id):
    """Повертає (submission_row_dict, file_row_dict_or_None) для останньої подачі команди."""
    sub = query_one("""SELECT id, repo_link, presentation_link, video_link, description, version, tags
                        FROM submissions WHERE team_id=? ORDER BY version DESC LIMIT 1""", (team_id,))
    if not sub:
        return None, None
    sub_dict = {"id": sub[0], "repo_link": sub[1], "presentation_link": sub[2], "video_link": sub[3],
                "description": sub[4], "version": sub[5], "tags": sub[6]}
    file_row = query_one("""SELECT id, filename, mimetype, data FROM files
                             WHERE submission_id=? ORDER BY uploaded_at DESC LIMIT 1""", (sub[0],))
    file_dict = None
    if file_row:
        file_dict = {"id": file_row[0], "filename": file_row[1], "mimetype": file_row[2], "data": file_row[3]}
    return sub_dict, file_dict


# ------------------------------------------------------------
# Медальні картки та аналітика для лідерборду
# ------------------------------------------------------------

MEDAL_STYLES = {
    0: {"gradient": "linear-gradient(135deg, #FFD700, #FFA500)", "emoji": "🥇", "label": "1 місце", "glow": "#FFD700"},
    1: {"gradient": "linear-gradient(135deg, #E8E8E8, #B8B8C0)", "emoji": "🥈", "label": "2 місце", "glow": "#C0C0C0"},
    2: {"gradient": "linear-gradient(135deg, #CD7F32, #A0522D)", "emoji": "🥉", "label": "3 місце", "glow": "#CD7F32"},
}


def inject_medal_css():
    st.markdown("""
        <style>
        @keyframes medalPulse {
            0%   { box-shadow: 0 0 0px 0px rgba(255,255,255,0.0); transform: translateY(0px); }
            50%  { box-shadow: 0 0 24px 4px var(--glow-color); transform: translateY(-3px); }
            100% { box-shadow: 0 0 0px 0px rgba(255,255,255,0.0); transform: translateY(0px); }
        }
        @keyframes medalPop {
            0%   { opacity: 0; transform: scale(0.85) translateY(10px); }
            100% { opacity: 1; transform: scale(1) translateY(0); }
        }
        .medal-card {
            border-radius: 16px;
            padding: 18px 20px;
            margin-bottom: 14px;
            color: #1a1a1a;
            animation: medalPop 0.5s ease-out, medalPulse 2.6s ease-in-out infinite;
            animation-delay: 0s, 0.5s;
        }
        .medal-card h3 { margin: 0 0 4px 0; font-size: 1.25rem; }
        .medal-card .medal-emoji { font-size: 1.8rem; margin-right: 8px; }
        .medal-card .medal-score { font-size: 1.6rem; font-weight: 800; float: right; }
        .medal-card .medal-sub { opacity: 0.75; font-size: 0.85rem; }
        </style>
    """, unsafe_allow_html=True)


def render_medal_card(rank_idx, team_name, faculty, score):
    style = MEDAL_STYLES[rank_idx]
    st.markdown(
        f"""<div class="medal-card" style="background:{style['gradient']}; --glow-color:{style['glow']};">
              <span class="medal-emoji">{style['emoji']}</span><b>{team_name}</b>
              <span class="medal-score">{score if score is not None else '—'}</span>
              <div class="medal-sub">{style['label']} · {faculty}</div>
            </div>""",
        unsafe_allow_html=True,
    )


def build_leaderboard_export(ev_id, ranked_rows, criteria_df):
    """Формує DataFrame для експорту повної аналітики лідерборду (CSV/Excel)."""
    rows = []
    for i, (t, score) in enumerate(ranked_rows):
        row = {"Місце": i + 1, "Команда": t["name"], "Факультет": t["faculty"]}
        for _, crit in criteria_df.iterrows():
            avg = query_one("SELECT AVG(score) FROM scores WHERE team_id=? AND criterion_id=?",
                             (t["id"], crit["id"]))
            row[f"{crit['name']} (з {int(crit['max_score'])})"] = round(avg[0], 2) if avg and avg[0] is not None else None
        row["Підсумковий бал"] = score
        rows.append(row)
    return pd.DataFrame(rows)


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


def refresh_session_user():
    """Перечитує дані користувача з БД у st.session_state після редагування профілю."""
    uid = st.session_state.user["id"]
    row = query_one("SELECT * FROM users WHERE id=?", (uid,))
    if row:
        cols = ["id", "username", "password", "role", "full_name", "email",
                "university", "faculty", "created_at", "email_opt_in"]
        st.session_state.user = dict(zip(cols, row))


ROLE_LABELS = {"admin": "Адміністратор", "participant": "Учасник", "jury": "Журі", "mentor": "Ментор"}


def _goto(menu_key, label):
    """Колбек для кнопок швидкої навігації: змінює вибір бічного меню.
    ВАЖЛИВО: це має виконуватись через on_click, а не напряму в тілі рендеру —
    Streamlit забороняє змінювати session_state ключа, для якого віджет із цим
    key вже був інстанційований у поточному прогоні скрипта (сайдбар-меню
    рендериться раніше за вміст сторінки, тож пряме присвоєння викликає
    StreamlitAPIException). Колбек виконується до повторного рендеру, тому
    конфлікту немає."""
    st.session_state[menu_key] = label


def page_my_profile():
    st.subheader("👤 Мій профіль")
    user = st.session_state.user

    with st.container(border=True):
        c1, c2 = st.columns(2)
        with c1:
            st.metric("Роль", ROLE_LABELS.get(user["role"], user["role"]))
            st.metric("Логін", user["username"])
        with c2:
            st.metric("У системі з", (user.get("created_at") or "—")[:10])
            if user["role"] == "participant":
                n_teams = query_one("SELECT COUNT(*) FROM team_members WHERE user_id=?", (user["id"],))[0]
                st.metric("Моїх команд", n_teams)
            elif user["role"] == "jury":
                n_assign = query_one("SELECT COUNT(*) FROM jury_assignments WHERE jury_id=?", (user["id"],))[0]
                n_scores = query_one("SELECT COUNT(*) FROM scores WHERE jury_id=?", (user["id"],))[0]
                st.metric("Призначень / оцінок", f"{n_assign} / {n_scores}")
            elif user["role"] == "mentor":
                n_slots = query_one("SELECT COUNT(*) FROM mentor_slots WHERE mentor_id=?", (user["id"],))[0]
                n_booked = query_one("SELECT COUNT(*) FROM mentor_slots WHERE mentor_id=? AND is_booked=1",
                                      (user["id"],))[0]
                st.metric("Слотів / заброньовано", f"{n_slots} / {n_booked}")
            elif user["role"] == "admin":
                n_events = query_one("SELECT COUNT(*) FROM events")[0]
                st.metric("Подій у системі", n_events)

    tab_edit, tab_password, tab_notify, tab_activity, tab_data = st.tabs(
        ["✏️ Редагувати дані", "🔑 Змінити пароль", "🔔 Сповіщення", "🕓 Моя активність", "📤 Мої дані"])

    # ================================================================
    # ✏️ РЕДАГУВАТИ ДАНІ
    # ================================================================
    with tab_edit:
        with st.form("edit_profile_form"):
            new_full_name = st.text_input("Повне ім'я", value=user.get("full_name") or "")
            new_email = st.text_input("Пошта", value=user.get("email") or "")
            faculty_label = "Факультет / кафедра" if user["role"] in ("participant", "jury", "admin") \
                else "Спеціалізація / компанія"
            new_faculty = st.text_input(faculty_label, value=user.get("faculty") or "")
            if st.form_submit_button("💾 Зберегти зміни"):
                if not new_full_name.strip():
                    st.error("Повне ім'я не може бути порожнім.")
                else:
                    execute("UPDATE users SET full_name=?, email=?, faculty=? WHERE id=?",
                            (new_full_name.strip(), new_email.strip(), new_faculty.strip(), user["id"]))
                    refresh_session_user()
                    st.success("Дані профілю оновлено.")
                    st.rerun()

    # ================================================================
    # 🔑 ЗМІНИТИ ПАРОЛЬ
    # ================================================================
    with tab_password:
        st.caption("Пароль зберігається у вигляді хешу — його не бачить у відкритому вигляді навіть адміністратор.")
        with st.form("change_password_form"):
            current_pw = st.text_input("Поточний пароль", type="password")
            new_pw1 = st.text_input("Новий пароль", type="password")
            new_pw2 = st.text_input("Повторіть новий пароль", type="password")
            if st.form_submit_button("🔑 Змінити пароль"):
                if not current_pw or not new_pw1:
                    st.error("Заповніть усі поля.")
                elif hash_pw(current_pw) != user.get("password"):
                    st.error("Поточний пароль вказано невірно.")
                elif new_pw1 != new_pw2:
                    st.error("Нові паролі не збігаються.")
                elif len(new_pw1) < 4:
                    st.error("Новий пароль має містити щонайменше 4 символи.")
                else:
                    execute("UPDATE users SET password=? WHERE id=?", (hash_pw(new_pw1), user["id"]))
                    refresh_session_user()
                    st.success("Пароль успішно змінено. Використовуйте його для наступного входу.")

    # ================================================================
    # 🔔 СПОВІЩЕННЯ
    # ================================================================
    with tab_notify:
        st.markdown("#### Email-сповіщення")
        current_opt_in = bool(user.get("email_opt_in", 1))
        if user["role"] == "participant":
            st.caption("Стосується листів про зміну статусу заявки вашої команди та email-дублікатів "
                       "оголошень організаторів (надсилаються капітану команди).")
        else:
            st.caption("Наразі автоматичні email-листи платформа надсилає лише капітанам команд-учасниць. "
                       "Якщо у вас є акаунт учасника, це налаштування стосуватиметься саме його.")
        new_opt_in = st.toggle("Надсилати мені email-сповіщення", value=current_opt_in, key="email_opt_toggle")
        if new_opt_in != current_opt_in:
            execute("UPDATE users SET email_opt_in=? WHERE id=?", (int(new_opt_in), user["id"]))
            refresh_session_user()
            st.success("Налаштування сповіщень оновлено.")
            st.rerun()

        if user["role"] == "participant":
            my_email_log = query_df("""SELECT el.created_at, e.title AS event, el.subject, el.status
                                        FROM email_log el
                                        JOIN teams t ON el.team_id = t.id
                                        JOIN events e ON t.event_id = e.id
                                        WHERE t.captain_id=?
                                        ORDER BY el.created_at DESC LIMIT 20""", (user["id"],))
            st.markdown("#### 📜 Останні листи, надіслані на вашу адресу")
            if my_email_log.empty:
                st.caption("Листів ще не надсилалося.")
            else:
                st.dataframe(my_email_log.rename(columns={"created_at": "Коли", "event": "Подія",
                                                            "subject": "Тема", "status": "Статус"}),
                             use_container_width=True, hide_index=True)

    # ================================================================
    # 🕓 МОЯ АКТИВНІСТЬ (рольова історія дій)
    # ================================================================
    with tab_activity:
        if user["role"] == "participant":
            st.markdown("#### 📦 Історія моїх подач проєкту")
            my_subs = query_df("""SELECT s.updated_at, t.name AS team, e.title AS event, s.version, s.description
                                   FROM submissions s
                                   JOIN teams t ON s.team_id = t.id
                                   JOIN team_members tm ON tm.team_id = t.id
                                   JOIN events e ON t.event_id = e.id
                                   WHERE tm.user_id=?
                                   ORDER BY s.updated_at DESC""", (user["id"],))
            if my_subs.empty:
                st.caption("Подач проєктів ще не було.")
            else:
                st.dataframe(my_subs.rename(columns={"updated_at": "Коли", "team": "Команда",
                                                       "event": "Подія", "version": "Версія",
                                                       "description": "Опис"}),
                             use_container_width=True, hide_index=True)

            st.markdown("#### 🗓️ Мої консультації з менторами")
            my_bookings = query_df("""SELECT ms.slot_date, ms.start_time, ms.end_time, u.full_name AS mentor,
                                              e.title AS event
                                       FROM mentor_slots ms
                                       JOIN team_members tm ON tm.team_id = ms.team_id
                                       JOIN users u ON ms.mentor_id = u.id
                                       JOIN events e ON ms.event_id = e.id
                                       WHERE tm.user_id=? AND ms.is_booked=1
                                       ORDER BY ms.slot_date DESC""", (user["id"],))
            if my_bookings.empty:
                st.caption("Записів на консультації ще не було.")
            else:
                st.dataframe(my_bookings.rename(columns={"slot_date": "Дата", "start_time": "Початок",
                                                           "end_time": "Кінець", "mentor": "Ментор",
                                                           "event": "Подія"}),
                             use_container_width=True, hide_index=True)

        elif user["role"] == "jury":
            st.markdown("#### ⭐ Останні виставлені оцінки")
            my_scores = query_df("""SELECT s.created_at, t.id AS team_id, t.name AS team, t.faculty,
                                            e.title AS event, e.double_blind, c.name AS criterion, s.score
                                     FROM scores s
                                     JOIN teams t ON s.team_id = t.id
                                     JOIN events e ON t.event_id = e.id
                                     JOIN criteria c ON s.criterion_id = c.id
                                     WHERE s.jury_id=?
                                     ORDER BY s.created_at DESC LIMIT 50""", (user["id"],))
            if my_scores.empty:
                st.caption("Оцінок ще не виставлено.")
            else:
                my_scores = my_scores.copy()
                my_scores["Команда"] = my_scores.apply(
                    lambda r: anon_code(r["team_id"]) if r["double_blind"] else r["team"], axis=1)
                st.dataframe(my_scores.rename(columns={"created_at": "Коли", "event": "Подія",
                                                         "criterion": "Критерій", "score": "Оцінка"})
                             [["Коли", "Подія", "Команда", "Критерій", "Оцінка"]],
                             use_container_width=True, hide_index=True)

        elif user["role"] == "mentor":
            st.markdown("#### 🗓️ Останні заброньовані консультації")
            my_bookings_m = query_df("""SELECT ms.slot_date, ms.start_time, ms.end_time, t.name AS team,
                                                e.title AS event
                                         FROM mentor_slots ms
                                         LEFT JOIN teams t ON ms.team_id = t.id
                                         JOIN events e ON ms.event_id = e.id
                                         WHERE ms.mentor_id=? AND ms.is_booked=1
                                         ORDER BY ms.slot_date DESC LIMIT 50""", (user["id"],))
            if my_bookings_m.empty:
                st.caption("Заброньованих консультацій ще не було.")
            else:
                st.dataframe(my_bookings_m.rename(columns={"slot_date": "Дата", "start_time": "Початок",
                                                             "end_time": "Кінець", "team": "Команда",
                                                             "event": "Подія"}),
                             use_container_width=True, hide_index=True)

        elif user["role"] == "admin":
            st.markdown("#### 🛠️ Події, створені мною")
            my_events = query_df("SELECT title, status, created_at FROM events WHERE created_by=? ORDER BY created_at DESC",
                                  (user["id"],))
            if my_events.empty:
                st.caption("Ви ще не створювали подій.")
            else:
                st.dataframe(my_events.rename(columns={"title": "Подія", "status": "Статус", "created_at": "Створено"}),
                             use_container_width=True, hide_index=True)

            st.markdown("#### 📢 Мої оголошення")
            my_anns = query_df("""SELECT created_at, title, COALESCE(priority,'Звичайне') AS priority
                                   FROM announcements WHERE created_by_name=? ORDER BY created_at DESC LIMIT 20""",
                                (user.get("full_name"),))
            if my_anns.empty:
                st.caption("Ви ще не публікували оголошень.")
            else:
                st.dataframe(my_anns.rename(columns={"created_at": "Коли", "title": "Заголовок",
                                                       "priority": "Пріоритет"}),
                             use_container_width=True, hide_index=True)

            st.markdown("#### 🔄 Останні зміни статусів заявок, які я вніс")
            my_status_changes = query_df("""SELECT changed_at, old_status, new_status, comment
                                             FROM team_status_log WHERE changed_by_id=?
                                             ORDER BY changed_at DESC LIMIT 20""", (user["id"],))
            if my_status_changes.empty:
                st.caption("Ви ще не змінювали статуси заявок.")
            else:
                st.dataframe(my_status_changes.rename(columns={"changed_at": "Коли", "old_status": "Було",
                                                                 "new_status": "Стало", "comment": "Коментар"}),
                             use_container_width=True, hide_index=True)

    # ================================================================
    # 📤 МОЇ ДАНІ (персональний експорт)
    # ================================================================
    with tab_data:
        st.caption("Завантажте копію ваших власних даних із платформи у форматі, зручному для збереження поза системою.")
        if st.button("📦 Сформувати мій персональний архів (Excel)"):
            profile_df = pd.DataFrame([{
                "Логін": user["username"], "ПІБ": user.get("full_name"), "Роль": ROLE_LABELS.get(user["role"], user["role"]),
                "Пошта": user.get("email"), "Факультет/спеціалізація": user.get("faculty"),
                "У системі з": user.get("created_at"),
            }])
            sheets = {"Профіль": profile_df}

            if user["role"] == "participant":
                sheets["Мої_команди"] = query_df("""SELECT t.name AS team, e.title AS event, t.status
                                                     FROM teams t JOIN team_members tm ON tm.team_id=t.id
                                                     JOIN events e ON t.event_id=e.id WHERE tm.user_id=?""",
                                                  (user["id"],))
                sheets["Мої_подачі"] = query_df("""SELECT s.updated_at, t.name AS team, s.version, s.description, s.tags
                                                    FROM submissions s JOIN team_members tm ON tm.team_id=s.team_id
                                                    WHERE tm.user_id=?""", (user["id"],))
                sheets["Мої_консультації"] = query_df("""SELECT ms.slot_date, ms.start_time, ms.end_time,
                                                                 u.full_name AS mentor
                                                          FROM mentor_slots ms
                                                          JOIN team_members tm ON tm.team_id = ms.team_id
                                                          JOIN users u ON ms.mentor_id = u.id
                                                          WHERE tm.user_id=? AND ms.is_booked=1""", (user["id"],))
            elif user["role"] == "jury":
                sheets["Мої_призначення"] = query_df("""SELECT e.title AS event, COALESCE(n.name,'вся подія') AS nomination
                                                         FROM jury_assignments ja JOIN events e ON ja.event_id=e.id
                                                         LEFT JOIN nominations n ON ja.nomination_id=n.id
                                                         WHERE ja.jury_id=?""", (user["id"],))
                sheets["Мої_оцінки"] = query_df("""SELECT s.created_at, e.title AS event, c.name AS criterion,
                                                           s.score, s.feedback
                                                    FROM scores s JOIN teams t ON s.team_id=t.id
                                                    JOIN events e ON t.event_id=e.id
                                                    JOIN criteria c ON s.criterion_id=c.id
                                                    WHERE s.jury_id=?""", (user["id"],))
            elif user["role"] == "mentor":
                sheets["Мої_слоти"] = query_df("""SELECT ms.slot_date, ms.start_time, ms.end_time, ms.location,
                                                          e.title AS event, COALESCE(t.name,'—') AS team
                                                   FROM mentor_slots ms JOIN events e ON ms.event_id=e.id
                                                   LEFT JOIN teams t ON ms.team_id=t.id
                                                   WHERE ms.mentor_id=?""", (user["id"],))
            elif user["role"] == "admin":
                sheets["Мої_події"] = query_df("SELECT title, status, created_at FROM events WHERE created_by=?",
                                                (user["id"],))

            data_bytes = _dfs_to_excel_bytes(sheets)
            st.download_button("⬇️ Завантажити мій_архів_campusbridge.xlsx", data_bytes,
                                file_name=f"my_campusbridge_data_{user['username']}.xlsx",
                                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


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
                    if ev.get("max_teams"):
                        st.metric("Команд подано", f"{teams_count} / {int(ev['max_teams'])}")
                        st.progress(min(teams_count / int(ev["max_teams"]), 1.0))
                        if ev["status"] == "Закрито":
                            st.caption("🔒 Реєстрацію закрито — ліміт команд вичерпано")
                    else:
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

    # --- фільтрація за номінаціями ---
    noms = query_df("SELECT id, name FROM nominations WHERE event_id=?", (ev_id,))
    if not noms.empty:
        nom_options = ["Усі номінації"] + noms["name"].tolist()
        nom_choice = st.selectbox("🏷️ Номінація", nom_options)
        if nom_choice != "Усі номінації":
            chosen_nom_id = int(noms[noms["name"] == nom_choice]["id"].iloc[0])
            teams = teams[teams["nomination_id"] == chosen_nom_id]

    if teams.empty:
        st.info("У цій номінації прийнятих команд поки немає.")
        return

    criteria = query_df("SELECT * FROM criteria WHERE event_id=? ORDER BY id", (ev_id,))

    ranked = []
    for _, t in teams.iterrows():
        score = compute_team_score(t["id"])
        ranked.append((t, score if score is not None else -1, score))
    ranked.sort(key=lambda x: x[1], reverse=True)
    ranked = [(t, score) for t, _, score in ranked]  # (team_row, score)

    # --- анімовані картки призерів (топ-3) ---
    inject_medal_css()
    st.markdown("#### 🏅 Призери")
    podium = ranked[:3]
    podium_cols = st.columns(len(podium)) if podium else []
    for i, (t, score) in enumerate(podium):
        with podium_cols[i]:
            render_medal_card(i, t["name"], t["faculty"], score)

    # --- повна таблиця ---
    st.markdown("#### 📋 Повна таблиця результатів")
    medals = ["🥇", "🥈", "🥉"]
    board_rows = []
    for i, (t, score) in enumerate(ranked):
        place = medals[i] if i < 3 and score is not None else str(i + 1)
        board_rows.append({"Місце": place, "Команда": t["name"], "Факультет": t["faculty"],
                            "Бал": score if score is not None else "—"})
    board_df = pd.DataFrame(board_rows)
    st.dataframe(board_df, use_container_width=True, hide_index=True)

    # --- експорт повної аналітики ---
    st.markdown("#### 📊 Експорт аналітики")
    export_df = build_leaderboard_export(ev_id, ranked, criteria)
    ce1, ce2 = st.columns(2)
    with ce1:
        csv_buf = io.StringIO()
        export_df.to_csv(csv_buf, index=False)
        st.download_button("⬇️ Завантажити аналітику (CSV)", csv_buf.getvalue(),
                            file_name=f"leaderboard_{ev_id}.csv", mime="text/csv")
    with ce2:
        xlsx_buf = io.BytesIO()
        with pd.ExcelWriter(xlsx_buf, engine="openpyxl") as writer:
            export_df.to_excel(writer, index=False, sheet_name="Leaderboard")
        st.download_button("⬇️ Завантажити аналітику (Excel)", xlsx_buf.getvalue(),
                            file_name=f"leaderboard_{ev_id}.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

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

    # --- інтерактивні графіки розподілу балів ---
    if not criteria.empty:
        st.markdown("#### 📈 Інтерактивна аналітика балів")
        tab_totals, tab_criteria, tab_dist = st.tabs(
            ["Підсумкові бали команд", "Розподіл за критеріями", "Гістограма оцінок"])

        with tab_totals:
            chart_df = pd.DataFrame([{"Команда": t["name"], "Бал": score if score is not None else 0}
                                      for t, score in ranked])
            chart = alt.Chart(chart_df).mark_bar(cornerRadiusTopLeft=6, cornerRadiusTopRight=6).encode(
                x=alt.X("Команда:N", sort="-y"),
                y=alt.Y("Бал:Q"),
                color=alt.Color("Бал:Q", scale=alt.Scale(scheme="goldgreen"), legend=None),
                tooltip=["Команда", "Бал"],
            ).properties(height=320)
            st.altair_chart(chart, use_container_width=True)

        with tab_criteria:
            rows = []
            for t, score in ranked:
                for _, crit in criteria.iterrows():
                    avg = query_one("SELECT AVG(score) FROM scores WHERE team_id=? AND criterion_id=?",
                                     (t["id"], crit["id"]))
                    if avg and avg[0] is not None:
                        rows.append({"Команда": t["name"], "Критерій": crit["name"], "Середній бал": round(avg[0], 2)})
            if rows:
                crit_df = pd.DataFrame(rows)
                chart2 = alt.Chart(crit_df).mark_bar().encode(
                    x=alt.X("Команда:N"),
                    y=alt.Y("Середній бал:Q"),
                    color=alt.Color("Критерій:N"),
                    xOffset="Критерій:N",
                    tooltip=["Команда", "Критерій", "Середній бал"],
                ).properties(height=340)
                st.altair_chart(chart2, use_container_width=True)
            else:
                st.info("Ще немає оцінок для побудови графіка.")

        with tab_dist:
            all_scores = query_df("""SELECT s.score, c.name AS criterion FROM scores s
                                      JOIN criteria c ON s.criterion_id=c.id
                                      JOIN teams t ON s.team_id=t.id WHERE t.event_id=?""", (ev_id,))
            if not all_scores.empty:
                hist = alt.Chart(all_scores).mark_bar().encode(
                    x=alt.X("score:Q", bin=alt.Bin(maxbins=15), title="Оцінка"),
                    y=alt.Y("count():Q", title="Кількість оцінок"),
                    color=alt.Color("criterion:N", title="Критерій"),
                    tooltip=["criterion", "count()"],
                ).properties(height=320)
                st.altair_chart(hist, use_container_width=True)
            else:
                st.info("Ще немає індивідуальних оцінок журі для побудови гістограми.")

    # --- порівняння команд між собою ---
    if len(ranked) >= 2:
        st.markdown("#### ⚖️ Порівняння команд")
        team_names = [t["name"] for t, _ in ranked]
        chosen = st.multiselect("Оберіть 2-4 команди для порівняння", team_names,
                                 default=team_names[:min(2, len(team_names))])
        if len(chosen) >= 2:
            if len(chosen) > 4:
                st.warning("Для наочності оберіть не більше 4 команд.")
            else:
                chosen_teams = [t for t, _ in ranked if t["name"] in chosen]
                comp_rows = []
                for _, crit in criteria.iterrows():
                    row = {"Критерій": f"{crit['name']} (вага {int(crit['weight'])}%)"}
                    for t in chosen_teams:
                        avg = query_one("SELECT AVG(score) FROM scores WHERE team_id=? AND criterion_id=?",
                                         (t["id"], crit["id"]))
                        row[t["name"]] = round(avg[0], 2) if avg and avg[0] is not None else "—"
                    comp_rows.append(row)
                total_row = {"Критерій": "Підсумковий зважений бал"}
                for t in chosen_teams:
                    total_row[t["name"]] = compute_team_score(t["id"]) or "—"
                comp_rows.append(total_row)
                st.dataframe(pd.DataFrame(comp_rows), use_container_width=True, hide_index=True)
        elif len(chosen) == 1:
            st.caption("Оберіть щонайменше 2 команди для порівняння.")

    st.markdown("#### Портфоліо та деталізація оцінок команд")
    for i, (t, score) in enumerate(ranked):
        place_label = f"{medals[i]} " if i < 3 and score is not None else ""
        with st.expander(f"{place_label}{t['name']} ({t['faculty']}) — {score if score is not None else '—'} балів"):
            tab_portfolio, tab_breakdown, tab_cert = st.tabs(
                ["📦 Портфоліо проєкту", "🔍 Деталізація балу", "🎓 Сертифікат"])
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
            with tab_cert:
                if not PDF_LIB_AVAILABLE:
                    st.caption("Для генерації сертифіката на сервері потрібен пакет `reportlab`.")
                else:
                    cert_bytes = generate_team_certificate_pdf(int(t["id"]))
                    if cert_bytes:
                        st.download_button(
                            "🎓 Завантажити сертифікат (PDF)", data=cert_bytes,
                            file_name=f"certificate_{t['name'][:30].replace(' ', '_')}.pdf",
                            mime="application/pdf", key=f"cert_dl_{t['id']}")
                    else:
                        st.caption("Не вдалося сформувати сертифікат для цієї команди.")


# ============================================================
# ЛОГІН / РЕЄСТРАЦІЯ
# ============================================================

@st.dialog("Деталі проєкту", width="large")
def show_project_detail_dialog(team_id, team_name, event_title, faculty, score):
    sub, file_row = get_latest_submission_with_file(team_id)
    st.markdown(f"### {team_name}")
    st.caption(f"{event_title} · {faculty}" + (f" · ⭐ {score} балів" if score is not None else ""))
    if sub:
        tags = parse_tags(sub.get("tags"))
        if tags:
            st.markdown(" ".join(f"`{tag}`" for tag in tags))
        if sub.get("description"):
            st.write(sub["description"])
        if sub.get("video_link"):
            st.video(youtube_embed_url(sub["video_link"]))
        if sub.get("repo_link"):
            st.markdown(f"🔗 [Репозиторій проєкту]({sub['repo_link']})")
        if file_row:
            st.markdown("**📄 Презентація**")
            render_pdf_inline(file_row["data"], height=600)
            st.download_button("⬇️ Завантажити презентацію", data=file_row["data"],
                                file_name=file_row["filename"], mime=file_row["mimetype"] or "application/pdf",
                                key=f"dialog_dl_{team_id}")
    else:
        st.info("Подача ще не завантажена.")

    st.markdown("---")
    liked = has_liked(team_id)
    like_count = get_like_count(team_id)
    label = f"💔 Прибрати лайк ({like_count})" if liked else f"❤️ Подобається ({like_count})"
    if st.button(label, key=f"dialog_like_{team_id}"):
        toggle_like(team_id)
        st.rerun()


def page_showcase():
    st.subheader("🖼️ Портфоліо проєктів (Showcase)")
    st.caption("Галерея студентських проєктів: пошук за технологіями, лайки глядачів (Community Choice Award), "
               "перегляд презентацій прямо в інтерфейсі — без обов'язкового завантаження.")

    only_archived = st.checkbox("Показувати лише завершені події (архів)", value=True)
    events = get_events("Архів") if only_archived else get_events()
    if events.empty:
        st.info("Завершених подій ще немає. Зніміть позначку вище, щоб побачити проєкти поточних подій.")
        return

    # зібрати всі картки одним списком для єдиної галереї
    items = []
    for _, ev in events.iterrows():
        teams = query_df("SELECT * FROM teams WHERE event_id=? AND status='Прийнято'", (ev["id"],))
        for _, t in teams.iterrows():
            sub, file_row = get_latest_submission_with_file(int(t["id"]))
            if not sub:
                continue
            items.append({"team": t, "event": ev, "sub": sub, "file": file_row,
                          "score": compute_team_score(int(t["id"])), "likes": get_like_count(int(t["id"]))})

    if not items:
        st.info("Проєктів для показу ще немає.")
        return

    all_tags = sorted({tag for it in items for tag in parse_tags(it["sub"].get("tags"))})

    f1, f2, f3 = st.columns([2, 2, 1])
    with f1:
        search_q = st.text_input("🔎 Пошук за назвою, описом або технологією")
    with f2:
        tag_filter = st.multiselect("Фільтр за тегами", all_tags) if all_tags else []
    with f3:
        sort_choice = st.selectbox("Сортувати", ["За балом", "За лайками", "За назвою"])

    filtered = []
    for it in items:
        blob = f"{it['team']['name']} {it['sub'].get('description') or ''} {it['sub'].get('tags') or ''}".lower()
        if search_q.strip() and search_q.strip().lower() not in blob:
            continue
        if tag_filter:
            item_tags = parse_tags(it["sub"].get("tags"))
            if not any(tag in item_tags for tag in tag_filter):
                continue
        filtered.append(it)

    if not filtered:
        st.info("За обраними фільтрами проєктів не знайдено.")
        return

    if sort_choice == "За балом":
        filtered.sort(key=lambda x: x["score"] if x["score"] is not None else -1, reverse=True)
    elif sort_choice == "За лайками":
        filtered.sort(key=lambda x: x["likes"], reverse=True)
    else:
        filtered.sort(key=lambda x: x["team"]["name"])

    max_likes = max((it["likes"] for it in filtered), default=0)
    community_choice_team_id = None
    if max_likes > 0:
        community_choice_team_id = next(it["team"]["id"] for it in filtered if it["likes"] == max_likes)

    best_score_per_event = {}
    for it in items:
        eid = it["event"]["id"]
        if it["score"] is not None and (eid not in best_score_per_event or it["score"] > best_score_per_event[eid]):
            best_score_per_event[eid] = it["score"]

    st.caption(f"Знайдено проєктів: {len(filtered)}")

    cols_per_row = 3
    cols = st.columns(cols_per_row)
    for idx, it in enumerate(filtered):
        t, ev, sub, file_row = it["team"], it["event"], it["sub"], it["file"]
        score, likes = it["score"], it["likes"]
        with cols[idx % cols_per_row]:
            with st.container(border=True):
                badges = ""
                if score is not None and best_score_per_event.get(ev["id"]) == score:
                    badges += " 🏆"
                if community_choice_team_id == t["id"]:
                    badges += " ❤️"
                st.markdown(f"**{t['name']}**{badges}")
                st.caption(f"{ev['title']} · {t['faculty']}" + (f" · ⭐ {score}" if score is not None else ""))

                tags = parse_tags(sub.get("tags"))
                if tags:
                    st.markdown(" ".join(f"`{tag}`" for tag in tags[:6]))

                if sub.get("description"):
                    preview = sub["description"][:140] + ("…" if len(sub["description"]) > 140 else "")
                    st.write(preview)

                like_col, detail_col = st.columns(2)
                with like_col:
                    liked = has_liked(t["id"])
                    like_label = f"💔 {likes}" if liked else f"❤️ {likes}"
                    if st.button(like_label, key=f"like_{t['id']}",
                                 help="Проголосувати за проєкт (Community Choice Award)"):
                        toggle_like(t["id"])
                        st.rerun()
                with detail_col:
                    if st.button("🔍 Детальніше", key=f"detail_{t['id']}"):
                        show_project_detail_dialog(int(t["id"]), t["name"], ev["title"], t["faculty"], score)

                if sub.get("repo_link"):
                    st.markdown(f"🔗 [Репозиторій]({sub['repo_link']})")
                if sub.get("video_link"):
                    with st.expander("🎬 Демо-відео"):
                        st.video(youtube_embed_url(sub["video_link"]))
                if file_row:
                    with st.expander("👁️ Переглянути презентацію"):
                        render_pdf_inline(file_row["data"], height=420)
                        st.download_button("⬇️ Завантажити", data=file_row["data"], file_name=file_row["filename"],
                                            mime=file_row["mimetype"] or "application/pdf",
                                            key=f"dl_{t['id']}")


def page_login():
    tab1, tab2, tab3 = st.tabs(["Вхід", "Реєстрація учасника", "🔑 Забули пароль?"])
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

    with tab3:
        st.caption("Введіть логін і пошту, вказані під час реєстрації. Якщо вони збігаються з існуючим "
                   "обліковим записом, ми одразу згенеруємо новий тимчасовий пароль і надішлемо його на "
                   "вказану пошту (або зафіксуємо в журналі email, якщо адміністратор ще не налаштував SMTP).")
        with st.form("forgot_pw_form"):
            fp_username = st.text_input("Логін")
            fp_email = st.text_input("Пошта, вказана в акаунті")
            if st.form_submit_button("Скинути пароль"):
                if not fp_username.strip() or not fp_email.strip():
                    st.error("Заповніть обидва поля.")
                else:
                    request_password_reset(fp_username, fp_email)
                    # навмисно однакове повідомлення незалежно від результату —
                    # щоб не розкривати стороннім, які логіни/пошти існують у системі
                    st.success("Якщо в системі є обліковий запис із такими логіном і поштою, ми щойно "
                               "скинули пароль і надіслали новий на вказану адресу. Немає листа? "
                               "Перевірте правильність даних або зверніться до адміністратора.")


# ============================================================
# АДМІНІСТРАТОР
# ============================================================

def admin_event_builder():
    st.subheader("🛠️ Конструктор подій")

    with st.expander("🧩 Створити на основі шаблону"):
        st.caption("Оберіть шаблон — форма нижче заповниться типовими налаштуваннями "
                   "(категорія, тривалість, критерії, номінації, ліміт команд). "
                   "Будь-яке поле можна змінити перед збереженням.")
        tmpl_name = st.selectbox("Шаблон події", ["— без шаблону —"] + list(EVENT_TEMPLATES.keys()))
        if st.button("Застосувати шаблон до нової події") and tmpl_name != "— без шаблону —":
            st.session_state["_event_template"] = EVENT_TEMPLATES[tmpl_name]
            st.session_state["_event_template_name"] = tmpl_name
            st.success(f"Шаблон «{tmpl_name}» застосовано до форми нижче. "
                       "Заповніть назву та дати, перевірте поля й натисніть «Зберегти подію».")
            st.rerun()

    events = get_events()
    options = ["➕ Створити нову подію"] + [
        f"{(row['title'] if row['title'] else '(без назви)')} (#{row['id']})"
        for _, row in events.iterrows()
    ]
    choice = st.selectbox("Подія", options)

    editing_id = None
    active_template = None
    if choice != "➕ Створити нову подію":
        editing_id = int(choice.split("#")[-1].rstrip(")"))
        ev = query_one("SELECT * FROM events WHERE id=?", (editing_id,))
        cols = ["id","title","category","format","description","regulations","reg_start","reg_end",
                "event_start","pitch_deadline","min_team","max_team","prize_fund","status",
                "leaderboard_live","avoid_conflict","university","faculty","created_by","created_at",
                "double_blind","banner_url","video_url","max_teams","jury_see_other_scores"]
        ev = dict(zip(cols, ev))
    else:
        ev = {c: "" for c in ["title","category","format","description","regulations",
                               "prize_fund","banner_url","video_url"]}
        ev.update({"status": "Чернетка", "min_team": 2, "max_team": 5,
                   "leaderboard_live": 0, "avoid_conflict": 1, "double_blind": 0,
                   "jury_see_other_scores": 0, "max_teams": None,
                   "university": MAIN_UNIVERSITY, "faculty": MAIN_FACULTY})
        active_template = st.session_state.get("_event_template")
        if active_template:
            st.info(f"📋 Активний шаблон: **{st.session_state.get('_event_template_name')}** "
                    "(поля нижче заповнено автоматично)")
            ev.update({k: v for k, v in active_template.items() if k not in ("nominations", "criteria")})

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

        st.markdown("**Ліміти та автоматичне закриття реєстрації**")
        l1, l2 = st.columns(2)
        with l1:
            max_teams_val = ev.get("max_teams")
            max_teams_enabled = st.checkbox("Обмежити максимальну кількість команд-учасниць",
                                             value=bool(max_teams_val))
        with l2:
            max_teams = st.number_input("Максимум команд на подію", min_value=1, max_value=1000,
                                         value=int(max_teams_val) if max_teams_val else 20,
                                         disabled=not max_teams_enabled)
        if editing_id:
            current_count = query_one("SELECT COUNT(*) FROM teams WHERE event_id=?", (editing_id,))[0]
            if max_teams_enabled:
                st.caption(f"Зареєстровано зараз: {current_count} / {max_teams} команд. "
                           "Коли ліміт буде вичерпано, статус події автоматично зміниться на «Закрито».")
        st.caption("Якщо галочку знято — кількість команд необмежена.")

        c3, c4 = st.columns(2)
        with c3:
            leaderboard_live = st.checkbox("Транслювати лідерборд у реальному часі", value=bool(ev.get("leaderboard_live")))
        with c4:
            avoid_conflict = st.checkbox("Забороняти журі оцінювати команди свого факультету (конфлікт інтересів)",
                                          value=bool(ev.get("avoid_conflict", 1)))

        st.markdown("**Налаштування журі**")
        j1, j2 = st.columns(2)
        with j1:
            double_blind = st.checkbox(
                "🕶️ Сліпе оцінювання (double-blind): журі не бачить назву команди та факультет",
                value=bool(ev.get("double_blind", 0)),
                help="Команди відображатимуться журі під анонімним кодом (наприклад, «Команда №A1B2»). "
                     "Захист від конфлікту інтересів за факультетом продовжує діяти автоматично.")
        with j2:
            jury_see_other_scores = st.checkbox(
                "👀 Журі бачать оцінки та фідбек одне одного під час оцінювання",
                value=bool(ev.get("jury_see_other_scores", 0)),
                help="Якщо увімкнено — кожен експерт бачить бали й коментарі колег по цій же команді "
                     "(прозорий процес). Якщо вимкнено — кожен журі оцінює незалежно, не бачачи чужих оцінок.")

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
                final_max_teams = int(max_teams) if max_teams_enabled else None
                if editing_id:
                    execute("""UPDATE events SET title=?, category=?, format=?, description=?, regulations=?,
                               reg_start=?, reg_end=?, event_start=?, pitch_deadline=?, min_team=?, max_team=?,
                               prize_fund=?, status=?, leaderboard_live=?, avoid_conflict=?, double_blind=?,
                               banner_url=?, video_url=?, max_teams=?, jury_see_other_scores=? WHERE id=?""",
                            (title, category, fmt, description, regulations, reg_start, reg_end, event_start,
                             pitch_deadline, min_team, max_team, prize, status, int(leaderboard_live),
                             int(avoid_conflict), int(double_blind), banner_url, video_url, final_max_teams,
                             int(jury_see_other_scores), editing_id))
                    maybe_autoclose_registration(editing_id)
                    st.success("Подію оновлено.")
                else:
                    new_id = execute("""INSERT INTO events (title,category,format,description,regulations,
                                        reg_start,reg_end,event_start,pitch_deadline,min_team,max_team,prize_fund,
                                        status,leaderboard_live,avoid_conflict,university,faculty,created_by,created_at,
                                        double_blind,banner_url,video_url,max_teams,jury_see_other_scores)
                                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                                     (title, category, fmt, description, regulations, reg_start, reg_end,
                                      event_start, pitch_deadline, min_team, max_team, prize, status,
                                      int(leaderboard_live), int(avoid_conflict), MAIN_UNIVERSITY, MAIN_FACULTY,
                                      st.session_state.user["id"], now(), int(double_blind), banner_url, video_url,
                                      final_max_teams, int(jury_see_other_scores)))
                    if active_template:
                        for nom in active_template.get("nominations", []):
                            execute("INSERT INTO nominations (event_id, name) VALUES (?,?)", (new_id, nom))
                        for cname, cw, cmax in active_template.get("criteria", []):
                            execute("INSERT INTO criteria (event_id,name,weight,max_score) VALUES (?,?,?,?)",
                                    (new_id, cname, cw, cmax))
                        st.session_state.pop("_event_template", None)
                        st.session_state.pop("_event_template_name", None)
                    st.success(f"Подію створено (ID {new_id}).")
                st.rerun()

    if editing_id:
        st.markdown("---")
        st.markdown("#### Номінації")
        noms = query_df("SELECT * FROM nominations WHERE event_id=?", (editing_id,))
        if noms.empty:
            st.caption("Номінацій ще немає.")
        else:
            for _, nom in noms.iterrows():
                nc1, nc2, nc3 = st.columns([4, 1, 1])
                with nc1:
                    new_nom_name = st.text_input("Назва номінації", value=nom["name"],
                                                  key=f"nom_name_{nom['id']}", label_visibility="collapsed")
                with nc2:
                    if st.button("💾", key=f"nom_save_{nom['id']}", help="Зберегти нову назву"):
                        execute("UPDATE nominations SET name=? WHERE id=?", (new_nom_name, int(nom["id"])))
                        st.rerun()
                with nc3:
                    if st.button("🗑️", key=f"nom_del_{nom['id']}", help="Видалити номінацію"):
                        n_teams_nom = query_one("SELECT COUNT(*) FROM teams WHERE nomination_id=?",
                                                 (int(nom["id"]),))[0]
                        if n_teams_nom:
                            st.warning(f"У номінації «{nom['name']}» є {n_teams_nom} команд(и) — спочатку "
                                       "перенесіть їх в іншу номінацію (у розділі «Модерація заявок») "
                                       "або видаліть ці команди.")
                        else:
                            execute("DELETE FROM nominations WHERE id=?", (int(nom["id"]),))
                            st.rerun()
        with st.form("nom_form"):
            nom_name = st.text_input("Нова номінація (наприклад, AI-трек, Бізнес-трек)")
            if st.form_submit_button("➕ Додати номінацію") and nom_name:
                execute("INSERT INTO nominations (event_id, name) VALUES (?,?)", (editing_id, nom_name))
                st.rerun()

        st.markdown("#### Критерії оцінювання")
        crit = query_df("SELECT * FROM criteria WHERE event_id=?", (editing_id,))
        if crit.empty:
            st.caption("Критеріїв ще немає.")
        else:
            for _, cr in crit.iterrows():
                cr1, cr2, cr3, cr4 = st.columns([3, 1, 1, 1])
                with cr1:
                    new_cname = st.text_input("Назва", value=cr["name"], key=f"crit_name_{cr['id']}",
                                               label_visibility="collapsed")
                with cr2:
                    new_cweight = st.number_input("Вага %", min_value=1, max_value=100, value=int(cr["weight"]),
                                                   key=f"crit_w_{cr['id']}", label_visibility="collapsed")
                with cr3:
                    new_cmax = st.number_input("Макс.", min_value=1, max_value=100, value=int(cr["max_score"]),
                                                key=f"crit_m_{cr['id']}", label_visibility="collapsed")
                with cr4:
                    bc1, bc2 = st.columns(2)
                    with bc1:
                        if st.button("💾", key=f"crit_save_{cr['id']}", help="Зберегти зміни"):
                            execute("UPDATE criteria SET name=?, weight=?, max_score=? WHERE id=?",
                                    (new_cname, new_cweight, new_cmax, int(cr["id"])))
                            st.rerun()
                    with bc2:
                        n_scores_crit = query_one("SELECT COUNT(*) FROM scores WHERE criterion_id=?",
                                                   (int(cr["id"]),))[0]
                        if st.button("🗑️", key=f"crit_del_{cr['id']}",
                                     help="Видалити критерій" + (f" (разом із {n_scores_crit} оцінками)"
                                                                  if n_scores_crit else "")):
                            st.session_state[f"confirm_crit_del_{cr['id']}"] = True
                if st.session_state.get(f"confirm_crit_del_{cr['id']}"):
                    n_scores_crit = query_one("SELECT COUNT(*) FROM scores WHERE criterion_id=?",
                                               (int(cr["id"]),))[0]
                    with st.container(border=True):
                        if n_scores_crit:
                            st.warning(f"⚠️ За критерієм «{cr['name']}» вже є {n_scores_crit} виставлених оцінок. "
                                       "Видалення критерію безповоротно видалить і їх.")
                        else:
                            st.warning(f"Видалити критерій «{cr['name']}»?")
                        bcc1, bcc2 = st.columns(2)
                        with bcc1:
                            if st.button("Так, видалити остаточно", key=f"crit_del_confirm_{cr['id']}"):
                                execute("DELETE FROM scores WHERE criterion_id=?", (int(cr["id"]),))
                                execute("DELETE FROM criteria WHERE id=?", (int(cr["id"]),))
                                st.session_state.pop(f"confirm_crit_del_{cr['id']}", None)
                                st.rerun()
                        with bcc2:
                            if st.button("Скасувати", key=f"crit_del_cancel_{cr['id']}"):
                                st.session_state.pop(f"confirm_crit_del_{cr['id']}", None)
                                st.rerun()
        with st.form("crit_form"):
            cc1, cc2, cc3 = st.columns(3)
            with cc1:
                cname = st.text_input("Назва критерію (наприклад, Інноваційність)")
            with cc2:
                cweight = st.number_input("Вага, %", min_value=1, max_value=100, value=25)
            with cc3:
                cmax = st.number_input("Макс. бал", min_value=1, max_value=100, value=10)
            if st.form_submit_button("➕ Додати критерій") and cname:
                execute("INSERT INTO criteria (event_id,name,weight,max_score) VALUES (?,?,?,?)",
                        (editing_id, cname, cweight, cmax))
                st.rerun()

        st.markdown("---")
        with st.expander("⚠️ Небезпечна зона: видалити подію остаточно"):
            st.error("Ця дія назавжди видалить подію разом з усіма її командами, учасниками, поданими "
                     "проєктами, файлами презентацій, оцінками журі, критеріями, номінаціями, "
                     "призначеннями журі, слотами консультацій та оголошеннями цієї події. "
                     "Скасувати цю дію неможливо.")
            confirm_ev_name = st.text_input("Для підтвердження введіть точну назву події",
                                             key=f"del_ev_confirm_{editing_id}")
            if st.button("🗑️ Видалити подію остаточно", key=f"del_ev_btn_{editing_id}", type="primary"):
                if confirm_ev_name.strip() == (ev.get("title") or "").strip():
                    delete_event_cascade(editing_id)
                    st.session_state.pop("_event_template", None)
                    st.session_state.pop("_event_template_name", None)
                    st.success("Подію остаточно видалено.")
                    st.rerun()
                else:
                    st.error("Введена назва не збігається з назвою події — видалення скасовано.")


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

    # --- перевірка унікальності та складу: дублювання учасників між командами ---
    dupes = find_duplicate_participants(ev_id)
    if not dupes.empty:
        with st.container(border=True):
            st.error(f"⚠️ Виявлено {dupes['user_id'].nunique()} учасник(ів), зареєстрованих одразу "
                     "у кількох командах на цю подію (можливе дублювання):")
            st.dataframe(
                dupes.rename(columns={"full_name": "ПІБ", "email": "Пошта",
                                       "team_name": "Команда", "team_id": "ID команди"})
                     [["ПІБ", "Пошта", "Команда", "ID команди"]],
                use_container_width=True, hide_index=True)
            st.caption("Рекомендується зв'язатися з учасником і залишити його лише в одній команді "
                       "перед підтвердженням заявок.")
    else:
        st.caption("✅ Перевірка унікальності: дублювання учасників між командами на цю подію не виявлено.")

    status_filter = st.multiselect("Фільтр за статусом", TEAM_STATUSES, default=TEAM_STATUSES)
    teams_view = teams[teams["status"].isin(status_filter)]

    st.dataframe(teams_view[["id", "name", "faculty", "status", "status_comment"]],
                 use_container_width=True, hide_index=True)

    st.markdown("#### Масові дії")
    st.caption("При переведенні у статус «Прийнято» або «Потребує доопрацювання» капітанам команд "
               "автоматично надсилається email-сповіщення (або симулюється, якщо SMTP не налаштовано).")
    ids = st.multiselect("Оберіть ID команд", teams_view["id"].tolist())
    bulk_status = st.selectbox("Новий статус", TEAM_STATUSES, key="bulk_status")
    bulk_comment = st.text_input("Коментар (за потреби, наприклад причина доопрацювання)")
    if st.button("Застосувати до обраних") and ids:
        email_results = []
        for tid in ids:
            _, email_result = apply_team_status_change(int(tid), bulk_status, bulk_comment)
            if email_result:
                email_results.append(email_result)
        st.success(f"Оновлено {len(ids)} команд(и).")
        if email_results:
            sent = sum(1 for r in email_results if r == "sent")
            simulated = sum(1 for r in email_results if r == "simulated")
            opted_out = sum(1 for r in email_results if r == "skipped_opt_out")
            failed = sum(1 for r in email_results if r.startswith("failed"))
            msg = []
            if sent:
                msg.append(f"✅ реально надіслано: {sent}")
            if simulated:
                msg.append(f"📧 симульовано (SMTP не налаштовано): {simulated}")
            if opted_out:
                msg.append(f"🔕 пропущено (отримувач вимкнув сповіщення): {opted_out}")
            if failed:
                msg.append(f"❌ помилок надсилання: {failed}")
            st.info(" · ".join(msg))
        st.rerun()

    st.markdown("#### Індивідуальна зміна статусу")
    for _, t in teams_view.iterrows():
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
                old_status, email_result = apply_team_status_change(int(t["id"]), new_status, comment)
                st.success(f"Статус оновлено: «{old_status}» → «{new_status}».")
                if email_result == "sent":
                    st.info("📧 Email-сповіщення капітану реально надіслано через SMTP.")
                elif email_result == "simulated":
                    st.info("📧 Email-сповіщення симульовано (SMTP не налаштовано в secrets.toml) — "
                            "лист збережено в журналі нижче.")
                elif email_result == "skipped_opt_out":
                    st.info("🔕 Email не надіслано: капітан вимкнув email-сповіщення у своєму профілі.")
                elif email_result and email_result.startswith("failed"):
                    st.warning(f"⚠️ Не вдалося надіслати email: {email_result}")
                st.rerun()

            st.markdown("**🕓 Історія змін статусу**")
            history = get_status_history(int(t["id"]))
            if history.empty:
                st.caption("Змін статусу ще не було.")
            else:
                st.dataframe(
                    history.rename(columns={"changed_at": "Коли", "old_status": "Було",
                                             "new_status": "Стало", "changed_by_name": "Хто змінив",
                                             "comment": "Коментар"}),
                    use_container_width=True, hide_index=True)

            st.markdown("**💬 Питання від команди**")
            questions_df = get_team_questions(int(t["id"]))
            if questions_df.empty:
                st.caption("Питань від цієї команди ще не було.")
            else:
                unanswered = questions_df[questions_df["answer"].isna()]
                answered = questions_df[questions_df["answer"].notna()]
                for _, q in unanswered.iterrows():
                    with st.container(border=True):
                        st.write(f"❓ **{q['question']}**")
                        st.caption(f"{q['asked_by_name']} · {q['asked_at'][:16]}")
                        with st.form(f"answer_form_{q['id']}"):
                            answer_text = st.text_area("Відповідь", key=f"answer_text_{q['id']}")
                            if st.form_submit_button("💬 Надіслати відповідь") and answer_text.strip():
                                answer_team_question(int(q["id"]), answer_text.strip())
                                st.success("Відповідь надіслано команді.")
                                st.rerun()
                if not answered.empty:
                    with st.expander(f"✅ Відповіді, надані раніше ({len(answered)})"):
                        for _, q in answered.iterrows():
                            st.write(f"❓ {q['question']}")
                            st.caption(f"💬 {q['answer']} — {q['answered_by_name']}, {q['answered_at'][:16]}")

            with st.expander("🗑️ Видалити цю заявку команди остаточно"):
                st.warning("Це остаточно видалить команду, її учасників, подані проєкти й файли презентацій, "
                           "оцінки журі та історію статусів. На відміну від зміни статусу на «Відхилено», "
                           "цю дію неможливо скасувати. Використовуйте для дублікатів або явного спаму.")
                if st.button("Так, видалити команду остаточно", key=f"hard_del_team_{t['id']}"):
                    delete_team_cascade(int(t["id"]))
                    st.success(f"Команду «{t['name']}» остаточно видалено.")
                    st.rerun()

    st.markdown("#### 📧 Журнал email-сповіщень")
    smtp_cfg = get_smtp_config()
    if smtp_cfg:
        st.caption(f"SMTP налаштовано ({smtp_cfg.get('host', '?')}) — листи надсилаються реально.")
    else:
        st.caption("SMTP не налаштовано в `.streamlit/secrets.toml` ([smtp] host/port/username/password/from_email) — "
                   "листи симулюються та записуються в журнал нижче, реально не надсилаються.")
    email_log = get_email_log_for_event(ev_id)
    if email_log.empty:
        st.caption("Сповіщень ще не надсилалося.")
    else:
        st.dataframe(
            email_log.rename(columns={"created_at": "Коли", "team": "Команда", "to_email": "Кому",
                                       "subject": "Тема", "status": "Статус"}),
            use_container_width=True, hide_index=True)


def admin_jury():
    st.subheader("⚖️ Керування журі")
    tab_create, tab_manage, tab_assign, tab_progress = st.tabs(
        ["➕ Створити", "👥 Список і керування", "🗂️ Розподіл за подіями", "📊 Прогрес оцінювання"])

    # ---------------------------------------------------------------
    # Створення нового журі
    # ---------------------------------------------------------------
    with tab_create:
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

    # ---------------------------------------------------------------
    # Список та керування обліковими записами журі
    # ---------------------------------------------------------------
    with tab_manage:
        st.markdown("#### Список журі")
        jury_all = query_df("SELECT id, username, full_name, email, faculty FROM users WHERE role='jury' ORDER BY full_name")
        if jury_all.empty:
            st.info("Журі ще не створено. Скористайтесь вкладкою «➕ Створити».")
        else:
            search = st.text_input("🔎 Пошук за ПІБ, логіном або поштою", key="jury_search")
            view = jury_all
            if search.strip():
                q = search.strip().lower()
                view = jury_all[
                    jury_all["full_name"].fillna("").str.lower().str.contains(q)
                    | jury_all["username"].fillna("").str.lower().str.contains(q)
                    | jury_all["email"].fillna("").str.lower().str.contains(q)
                ]

            # швидка статистика навантаження: скільки подій та скільки оцінок уже виставлено
            workload_rows = []
            for _, j in view.iterrows():
                n_assign = query_one("SELECT COUNT(*) FROM jury_assignments WHERE jury_id=?", (j["id"],))[0]
                n_scores = query_one("SELECT COUNT(*) FROM scores WHERE jury_id=?", (j["id"],))[0]
                workload_rows.append({"ID": j["id"], "Логін": j["username"], "ПІБ": j["full_name"],
                                       "Пошта": j["email"], "Факультет": j["faculty"],
                                       "Призначень": n_assign, "Виставлено оцінок": n_scores})
            st.dataframe(pd.DataFrame(workload_rows), use_container_width=True, hide_index=True)

            st.markdown("#### Редагування обраного журі")
            jmap_edit = dict(zip(view["full_name"] + " (" + view["username"] + ")", view["id"]))
            if jmap_edit:
                sel_label = st.selectbox("Оберіть журі", list(jmap_edit.keys()), key="jury_edit_select")
                jid = int(jmap_edit[sel_label])
                jrow = query_one("SELECT full_name, email, faculty FROM users WHERE id=?", (jid,))

                with st.form(f"jury_edit_form_{jid}"):
                    new_name = st.text_input("ПІБ", value=jrow[0] or "")
                    new_email = st.text_input("Пошта", value=jrow[1] or "")
                    new_faculty = st.text_input("Факультет/кафедра", value=jrow[2] or "")
                    ec1, ec2 = st.columns(2)
                    with ec1:
                        save_btn = st.form_submit_button("💾 Зберегти зміни")
                    with ec2:
                        reset_pw_btn = st.form_submit_button("🔑 Скинути пароль")
                    if save_btn:
                        execute("UPDATE users SET full_name=?, email=?, faculty=? WHERE id=?",
                                (new_name, new_email, new_faculty, jid))
                        st.success("Дані журі оновлено.")
                        st.rerun()
                    if reset_pw_btn:
                        new_pw = gen_code(8)
                        execute("UPDATE users SET password=? WHERE id=?", (hash_pw(new_pw), jid))
                        st.success(f"Новий тимчасовий пароль для {jrow[0]}: **{new_pw}** "
                                   "(передайте його журі особисто, не публічно).")

                st.markdown("##### 🗑️ Видалення облікового запису")
                st.caption("Видалення можливе лише якщо в журі немає збережених оцінок чи призначень — "
                           "інакше спершу заберіть призначення на вкладці «Розподіл за подіями».")
                if st.button("Видалити обраного журі", key=f"del_jury_{jid}"):
                    try:
                        execute("DELETE FROM users WHERE id=?", (jid,))
                        st.success("Журі видалено.")
                        st.rerun()
                    except sqlite3.IntegrityError:
                        st.error("Неможливо видалити: у журі вже є призначення та/або збережені оцінки.")

    # ---------------------------------------------------------------
    # Розподіл журі за подіями/номінаціями
    # ---------------------------------------------------------------
    with tab_assign:
        events = get_events()
        if events.empty:
            st.info("Спочатку створіть подію.")
        else:
            ev_map = dict(zip(events["title"], events["id"]))
            ev_title = st.selectbox("Подія", list(ev_map.keys()), key="jury_event")
            ev_id = ev_map[ev_title]

            jury_list = query_df("SELECT id, full_name, faculty FROM users WHERE role='jury'")
            noms = query_df("SELECT id, name FROM nominations WHERE event_id=?", (ev_id,))
            if jury_list.empty:
                st.info("Спершу створіть облікові записи журі на вкладці «➕ Створити».")
            else:
                with st.form("assign_form"):
                    jmap = dict(zip(jury_list["full_name"], jury_list["id"]))
                    jname = st.selectbox("Журі", list(jmap.keys()))
                    nmap = {"— вся подія —": None}
                    nmap.update(dict(zip(noms["name"], noms["id"])))
                    nname = st.selectbox("Номінація", list(nmap.keys()))
                    if st.form_submit_button("Призначити"):
                        already = query_one(
                            """SELECT id FROM jury_assignments WHERE event_id=? AND jury_id=?
                               AND (nomination_id IS ? OR nomination_id=?)""",
                            (ev_id, jmap[jname], nmap[nname], nmap[nname]))
                        if already:
                            st.warning("Це журі вже призначено на цю подію/номінацію.")
                        else:
                            execute("INSERT INTO jury_assignments (event_id,jury_id,nomination_id) VALUES (?,?,?)",
                                    (ev_id, jmap[jname], nmap[nname]))
                            st.success("Журі призначено.")
                            st.rerun()

                st.markdown("#### Поточні призначення")
                assign_df = query_df("""SELECT ja.id, u.full_name AS jury, u.faculty,
                                                COALESCE(n.name,'вся подія') AS nomination
                                         FROM jury_assignments ja
                                         JOIN users u ON ja.jury_id=u.id
                                         LEFT JOIN nominations n ON ja.nomination_id=n.id
                                         WHERE ja.event_id=?""", (ev_id,))
                if assign_df.empty:
                    st.caption("Журі на цю подію ще не призначено.")
                else:
                    ev_conflict = query_one("SELECT avoid_conflict FROM events WHERE id=?", (ev_id,))
                    avoid_conflict_on = bool(ev_conflict[0]) if ev_conflict else False
                    for _, a in assign_df.iterrows():
                        c1, c2 = st.columns([5, 1])
                        with c1:
                            line = f"**{a['jury']}** · {a['nomination']} · факультет: {a['faculty'] or '—'}"
                            if avoid_conflict_on and a["faculty"] == MAIN_FACULTY:
                                line += "  \n⚠️ *Може мати конфлікт інтересів з командами свого факультету — оцінювання таких команд для цього журі автоматично заблоковано.*"
                            st.markdown(line)
                        with c2:
                            if st.button("🗑️ Зняти", key=f"unassign_{a['id']}"):
                                execute("DELETE FROM jury_assignments WHERE id=?", (int(a["id"]),))
                                st.rerun()

    # ---------------------------------------------------------------
    # Прогрес оцінювання: хто ще не завершив
    # ---------------------------------------------------------------
    with tab_progress:
        events2 = get_events()
        if events2.empty:
            st.info("Немає подій для аналізу прогресу.")
        else:
            ev_map3 = dict(zip(events2["title"], events2["id"]))
            ev_title3 = st.selectbox("Подія", list(ev_map3.keys()), key="jury_progress_event")
            ev_id3 = ev_map3[ev_title3]

            assigns = query_df("""SELECT ja.jury_id, u.full_name, ja.nomination_id,
                                          COALESCE(n.name,'вся подія') AS nomination
                                   FROM jury_assignments ja
                                   JOIN users u ON ja.jury_id=u.id
                                   LEFT JOIN nominations n ON ja.nomination_id=n.id
                                   WHERE ja.event_id=?""", (ev_id3,))
            if assigns.empty:
                st.info("Журі ще не призначено на цю подію.")
            else:
                teams_total_df = query_df("SELECT id, nomination_id, faculty FROM teams WHERE event_id=? AND status='Прийнято'",
                                           (ev_id3,))
                crit_count = query_one("SELECT COUNT(*) FROM criteria WHERE event_id=?", (ev_id3,))[0]

                rows = []
                for _, a in assigns.iterrows():
                    if pd.isna(a["nomination_id"]):
                        scope_teams = teams_total_df
                    else:
                        scope_teams = teams_total_df[teams_total_df["nomination_id"] == a["nomination_id"]]
                    # виключаємо команди, оцінювання яких для цього журі заблоковано через конфлікт інтересів
                    scope_teams = scope_teams[scope_teams["faculty"] != MAIN_FACULTY] \
                        if query_one("SELECT avoid_conflict FROM events WHERE id=?", (ev_id3,))[0] else scope_teams
                    total_teams = len(scope_teams)
                    scored_teams = 0
                    for _, tt in scope_teams.iterrows():
                        cnt = query_one("SELECT COUNT(DISTINCT criterion_id) FROM scores WHERE team_id=? AND jury_id=?",
                                         (int(tt["id"]), int(a["jury_id"])))[0]
                        if crit_count and cnt >= crit_count:
                            scored_teams += 1
                    pct = round(scored_teams / total_teams * 100, 1) if total_teams else 0.0
                    rows.append({"Журі": a["full_name"], "Номінація": a["nomination"],
                                 "Команд до оцінки": total_teams, "Оцінено повністю": scored_teams,
                                 "Прогрес, %": pct})

                prog_df = pd.DataFrame(rows)
                st.dataframe(prog_df, use_container_width=True, hide_index=True)

                if not prog_df.empty:
                    st.progress(min(prog_df["Прогрес, %"].mean() / 100, 1.0))
                    incomplete = prog_df[prog_df["Прогрес, %"] < 100]
                    if not incomplete.empty:
                        names = ", ".join(sorted(incomplete["Журі"].unique()))
                        st.warning(f"⏳ Ще не завершили оцінювання всіх своїх команд: {names}")
                    else:
                        st.success("✅ Усі призначені журі завершили оцінювання своїх команд.")

                st.markdown("#### ⚠️ Аномалії в оцінках цієї події")
                anomalies = detect_anomalies(ev_id3)
                if anomalies.empty:
                    st.caption("Суттєвих розходжень в оцінках журі не виявлено.")
                else:
                    st.dataframe(anomalies, use_container_width=True, hide_index=True)


def admin_mentors():
    st.subheader("🧑‍🏫 Ментори (Office Hours)")
    tab_create, tab_manage, tab_slots, tab_stats = st.tabs(
        ["➕ Створити", "👥 Список і керування", "🗓️ Огляд і керування слотами", "📊 Статистика"])

    # ---------------------------------------------------------------
    # Створення нового ментора
    # ---------------------------------------------------------------
    with tab_create:
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

    # ---------------------------------------------------------------
    # Список та керування обліковими записами менторів
    # ---------------------------------------------------------------
    with tab_manage:
        st.markdown("#### Список менторів")
        mentors_all = query_df("SELECT id, username, full_name, email, faculty FROM users WHERE role='mentor' ORDER BY full_name")
        if mentors_all.empty:
            st.info("Менторів ще не створено. Скористайтесь вкладкою «➕ Створити».")
        else:
            search_m = st.text_input("🔎 Пошук за ПІБ, логіном або поштою", key="mentor_search")
            view_m = mentors_all
            if search_m.strip():
                q = search_m.strip().lower()
                view_m = mentors_all[
                    mentors_all["full_name"].fillna("").str.lower().str.contains(q)
                    | mentors_all["username"].fillna("").str.lower().str.contains(q)
                    | mentors_all["email"].fillna("").str.lower().str.contains(q)
                ]

            # навантаження: скільки слотів створено і скільки з них заброньовано
            workload_rows = []
            for _, m in view_m.iterrows():
                n_slots = query_one("SELECT COUNT(*) FROM mentor_slots WHERE mentor_id=?", (m["id"],))[0]
                n_booked = query_one("SELECT COUNT(*) FROM mentor_slots WHERE mentor_id=? AND is_booked=1", (m["id"],))[0]
                workload_rows.append({"ID": m["id"], "Логін": m["username"], "ПІБ": m["full_name"],
                                       "Пошта": m["email"], "Спеціалізація": m["faculty"],
                                       "Слотів створено": n_slots, "З них заброньовано": n_booked})
            st.dataframe(pd.DataFrame(workload_rows), use_container_width=True, hide_index=True)

            st.markdown("#### Редагування обраного ментора")
            mmap_edit = dict(zip(view_m["full_name"] + " (" + view_m["username"] + ")", view_m["id"]))
            if mmap_edit:
                sel_label_m = st.selectbox("Оберіть ментора", list(mmap_edit.keys()), key="mentor_edit_select")
                mid = int(mmap_edit[sel_label_m])
                mrow = query_one("SELECT full_name, email, faculty FROM users WHERE id=?", (mid,))

                with st.form(f"mentor_edit_form_{mid}"):
                    new_name_m = st.text_input("ПІБ", value=mrow[0] or "")
                    new_email_m = st.text_input("Пошта", value=mrow[1] or "")
                    new_spec_m = st.text_input("Спеціалізація / факультет / компанія", value=mrow[2] or "")
                    emc1, emc2 = st.columns(2)
                    with emc1:
                        save_btn_m = st.form_submit_button("💾 Зберегти зміни")
                    with emc2:
                        reset_pw_btn_m = st.form_submit_button("🔑 Скинути пароль")
                    if save_btn_m:
                        execute("UPDATE users SET full_name=?, email=?, faculty=? WHERE id=?",
                                (new_name_m, new_email_m, new_spec_m, mid))
                        st.success("Дані ментора оновлено.")
                        st.rerun()
                    if reset_pw_btn_m:
                        new_pw_m = gen_code(8)
                        execute("UPDATE users SET password=? WHERE id=?", (hash_pw(new_pw_m), mid))
                        st.success(f"Новий тимчасовий пароль для {mrow[0]}: **{new_pw_m}** "
                                   "(передайте його ментору особисто, не публічно).")

                st.markdown("##### 🗑️ Видалення облікового запису")
                m_slot_count = query_one("SELECT COUNT(*) FROM mentor_slots WHERE mentor_id=?", (mid,))[0]
                if m_slot_count:
                    st.caption(f"У ментора є {m_slot_count} слот(ів) у розкладі. Видалення користувача автоматично "
                               "звільнить заброньовані на нього слоти командам (запис буде видалено).")
                if st.button("Видалити обраного ментора", key=f"del_mentor_{mid}"):
                    try:
                        execute("DELETE FROM mentor_slots WHERE mentor_id=?", (mid,))
                        execute("DELETE FROM users WHERE id=?", (mid,))
                        st.success("Ментора та його слоти видалено.")
                        st.rerun()
                    except sqlite3.IntegrityError:
                        st.error("Неможливо видалити обліковий запис через пов'язані дані.")

    # ---------------------------------------------------------------
    # Огляд і ручне керування всіма слотами Office Hours
    # ---------------------------------------------------------------
    with tab_slots:
        events = get_events()
        if events.empty:
            st.info("Подій ще немає.")
        else:
            ev_map = dict(zip(events["title"], events["id"]))
            ev_title = st.selectbox("Подія", list(ev_map.keys()), key="mentor_overview_event")
            ev_id = ev_map[ev_title]

            mentors_for_ev = query_df("""SELECT DISTINCT u.id, u.full_name FROM mentor_slots ms
                                          JOIN users u ON ms.mentor_id=u.id WHERE ms.event_id=?""", (ev_id,))
            fcol1, fcol2 = st.columns(2)
            with fcol1:
                mentor_filter_map = {"Усі ментори": None}
                mentor_filter_map.update(dict(zip(mentors_for_ev["full_name"], mentors_for_ev["id"])))
                mentor_filter_name = st.selectbox("Ментор", list(mentor_filter_map.keys()))
            with fcol2:
                status_filter_m = st.selectbox("Статус", ["Усі", "Тільки вільні", "Тільки заброньовані"])

            sql = """SELECT ms.id, ms.mentor_id, u.full_name AS mentor, ms.slot_date, ms.start_time, ms.end_time,
                            ms.location, ms.team_id, COALESCE(t.name,'—') AS team,
                            CASE WHEN ms.is_booked=1 THEN 'заброньовано' ELSE 'вільно' END AS status
                     FROM mentor_slots ms
                     JOIN users u ON ms.mentor_id=u.id
                     LEFT JOIN teams t ON ms.team_id=t.id
                     WHERE ms.event_id=?"""
            params = [ev_id]
            if mentor_filter_map[mentor_filter_name] is not None:
                sql += " AND ms.mentor_id=?"
                params.append(mentor_filter_map[mentor_filter_name])
            if status_filter_m == "Тільки вільні":
                sql += " AND ms.is_booked=0"
            elif status_filter_m == "Тільки заброньовані":
                sql += " AND ms.is_booked=1"
            sql += " ORDER BY ms.slot_date, ms.start_time"
            slots = query_df(sql, params)

            if slots.empty:
                st.info("Слотів за обраними фільтрами не знайдено.")
            else:
                st.dataframe(slots[["id", "mentor", "slot_date", "start_time", "end_time", "location", "team", "status"]],
                             use_container_width=True, hide_index=True)

                st.markdown("#### Керування окремими слотами")
                teams_for_ev = query_df("SELECT id, name FROM teams WHERE event_id=?", (ev_id,))
                team_map_admin = dict(zip(teams_for_ev["name"], teams_for_ev["id"]))
                for _, s in slots.iterrows():
                    with st.container(border=True):
                        st.write(f"**#{s['id']}** · {s['mentor']} · {s['slot_date']} {s['start_time']}–{s['end_time']} "
                                 f"· {s['location'] or 'онлайн'} · **{s['status']}** ({s['team']})")
                        bc1, bc2, bc3 = st.columns([2, 1, 1])
                        if s["team_id"]:
                            with bc1:
                                st.caption(f"Заброньовано командою «{s['team']}».")
                            with bc2:
                                if st.button("🔓 Звільнити слот", key=f"unbook_{s['id']}"):
                                    execute("UPDATE mentor_slots SET is_booked=0, team_id=NULL WHERE id=?", (int(s["id"]),))
                                    st.rerun()
                        else:
                            with bc1:
                                if team_map_admin:
                                    force_team_name = st.selectbox("Призначити команду вручну", list(team_map_admin.keys()),
                                                                    key=f"force_team_{s['id']}")
                                else:
                                    force_team_name = None
                            with bc2:
                                if team_map_admin and st.button("📌 Призначити", key=f"force_assign_{s['id']}"):
                                    execute("UPDATE mentor_slots SET is_booked=1, team_id=? WHERE id=?",
                                            (int(team_map_admin[force_team_name]), int(s["id"])))
                                    st.rerun()
                        with bc3:
                            if st.button("🗑️ Видалити слот", key=f"del_slot_admin_{s['id']}"):
                                execute("DELETE FROM mentor_slots WHERE id=?", (int(s["id"]),))
                                st.rerun()

    # ---------------------------------------------------------------
    # Статистика по менторах і подіях
    # ---------------------------------------------------------------
    with tab_stats:
        events2 = get_events()
        if events2.empty:
            st.info("Немає даних для статистики.")
        else:
            ev_map2 = dict(zip(events2["title"], events2["id"]))
            ev_title2 = st.selectbox("Подія", list(ev_map2.keys()), key="mentor_stats_event")
            ev_id2 = ev_map2[ev_title2]

            all_slots = query_df("""SELECT ms.mentor_id, u.full_name AS mentor, ms.is_booked
                                     FROM mentor_slots ms JOIN users u ON ms.mentor_id=u.id
                                     WHERE ms.event_id=?""", (ev_id2,))
            if all_slots.empty:
                st.info("Слотів для цієї події ще не створено.")
            else:
                total = len(all_slots)
                booked = int(all_slots["is_booked"].sum())
                free = total - booked
                sc1, sc2, sc3 = st.columns(3)
                sc1.metric("Всього слотів", total)
                sc2.metric("Заброньовано", booked)
                sc3.metric("Вільно", free)
                if total:
                    st.progress(min(booked / total, 1.0))

                st.markdown("#### Слотів на ментора")
                per_mentor = all_slots.groupby("mentor").size()
                st.bar_chart(per_mentor)

                st.markdown("#### Заброньованих слотів на ментора")
                booked_per_mentor = all_slots[all_slots["is_booked"] == 1].groupby("mentor").size()
                if not booked_per_mentor.empty:
                    st.bar_chart(booked_per_mentor)
                else:
                    st.caption("Заброньованих слотів поки немає.")

                teams_without_slot = query_df("""SELECT t.id, t.name, t.faculty FROM teams t
                                                  WHERE t.event_id=? AND t.status='Прийнято'
                                                  AND t.id NOT IN (
                                                      SELECT team_id FROM mentor_slots
                                                      WHERE event_id=? AND team_id IS NOT NULL
                                                  )""", (ev_id2, ev_id2))
                st.markdown("#### Команди без запису на консультацію")
                if teams_without_slot.empty:
                    st.success("✅ Усі прийняті команди вже мають (або мали) запис на Office Hours.")
                else:
                    st.dataframe(teams_without_slot.rename(columns={"name": "Команда", "faculty": "Факультет"})
                                 [["Команда", "Факультет"]], use_container_width=True, hide_index=True)


def _parse_created_date(text):
    """Витягує саму дату (без часу) з поля created_at (формат 'YYYY-MM-DD HH:MM:SS.ffffff')."""
    if not text:
        return None
    dt = parse_date_flexible(str(text)[:19])
    return dt.date() if dt else None


def admin_analytics():
    st.subheader("📊 Аналітика та звіти")
    events = get_events()
    if events.empty:
        st.info("Немає даних для аналітики.")
        return

    tab_overview, tab_events, tab_people, tab_scoring, tab_export = st.tabs(
        ["📈 Загальний огляд", "🏁 По подіях", "👥 Команди та факультети",
         "⚖️ Оцінювання", "📤 Експорт звітів"])

    teams_all = query_df("""SELECT t.*, e.title AS event_title, e.category AS event_category,
                                    e.format AS event_format
                             FROM teams t JOIN events e ON t.event_id=e.id""")

    # ================================================================
    # 📈 ЗАГАЛЬНИЙ ОГЛЯД
    # ================================================================
    with tab_overview:
        total_teams = query_one("SELECT COUNT(*) FROM teams")[0]
        total_members = query_one("SELECT COUNT(*) FROM team_members")[0]
        total_events = len(events)
        total_submissions = query_one("SELECT COUNT(DISTINCT team_id) FROM submissions")[0]
        total_likes = query_one("SELECT COUNT(*) FROM showcase_likes")[0]
        avg_team_size = round(total_members / total_teams, 1) if total_teams else 0

        k1, k2, k3, k4, k5 = st.columns(5)
        k1.metric("Всього подій", total_events)
        k2.metric("Всього команд", total_teams)
        k3.metric("Всього учасників", total_members)
        k4.metric("Сер. розмір команди", avg_team_size)
        k5.metric("❤️ Лайків у портфоліо", total_likes)

        accepted_teams = int((teams_all["status"] == "Прийнято").sum()) if not teams_all.empty else 0
        submission_rate = round(total_submissions / accepted_teams * 100, 1) if accepted_teams else 0
        st.caption(f"📦 Подачі проєктів завантажили {total_submissions} із {accepted_teams} прийнятих команд "
                   f"({submission_rate}%).")

        if not teams_all.empty:
            st.markdown("#### 🗓️ Динаміка реєстрації команд у часі")
            trend_df = teams_all.copy()
            trend_df["Дата"] = trend_df["created_at"].apply(_parse_created_date)
            trend_df = trend_df.dropna(subset=["Дата"])
            if not trend_df.empty:
                daily = trend_df.groupby("Дата").size().reset_index(name="Нових команд")
                daily = daily.sort_values("Дата")
                daily["Наростаючим підсумком"] = daily["Нових команд"].cumsum()
                trend_long = daily.melt(id_vars="Дата", value_vars=["Нових команд", "Наростаючим підсумком"],
                                         var_name="Показник", value_name="Кількість")
                trend_chart = alt.Chart(trend_long).mark_line(point=True).encode(
                    x=alt.X("Дата:T", title="Дата реєстрації"),
                    y=alt.Y("Кількість:Q"),
                    color=alt.Color("Показник:N", scale=alt.Scale(range=["#4F8BF9", "#27AE60"])),
                    tooltip=["Дата:T", "Показник:N", "Кількість:Q"],
                ).properties(height=300)
                st.altair_chart(trend_chart, use_container_width=True)
            else:
                st.caption("Недостатньо даних для побудови динаміки.")

            oc1, oc2 = st.columns(2)
            with oc1:
                st.markdown("#### 🏆 Команди за подіями")
                by_event = teams_all.groupby("event_title").size().reset_index(name="Команд")
                chart_ev = alt.Chart(by_event).mark_bar(cornerRadiusTopLeft=6, cornerRadiusTopRight=6).encode(
                    x=alt.X("Команд:Q"),
                    y=alt.Y("event_title:N", sort="-x", title="Подія"),
                    color=alt.Color("Команд:Q", scale=alt.Scale(scheme="blues"), legend=None),
                    tooltip=["event_title", "Команд"],
                ).properties(height=max(160, 32 * len(by_event)))
                st.altair_chart(chart_ev, use_container_width=True)
            with oc2:
                st.markdown("#### 🗂️ Розподіл за категоріями")
                by_cat = teams_all.groupby("event_category").size().reset_index(name="Команд")
                donut = alt.Chart(by_cat).mark_arc(innerRadius=60).encode(
                    theta=alt.Theta("Команд:Q"),
                    color=alt.Color("event_category:N", title="Категорія",
                                     scale=alt.Scale(scheme="category10")),
                    tooltip=["event_category", "Команд"],
                ).properties(height=300)
                st.altair_chart(donut, use_container_width=True)

    # ================================================================
    # 🏁 ПО ПОДІЯХ (deep dive для однієї події)
    # ================================================================
    with tab_events:
        ev_map = dict(zip(events["title"], events["id"]))
        ev_title_a = st.selectbox("Подія", list(ev_map.keys()), key="analytics_event_select")
        ev_id_a = ev_map[ev_title_a]

        ev_teams = query_df("SELECT * FROM teams WHERE event_id=?", (ev_id_a,))
        n_teams = len(ev_teams)
        n_accepted = int((ev_teams["status"] == "Прийнято").sum()) if n_teams else 0
        n_members_ev = query_one("""SELECT COUNT(*) FROM team_members tm
                                     JOIN teams t ON tm.team_id=t.id WHERE t.event_id=?""", (ev_id_a,))[0]
        n_sub_ev = query_one("""SELECT COUNT(DISTINCT team_id) FROM submissions s
                                 JOIN teams t ON s.team_id=t.id WHERE t.event_id=?""", (ev_id_a,))[0]

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Команд подано", n_teams)
        m2.metric("Прийнято", n_accepted)
        m3.metric("Учасників", n_members_ev)
        m4.metric("Із подачею проєкту", f"{n_sub_ev}/{n_accepted}" if n_accepted else n_sub_ev)

        if n_teams:
            ec1, ec2 = st.columns(2)
            with ec1:
                st.markdown("#### 📋 Вирва статусів заявок")
                status_counts = ev_teams.groupby("status").size().reindex(TEAM_STATUSES).fillna(0).reset_index()
                status_counts.columns = ["Статус", "Команд"]
                status_chart = alt.Chart(status_counts).mark_bar(cornerRadiusTopLeft=6, cornerRadiusTopRight=6).encode(
                    x=alt.X("Статус:N", sort=TEAM_STATUSES),
                    y=alt.Y("Команд:Q"),
                    color=alt.Color("Статус:N", scale=alt.Scale(
                        domain=TEAM_STATUSES,
                        range=["#4F8BF9", "#27AE60", "#F1C40F", "#E74C3C"])),
                    tooltip=["Статус", "Команд"],
                ).properties(height=300)
                st.altair_chart(status_chart, use_container_width=True)
            with ec2:
                noms_ev = query_df("SELECT id, name FROM nominations WHERE event_id=?", (ev_id_a,))
                if not noms_ev.empty:
                    st.markdown("#### 🏷️ Команди за номінаціями")
                    nom_join = ev_teams.merge(noms_ev, left_on="nomination_id", right_on="id",
                                               how="left", suffixes=("", "_nom"))
                    nom_join["name"] = nom_join["name"].fillna("Без номінації")
                    nom_counts = nom_join.groupby("name").size().reset_index(name="Команд")
                    nom_donut = alt.Chart(nom_counts).mark_arc(innerRadius=55).encode(
                        theta=alt.Theta("Команд:Q"),
                        color=alt.Color("name:N", title="Номінація", scale=alt.Scale(scheme="set2")),
                        tooltip=["name", "Команд"],
                    ).properties(height=300)
                    st.altair_chart(nom_donut, use_container_width=True)
                else:
                    st.markdown("#### 🎓 Команди за факультетами (ця подія)")
                    fac_counts = ev_teams.groupby("faculty").size().reset_index(name="Команд")
                    fac_chart = alt.Chart(fac_counts).mark_bar().encode(
                        x=alt.X("Команд:Q"),
                        y=alt.Y("faculty:N", sort="-x", title="Факультет"),
                        color=alt.Color("Команд:Q", scale=alt.Scale(scheme="purples"), legend=None),
                        tooltip=["faculty", "Команд"],
                    ).properties(height=max(160, 32 * len(fac_counts)))
                    st.altair_chart(fac_chart, use_container_width=True)

            criteria_ev = query_df("SELECT * FROM criteria WHERE event_id=?", (ev_id_a,))
            if not criteria_ev.empty:
                st.markdown("#### 🎯 Середній бал за критеріями (ця подія)")
                crit_rows = []
                for _, crit in criteria_ev.iterrows():
                    avg_row = query_one("""SELECT AVG(s.score) FROM scores s
                                            JOIN teams t ON s.team_id=t.id
                                            WHERE t.event_id=? AND s.criterion_id=?""", (ev_id_a, crit["id"]))
                    if avg_row and avg_row[0] is not None:
                        crit_rows.append({"Критерій": crit["name"], "Сер. бал": round(avg_row[0], 2),
                                           "Максимум": crit["max_score"]})
                if crit_rows:
                    crit_df = pd.DataFrame(crit_rows)
                    crit_chart = alt.Chart(crit_df).mark_bar(cornerRadiusTopLeft=6, cornerRadiusTopRight=6).encode(
                        x=alt.X("Критерій:N", sort="-y"),
                        y=alt.Y("Сер. бал:Q"),
                        color=alt.Color("Сер. бал:Q", scale=alt.Scale(scheme="goldgreen"), legend=None),
                        tooltip=["Критерій", "Сер. бал", "Максимум"],
                    ).properties(height=300)
                    st.altair_chart(crit_chart, use_container_width=True)
                else:
                    st.caption("Оцінок для цієї події ще немає.")
        else:
            st.info("Для цієї події ще немає жодної команди.")

    # ================================================================
    # 👥 КОМАНДИ ТА ФАКУЛЬТЕТИ (загальний розподіл по всій платформі)
    # ================================================================
    with tab_people:
        if teams_all.empty:
            st.info("Команд ще немає.")
        else:
            pc1, pc2 = st.columns(2)
            with pc1:
                st.markdown("#### 🎓 Розподіл команд за факультетами")
                fac_all = teams_all.groupby("faculty").size().reset_index(name="Команд")
                fac_chart_all = alt.Chart(fac_all).mark_bar(cornerRadiusTopLeft=6, cornerRadiusTopRight=6).encode(
                    x=alt.X("Команд:Q"),
                    y=alt.Y("faculty:N", sort="-x", title="Факультет"),
                    color=alt.Color("Команд:Q", scale=alt.Scale(scheme="teals"), legend=None),
                    tooltip=["faculty", "Команд"],
                ).properties(height=max(200, 32 * len(fac_all)))
                st.altair_chart(fac_chart_all, use_container_width=True)
            with pc2:
                st.markdown("#### 📥 Розподіл за статусами заявок (усі події)")
                status_all = teams_all.groupby("status").size().reindex(TEAM_STATUSES).fillna(0).reset_index()
                status_all.columns = ["Статус", "Команд"]
                status_donut_all = alt.Chart(status_all).mark_arc(innerRadius=60).encode(
                    theta=alt.Theta("Команд:Q"),
                    color=alt.Color("Статус:N", scale=alt.Scale(
                        domain=TEAM_STATUSES,
                        range=["#4F8BF9", "#27AE60", "#F1C40F", "#E74C3C"])),
                    tooltip=["Статус", "Команд"],
                ).properties(height=320)
                st.altair_chart(status_donut_all, use_container_width=True)

            st.markdown("#### 📐 Розподіл команд за розміром")
            size_df = query_df("""SELECT tm.team_id, COUNT(*) AS members FROM team_members tm GROUP BY tm.team_id""")
            if not size_df.empty:
                size_hist = alt.Chart(size_df).mark_bar().encode(
                    x=alt.X("members:O", title="Кількість учасників у команді"),
                    y=alt.Y("count():Q", title="Кількість команд"),
                    color=alt.Color("members:O", scale=alt.Scale(scheme="oranges"), legend=None),
                    tooltip=["members", "count()"],
                ).properties(height=280)
                st.altair_chart(size_hist, use_container_width=True)
            else:
                st.caption("Ще немає команд зі складом учасників.")

            st.markdown("#### 🖥️ Розподіл подій за форматом")
            fmt_all = teams_all.groupby("event_format").size().reset_index(name="Команд")
            fmt_chart = alt.Chart(fmt_all).mark_bar(cornerRadiusTopLeft=6, cornerRadiusTopRight=6).encode(
                x=alt.X("event_format:N", title="Формат"),
                y=alt.Y("Команд:Q"),
                color=alt.Color("event_format:N", scale=alt.Scale(scheme="dark2"), legend=None),
                tooltip=["event_format", "Команд"],
            ).properties(height=280)
            st.altair_chart(fmt_chart, use_container_width=True)

    # ================================================================
    # ⚖️ ОЦІНЮВАННЯ (аномалії + активність журі)
    # ================================================================
    with tab_scoring:
        st.markdown("#### ⚠️ Виявлені аномалії в оцінюванні")
        ev_map2 = dict(zip(events["title"], events["id"]))
        ev_title2 = st.selectbox("Подія для перевірки аномалій", list(ev_map2.keys()), key="anomaly_event")
        anomalies = detect_anomalies(ev_map2[ev_title2])
        if anomalies.empty:
            st.success("Аномалій не виявлено.")
        else:
            st.warning("Знайдено оцінки з суттєвим відхиленням від середнього — рекомендується перегляд.")
            st.dataframe(anomalies, use_container_width=True, hide_index=True)
            anomaly_chart = alt.Chart(anomalies).mark_circle(size=120).encode(
                x=alt.X("Команда:N"),
                y=alt.Y("Відхилення:Q"),
                color=alt.Color("Журі:N", scale=alt.Scale(scheme="category10")),
                tooltip=["Команда", "Критерій", "Журі", "Оцінка", "Середнє", "Відхилення"],
            ).properties(height=300)
            st.altair_chart(anomaly_chart, use_container_width=True)

        st.markdown("#### 👩‍⚖️ Активність журі (кількість виставлених оцінок)")
        jury_activity = query_df("""SELECT u.full_name AS jury, COUNT(*) AS scores
                                     FROM scores s JOIN users u ON s.jury_id=u.id
                                     GROUP BY u.full_name ORDER BY scores DESC""")
        if jury_activity.empty:
            st.caption("Оцінок ще немає.")
        else:
            jury_chart = alt.Chart(jury_activity).mark_bar(cornerRadiusTopLeft=6, cornerRadiusTopRight=6).encode(
                x=alt.X("scores:Q", title="Виставлено оцінок"),
                y=alt.Y("jury:N", sort="-x", title="Журі"),
                color=alt.Color("scores:Q", scale=alt.Scale(scheme="greens"), legend=None),
                tooltip=["jury", "scores"],
            ).properties(height=max(160, 32 * len(jury_activity)))
            st.altair_chart(jury_chart, use_container_width=True)

        st.markdown("#### 📊 Загальний розподіл усіх виставлених оцінок")
        all_scores_global = query_df("SELECT score FROM scores")
        if all_scores_global.empty:
            st.caption("Оцінок ще немає.")
        else:
            global_hist = alt.Chart(all_scores_global).mark_bar().encode(
                x=alt.X("score:Q", bin=alt.Bin(maxbins=20), title="Оцінка"),
                y=alt.Y("count():Q", title="Кількість"),
                color=alt.value("#4F8BF9"),
                tooltip=["count()"],
            ).properties(height=280)
            st.altair_chart(global_hist, use_container_width=True)

    # ================================================================
    # 📤 ЕКСПОРТ ЗВІТІВ
    # ================================================================
    with tab_export:
        st.markdown("#### Вивантаження зведеного звіту")
        st.caption("Excel-звіт містить окремі аркуші з подіями, командами, учасниками, оцінками, "
                   "критеріями, номінаціями та слотами Office Hours.")
        export_format = st.radio("Формат", ["CSV (лише команди)", "Excel (повний звіт)"], horizontal=True)
        if st.button("Сформувати звіт"):
            events_df = query_df("SELECT * FROM events")
            teams_df = query_df("SELECT * FROM teams")
            scores_df = query_df("SELECT * FROM scores")
            if export_format == "CSV (лише команди)":
                buf = io.StringIO()
                teams_df.to_csv(buf, index=False)
                st.download_button("⬇️ Завантажити teams.csv", buf.getvalue(), file_name="teams.csv", mime="text/csv")
            else:
                members_df = query_df("""SELECT tm.team_id, u.full_name, u.email, u.faculty
                                          FROM team_members tm JOIN users u ON tm.user_id=u.id""")
                criteria_df = query_df("SELECT * FROM criteria")
                nominations_df = query_df("SELECT * FROM nominations")
                mentor_slots_df = query_df("SELECT * FROM mentor_slots")
                buf = io.BytesIO()
                with pd.ExcelWriter(buf, engine="openpyxl") as writer:
                    events_df.to_excel(writer, sheet_name="Events", index=False)
                    teams_df.to_excel(writer, sheet_name="Teams", index=False)
                    members_df.to_excel(writer, sheet_name="Team_Members", index=False)
                    scores_df.to_excel(writer, sheet_name="Scores", index=False)
                    criteria_df.to_excel(writer, sheet_name="Criteria", index=False)
                    nominations_df.to_excel(writer, sheet_name="Nominations", index=False)
                    mentor_slots_df.to_excel(writer, sheet_name="Mentor_Slots", index=False)
                st.download_button("⬇️ Завантажити CampusBridge_report.xlsx", buf.getvalue(),
                                    file_name="CampusBridge_report.xlsx",
                                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


def admin_announcements():
    st.subheader("📢 Сповіщення та розсилки")
    tab_new, tab_history, tab_stats = st.tabs(
        ["✉️ Нове оголошення", "🗂️ Історія та керування", "📊 Огляд охоплення"])

    events = get_events()
    ev_map = {"— глобальне (усі учасники) —": None}
    ev_map.update(dict(zip(events["title"], events["id"])) if not events.empty else {})

    AUDIENCE_STATUS_MAP = {
        "Усі команди": None, "Лише «Прийнято»": "Прийнято",
        "Лише «На розгляді»": "На розгляді",
        "Лише «Потребує доопрацювання»": "Потребує доопрацювання",
    }

    # ================================================================
    # ✉️ НОВЕ ОГОЛОШЕННЯ
    # ================================================================
    with tab_new:
        with st.form("announce_form"):
            ev_title = st.selectbox("Подія", list(ev_map.keys()), key="ann_event_select")
            ev_id = ev_map[ev_title]

            target_team_id = None
            audience_label = "Усі"
            teams = pd.DataFrame()
            if ev_id:
                teams = query_df("SELECT id, name, status, captain_id FROM teams WHERE event_id=?", (ev_id,))
                tmap = {"— всі команди події —": None}
                tmap.update(dict(zip(teams["name"], teams["id"])) if not teams.empty else {})
                tname = st.selectbox("Отримувач", list(tmap.keys()))
                target_team_id = tmap[tname]

                if target_team_id is None and not teams.empty:
                    audience_label = st.selectbox(
                        "Фільтр аудиторії (звужує коло команд для email-дублювання й статистики)",
                        list(AUDIENCE_STATUS_MAP.keys()))
                else:
                    audience_label = "Конкретна команда" if target_team_id else "Усі"

            priority = st.radio("Пріоритет", ["Звичайне", "⭐ Важливе"], horizontal=True)
            title = st.text_input("Заголовок")
            body = st.text_area("Текст повідомлення")

            send_email_copy = False
            if ev_id:
                send_email_copy = st.checkbox(
                    "📧 Також продублювати капітанам на email",
                    help="Реально надішле лист, якщо в secrets.toml налаштовано SMTP; "
                         "інакше надсилання симулюється й фіксується в журналі email.")

            submitted = st.form_submit_button("📢 Опублікувати")
            if submitted:
                if not title:
                    st.error("Вкажіть заголовок оголошення.")
                else:
                    user = st.session_state.user
                    new_ann_id = execute(
                        """INSERT INTO announcements (event_id,title,body,target_team_id,created_at,
                           priority,audience,created_by_name,email_status)
                           VALUES (?,?,?,?,?,?,?,?,?)""",
                        (ev_id, title, body, target_team_id, now(), priority, audience_label,
                         user["full_name"], None))

                    email_summary = None
                    if send_email_copy and ev_id:
                        if target_team_id:
                            target_ids = [target_team_id]
                        else:
                            wanted_status = AUDIENCE_STATUS_MAP.get(audience_label)
                            df_targets = teams if wanted_status is None else teams[teams["status"] == wanted_status]
                            target_ids = df_targets["id"].tolist()

                        results = [send_announcement_email(int(tid), title, body) for tid in target_ids]
                        results = [r for r in results if r]
                        sent = sum(1 for r in results if r == "sent")
                        simulated = sum(1 for r in results if r == "simulated")
                        opted_out = sum(1 for r in results if r == "skipped_opt_out")
                        failed = sum(1 for r in results if r.startswith("failed"))
                        email_summary = (f"реально надіслано: {sent} · симульовано: {simulated} · "
                                          f"пропущено (вимкнули сповіщення): {opted_out} · помилок: {failed}")
                        execute("UPDATE announcements SET email_status=? WHERE id=?", (email_summary, new_ann_id))

                    st.success("Оголошення опубліковано.")
                    if email_summary:
                        st.info(f"📧 Email-дублікати — {email_summary}")
                    st.rerun()

    # ================================================================
    # 🗂️ ІСТОРІЯ ТА КЕРУВАННЯ
    # ================================================================
    with tab_history:
        hist_all = query_df("""SELECT a.id, a.created_at, a.event_id, COALESCE(e.title,'Глобальне') AS event,
                                       COALESCE(t.name,'Усі команди') AS target, a.title, a.body,
                                       COALESCE(a.priority,'Звичайне') AS priority,
                                       COALESCE(a.audience,'Усі') AS audience,
                                       a.created_by_name, a.email_status
                                FROM announcements a
                                LEFT JOIN events e ON a.event_id=e.id
                                LEFT JOIN teams t ON a.target_team_id=t.id
                                ORDER BY a.created_at DESC""")
        if hist_all.empty:
            st.info("Оголошень ще не було.")
        else:
            fc1, fc2, fc3 = st.columns([2, 2, 2])
            with fc1:
                event_filter = st.multiselect("Фільтр за подією", sorted(hist_all["event"].unique().tolist()))
            with fc2:
                priority_filter = st.multiselect("Фільтр за пріоритетом", sorted(hist_all["priority"].unique().tolist()))
            with fc3:
                search_ann = st.text_input("🔎 Пошук за заголовком/текстом")

            view = hist_all
            if event_filter:
                view = view[view["event"].isin(event_filter)]
            if priority_filter:
                view = view[view["priority"].isin(priority_filter)]
            if search_ann.strip():
                q = search_ann.strip().lower()
                view = view[view["title"].fillna("").str.lower().str.contains(q)
                            | view["body"].fillna("").str.lower().str.contains(q)]

            st.caption(f"Знайдено оголошень: {len(view)}")
            for _, a in view.iterrows():
                badge = "⭐ " if a["priority"] == "⭐ Важливе" else ""
                with st.container(border=True):
                    hc1, hc2 = st.columns([5, 1])
                    with hc1:
                        st.markdown(f"**{badge}{a['title']}**")
                        st.caption(f"{a['created_at']} · {a['event']} · Отримувач: {a['target']} "
                                   f"· Аудиторія: {a['audience']}"
                                   + (f" · Автор: {a['created_by_name']}" if a['created_by_name'] else ""))
                    with hc2:
                        if st.button("🗑️ Видалити", key=f"del_ann_{a['id']}"):
                            execute("DELETE FROM announcements WHERE id=?", (int(a["id"]),))
                            st.rerun()
                    st.write(a["body"])
                    if a["email_status"]:
                        st.caption(f"📧 Email-дублікати: {a['email_status']}")

    # ================================================================
    # 📊 ОГЛЯД ОХОПЛЕННЯ
    # ================================================================
    with tab_stats:
        stats_all = query_df("""SELECT a.id, COALESCE(e.title,'Глобальне') AS event,
                                        COALESCE(a.priority,'Звичайне') AS priority, a.email_status
                                 FROM announcements a LEFT JOIN events e ON a.event_id=e.id""")
        if stats_all.empty:
            st.info("Ще немає даних для статистики — опублікуйте перше оголошення.")
        else:
            total_ann = len(stats_all)
            important_ann = int((stats_all["priority"] == "⭐ Важливе").sum())
            with_email = int(stats_all["email_status"].notna().sum())
            sc1, sc2, sc3 = st.columns(3)
            sc1.metric("Всього оголошень", total_ann)
            sc2.metric("⭐ Важливих", important_ann)
            sc3.metric("З email-дублюванням", with_email)

            st.markdown("#### Оголошення за подіями")
            by_event = stats_all.groupby("event").size().reset_index(name="Оголошень")
            chart_ann = alt.Chart(by_event).mark_bar(cornerRadiusTopLeft=6, cornerRadiusTopRight=6).encode(
                x=alt.X("Оголошень:Q"),
                y=alt.Y("event:N", sort="-x", title="Подія"),
                color=alt.Color("Оголошень:Q", scale=alt.Scale(scheme="blues"), legend=None),
                tooltip=["event", "Оголошень"],
            ).properties(height=max(160, 32 * len(by_event)))
            st.altair_chart(chart_ann, use_container_width=True)

            st.markdown("#### Скільки учасників побачить кожне активне оголошення")
            reach_rows = []
            active_events = query_df("""SELECT a.id, a.title, a.event_id, a.target_team_id
                                         FROM announcements a WHERE a.event_id IS NOT NULL""")
            for _, a in active_events.iterrows():
                if a["target_team_id"]:
                    n = query_one("SELECT COUNT(*) FROM team_members WHERE team_id=?", (int(a["target_team_id"]),))[0]
                else:
                    n = query_one("""SELECT COUNT(*) FROM team_members tm
                                      JOIN teams t ON tm.team_id=t.id WHERE t.event_id=?""",
                                   (int(a["event_id"]),))[0]
                reach_rows.append({"Оголошення": a["title"], "Учасників охоплено": n})
            global_ann_count = len(stats_all) - len(active_events)
            if global_ann_count > 0:
                total_participants = query_one("SELECT COUNT(*) FROM users WHERE role='participant'")[0]
                reach_rows.append({"Оголошення": f"Глобальні оголошення ({global_ann_count} шт.)",
                                    "Учасників охоплено": total_participants})
            if reach_rows:
                st.dataframe(pd.DataFrame(reach_rows), use_container_width=True, hide_index=True)


EXPORT_TABLES = ["events", "teams", "team_members", "users", "scores", "criteria", "nominations",
                  "submissions", "files", "mentor_slots", "announcements", "showcase_likes",
                  "email_log", "team_status_log"]


def get_exportable_df(table_name):
    """Повертає DataFrame таблиці для експорту, приховуючи чутливі/важкі поля."""
    if table_name == "users":
        return query_df("""SELECT id, username, role, full_name, email, university, faculty, created_at
                            FROM users""")
    if table_name == "files":
        return query_df("SELECT id, submission_id, filename, mimetype, uploaded_at FROM files")
    return query_df(f"SELECT * FROM {table_name}")


def _df_to_csv_bytes(df):
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    return buf.getvalue()


def _dfs_to_excel_bytes(sheets: dict):
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        for name, df in sheets.items():
            df.to_excel(writer, index=False, sheet_name=name[:31])
    return buf.getvalue()


def admin_import_export():
    st.subheader("📤 Імпорт / Експорт даних")
    tab_export, tab_import, tab_backup = st.tabs(
        ["📥 Експорт", "📤 Імпорт", "🗄️ Резервне копіювання"])

    # ================================================================
    # 📥 ЕКСПОРТ
    # ================================================================
    with tab_export:
        st.markdown("#### Експорт однієї таблиці")
        table_choice = st.selectbox("Таблиця для експорту", EXPORT_TABLES)
        df = get_exportable_df(table_choice)
        st.caption(f"Рядків: {len(df)}")
        st.dataframe(df, use_container_width=True, hide_index=True)
        col1, col2 = st.columns(2)
        with col1:
            st.download_button(f"⬇️ {table_choice}.csv", _df_to_csv_bytes(df),
                                file_name=f"{table_choice}.csv", mime="text/csv")
        with col2:
            st.download_button(f"⬇️ {table_choice}.xlsx", _dfs_to_excel_bytes({table_choice: df}),
                                file_name=f"{table_choice}.xlsx",
                                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

        st.markdown("---")
        st.markdown("#### 🗄️ Повний бекап у Excel (усі таблиці одразу)")
        st.caption("Один файл із окремим аркушем на кожну таблицю платформи (без паролів і без бінарних файлів презентацій).")
        if st.button("Сформувати повний Excel-бекап"):
            sheets = {t: get_exportable_df(t) for t in EXPORT_TABLES}
            data = _dfs_to_excel_bytes(sheets)
            st.download_button("⬇️ Завантажити CampusBridge_full_backup.xlsx", data,
                                file_name=f"CampusBridge_full_backup_{datetime.date.today()}.xlsx",
                                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                key="full_backup_dl")

        st.markdown("---")
        st.markdown("#### 🎯 Пакетний експорт по одній події")
        st.caption("Усі дані, пов'язані з обраною подією (команди, учасники, подачі, оцінки, критерії, "
                   "номінації, слоти консультацій) — в один Excel-файл.")
        events_exp = get_events()
        if events_exp.empty:
            st.info("Подій ще немає.")
        else:
            ev_map_exp = dict(zip(events_exp["title"], events_exp["id"]))
            ev_title_exp = st.selectbox("Подія", list(ev_map_exp.keys()), key="export_event_select")
            ev_id_exp = ev_map_exp[ev_title_exp]
            if st.button("Сформувати пакет по події"):
                ev_df = query_df("SELECT * FROM events WHERE id=?", (ev_id_exp,))
                teams_df = query_df("SELECT * FROM teams WHERE event_id=?", (ev_id_exp,))
                members_df = query_df("""SELECT tm.team_id, u.full_name, u.email, u.faculty
                                          FROM team_members tm JOIN teams t ON tm.team_id=t.id
                                          JOIN users u ON tm.user_id=u.id WHERE t.event_id=?""", (ev_id_exp,))
                submissions_df = query_df("""SELECT s.* FROM submissions s
                                              JOIN teams t ON s.team_id=t.id WHERE t.event_id=?""", (ev_id_exp,))
                scores_df = query_df("""SELECT s.* FROM scores s
                                         JOIN teams t ON s.team_id=t.id WHERE t.event_id=?""", (ev_id_exp,))
                criteria_df = query_df("SELECT * FROM criteria WHERE event_id=?", (ev_id_exp,))
                nominations_df = query_df("SELECT * FROM nominations WHERE event_id=?", (ev_id_exp,))
                mentor_slots_df = query_df("SELECT * FROM mentor_slots WHERE event_id=?", (ev_id_exp,))
                package = {
                    "Event": ev_df, "Teams": teams_df, "Team_Members": members_df,
                    "Submissions": submissions_df, "Scores": scores_df, "Criteria": criteria_df,
                    "Nominations": nominations_df, "Mentor_Slots": mentor_slots_df,
                }
                data_pkg = _dfs_to_excel_bytes(package)
                safe_title = "".join(ch if ch.isalnum() else "_" for ch in ev_title_exp)[:40]
                st.download_button(f"⬇️ Завантажити {safe_title}.xlsx", data_pkg,
                                    file_name=f"{safe_title}_export.xlsx",
                                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                    key="event_package_dl")

    # ================================================================
    # 📤 ІМПОРТ
    # ================================================================
    with tab_import:
        st.markdown("#### Імпорт команд (масове попереднє додавання)")
        st.caption("Очікувані колонки: `event_id`, `name`, `faculty`, `status` (необов'язково).")
        st.download_button("📄 Завантажити шаблон teams_template.csv",
                            _df_to_csv_bytes(pd.DataFrame([{"event_id": 1, "name": "Приклад Команди",
                                                             "faculty": MAIN_FACULTY, "status": "На розгляді"}])),
                            file_name="teams_template.csv", mime="text/csv", key="tmpl_teams")
        up = st.file_uploader("Завантажте CSV або Excel файл із командами", type=["csv", "xlsx"], key="import_teams")
        if up is not None:
            try:
                imp_df = pd.read_csv(up) if up.name.endswith(".csv") else pd.read_excel(up)
                missing_cols = {"event_id", "name"} - set(imp_df.columns)
                if missing_cols:
                    st.error(f"У файлі бракує обов'язкових колонок: {', '.join(missing_cols)}")
                else:
                    valid_event_ids = set(query_df("SELECT id FROM events")["id"].tolist())
                    bad_rows = imp_df[~imp_df["event_id"].isin(valid_event_ids)]
                    if not bad_rows.empty:
                        st.warning(f"⚠️ {len(bad_rows)} рядк(ів) посилаються на неіснуючий event_id і будуть пропущені "
                                   f"при імпорті: {sorted(bad_rows['event_id'].unique().tolist())}")
                    st.dataframe(imp_df, use_container_width=True, hide_index=True)
                    if st.button("Підтвердити імпорт команд"):
                        count, skipped = 0, 0
                        affected_events = set()
                        for _, r in imp_df.iterrows():
                            if r.get("event_id") not in valid_event_ids or not r.get("name"):
                                skipped += 1
                                continue
                            ev_id_val = int(r.get("event_id"))
                            execute("""INSERT INTO teams (event_id,nomination_id,name,captain_id,invite_code,
                                       faculty,status,status_comment,created_at) VALUES (?,?,?,?,?,?,?,?,?)""",
                                    (ev_id_val, None, r.get("name"), None, gen_code(),
                                     r.get("faculty", ""), r.get("status", "На розгляді"), "", now()))
                            affected_events.add(ev_id_val)
                            count += 1
                        for eid in affected_events:
                            maybe_autoclose_registration(eid)
                        st.success(f"Імпортовано {count} команд(и)." + (f" Пропущено: {skipped}." if skipped else ""))
            except Exception as e:
                st.error(f"Помилка обробки файлу: {e}")

        st.markdown("---")
        st.markdown("#### Імпорт подій (масове створення)")
        st.caption("Очікувані колонки: `title` (обов'язково), `category`, `format`, `description`, `status`, "
                   "`reg_start`, `reg_end`, `event_start`, `pitch_deadline`, `prize_fund`, `banner_url`, `video_url`.")
        st.download_button("📄 Завантажити шаблон events_template.csv",
                            _df_to_csv_bytes(pd.DataFrame([{
                                "title": "Приклад Хакатону", "category": "IT", "format": "Онлайн",
                                "description": "", "status": "Чернетка", "reg_start": "2026-10-01",
                                "reg_end": "2026-10-15", "event_start": "2026-10-20", "pitch_deadline": "2026-10-22",
                                "prize_fund": "10 000 грн", "banner_url": "", "video_url": ""}])),
                            file_name="events_template.csv", mime="text/csv", key="tmpl_events")
        up2 = st.file_uploader("Завантажте CSV або Excel файл із подіями", type=["csv", "xlsx"], key="import_events")
        if up2 is not None:
            try:
                imp_df2 = pd.read_csv(up2) if up2.name.endswith(".csv") else pd.read_excel(up2)
                if "title" not in imp_df2.columns:
                    st.error("У файлі бракує обов'язкової колонки `title`.")
                else:
                    st.dataframe(imp_df2, use_container_width=True, hide_index=True)
                    if st.button("Підтвердити імпорт подій"):
                        count, skipped = 0, 0
                        for _, r in imp_df2.iterrows():
                            if not r.get("title"):
                                skipped += 1
                                continue
                            execute("""INSERT INTO events (title,category,format,description,regulations,reg_start,reg_end,
                                       event_start,pitch_deadline,min_team,max_team,prize_fund,status,leaderboard_live,
                                       avoid_conflict,university,faculty,created_by,created_at,double_blind,banner_url,video_url)
                                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                                    (r.get("title"), r.get("category", "IT"), r.get("format", "Онлайн"),
                                     r.get("description", ""), "", r.get("reg_start", ""), r.get("reg_end", ""),
                                     r.get("event_start", ""), r.get("pitch_deadline", ""), 2, 5,
                                     r.get("prize_fund", ""), r.get("status", "Чернетка"),
                                     0, 1, MAIN_UNIVERSITY, MAIN_FACULTY, st.session_state.user["id"], now(), 0,
                                     r.get("banner_url", ""), r.get("video_url", "")))
                            count += 1
                        st.success(f"Імпортовано {count} подій(ї)." + (f" Пропущено: {skipped}." if skipped else ""))
            except Exception as e:
                st.error(f"Помилка обробки файлу: {e}")

        st.markdown("---")
        st.markdown("#### Імпорт критеріїв оцінювання")
        st.caption("Очікувані колонки: `event_id`, `name`, `weight` (%), `max_score`.")
        st.download_button("📄 Завантажити шаблон criteria_template.csv",
                            _df_to_csv_bytes(pd.DataFrame([{"event_id": 1, "name": "Інноваційність",
                                                             "weight": 30, "max_score": 10}])),
                            file_name="criteria_template.csv", mime="text/csv", key="tmpl_criteria")
        up3 = st.file_uploader("Завантажте CSV або Excel файл із критеріями", type=["csv", "xlsx"], key="import_criteria")
        if up3 is not None:
            try:
                imp_df3 = pd.read_csv(up3) if up3.name.endswith(".csv") else pd.read_excel(up3)
                missing3 = {"event_id", "name", "weight", "max_score"} - set(imp_df3.columns)
                if missing3:
                    st.error(f"У файлі бракує обов'язкових колонок: {', '.join(missing3)}")
                else:
                    valid_event_ids3 = set(query_df("SELECT id FROM events")["id"].tolist())
                    st.dataframe(imp_df3, use_container_width=True, hide_index=True)
                    if st.button("Підтвердити імпорт критеріїв"):
                        count, skipped = 0, 0
                        for _, r in imp_df3.iterrows():
                            if r.get("event_id") not in valid_event_ids3:
                                skipped += 1
                                continue
                            execute("INSERT INTO criteria (event_id,name,weight,max_score) VALUES (?,?,?,?)",
                                    (int(r.get("event_id")), r.get("name"), float(r.get("weight")), float(r.get("max_score"))))
                            count += 1
                        st.success(f"Імпортовано {count} критеріїв." + (f" Пропущено: {skipped}." if skipped else ""))
            except Exception as e:
                st.error(f"Помилка обробки файлу: {e}")

        st.markdown("---")
        st.markdown("#### Імпорт номінацій")
        st.caption("Очікувані колонки: `event_id`, `name`.")
        st.download_button("📄 Завантажити шаблон nominations_template.csv",
                            _df_to_csv_bytes(pd.DataFrame([{"event_id": 1, "name": "AI / Machine Learning"}])),
                            file_name="nominations_template.csv", mime="text/csv", key="tmpl_noms")
        up4 = st.file_uploader("Завантажте CSV або Excel файл із номінаціями", type=["csv", "xlsx"], key="import_noms")
        if up4 is not None:
            try:
                imp_df4 = pd.read_csv(up4) if up4.name.endswith(".csv") else pd.read_excel(up4)
                missing4 = {"event_id", "name"} - set(imp_df4.columns)
                if missing4:
                    st.error(f"У файлі бракує обов'язкових колонок: {', '.join(missing4)}")
                else:
                    valid_event_ids4 = set(query_df("SELECT id FROM events")["id"].tolist())
                    st.dataframe(imp_df4, use_container_width=True, hide_index=True)
                    if st.button("Підтвердити імпорт номінацій"):
                        count, skipped = 0, 0
                        for _, r in imp_df4.iterrows():
                            if r.get("event_id") not in valid_event_ids4 or not r.get("name"):
                                skipped += 1
                                continue
                            execute("INSERT INTO nominations (event_id, name) VALUES (?,?)",
                                    (int(r.get("event_id")), r.get("name")))
                            count += 1
                        st.success(f"Імпортовано {count} номінацій." + (f" Пропущено: {skipped}." if skipped else ""))
            except Exception as e:
                st.error(f"Помилка обробки файлу: {e}")

    # ================================================================
    # 🗄️ РЕЗЕРВНЕ КОПІЮВАННЯ
    # ================================================================
    with tab_backup:
        st.markdown("#### 📦 Стан бази даних")
        db_size_mb = round(os.path.getsize(DB_PATH) / (1024 * 1024), 2) if os.path.exists(DB_PATH) else 0
        row_counts = []
        for t in ["events", "teams", "team_members", "users", "scores", "submissions", "files",
                  "mentor_slots", "announcements", "showcase_likes", "email_log"]:
            n = query_one(f"SELECT COUNT(*) FROM {t}")[0]
            row_counts.append({"Таблиця": t, "Рядків": n})
        bc1, bc2 = st.columns([1, 2])
        with bc1:
            st.metric("Розмір файлу БД", f"{db_size_mb} МБ")
        with bc2:
            st.dataframe(pd.DataFrame(row_counts), use_container_width=True, hide_index=True)

        st.markdown("---")
        st.markdown("#### ⬇️ Завантажити повну резервну копію (.db)")
        st.caption("Файл SQLite з усіма даними платформи (включно з бінарними презентаціями). "
                   "Зберігайте його в надійному місці — він містить хеші паролів усіх користувачів.")
        if os.path.exists(DB_PATH):
            with open(DB_PATH, "rb") as f:
                db_bytes = f.read()
            st.download_button("⬇️ Завантажити campusbridge_backup.db", db_bytes,
                                file_name=f"campusbridge_backup_{datetime.date.today()}.db",
                                mime="application/octet-stream")
        else:
            st.warning("Файл бази даних не знайдено.")

        st.markdown("---")
        with st.expander("⚠️ Небезпечна зона: відновлення з резервної копії"):
            st.error("Ця дія повністю замінить поточну базу даних платформи завантаженим файлом. "
                     "Усі поточні дані (події, команди, оцінки тощо) будуть безповоротно втрачені, "
                     "якщо ви не зробили власний бекап заздалегідь.")
            restore_file = st.file_uploader("Файл резервної копії (.db)", type=["db"], key="restore_db")
            confirm_text = st.text_input("Для підтвердження введіть слово: ПІДТВЕРДЖУЮ")
            confirm_checkbox = st.checkbox("Я розумію наслідки та маю власний бекап поточних даних")
            if st.button("🗄️ Відновити базу даних з файлу", type="primary"):
                if restore_file is None:
                    st.error("Спочатку завантажте .db файл.")
                elif confirm_text.strip() != "ПІДТВЕРДЖУЮ" or not confirm_checkbox:
                    st.error("Підтвердіть дію: введіть слово ПІДТВЕРДЖУЮ та встановіть позначку вище.")
                else:
                    try:
                        with open(DB_PATH, "wb") as f:
                            f.write(restore_file.getvalue())
                        st.success("Базу даних відновлено з резервної копії. Перезавантажте сторінку.")
                        logout()
                    except Exception as e:
                        st.error(f"Не вдалося відновити базу даних: {e}")


def page_admin_dashboard():
    st.subheader(f"🏠 Вітаємо, {st.session_state.user['full_name'].split(' ')[0]}!")
    st.caption("Швидкий огляд стану платформи та того, що потребує вашої уваги.")

    events_all = get_events()
    total_events = len(events_all)
    total_teams = query_one("SELECT COUNT(*) FROM teams")[0]
    pending_teams = query_one("SELECT COUNT(*) FROM teams WHERE status='На розгляді'")[0]
    total_members = query_one("SELECT COUNT(*) FROM team_members")[0]

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Подій", total_events)
    k2.metric("Команд усього", total_teams)
    k3.metric("⏳ Очікують розгляду", pending_teams)
    k4.metric("Учасників", total_members)

    st.markdown("#### ⚡ Швидкі дії")
    nb1, nb2, nb3, nb4, nb5 = st.columns(5)
    with nb1:
        st.button("📥 Модерація заявок", use_container_width=True,
                   on_click=_goto, args=("admin_menu", "📥 Модерація заявок"))
    with nb2:
        st.button("🛠️ Конструктор подій", use_container_width=True,
                   on_click=_goto, args=("admin_menu", "🛠️ Конструктор подій"))
    with nb3:
        st.button("📊 Аналітика", use_container_width=True,
                   on_click=_goto, args=("admin_menu", "📊 Аналітика та звіти"))
    with nb4:
        st.button("📢 Сповіщення", use_container_width=True,
                   on_click=_goto, args=("admin_menu", "📢 Сповіщення"))
    with nb5:
        if st.button("🔄 Оновити дашборд", use_container_width=True):
            st.rerun()

    st.markdown("---")
    st.markdown("#### 🔔 Потребує уваги")
    attention_items = []

    if pending_teams:
        attention_items.append(("📥", f"**{pending_teams}** заявок команд очікують модерації",
                                 "Перейдіть у розділ «📥 Модерація заявок»."))

    unanswered_q = get_unanswered_questions_count()
    if unanswered_q:
        attention_items.append(("💬", f"**{unanswered_q}** питань від команд ще без відповіді",
                                 "Відповіді можна дати в розділі «📥 Модерація заявок» під кожною командою."))

    today = datetime.date.today()
    upcoming_milestones = []
    if not events_all.empty:
        for _, ev in events_all.iterrows():
            pitch_dt = parse_date_flexible(ev.get("pitch_deadline"))
            if pitch_dt and 0 <= (pitch_dt.date() - today).days <= 7:
                days_left = (pitch_dt.date() - today).days
                label = "сьогодні" if days_left == 0 else f"через {days_left} дн."
                attention_items.append(("🏁", f"Дедлайн пітчингу події «{ev['title']}» — {label} ({ev['pitch_deadline']})",
                                         "Перевірте готовність журі та менторів."))
            if ev.get("max_teams") and ev["status"] == "Реєстрація відкрита":
                cnt = query_one("SELECT COUNT(*) FROM teams WHERE event_id=?", (ev["id"],))[0]
                if cnt / ev["max_teams"] >= 0.9:
                    attention_items.append(("📈", f"Подія «{ev['title']}»: заповнено {cnt}/{int(ev['max_teams'])} "
                                             "місць — реєстрація скоро автозакриється", ""))
            for label, date_str in [("Старт реєстрації", ev.get("reg_start")), ("Кінець реєстрації", ev.get("reg_end")),
                                     ("Старт події", ev.get("event_start")), ("Пітчинг", ev.get("pitch_deadline"))]:
                dt = parse_date_flexible(date_str)
                if dt and 0 <= (dt.date() - today).days <= 14:
                    upcoming_milestones.append({"Дата": dt.date(), "Подія": ev["title"], "Етап": label})

    for _, ev in events_all.iterrows() if not events_all.empty else []:
        anomalies = detect_anomalies(int(ev["id"]))
        if not anomalies.empty:
            attention_items.append(("⚠️", f"У події «{ev['title']}» виявлено {len(anomalies)} аномальних оцінок",
                                     "Перевірте в «📊 Аналітика та звіти» → «Оцінювання»."))

    if not attention_items:
        st.success("✅ Наразі нічого термінового не потребує вашої уваги.")
    else:
        for icon, text, hint in attention_items[:10]:
            with st.container(border=True):
                st.markdown(f"{icon} {text}")
                if hint:
                    st.caption(hint)

    if upcoming_milestones:
        st.markdown("#### 🗓️ Найближчі 14 днів")
        milestones_df = pd.DataFrame(upcoming_milestones).sort_values("Дата")
        st.dataframe(milestones_df, use_container_width=True, hide_index=True)

    st.markdown("---")
    st.markdown("#### 📊 Динаміка та розподіл")
    dc1, dc2 = st.columns(2)
    teams_all_dash = query_df("""SELECT t.*, e.category AS event_category FROM teams t
                                  JOIN events e ON t.event_id=e.id""")
    with dc1:
        st.markdown("**Реєстрації команд за останні 14 днів**")
        if not teams_all_dash.empty:
            trend_df = teams_all_dash.copy()
            trend_df["Дата"] = trend_df["created_at"].apply(_parse_created_date)
            trend_df = trend_df.dropna(subset=["Дата"])
            trend_df = trend_df[trend_df["Дата"] >= (today - timedelta(days=14))]
            if not trend_df.empty:
                daily = trend_df.groupby("Дата").size().reset_index(name="Нових команд")
                chart = alt.Chart(daily).mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4).encode(
                    x=alt.X("Дата:T"), y=alt.Y("Нових команд:Q"),
                    color=alt.value("#4F8BF9"), tooltip=["Дата:T", "Нових команд:Q"],
                ).properties(height=240)
                st.altair_chart(chart, use_container_width=True)
            else:
                st.caption("За останні 14 днів нових реєстрацій не було.")
        else:
            st.caption("Команд ще немає.")
    with dc2:
        st.markdown("**Заявки за статусами (усі події)**")
        if not teams_all_dash.empty:
            status_counts = teams_all_dash.groupby("status").size().reindex(TEAM_STATUSES).fillna(0).reset_index()
            status_counts.columns = ["Статус", "Команд"]
            donut = alt.Chart(status_counts).mark_arc(innerRadius=55).encode(
                theta=alt.Theta("Команд:Q"),
                color=alt.Color("Статус:N", scale=alt.Scale(domain=TEAM_STATUSES,
                                 range=["#4F8BF9", "#27AE60", "#F1C40F", "#E74C3C"])),
                tooltip=["Статус", "Команд"],
            ).properties(height=240)
            st.altair_chart(donut, use_container_width=True)
        else:
            st.caption("Команд ще немає.")

    st.markdown("#### 👥 Навантаження команди організаторів")
    oc1, oc2 = st.columns(2)
    with oc1:
        n_jury = query_one("SELECT COUNT(*) FROM users WHERE role='jury'")[0]
        jury_progress = query_df("""SELECT ja.jury_id, ja.event_id FROM jury_assignments ja""")
        avg_jury_pct = None
        if not jury_progress.empty:
            pct_list = []
            for _, row in jury_progress.drop_duplicates().iterrows():
                crit_count = query_one("SELECT COUNT(*) FROM criteria WHERE event_id=?", (int(row["event_id"]),))[0]
                teams_ev = query_df("SELECT id FROM teams WHERE event_id=? AND status='Прийнято'", (int(row["event_id"]),))
                if teams_ev.empty or not crit_count:
                    continue
                scored = 0
                for _, tt in teams_ev.iterrows():
                    cnt = query_one("SELECT COUNT(DISTINCT criterion_id) FROM scores WHERE team_id=? AND jury_id=?",
                                     (int(tt["id"]), int(row["jury_id"])))[0]
                    if cnt >= crit_count:
                        scored += 1
                pct_list.append(scored / len(teams_ev) * 100)
            avg_jury_pct = round(sum(pct_list) / len(pct_list), 1) if pct_list else 0
        st.metric("Журі в системі", n_jury)
        if avg_jury_pct is not None:
            st.metric("Середній прогрес оцінювання", f"{avg_jury_pct}%")
            st.progress(min(avg_jury_pct / 100, 1.0))
    with oc2:
        n_mentors = query_one("SELECT COUNT(*) FROM users WHERE role='mentor'")[0]
        total_slots_all = query_one("SELECT COUNT(*) FROM mentor_slots")[0]
        booked_slots_all = query_one("SELECT COUNT(*) FROM mentor_slots WHERE is_booked=1")[0]
        st.metric("Менторів у системі", n_mentors)
        if total_slots_all:
            occ_pct = round(booked_slots_all / total_slots_all * 100, 1)
            st.metric("Заповненість Office Hours", f"{occ_pct}%")
            st.progress(min(occ_pct / 100, 1.0))
        else:
            st.caption("Слотів консультацій ще не створено.")

    st.markdown("---")
    st.markdown("#### 🕓 Останні дії на платформі")
    ac1, ac2 = st.columns(2)
    with ac1:
        st.markdown("**Нещодавно змінені статуси заявок**")
        recent_status = query_df("""SELECT changed_at, new_status, changed_by_name FROM team_status_log
                                     ORDER BY changed_at DESC LIMIT 5""")
        if recent_status.empty:
            st.caption("Ще не було змін статусів.")
        else:
            for _, r in recent_status.iterrows():
                st.caption(f"{r['changed_at'][:16]} · → «{r['new_status']}» ({r['changed_by_name'] or '—'})")
    with ac2:
        st.markdown("**Останні подані проєкти**")
        recent_subs = query_df("""SELECT s.updated_at, t.name AS team FROM submissions s
                                   JOIN teams t ON s.team_id=t.id ORDER BY s.updated_at DESC LIMIT 5""")
        if recent_subs.empty:
            st.caption("Подач ще не було.")
        else:
            for _, r in recent_subs.iterrows():
                st.caption(f"{r['updated_at'][:16]} · «{r['team']}»")

    st.markdown("---")
    st.markdown("#### ⚡ Дія одним кліком")
    no_sub_teams = query_df("""SELECT t.id, t.name FROM teams t
                                WHERE t.status='Прийнято'
                                AND t.id NOT IN (SELECT DISTINCT team_id FROM submissions)""")
    if no_sub_teams.empty:
        st.caption("✅ Усі прийняті команди вже подали проєкт — нагадування не потрібне.")
    else:
        st.caption(f"⚠️ {len(no_sub_teams)} прийнятих команд ще не подали проєкт.")
        if st.button(f"📧 Надіслати нагадування {len(no_sub_teams)} командам без поданого проєкту"):
            results = []
            for _, tt in no_sub_teams.iterrows():
                r = send_announcement_email(
                    int(tt["id"]), "Нагадування: подайте проєкт",
                    "Ми ще не отримали подачу проєкту від вашої команди. Будь ласка, завантажте опис, "
                    "посилання на репозиторій і презентацію в особистому кабінеті («🚀 Моя команда») "
                    "якнайшвидше — це важливо для участі в оцінюванні.")
                if r:
                    results.append(r)
            sent = sum(1 for r in results if r == "sent")
            simulated = sum(1 for r in results if r == "simulated")
            opted_out = sum(1 for r in results if r == "skipped_opt_out")
            failed = sum(1 for r in results if r.startswith("failed"))
            st.success(f"Готово — реально надіслано: {sent} · симульовано: {simulated} · "
                       f"пропущено (вимкнули сповіщення): {opted_out} · помилок: {failed}")


def page_admin():
    st.sidebar.markdown("### 👑 Меню адміністратора")
    menu = st.sidebar.radio("Розділ", [
        "🏠 Дашборд", "🛠️ Конструктор подій", "📥 Модерація заявок", "⚖️ Журі", "🧑‍🏫 Ментори",
        "📊 Аналітика та звіти", "📢 Сповіщення", "📤 Імпорт/Експорт", "🏆 Лідерборд",
        "🖼️ Портфоліо проєктів", "👤 Мій профіль"
    ], key="admin_menu")
    if menu == "🏠 Дашборд":
        page_admin_dashboard()
    elif menu == "🛠️ Конструктор подій":
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
    elif menu == "👤 Мій профіль":
        page_my_profile()


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
        # самозцілення: якщо ліміт команд вже вичерпано (наприклад, після зміни адміном),
        # закриваємо реєстрацію ще до показу форми
        for _, ev_row in events.iterrows():
            maybe_autoclose_registration(int(ev_row["id"]))
        events = get_events("Реєстрація відкрита")
        if events.empty:
            st.info("Наразі немає подій з відкритою реєстрацією.")
        else:
            with st.form("create_team_form"):
                ev_map = dict(zip(events["title"], events["id"]))
                ev_title = st.selectbox("Подія", list(ev_map.keys()))
                ev_id = ev_map[ev_title]

                ev_limit = query_one("SELECT max_teams FROM events WHERE id=?", (ev_id,))
                if ev_limit and ev_limit[0]:
                    reg_count = query_one("SELECT COUNT(*) FROM teams WHERE event_id=?", (ev_id,))[0]
                    st.caption(f"Заповнено місць: {reg_count} / {ev_limit[0]}")

                noms = query_df("SELECT id, name FROM nominations WHERE event_id=?", (ev_id,))
                nom_id = None
                if not noms.empty:
                    nmap = dict(zip(noms["name"], noms["id"]))
                    nom_name = st.selectbox("Номінація", list(nmap.keys()))
                    nom_id = nmap[nom_name]
                team_name = st.text_input("Назва команди")
                faculty = st.text_input("Факультет", value=user.get("faculty") or MAIN_FACULTY)
                if st.form_submit_button("Створити команду") and team_name:
                    # перевірка унікальності: чи не в іншій команді на цю ж подію вже цей учасник
                    dup = get_user_team_for_event(user["id"], ev_id)
                    ev_check = query_one("SELECT max_teams, status FROM events WHERE id=?", (ev_id,))
                    current_count = query_one("SELECT COUNT(*) FROM teams WHERE event_id=?", (ev_id,))[0]
                    if dup:
                        st.error(f"Ви вже зареєстровані в команді «{dup[1]}» на цю подію. "
                                 "Участь в кількох командах на одну й ту саму подію заборонена.")
                    elif ev_check and ev_check[1] != "Реєстрація відкрита":
                        st.error("На жаль, реєстрацію на цю подію щойно закрито. Оберіть іншу подію.")
                    elif ev_check and ev_check[0] and current_count >= ev_check[0]:
                        execute("UPDATE events SET status='Закрито' WHERE id=?", (ev_id,))
                        st.error("На жаль, ліміт команд на цю подію вичерпано. Реєстрацію закрито.")
                    else:
                        code = gen_code()
                        tid = execute("""INSERT INTO teams (event_id,nomination_id,name,captain_id,invite_code,
                                         faculty,status,status_comment,created_at) VALUES (?,?,?,?,?,?,?,?,?)""",
                                      (ev_id, nom_id, team_name, user["id"], code, faculty, "На розгляді", "", now()))
                        execute("INSERT INTO team_members (team_id,user_id,joined_at) VALUES (?,?,?)",
                                (tid, user["id"], now()))
                        st.success(f"Команду створено! Інвайт-код для запрошення учасників: **{code}**")
                        if closed_now:
                            st.info("ℹ️ Це була остання вільна квота — реєстрацію на подію щойно автоматично закрито.")
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
                    dup = get_user_team_for_event(user["id"], ev_id)
                    if already:
                        st.warning("Ви вже у цій команді.")
                    elif dup:
                        st.error(f"Ви вже зареєстровані в команді «{dup[1]}» на цю подію. "
                                 "Спочатку вийдіть з поточної команди, щоб приєднатись до іншої.")
                    else:
                        ev = query_one("SELECT max_team FROM events WHERE id=?", (ev_id,))
                        current_count = query_one("SELECT COUNT(*) FROM team_members WHERE team_id=?", (tid,))[0]
                        if ev and current_count >= ev[0]:
                            st.error("Команда вже заповнена (досягнуто максимальної кількості учасників).")
                        else:
                            execute("INSERT INTO team_members (team_id,user_id,joined_at) VALUES (?,?,?)",
                                    (tid, user["id"], now()))
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

                with st.expander("📧 Запросити учасника на email"):
                    st.caption("Надішле інвайт-код на вказану пошту — зручно, якщо не хочете передавати "
                               "код повідомленням вручну.")
                    invite_cols = st.columns([3, 1])
                    with invite_cols[0]:
                        invite_email = st.text_input("Email запрошеного", key=f"invite_email_{t['id']}",
                                                       label_visibility="collapsed",
                                                       placeholder="friend@vspu.edu.ua")
                    with invite_cols[1]:
                        if st.button("Надіслати", key=f"invite_send_{t['id']}") and invite_email.strip():
                            inv_status = send_team_invite_email(int(t["id"]), invite_email.strip())
                            if inv_status == "sent":
                                st.success("Запрошення реально надіслано на пошту.")
                            elif inv_status == "simulated":
                                st.info("SMTP ще не налаштовано — запрошення симульовано. "
                                        "Передайте інвайт-код вручну або попросіть адміністратора налаштувати SMTP.")
                            elif inv_status and inv_status.startswith("failed"):
                                st.warning(f"Не вдалося надіслати: {inv_status}")

                with st.expander("📱 QR-код для офлайн-приєднання"):
                    st.caption("Покажіть цей код на екрані під час реєстрації на хакатоні — новий учасник "
                               "відсканує його камерою телефону й одразу побачить інвайт-код.")
                    st.image(qr_code_url(t["invite_code"]), width=180)
                    st.caption(f"Закодований інвайт-код: `{t['invite_code']}`")

                if t["status"] == "Прийнято":
                    if not PDF_LIB_AVAILABLE:
                        st.caption("🎓 Сертифікат участі буде доступний, коли на сервері встановлять пакет `reportlab`.")
                    else:
                        cert_bytes = generate_team_certificate_pdf(int(t["id"]))
                        if cert_bytes:
                            st.download_button(
                                "🎓 Завантажити сертифікат участі (PDF)", data=cert_bytes,
                                file_name=f"certificate_{t['name'][:30].replace(' ', '_')}.pdf",
                                mime="application/pdf", key=f"my_cert_dl_{t['id']}")

                with st.expander("💬 Питання до організаторів"):
                    with st.form(f"ask_question_form_{t['id']}"):
                        new_question = st.text_area("Ваше запитання", key=f"q_text_{t['id']}",
                                                      placeholder="Наприклад: чи можна змінити склад команди "
                                                                  "після дедлайну реєстрації?")
                        if st.form_submit_button("📨 Надіслати запитання") and new_question.strip():
                            ask_team_question(int(t["id"]), new_question.strip())
                            st.success("Запитання надіслано організаторам. Відповідь з'явиться тут.")
                            st.rerun()

                    questions_df = get_team_questions(int(t["id"]))
                    if questions_df.empty:
                        st.caption("Запитань ще не було.")
                    else:
                        for _, q in questions_df.iterrows():
                            with st.container(border=True):
                                st.write(f"❓ **{q['question']}**")
                                st.caption(f"Запитав(ла): {q['asked_by_name']} · {q['asked_at'][:16]}")
                                if q["answer"]:
                                    st.success(f"💬 {q['answer']}")
                                    st.caption(f"Відповів(ла): {q['answered_by_name']} · {q['answered_at'][:16]}")
                                else:
                                    st.info("⏳ Очікує відповіді організаторів.")

                members_full = query_df("""SELECT tm.id AS membership_id, u.id AS user_id, u.full_name, u.email
                                            FROM team_members tm JOIN users u ON tm.user_id=u.id
                                            WHERE tm.team_id=? ORDER BY tm.id""", (t["id"],))
                is_captain = (t["captain_id"] == user["id"])
                st.write("**Учасники команди:**")
                for _, m in members_full.iterrows():
                    mc1, mc2 = st.columns([4, 1])
                    with mc1:
                        captain_tag = " 👑 капітан" if m["user_id"] == t["captain_id"] else ""
                        st.write(f"{m['full_name']}{captain_tag} · {m['email']}")
                    with mc2:
                        if is_captain and m["user_id"] != user["id"]:
                            if st.button("🗑️ Прибрати", key=f"kick_{t['id']}_{m['membership_id']}"):
                                execute("DELETE FROM team_members WHERE id=?", (int(m["membership_id"]),))
                                st.success(f"{m['full_name']} видалено з команди.")
                                st.rerun()
                        elif not is_captain and m["user_id"] == user["id"]:
                            if st.button("🚪 Покинути", key=f"leave_{t['id']}_{m['membership_id']}"):
                                execute("DELETE FROM team_members WHERE id=?", (int(m["membership_id"]),))
                                st.success("Ви покинули команду.")
                                st.rerun()

                if is_captain:
                    with st.expander("✏️ Редагувати назву команди / факультет"):
                        with st.form(f"edit_team_form_{t['id']}"):
                            new_team_name = st.text_input("Назва команди", value=t["name"])
                            new_team_faculty = st.text_input("Факультет", value=t["faculty"] or "")
                            if st.form_submit_button("💾 Зберегти"):
                                if not new_team_name.strip():
                                    st.error("Назва команди не може бути порожньою.")
                                else:
                                    execute("UPDATE teams SET name=?, faculty=? WHERE id=?",
                                            (new_team_name.strip(), new_team_faculty.strip(), int(t["id"])))
                                    st.success("Дані команди оновлено.")
                                    st.rerun()

                    if t["status"] in ("На розгляді", "Потребує доопрацювання"):
                        with st.expander("🗑️ Відкликати заявку команди"):
                            st.warning("Це остаточно видалить команду, учасників і подані дані. Дію неможливо "
                                       "скасувати. Доступно лише поки заявку ще не прийнято організаторами.")
                            if st.button("Так, відкликати та видалити команду", key=f"withdraw_{t['id']}"):
                                delete_team_cascade(int(t["id"]))
                                st.success("Заявку відкликано, команду видалено.")
                                st.rerun()
                    else:
                        st.caption("ℹ️ Заявку вже прийнято організаторами — для видалення команди зверніться "
                                   "до адміністратора платформи.")

                st.markdown("#### 📦 Подача проєкту")
                last_sub = query_one("""SELECT repo_link, presentation_link, video_link, description, version, tags
                                         FROM submissions WHERE team_id=? ORDER BY version DESC LIMIT 1""", (t["id"],))
                with st.form(f"submit_form_{t['id']}"):
                    repo_link = st.text_input("Посилання на репозиторій (GitHub)",
                                               value=last_sub[0] if last_sub else "")
                    video_link = st.text_input("Посилання на відео (YouTube/Google Drive)",
                                                value=last_sub[2] if last_sub else "")
                    description = st.text_area("Опис проєкту",
                                                value=last_sub[3] if last_sub else "")
                    tags_input = st.text_input(
                        "Технології / теги (через кому)",
                        value=(last_sub[5] if last_sub and len(last_sub) > 5 and last_sub[5] else ""),
                        help="Наприклад: Python, React, PostgreSQL — використовуються для пошуку у портфоліо.")
                    pdf_file = st.file_uploader("Презентація (PDF, до 50 МБ)", type=["pdf"], key=f"pdf_{t['id']}")
                    if st.form_submit_button("Зберегти / оновити подачу"):
                        new_version = (last_sub[4] + 1) if last_sub else 1
                        pres_link = last_sub[1] if last_sub else ""
                        sub_id = execute("""INSERT INTO submissions (team_id,repo_link,presentation_link,video_link,
                                           description,version,updated_at,tags) VALUES (?,?,?,?,?,?,?,?)""",
                                        (t["id"], repo_link, pres_link, video_link, description, new_version, now(),
                                         tags_input))
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

    today_str = str(datetime.date.today())
    all_bookings = query_df("""SELECT ms.id, ms.mentor_id, u.full_name AS mentor, ms.slot_date, ms.start_time,
                                       ms.end_time, ms.location, ms.notes
                                FROM mentor_slots ms JOIN users u ON ms.mentor_id=u.id
                                WHERE ms.team_id=? AND ms.event_id=?
                                ORDER BY ms.slot_date DESC, ms.start_time DESC""", (team_id, event_id))

    active_booking = all_bookings[all_bookings["slot_date"] >= today_str] if not all_bookings.empty else all_bookings
    past_bookings = all_bookings[all_bookings["slot_date"] < today_str] if not all_bookings.empty else all_bookings

    if not active_booking.empty:
        row = active_booking.iloc[0]
        st.success(f"✅ У вашої команди вже є записана консультація: **{row['mentor']}** · "
                   f"{row['slot_date']} {row['start_time']}–{row['end_time']} · {row['location'] or 'онлайн'}")
        if row["notes"]:
            st.caption(f"📝 {row['notes']}")
        if st.button("Скасувати запис"):
            execute("UPDATE mentor_slots SET is_booked=0, team_id=NULL WHERE id=?", (int(row["id"]),))
            st.success("Запис скасовано, слот знову вільний.")
            st.rerun()
    else:
        st.markdown("#### Вільні слоти для консультацій перед пітчингом")
        free_slots = query_df("""SELECT ms.id, u.full_name AS mentor, ms.slot_date, ms.start_time, ms.end_time,
                                         ms.location
                                  FROM mentor_slots ms JOIN users u ON ms.mentor_id=u.id
                                  WHERE ms.event_id=? AND ms.is_booked=0 AND ms.slot_date >= ?
                                  ORDER BY ms.slot_date, ms.start_time""", (event_id, today_str))
        if free_slots.empty:
            st.info("Наразі немає вільних слотів для цієї події. Спробуйте пізніше.")
        else:
            st.dataframe(free_slots, use_container_width=True, hide_index=True)
            slot_map = {
                f"{row['mentor']} · {row['slot_date']} {row['start_time']}–{row['end_time']} "
                f"({row['location'] or 'онлайн'})": row["id"]
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

    # ------------------------------------------------------------
    # Минулі консультації + оцінювання ментора
    # ------------------------------------------------------------
    if not past_bookings.empty:
        st.markdown("---")
        st.markdown("#### 📜 Минулі консультації")
        for _, pb in past_bookings.iterrows():
            with st.container(border=True):
                st.write(f"**{pb['mentor']}** · {pb['slot_date']} {pb['start_time']}–{pb['end_time']} "
                         f"· {pb['location'] or 'онлайн'}")
                existing_fb = query_one("""SELECT rating, comment FROM mentor_feedback
                                            WHERE slot_id=? AND team_id=?""", (int(pb["id"]), team_id))
                if existing_fb:
                    stars = "⭐" * int(existing_fb[0]) + "☆" * (5 - int(existing_fb[0]))
                    st.write(f"Ваша оцінка: {stars}")
                    if existing_fb[1]:
                        st.caption(f"💬 {existing_fb[1]}")
                else:
                    with st.form(f"rate_mentor_form_{pb['id']}"):
                        rating = st.slider("Оцініть консультацію", min_value=1, max_value=5, value=5,
                                            key=f"rating_{pb['id']}")
                        comment = st.text_area("Коментар (необов'язково)", key=f"rating_comment_{pb['id']}")
                        if st.form_submit_button("⭐ Залишити відгук"):
                            execute("""INSERT INTO mentor_feedback (slot_id,mentor_id,team_id,rating,comment,created_at)
                                       VALUES (?,?,?,?,?,?)""",
                                    (int(pb["id"]), int(pb["mentor_id"]), team_id, rating, comment, now()))
                            st.success("Дякуємо за відгук!")
                            st.rerun()


def page_participant_dashboard():
    user = st.session_state.user
    st.subheader(f"🏠 Вітаємо, {user['full_name'].split(' ')[0]}!")

    st.markdown("#### ⚡ Швидкі дії")
    nb1, nb2, nb3, nb4 = st.columns(4)
    with nb1:
        st.button("🚀 Моя команда", use_container_width=True,
                   on_click=_goto, args=("participant_menu", "🚀 Моя команда"))
    with nb2:
        st.button("🗓️ Office Hours", use_container_width=True,
                   on_click=_goto, args=("participant_menu", "🗓️ Office Hours"))
    with nb3:
        st.button("📅 Календар подій", use_container_width=True,
                   on_click=_goto, args=("participant_menu", "📅 Календар подій"))
    with nb4:
        st.button("🖼️ Портфоліо", use_container_width=True,
                   on_click=_goto, args=("participant_menu", "🖼️ Портфоліо проєктів"))

    my_teams = query_df("""SELECT t.*, e.title AS event_title, e.pitch_deadline, e.event_start,
                                   e.min_team, e.max_team, e.leaderboard_live
                            FROM teams t JOIN team_members tm ON t.id=tm.team_id
                            JOIN events e ON t.event_id=e.id WHERE tm.user_id=?""", (user["id"],))
    if my_teams.empty:
        st.info("Ви ще не в жодній команді. Перейдіть у «🚀 Моя команда», щоб створити команду або "
                "приєднатися за інвайт-кодом.")
    else:
        today = datetime.date.today()
        status_colors = {"Прийнято": "green", "Відхилено": "red",
                          "Потребує доопрацювання": "orange", "На розгляді": "blue"}
        for _, t in my_teams.iterrows():
            with st.container(border=True):
                st.markdown(f"### {t['name']} · {t['event_title']}")
                st.markdown(f":{status_colors.get(t['status'], 'gray')}[**Статус: {t['status']}**]")

                n_members = query_one("SELECT COUNT(*) FROM team_members WHERE team_id=?", (t["id"],))[0]
                has_sub = query_one("SELECT COUNT(*) FROM submissions WHERE team_id=?", (t["id"],))[0] > 0
                has_booking = query_one("SELECT COUNT(*) FROM mentor_slots WHERE team_id=? AND is_booked=1",
                                         (t["id"],))[0] > 0
                team_ok_size = (t["min_team"] or 1) <= n_members

                st.markdown("**✅ Чек-лист готовності:**")
                cl1, cl2, cl3 = st.columns(3)
                with cl1:
                    st.write(("✅" if team_ok_size else "⚠️") +
                             f" Склад команди: {n_members} (мін. {int(t['min_team'] or 1)}, макс. {int(t['max_team'] or 1)})")
                with cl2:
                    st.write(("✅ Проєкт подано" if has_sub else "⚠️ Проєкт ще не подано"))
                with cl3:
                    st.write(("✅ Консультацію заброньовано" if has_booking else "◻️ Консультацію не заброньовано"))

                pitch_dt = parse_date_flexible(t.get("pitch_deadline"))
                if pitch_dt:
                    days_left = (pitch_dt.date() - today).days
                    if days_left > 0:
                        st.caption(f"🏁 До дедлайну пітчингу лишилось {days_left} дн. ({t['pitch_deadline']})")
                    elif days_left == 0:
                        st.caption("🏁 Дедлайн пітчингу — сьогодні!")
                    else:
                        st.caption(f"🏁 Дедлайн пітчингу минув ({t['pitch_deadline']})")

                if t["status"] == "Прийнято" and t["leaderboard_live"]:
                    my_score = compute_team_score(int(t["id"]))
                    if my_score is not None:
                        st.metric("⭐ Ваш поточний бал", my_score)
                    else:
                        st.caption("Оцінки журі ще не виставлено.")

    st.markdown("---")
    my_booking = query_df("""SELECT ms.slot_date, ms.start_time, ms.end_time, u.full_name AS mentor
                              FROM mentor_slots ms JOIN team_members tm ON tm.team_id=ms.team_id
                              JOIN users u ON ms.mentor_id=u.id
                              WHERE tm.user_id=? AND ms.is_booked=1
                              ORDER BY ms.slot_date LIMIT 1""", (user["id"],))
    if not my_booking.empty:
        b = my_booking.iloc[0]
        st.info(f"🗓️ Найближча консультація: **{b['slot_date']} {b['start_time']}–{b['end_time']}** з {b['mentor']}")

    my_event_ids = my_teams["event_id"].tolist() if not my_teams.empty else []
    open_events = get_events("Реєстрація відкрита")
    if not open_events.empty:
        suggestions = open_events[~open_events["id"].isin(my_event_ids)]
        if not suggestions.empty:
            st.markdown("#### 💡 Інші події з відкритою реєстрацією")
            for _, ev in suggestions.head(3).iterrows():
                st.caption(f"🎯 **{ev['title']}** · {ev['category']} · реєстрація до {ev['reg_end']}")

    st.markdown("#### 📢 Останнє оголошення")
    latest_ann = query_df("""SELECT created_at, title, body, COALESCE(priority,'Звичайне') AS priority
                              FROM announcements WHERE target_team_id IS NULL
                              ORDER BY created_at DESC LIMIT 1""")
    if latest_ann.empty:
        st.caption("Оголошень поки немає.")
    else:
        a = latest_ann.iloc[0]
        badge = "⭐ " if a["priority"] == "⭐ Важливе" else ""
        with st.container(border=True):
            st.markdown(f"**{badge}{a['title']}**")
            st.caption(a["created_at"][:16])
            st.write(a["body"])


def page_participant():
    st.sidebar.markdown("### 🎓 Меню учасника")
    menu = st.sidebar.radio("Розділ", ["🏠 Дашборд", "📅 Календар подій", "🚀 Моя команда", "🗓️ Office Hours",
                                        "🏆 Лідерборд", "🖼️ Портфоліо проєктів", "📢 Оголошення", "👤 Профіль"],
                             key="participant_menu")
    if menu == "🏠 Дашборд":
        page_participant_dashboard()
    elif menu == "📅 Календар подій":
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
    elif menu == "👤 Профіль":
        page_my_profile()


def page_announcements_view():
    st.subheader("📢 Оголошення")
    user = st.session_state.user
    my_team_ids = query_df("SELECT team_id FROM team_members WHERE user_id=?", (user["id"],))["team_id"].tolist()
    if my_team_ids:
        placeholders = ",".join(["?"] * len(my_team_ids))
        sql = f"""SELECT created_at, title, body, COALESCE(priority,'Звичайне') AS priority
                  FROM announcements
                  WHERE target_team_id IS NULL OR target_team_id IN ({placeholders})
                  ORDER BY created_at DESC"""
        anns = query_df(sql, my_team_ids)
    else:
        anns = query_df("""SELECT created_at, title, body, COALESCE(priority,'Звичайне') AS priority
                            FROM announcements WHERE target_team_id IS NULL ORDER BY created_at DESC""")
    if anns.empty:
        st.info("Оголошень поки немає.")
    else:
        anns = anns.copy()
        anns["_is_important"] = (anns["priority"] == "⭐ Важливе").astype(int)
        anns = anns.sort_values(["_is_important", "created_at"], ascending=[False, False])
        for _, a in anns.iterrows():
            badge = "⭐ " if a["priority"] == "⭐ Важливе" else ""
            with st.container(border=True):
                st.markdown(f"**{badge}{a['title']}**")
                st.caption(a["created_at"])
                st.write(a["body"])


# ============================================================
# ЖУРІ / ЕКСПЕРТ
# ============================================================

def page_jury_dashboard():
    user = st.session_state.user
    st.subheader(f"🏠 Вітаємо, {user['full_name'].split(' ')[0]}!")

    st.markdown("#### ⚡ Швидкі дії")
    nb1, nb2, nb3 = st.columns(3)
    with nb1:
        st.button("📋 Перейти до оцінювання", use_container_width=True,
                   on_click=_goto, args=("jury_menu", "📋 Оцінювання"))
    with nb2:
        st.button("🏆 Лідерборд", use_container_width=True,
                   on_click=_goto, args=("jury_menu", "🏆 Лідерборд"))
    with nb3:
        st.button("📢 Оголошення", use_container_width=True,
                   on_click=_goto, args=("jury_menu", "📢 Оголошення"))

    assignments = query_df("""SELECT DISTINCT ja.event_id, e.title AS event_title, e.double_blind, e.pitch_deadline
                               FROM jury_assignments ja JOIN events e ON ja.event_id=e.id
                               WHERE ja.jury_id=?""", (user["id"],))
    if assignments.empty:
        st.info("Вам ще не призначено подій для оцінювання. Зверніться до організаторів.")
        return

    today = datetime.date.today()
    total_scored, total_scorable = 0, 0
    rows = []
    unscored_teams = []
    for _, a in assignments.iterrows():
        eid = int(a["event_id"])
        crit_count = query_one("SELECT COUNT(*) FROM criteria WHERE event_id=?", (eid,))[0]
        avoid_conflict = query_one("SELECT avoid_conflict FROM events WHERE id=?", (eid,))[0]
        teams_ev = query_df("SELECT id, name, faculty FROM teams WHERE event_id=? AND status='Прийнято'", (eid,))
        if avoid_conflict:
            teams_ev = teams_ev[teams_ev["faculty"] != user.get("faculty")]
        total = len(teams_ev)
        scored = 0
        for _, tt in teams_ev.iterrows():
            cnt = query_one("SELECT COUNT(DISTINCT criterion_id) FROM scores WHERE team_id=? AND jury_id=?",
                             (int(tt["id"]), user["id"]))[0]
            if crit_count and cnt >= crit_count:
                scored += 1
            else:
                name = anon_code(int(tt["id"])) if a["double_blind"] else tt["name"]
                unscored_teams.append({"event": a["event_title"], "team": name})
        total_scored += scored
        total_scorable += total
        rows.append({"event": a["event_title"], "total": total, "scored": scored})

    k1, k2, k3 = st.columns(3)
    k1.metric("Подій призначено", len(assignments))
    k2.metric("Оцінено команд", f"{total_scored}/{total_scorable}" if total_scorable else "0/0")
    pct = round(total_scored / total_scorable * 100, 1) if total_scorable else 0
    k3.metric("Загальний прогрес", f"{pct}%")
    st.progress(min(pct / 100, 1.0))

    st.markdown("---")
    st.markdown("#### 📋 Прогрес за подіями")
    for r in rows:
        with st.container(border=True):
            done = r["total"] > 0 and r["scored"] >= r["total"]
            icon = "✅" if done else "🕓"
            st.markdown(f"{icon} **{r['event']}** — {r['scored']}/{r['total']} команд оцінено")
            if r["total"]:
                st.progress(min(r["scored"] / r["total"], 1.0))
    if total_scorable and total_scored < total_scorable:
        st.warning(f"⏳ Вам ще залишилось оцінити {total_scorable - total_scored} команд(и). "
                   "Перейдіть у розділ «📋 Оцінювання».")
    elif total_scorable:
        st.success("✅ Ви завершили оцінювання всіх призначених вам команд!")

    if unscored_teams:
        st.markdown("#### ⏭️ Наступні команди для оцінювання")
        for item in unscored_teams[:8]:
            st.caption(f"🕓 «{item['team']}» · {item['event']}")

    pitch_rows = []
    for _, a in assignments.iterrows():
        pitch_dt = parse_date_flexible(a.get("pitch_deadline"))
        if pitch_dt:
            days_left = (pitch_dt.date() - today).days
            if days_left >= 0:
                pitch_rows.append((a["event_title"], days_left, a["pitch_deadline"]))
    if pitch_rows:
        st.markdown("#### 🏁 Дедлайни пітчингу подій, які ви оцінюєте")
        for ev_title, days_left, date_str in sorted(pitch_rows, key=lambda x: x[1]):
            label = "сьогодні" if days_left == 0 else f"через {days_left} дн."
            st.caption(f"«{ev_title}» — {label} ({date_str})")

    if total_scored:
        st.markdown("---")
        st.markdown("#### 🎯 Самоаналіз калібрування")
        my_avgs, overall_avgs = [], []
        for _, a in assignments.iterrows():
            eid = int(a["event_id"])
            teams_ev = query_df("SELECT id FROM teams WHERE event_id=? AND status='Прийнято'", (eid,))
            for _, tt in teams_ev.iterrows():
                ms = compute_team_score_for_jury(int(tt["id"]), user["id"])
                os_ = compute_team_score(int(tt["id"]))
                if ms is not None and os_ is not None:
                    my_avgs.append(ms)
                    overall_avgs.append(os_)
        if my_avgs:
            my_mean = round(sum(my_avgs) / len(my_avgs), 1)
            overall_mean = round(sum(overall_avgs) / len(overall_avgs), 1)
            diff = round(my_mean - overall_mean, 1)
            cc1, cc2, cc3 = st.columns(3)
            cc1.metric("Мій середній бал", my_mean)
            cc2.metric("Загальний середній", overall_mean)
            cc3.metric("Різниця", f"{'+' if diff > 0 else ''}{diff}")
            if abs(diff) >= 10:
                tone = "суворіше" if diff < 0 else "м'якше"
                st.caption(f"ℹ️ Ваші оцінки в середньому {tone}, ніж у колег по журі — це нормально, "
                           "але варто звернути увагу під час подальшого оцінювання.")


def page_jury():
    st.sidebar.markdown("### ⚖️ Меню журі")
    menu = st.sidebar.radio("Розділ", ["🏠 Дашборд", "📋 Оцінювання", "🏆 Лідерборд", "🖼️ Портфоліо проєктів",
                                        "📢 Оголошення", "👤 Профіль"], key="jury_menu")
    if menu == "🏠 Дашборд":
        page_jury_dashboard()
    elif menu == "📋 Оцінювання":
        jury_evaluation()
    elif menu == "🏆 Лідерборд":
        page_leaderboard()
    elif menu == "🖼️ Портфоліо проєктів":
        page_showcase()
    elif menu == "📢 Оголошення":
        page_jury_announcements()
    elif menu == "👤 Профіль":
        page_my_profile()


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

    ev_row = query_one("SELECT double_blind, jury_see_other_scores FROM events WHERE id=?", (ev_id,))
    double_blind = bool(ev_row[0]) if ev_row else False
    jury_see_other_scores = bool(ev_row[1]) if ev_row else False
    if double_blind:
        st.info("🕶️ Для цієї події увімкнено **сліпе оцінювання** — назви команд і факультети приховано.")
    if jury_see_other_scores:
        st.caption("👀 Для цієї події увімкнено прозорий режим — ви бачите оцінки й фідбек колег по журі.")

    with st.expander("🚪 Відмовитися від оцінювання цієї події"):
        st.caption("Ваше призначення на цю подію буде знято, і нові команди для оцінювання вам більше "
                   "не показуватимуться. Оцінки, які ви вже встигли виставити, залишаться в системі "
                   "для організаторів — щоб їх теж прибрати, спочатку скиньте їх нижче біля кожної команди.")
        if st.button("Так, відмовитися від оцінювання цієї події", key=f"jury_unassign_{ev_id}"):
            execute("DELETE FROM jury_assignments WHERE event_id=? AND jury_id=?", (ev_id, user["id"]))
            st.success("Призначення на цю подію знято.")
            st.rerun()

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

    crit_count = len(criteria)

    # ------------------------------------------------------------
    # Готуємо статус кожної команди: конфлікт інтересів / оцінено чи ні
    # ------------------------------------------------------------
    team_items = []
    for _, t in teams.iterrows():
        conflict = has_conflict(ev_id, t["id"], user)
        scored_cnt = query_one("SELECT COUNT(DISTINCT criterion_id) FROM scores WHERE team_id=? AND jury_id=?",
                                (t["id"], user["id"]))[0]
        is_scored = bool(crit_count) and scored_cnt >= crit_count
        team_items.append({"row": t, "conflict": conflict, "scored": is_scored})

    scorable = [ti for ti in team_items if not ti["conflict"]]
    scored_count = sum(1 for ti in scorable if ti["scored"])
    total_scorable = len(scorable)

    # ------------------------------------------------------------
    # Прогрес-дашборд
    # ------------------------------------------------------------
    pc1, pc2, pc3 = st.columns(3)
    pc1.metric("Команд призначено", len(teams))
    pc2.metric("Оцінено повністю", f"{scored_count}/{total_scorable}" if total_scorable else "0/0")
    pct = round(scored_count / total_scorable * 100, 1) if total_scorable else 0
    pc3.metric("Мій прогрес", f"{pct}%")
    st.progress(min(pct / 100, 1.0))
    if total_scorable and scored_count == total_scorable:
        st.success("✅ Ви завершили оцінювання всіх призначених вам команд у цій події.")

    # ------------------------------------------------------------
    # Фільтри та сортування
    # ------------------------------------------------------------
    fc1, fc2, fc3 = st.columns([2, 1, 1])
    with fc2:
        only_unscored = st.checkbox("Лише неоцінені")
    with fc3:
        sort_choice = st.selectbox("Порядок", ["За замовчуванням", "Спочатку неоцінені"])
    with fc1:
        if double_blind:
            search_q = ""
            st.caption("🔎 Пошук за назвою вимкнено — увімкнено сліпе оцінювання.")
        else:
            search_q = st.text_input("🔎 Пошук за назвою команди або факультетом")

    filtered_items = team_items
    if only_unscored:
        filtered_items = [ti for ti in filtered_items if not ti["conflict"] and not ti["scored"]]
    if search_q.strip():
        q = search_q.strip().lower()
        filtered_items = [ti for ti in filtered_items
                           if q in str(ti["row"]["name"]).lower() or q in str(ti["row"]["faculty"]).lower()]
    if sort_choice == "Спочатку неоцінені":
        filtered_items = sorted(filtered_items, key=lambda ti: (ti["conflict"], ti["scored"]))

    if not filtered_items:
        st.info("Немає команд за обраними фільтрами.")
        return

    # ------------------------------------------------------------
    # Картки команд для оцінювання
    # ------------------------------------------------------------
    for ti in filtered_items:
        t = ti["row"]
        display_name = anon_code(t["id"]) if double_blind else f"{t['name']} ({t['faculty']})"

        if ti["conflict"]:
            with st.container(border=True):
                st.markdown(f"### {display_name if double_blind else t['name']}")
                st.warning("⛔ Оцінювання недоступне: команда належить до вашого факультету (конфлікт інтересів).")
            continue

        with st.container(border=True):
            status_badge = "✅ Оцінено" if ti["scored"] else "🕓 Ще не оцінено"
            st.markdown(f"### {display_name}  ·  {status_badge}")

            sub, file_row = get_latest_submission_with_file(int(t["id"]))
            if sub:
                tags = parse_tags(sub.get("tags"))
                if tags:
                    st.markdown(" ".join(f"`{tag}`" for tag in tags[:6]))
                st.write(sub.get("description") or "_Опис відсутній_")
                if sub.get("repo_link"):
                    st.write(f"🔗 Репозиторій: {sub['repo_link']}")
                if sub.get("video_link"):
                    with st.expander("🎬 Демо-відео"):
                        st.video(youtube_embed_url(sub["video_link"]))
                if file_row:
                    with st.expander(f"📄 Переглянути презентацію ({file_row['filename']})"):
                        render_pdf_inline(file_row["data"], height=420)
            else:
                st.warning("Команда ще не завантажила подачу.")

            if jury_see_other_scores:
                others = query_df("""SELECT c.name AS criterion, u.full_name AS jury, s.score, s.feedback
                                      FROM scores s JOIN criteria c ON s.criterion_id=c.id
                                      JOIN users u ON s.jury_id=u.id
                                      WHERE s.team_id=? AND s.jury_id!=?
                                      ORDER BY c.id, u.full_name""", (t["id"], user["id"]))
                if not others.empty:
                    with st.expander("👥 Оцінки та фідбек інших членів журі по цій команді"):
                        st.dataframe(others.rename(columns={"criterion": "Критерій", "jury": "Журі",
                                                             "score": "Оцінка", "feedback": "Фідбек"}),
                                     use_container_width=True, hide_index=True)

            last_score_ts = query_one("SELECT created_at FROM scores WHERE team_id=? AND jury_id=? "
                                       "ORDER BY created_at DESC LIMIT 1", (t["id"], user["id"]))
            if last_score_ts:
                st.caption(f"🕓 Востаннє оцінено вами: {last_score_ts[0][:16]}")

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

            if ti["scored"]:
                if st.button("🗑️ Скинути мою оцінку для цієї команди", key=f"reset_score_{t['id']}"):
                    execute("DELETE FROM scores WHERE team_id=? AND jury_id=?", (t["id"], user["id"]))
                    st.success("Вашу оцінку для цієї команди скинуто — можете оцінити її ще раз.")
                    st.rerun()

    # ------------------------------------------------------------
    # Самоаналіз: мої оцінки в порівнянні із загальним середнім
    # ------------------------------------------------------------
    my_rated = [ti for ti in scorable if ti["scored"]]
    if my_rated:
        st.markdown("---")
        st.markdown("#### 📊 Огляд моїх оцінок по командах цієї події")
        overview_rows = []
        for ti in my_rated:
            t = ti["row"]
            name_for_overview = anon_code(t["id"]) if double_blind else t["name"]
            my_score = compute_team_score_for_jury(int(t["id"]), user["id"])
            overall_score = compute_team_score(int(t["id"]))
            overview_rows.append({"Команда": name_for_overview, "Мій бал": my_score,
                                   "Загальний середній бал": overall_score,
                                   "Різниця": round(my_score - overall_score, 2)
                                   if my_score is not None and overall_score is not None else None})
        overview_df = pd.DataFrame(overview_rows)
        st.dataframe(overview_df, use_container_width=True, hide_index=True)

        st.markdown("#### 🎯 Мій середній бал за критеріями (у цій події)")
        crit_rows = []
        for _, crit in criteria.iterrows():
            avg_row = query_one("""SELECT AVG(score) FROM scores WHERE jury_id=? AND criterion_id=? AND team_id IN
                                    (SELECT id FROM teams WHERE event_id=?)""", (user["id"], crit["id"], ev_id))
            if avg_row and avg_row[0] is not None:
                crit_rows.append({"Критерій": crit["name"], "Мій сер. бал": round(avg_row[0], 2),
                                   "Максимум": crit["max_score"]})
        if crit_rows:
            crit_df = pd.DataFrame(crit_rows)
            crit_chart = alt.Chart(crit_df).mark_bar(cornerRadiusTopLeft=6, cornerRadiusTopRight=6).encode(
                x=alt.X("Критерій:N", sort=None),
                y=alt.Y("Мій сер. бал:Q"),
                color=alt.Color("Мій сер. бал:Q", scale=alt.Scale(scheme="teals"), legend=None),
                tooltip=["Критерій", "Мій сер. бал", "Максимум"],
            ).properties(height=280)
            st.altair_chart(crit_chart, use_container_width=True)


def page_jury_announcements():
    st.subheader("📢 Оголошення")
    st.caption("Показані глобальні оголошення платформи та оголошення для подій, на які вас призначено журі.")
    user = st.session_state.user

    assigned_events = query_df("""SELECT DISTINCT e.id, e.title FROM jury_assignments ja
                                   JOIN events e ON ja.event_id=e.id WHERE ja.jury_id=?""", (user["id"],))

    if assigned_events.empty:
        anns = query_df("""SELECT a.created_at, a.title, a.body, COALESCE(a.priority,'Звичайне') AS priority,
                                   'Глобальне' AS event
                            FROM announcements a
                            WHERE a.event_id IS NULL AND a.target_team_id IS NULL
                            ORDER BY a.created_at DESC""")
    else:
        ids = assigned_events["id"].tolist()
        placeholders = ",".join(["?"] * len(ids))
        anns = query_df(f"""SELECT a.created_at, a.title, a.body, COALESCE(a.priority,'Звичайне') AS priority,
                                    COALESCE(e.title,'Глобальне') AS event
                             FROM announcements a
                             LEFT JOIN events e ON a.event_id=e.id
                             WHERE a.target_team_id IS NULL
                               AND (a.event_id IS NULL OR a.event_id IN ({placeholders}))
                             ORDER BY a.created_at DESC""", ids)

    if anns.empty:
        st.info("Оголошень поки немає.")
        return

    fc1, fc2 = st.columns([2, 2])
    with fc1:
        event_options = sorted(anns["event"].unique().tolist())
        event_filter = st.multiselect("Фільтр за подією", event_options)
    with fc2:
        search_ann = st.text_input("🔎 Пошук за заголовком/текстом")

    view = anns.copy()
    if event_filter:
        view = view[view["event"].isin(event_filter)]
    if search_ann.strip():
        q = search_ann.strip().lower()
        view = view[view["title"].fillna("").str.lower().str.contains(q)
                    | view["body"].fillna("").str.lower().str.contains(q)]

    if view.empty:
        st.info("За обраними фільтрами оголошень не знайдено.")
        return

    view["_is_important"] = (view["priority"] == "⭐ Важливе").astype(int)
    view = view.sort_values(["_is_important", "created_at"], ascending=[False, False])

    st.caption(f"Знайдено оголошень: {len(view)}")
    for _, a in view.iterrows():
        badge = "⭐ " if a["priority"] == "⭐ Важливе" else ""
        with st.container(border=True):
            st.markdown(f"**{badge}{a['title']}**")
            st.caption(f"{a['created_at']} · {a['event']}")
            st.write(a["body"])


# ============================================================
# МЕНТОР (OFFICE HOURS)
# ============================================================

def page_mentor_dashboard():
    user = st.session_state.user
    st.subheader(f"🏠 Вітаємо, {user['full_name'].split(' ')[0]}!")

    st.markdown("#### ⚡ Швидкі дії")
    nb1, nb2, nb3 = st.columns(3)
    with nb1:
        st.button("🗓️ Мої слоти консультацій", use_container_width=True,
                   on_click=_goto, args=("mentor_menu", "🗓️ Мої слоти консультацій"))
    with nb2:
        st.button("📢 Оголошення", use_container_width=True,
                   on_click=_goto, args=("mentor_menu", "📢 Оголошення"))
    with nb3:
        quick_events = get_events()
        if not quick_events.empty and st.button("➕ Додати слот на сьогодні 15:00–15:15", use_container_width=True):
            quick_ev_id = int(quick_events.iloc[0]["id"])
            dup = query_one("""SELECT id FROM mentor_slots WHERE mentor_id=? AND event_id=?
                                AND slot_date=? AND start_time=?""",
                             (user["id"], quick_ev_id, str(datetime.date.today()), "15:00"))
            if dup:
                st.warning("Такий слот уже існує на сьогодні.")
            else:
                execute("""INSERT INTO mentor_slots (mentor_id,event_id,slot_date,start_time,end_time,
                           location,is_booked,team_id,notes,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                        (user["id"], quick_ev_id, str(datetime.date.today()), "15:00", "15:15",
                         "Онлайн", 0, None, "", now()))
                st.success(f"Слот 15:00–15:15 на сьогодні додано для події «{quick_events.iloc[0]['title']}».")
                st.rerun()

    all_slots = query_df("""SELECT ms.*, e.title AS event_title FROM mentor_slots ms
                             JOIN events e ON ms.event_id=e.id WHERE ms.mentor_id=?""", (user["id"],))
    if all_slots.empty:
        st.info("У вас ще немає жодного слоту консультацій. Перейдіть у «🗓️ Мої слоти консультацій», "
                "щоб додати їх, або скористайтесь кнопкою вище.")
        return

    total = len(all_slots)
    booked = int((all_slots["is_booked"] == 1).sum())
    free = total - booked
    k1, k2, k3 = st.columns(3)
    k1.metric("Слотів усього", total)
    k2.metric("Заброньовано", booked)
    k3.metric("Вільно", free)

    today_str = str(datetime.date.today())
    upcoming = all_slots[(all_slots["is_booked"] == 1) & (all_slots["slot_date"] >= today_str)].sort_values("slot_date")
    st.markdown("---")
    st.markdown("#### 🔔 Найближчі консультації")
    if upcoming.empty:
        st.caption("Немає майбутніх заброньованих консультацій.")
    else:
        for _, s in upcoming.head(5).iterrows():
            contact = query_one("""SELECT u.full_name, u.email FROM teams t
                                    LEFT JOIN users u ON t.captain_id=u.id WHERE t.id=?""", (int(s["team_id"]),)) \
                if s["team_id"] else None
            team_name = query_one("SELECT name FROM teams WHERE id=?", (int(s["team_id"]),))[0] if s["team_id"] else "—"
            contact_str = f" · 📧 {contact[1]}" if contact and contact[1] else ""
            st.info(f"**{s['slot_date']} {s['start_time']}–{s['end_time']}** · {s['event_title']} · "
                    f"команда «{team_name}»{contact_str}")

    upcoming_free = all_slots[(all_slots["is_booked"] == 0) & (all_slots["slot_date"] >= today_str)]
    if not upcoming_free.empty:
        st.caption(f"🟢 У вас ще є {len(upcoming_free)} вільних майбутніх слотів, які команди можуть забронювати.")

    st.markdown("---")
    occ_pct = round(booked / total * 100, 1) if total else 0
    st.markdown(f"#### 📊 Заповненість слотів: {occ_pct}%")
    st.progress(min(occ_pct / 100, 1.0))

    dc1, dc2 = st.columns(2)
    with dc1:
        st.markdown("**Слотів за подіями**")
        by_ev = all_slots.groupby("event_title").size().reset_index(name="Слотів")
        chart_ev = alt.Chart(by_ev).mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4).encode(
            x=alt.X("Слотів:Q"), y=alt.Y("event_title:N", sort="-x", title="Подія"),
            color=alt.Color("Слотів:Q", scale=alt.Scale(scheme="teals"), legend=None),
            tooltip=["event_title", "Слотів"],
        ).properties(height=max(160, 32 * len(by_ev)))
        st.altair_chart(chart_ev, use_container_width=True)
    with dc2:
        st.markdown("**Бронювання за датами**")
        booked_df = all_slots[all_slots["is_booked"] == 1]
        if not booked_df.empty:
            by_date = booked_df.groupby("slot_date").size().reset_index(name="Бронювань")
            chart_date = alt.Chart(by_date).mark_bar().encode(
                x=alt.X("slot_date:N", title="Дата", sort=None), y=alt.Y("Бронювань:Q"),
                color=alt.value("#4F8BF9"), tooltip=["slot_date", "Бронювань"],
            ).properties(height=max(160, 32 * len(by_ev)))
            st.altair_chart(chart_date, use_container_width=True)
        else:
            st.caption("Заброньованих слотів поки немає.")

    events_with_slots = all_slots["event_id"].unique().tolist()
    no_booking_rows = []
    for eid in events_with_slots:
        ev_title_row = query_one("SELECT title FROM events WHERE id=?", (int(eid),))
        teams_no_slot = query_df("""SELECT t.name, t.faculty FROM teams t
                                     WHERE t.event_id=? AND t.status='Прийнято'
                                     AND t.id NOT IN (SELECT team_id FROM mentor_slots
                                                       WHERE event_id=? AND mentor_id=? AND team_id IS NOT NULL)""",
                                  (int(eid), int(eid), user["id"]))
        for _, tt in teams_no_slot.iterrows():
            no_booking_rows.append({"Подія": ev_title_row[0] if ev_title_row else "—",
                                     "Команда": tt["name"], "Факультет": tt["faculty"]})
    if no_booking_rows:
        st.markdown("#### 📋 Прийняті команди, які ще не бронювали консультацію з вами")
        st.dataframe(pd.DataFrame(no_booking_rows), use_container_width=True, hide_index=True)


def page_mentor():
    st.sidebar.markdown("### 🧑‍🏫 Меню ментора")
    menu = st.sidebar.radio("Розділ", ["🏠 Дашборд", "🗓️ Мої слоти консультацій", "🏆 Лідерборд",
                                        "🖼️ Портфоліо проєктів", "📢 Оголошення", "👤 Профіль"], key="mentor_menu")
    if menu == "🏠 Дашборд":
        page_mentor_dashboard()
    elif menu == "🗓️ Мої слоти консультацій":
        mentor_slots_manager()
    elif menu == "🏆 Лідерборд":
        page_leaderboard()
    elif menu == "🖼️ Портфоліо проєктів":
        page_showcase()
    elif menu == "📢 Оголошення":
        page_mentor_announcements()
    elif menu == "👤 Профіль":
        page_my_profile()


def _parse_hhmm(text):
    try:
        return datetime.datetime.strptime(str(text).strip(), "%H:%M").time()
    except (ValueError, AttributeError):
        return None


def _generate_slot_windows(start_t, end_t, duration_min, break_min):
    """Розбиває часовий проміжок на послідовні слоти заданої тривалості з перервами між ними."""
    windows = []
    base_day = datetime.date.today()
    cur = datetime.datetime.combine(base_day, start_t)
    end_dt = datetime.datetime.combine(base_day, end_t)
    step = timedelta(minutes=duration_min)
    gap = timedelta(minutes=break_min)
    while cur + step <= end_dt:
        slot_end = cur + step
        windows.append((cur.strftime("%H:%M"), slot_end.strftime("%H:%M")))
        cur = slot_end + gap
    return windows


def mentor_slots_manager():
    st.subheader("🗓️ Office Hours — мої слоти консультацій")
    user = st.session_state.user

    events = get_events()
    if events.empty:
        st.info("Подій ще немає.")
        return
    ev_map = dict(zip(events["title"], events["id"]))
    ev_title = st.selectbox("Подія", list(ev_map.keys()), key="mentor_main_event")
    ev_id = ev_map[ev_title]

    tab_add, tab_schedule, tab_stats = st.tabs(
        ["➕ Додати слоти", "🗓️ Мій розклад", "📊 Статистика"])

    # ================================================================
    # ➕ ДОДАТИ СЛОТИ
    # ================================================================
    with tab_add:
        st.markdown("#### Один слот")
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

        st.markdown("---")
        st.markdown("#### 🧩 Масове створення слотів на день")
        st.caption("Задайте робочу сесію (наприклад, 10:00–13:00), тривалість одного слоту та перерву між ними — "
                   "система сама розіб'є цей проміжок на послідовні слоти.")
        bd1, bd2, bd3 = st.columns(3)
        with bd1:
            bulk_date = st.text_input("Дата (ГГГГ-ММ-ДД)", key="bulk_date")
        with bd2:
            bulk_start = st.text_input("Початок сесії (ГГ:ХХ)", value="10:00", key="bulk_start")
        with bd3:
            bulk_end = st.text_input("Кінець сесії (ГГ:ХХ)", value="13:00", key="bulk_end")
        bd4, bd5, bd6 = st.columns(3)
        with bd4:
            bulk_duration = st.number_input("Тривалість слоту, хв", min_value=5, max_value=180, value=15, step=5)
        with bd5:
            bulk_break = st.number_input("Перерва між слотами, хв", min_value=0, max_value=60, value=0, step=5)
        with bd6:
            bulk_location = st.text_input("Місце / посилання", value="Онлайн", key="bulk_loc")
        bulk_notes = st.text_input("Примітка (необов'язково)", value="", key="bulk_notes")

        start_t, end_t = _parse_hhmm(bulk_start), _parse_hhmm(bulk_end)
        if bulk_date and start_t and end_t:
            windows = _generate_slot_windows(start_t, end_t, int(bulk_duration), int(bulk_break))
            if not windows:
                st.warning("З обраними параметрами не вдалось сформувати жодного слоту — перевірте час і тривалість.")
            else:
                st.info(f"Буде створено **{len(windows)}** слот(ів): "
                        + ", ".join(f"{s}–{e}" for s, e in windows[:8])
                        + (" …" if len(windows) > 8 else ""))
                if st.button(f"➕ Створити {len(windows)} слот(ів)"):
                    existing = query_df("""SELECT start_time FROM mentor_slots
                                            WHERE mentor_id=? AND event_id=? AND slot_date=?""",
                                         (user["id"], ev_id, bulk_date))
                    existing_starts = set(existing["start_time"].tolist()) if not existing.empty else set()
                    created, skipped_dup = 0, 0
                    for s, e in windows:
                        if s in existing_starts:
                            skipped_dup += 1
                            continue
                        execute("""INSERT INTO mentor_slots (mentor_id,event_id,slot_date,start_time,end_time,
                                   location,is_booked,team_id,notes,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                                (user["id"], ev_id, bulk_date, s, e, bulk_location, 0, None, bulk_notes, now()))
                        created += 1
                    st.success(f"Створено {created} слот(ів)."
                               + (f" Пропущено {skipped_dup} через дублювання часу." if skipped_dup else ""))
                    st.rerun()
        else:
            st.caption("Вкажіть дату та коректний час початку/кінця сесії (формат ГГ:ХХ), щоб побачити попередній перегляд.")

    # ================================================================
    # 🗓️ МІЙ РОЗКЛАД
    # ================================================================
    with tab_schedule:
        all_my_slots = query_df("""SELECT ms.id, ms.slot_date, ms.start_time, ms.end_time, ms.location,
                                           ms.notes, ms.team_id, COALESCE(t.name,'—') AS team,
                                           ms.is_booked
                                    FROM mentor_slots ms LEFT JOIN teams t ON ms.team_id=t.id
                                    WHERE ms.mentor_id=? AND ms.event_id=?
                                    ORDER BY ms.slot_date, ms.start_time""", (user["id"], ev_id))
        if all_my_slots.empty:
            st.info("Слотів ще не створено — додайте їх на вкладці «➕ Додати слоти».")
        else:
            today_str = str(datetime.date.today())
            upcoming_booked = all_my_slots[(all_my_slots["is_booked"] == 1) & (all_my_slots["slot_date"] >= today_str)]
            if not upcoming_booked.empty:
                st.markdown("#### 🔔 Найближчі заброньовані консультації")
                for _, s in upcoming_booked.head(5).iterrows():
                    contact = query_one("""SELECT u.full_name, u.email FROM teams t
                                            LEFT JOIN users u ON t.captain_id=u.id WHERE t.id=?""", (int(s["team_id"]),))
                    contact_str = f" · 📧 {contact[1]}" if contact and contact[1] else ""
                    st.info(f"**{s['slot_date']} {s['start_time']}–{s['end_time']}** · команда «{s['team']}»"
                            f"{contact_str} · {s['location'] or 'онлайн'}")

            st.markdown("#### 🧹 Масове видалення вільних слотів")
            st.caption("Швидко прибрати всі ще не заброньовані слоти на конкретну дату (наприклад, "
                       "якщо плани змінилися й ви не зможете провести консультації того дня).")
            bd_col1, bd_col2 = st.columns([2, 1])
            with bd_col1:
                bulk_del_date = st.text_input("Дата (ГГГГ-ММ-ДД)", key="bulk_del_date")
            with bd_col2:
                st.write("")
                st.write("")
                if st.button("🗑️ Видалити вільні слоти цієї дати") and bulk_del_date:
                    n_del = query_one("""SELECT COUNT(*) FROM mentor_slots
                                          WHERE mentor_id=? AND event_id=? AND slot_date=? AND is_booked=0""",
                                       (user["id"], ev_id, bulk_del_date))[0]
                    execute("""DELETE FROM mentor_slots
                               WHERE mentor_id=? AND event_id=? AND slot_date=? AND is_booked=0""",
                            (user["id"], ev_id, bulk_del_date))
                    st.success(f"Видалено {n_del} вільних слотів на {bulk_del_date}.")
                    st.rerun()

            st.markdown("#### Фільтри розкладу")
            f1, f2 = st.columns(2)
            with f1:
                status_filter_s = st.selectbox("Статус", ["Усі", "Тільки вільні", "Тільки заброньовані"])
            with f2:
                period_filter = st.selectbox("Період", ["Усі", "Лише майбутні", "Лише минулі"])

            view = all_my_slots.copy()
            if status_filter_s == "Тільки вільні":
                view = view[view["is_booked"] == 0]
            elif status_filter_s == "Тільки заброньовані":
                view = view[view["is_booked"] == 1]
            if period_filter == "Лише майбутні":
                view = view[view["slot_date"] >= today_str]
            elif period_filter == "Лише минулі":
                view = view[view["slot_date"] < today_str]

            if view.empty:
                st.info("Немає слотів за обраними фільтрами.")
            else:
                display_df = view.copy()
                display_df["Статус"] = display_df["is_booked"].apply(lambda x: "🔴 заброньовано" if x == 1 else "🟢 вільно")
                st.dataframe(display_df[["id", "slot_date", "start_time", "end_time", "location", "team", "Статус"]]
                             .rename(columns={"id": "ID", "slot_date": "Дата", "start_time": "Початок",
                                               "end_time": "Кінець", "location": "Місце", "team": "Команда"}),
                             use_container_width=True, hide_index=True)

                st.markdown("#### Керування слотами")
                for _, s in view.iterrows():
                    with st.container(border=True):
                        status_lbl = "🔴 заброньовано" if s["is_booked"] == 1 else "🟢 вільно"
                        st.write(f"**#{s['id']}** · {s['slot_date']} {s['start_time']}–{s['end_time']} "
                                 f"· {s['location'] or 'онлайн'} · {status_lbl} · {s['team']}")
                        if s["notes"]:
                            st.caption(f"📝 {s['notes']}")

                        with st.expander("✏️ Редагувати слот"):
                            with st.form(f"edit_slot_form_{s['id']}"):
                                ec1, ec2, ec3 = st.columns(3)
                                with ec1:
                                    new_date = st.text_input("Дата", value=s["slot_date"], key=f"edate_{s['id']}")
                                with ec2:
                                    new_start = st.text_input("Початок", value=s["start_time"], key=f"estart_{s['id']}")
                                with ec3:
                                    new_end = st.text_input("Кінець", value=s["end_time"], key=f"eend_{s['id']}")
                                new_location = st.text_input("Місце / посилання", value=s["location"] or "",
                                                              key=f"eloc_{s['id']}")
                                new_notes = st.text_input("Примітка", value=s["notes"] or "", key=f"enotes_{s['id']}")
                                if st.form_submit_button("💾 Зберегти зміни"):
                                    execute("""UPDATE mentor_slots SET slot_date=?, start_time=?, end_time=?,
                                               location=?, notes=? WHERE id=?""",
                                            (new_date, new_start, new_end, new_location, new_notes, int(s["id"])))
                                    st.success("Слот оновлено.")
                                    st.rerun()

                        bc1, bc2 = st.columns(2)
                        with bc1:
                            if s["is_booked"] == 1:
                                if st.button("🔓 Звільнити (скасувати бронювання)", key=f"unbook_mentor_{s['id']}"):
                                    execute("UPDATE mentor_slots SET is_booked=0, team_id=NULL WHERE id=?", (int(s["id"]),))
                                    st.rerun()
                        with bc2:
                            if st.button("🗑️ Видалити слот", key=f"del_slot_{s['id']}"):
                                execute("DELETE FROM mentor_slots WHERE id=?", (int(s["id"]),))
                                st.rerun()

    # ================================================================
    # 📊 СТАТИСТИКА
    # ================================================================
    with tab_stats:
        my_all_events_slots = query_df("""SELECT ms.*, e.title AS event_title FROM mentor_slots ms
                                           JOIN events e ON ms.event_id=e.id WHERE ms.mentor_id=?""", (user["id"],))
        if my_all_events_slots.empty:
            st.info("У вас ще немає жодного слоту.")
        else:
            total = len(my_all_events_slots)
            booked = int((my_all_events_slots["is_booked"] == 1).sum())
            free = total - booked
            sc1, sc2, sc3 = st.columns(3)
            sc1.metric("Всього слотів (усі події)", total)
            sc2.metric("Заброньовано", booked)
            sc3.metric("Вільно", free)
            st.progress(min(booked / total, 1.0) if total else 0)

            st.markdown("#### Слотів за подіями")
            by_ev = my_all_events_slots.groupby("event_title").size().reset_index(name="Слотів")
            chart_ev = alt.Chart(by_ev).mark_bar(cornerRadiusTopLeft=6, cornerRadiusTopRight=6).encode(
                x=alt.X("Слотів:Q"),
                y=alt.Y("event_title:N", sort="-x", title="Подія"),
                color=alt.Color("Слотів:Q", scale=alt.Scale(scheme="teals"), legend=None),
                tooltip=["event_title", "Слотів"],
            ).properties(height=max(160, 32 * len(by_ev)))
            st.altair_chart(chart_ev, use_container_width=True)

            st.markdown("#### Бронювання за датами")
            booked_df = my_all_events_slots[my_all_events_slots["is_booked"] == 1]
            if not booked_df.empty:
                by_date = booked_df.groupby("slot_date").size().reset_index(name="Бронювань")
                chart_date = alt.Chart(by_date).mark_bar().encode(
                    x=alt.X("slot_date:N", title="Дата", sort=None),
                    y=alt.Y("Бронювань:Q"),
                    color=alt.value("#4F8BF9"),
                    tooltip=["slot_date", "Бронювань"],
                ).properties(height=280)
                st.altair_chart(chart_date, use_container_width=True)
            else:
                st.caption("Заброньованих слотів поки немає.")

            st.markdown("---")
            st.markdown("#### ⭐ Відгуки про консультації")
            my_feedback = query_df("""SELECT mf.created_at, mf.rating, mf.comment, t.name AS team, e.title AS event
                                       FROM mentor_feedback mf
                                       LEFT JOIN teams t ON mf.team_id = t.id
                                       JOIN mentor_slots ms ON mf.slot_id = ms.id
                                       JOIN events e ON ms.event_id = e.id
                                       WHERE mf.mentor_id=? ORDER BY mf.created_at DESC""", (user["id"],))
            if my_feedback.empty:
                st.caption("Відгуків від учасників ще не було.")
            else:
                avg_rating = round(my_feedback["rating"].mean(), 2)
                fc1, fc2 = st.columns(2)
                fc1.metric("Середня оцінка", f"{avg_rating} / 5")
                fc2.metric("Кількість відгуків", len(my_feedback))
                for _, fb in my_feedback.iterrows():
                    stars = "⭐" * int(fb["rating"]) + "☆" * (5 - int(fb["rating"]))
                    with st.container(border=True):
                        st.write(f"{stars} · {fb['team']} · {fb['event']}")
                        if fb["comment"]:
                            st.caption(f"💬 {fb['comment']}")
                        st.caption(fb["created_at"][:16])


def page_mentor_announcements():
    st.subheader("📢 Оголошення")
    st.caption("Показані глобальні оголошення платформи та оголошення для подій, у яких ви ведете Office Hours.")
    user = st.session_state.user

    assigned_events = query_df("""SELECT DISTINCT e.id, e.title FROM mentor_slots ms
                                   JOIN events e ON ms.event_id=e.id WHERE ms.mentor_id=?""", (user["id"],))

    if assigned_events.empty:
        anns = query_df("""SELECT a.created_at, a.title, a.body, COALESCE(a.priority,'Звичайне') AS priority,
                                   'Глобальне' AS event
                            FROM announcements a
                            WHERE a.event_id IS NULL AND a.target_team_id IS NULL
                            ORDER BY a.created_at DESC""")
    else:
        ids = assigned_events["id"].tolist()
        placeholders = ",".join(["?"] * len(ids))
        anns = query_df(f"""SELECT a.created_at, a.title, a.body, COALESCE(a.priority,'Звичайне') AS priority,
                                    COALESCE(e.title,'Глобальне') AS event
                             FROM announcements a
                             LEFT JOIN events e ON a.event_id=e.id
                             WHERE a.target_team_id IS NULL
                               AND (a.event_id IS NULL OR a.event_id IN ({placeholders}))
                             ORDER BY a.created_at DESC""", ids)

    if anns.empty:
        st.info("Оголошень поки немає.")
        return

    fc1, fc2 = st.columns([2, 2])
    with fc1:
        event_options = sorted(anns["event"].unique().tolist())
        event_filter = st.multiselect("Фільтр за подією", event_options)
    with fc2:
        search_ann = st.text_input("🔎 Пошук за заголовком/текстом")

    view = anns.copy()
    if event_filter:
        view = view[view["event"].isin(event_filter)]
    if search_ann.strip():
        q = search_ann.strip().lower()
        view = view[view["title"].fillna("").str.lower().str.contains(q)
                    | view["body"].fillna("").str.lower().str.contains(q)]

    if view.empty:
        st.info("За обраними фільтрами оголошень не знайдено.")
        return

    view["_is_important"] = (view["priority"] == "⭐ Важливе").astype(int)
    view = view.sort_values(["_is_important", "created_at"], ascending=[False, False])

    st.caption(f"Знайдено оголошень: {len(view)}")
    for _, a in view.iterrows():
        badge = "⭐ " if a["priority"] == "⭐ Важливе" else ""
        with st.container(border=True):
            st.markdown(f"**{badge}{a['title']}**")
            st.caption(f"{a['created_at']} · {a['event']}")
            st.write(a["body"])


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
