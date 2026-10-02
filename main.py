from flask import Flask, render_template_string, request, redirect, session, url_for, send_file
from werkzeug.security import generate_password_hash, check_password_hash

import sqlite3
import os
import hashlib
import asyncio
import random
import edge_tts


app = Flask(__name__)
app.secret_key = "KOREAN_TJ_SECRET_2026"

DB_NAME = "korean.db"

AUDIO_DIR = os.path.join("static", "audio")
os.makedirs(AUDIO_DIR, exist_ok=True)


# =========================================================
# DATABASE
# =========================================================

def get_db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            xp INTEGER DEFAULT 0,
            difficulty TEXT DEFAULT 'easy',
            streak INTEGER DEFAULT 0
        )
    """)

    # Агар базаи кӯҳна бошад, колонкаҳои навро илова мекунем
    columns = [
        row["name"]
        for row in conn.execute("PRAGMA table_info(users)").fetchall()
    ]

    if "difficulty" not in columns:
        conn.execute(
            "ALTER TABLE users ADD COLUMN difficulty TEXT DEFAULT 'easy'"
        )

    if "streak" not in columns:
        conn.execute(
            "ALTER TABLE users ADD COLUMN streak INTEGER DEFAULT 0"
        )

    conn.execute("""
        CREATE TABLE IF NOT EXISTS questions_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            question TEXT,
            correct_answer TEXT,
            user_answer TEXT,
            correct INTEGER,
            difficulty TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    history_columns = [
        row["name"]
        for row in conn.execute(
            "PRAGMA table_info(questions_history)"
        ).fetchall()
    ]

    if "difficulty" not in history_columns:
        conn.execute(
            "ALTER TABLE questions_history "
            "ADD COLUMN difficulty TEXT DEFAULT 'easy'"
        )

    conn.commit()
    conn.close()


init_db()


# =========================================================
# XP / LEVEL
# =========================================================

def get_level(xp):
    return (xp // 100) + 1


def get_progress(xp):
    return xp % 100


def get_xp_for_question(difficulty):
    if difficulty == "easy":
        return 5

    if difficulty == "medium":
        return 10

    return 20


# =========================================================
# USER
# =========================================================

def get_user():
    if "user_id" not in session:
        return None

    conn = get_db()

    user = conn.execute(
        "SELECT * FROM users WHERE id = ?",
        (session["user_id"],)
    ).fetchone()

    conn.close()

    return user


def add_xp(user_id, amount):
    conn = get_db()

    conn.execute(
        "UPDATE users SET xp = xp + ? WHERE id = ?",
        (amount, user_id)
    )

    conn.commit()
    conn.close()


# =========================================================
# WORDS
# =========================================================

EASY_WORDS = [
    ("안녕", "Салом"),
    ("네", "Ҳа"),
    ("아니요", "Не"),
    ("물", "Об"),
    ("밥", "Хӯрок"),
    ("집", "Хона"),
    ("책", "Китоб"),
    ("친구", "Дӯст"),
    ("사람", "Одам"),
    ("학교", "Мактаб"),
    ("사과", "Себ"),
    ("빵", "Нон"),
    ("우유", "Шир"),
    ("차", "Чой"),
    ("오늘", "Имрӯз"),
    ("내일", "Фардо"),
    ("어제", "Дирӯз"),
    ("아침", "Субҳ"),
    ("밤", "Шаб"),
    ("사랑", "Муҳаббат"),
]

MEDIUM_WORDS = [
    ("감사합니다", "Ташаккур"),
    ("미안해요", "Бубахшед"),
    ("학생", "Донишҷӯ"),
    ("선생님", "Муаллим"),
    ("한국", "Корея"),
    ("한국어", "Забони кореягӣ"),
    ("가족", "Оила"),
    ("공책", "Дафтар"),
    ("연필", "Қалам"),
    ("회사", "Ширкат"),
    ("병원", "Беморхона"),
    ("식당", "Тарабхона"),
    ("시장", "Бозор"),
    ("점심", "Нисфирӯзӣ"),
    ("저녁", "Шом"),
    ("시간", "Вақт"),
    ("행복", "Хушбахтӣ"),
    ("과일", "Мева"),
    ("고기", "Гӯшт"),
    ("커피", "Қаҳва"),
]

HARD_WORDS = [
    ("공부하다", "Таҳсил кардан"),
    ("일어나다", "Бедор шудан"),
    ("만나다", "Вохӯрдан"),
    ("사다", "Харидан"),
    ("받다", "Гирифтан"),
    ("알다", "Донистан"),
    ("모르다", "Надонистан"),
    ("재미있다", "Шавқовар будан"),
    ("어렵다", "Душвор будан"),
    ("쉽다", "Осон будан"),
    ("예쁘다", "Зебо будан"),
    ("빠르다", "Тез будан"),
    ("느리다", "Оҳиста будан"),
    ("많다", "Зиёд будан"),
    ("적다", "Кам будан"),
    ("일하다", "Кор кардан"),
    ("한국어를 배우다", "Забони кореягиро омӯхтан"),
    ("한국어를 공부하다", "Забони кореягиро таҳсил кардан"),
]


# =========================================================
# SENTENCES
# =========================================================

EASY_SENTENCES = [
    ("안녕하세요", "Салом"),
    ("감사합니다", "Ташаккур"),
    ("괜찮아요", "Ҳеҷ гап не"),
    ("잘 지내요?", "Хуб ҳастӣ?"),
    ("이름이 뭐예요?", "Номат чист?"),
]

MEDIUM_SENTENCES = [
    ("저는 학생이에요.", "Ман донишҷӯ ҳастам."),
    ("저는 물을 마셔요.", "Ман об менӯшам."),
    ("저는 밥을 먹어요.", "Ман хӯрок мехӯрам."),
    ("친구가 와요.", "Дӯст меояд."),
    ("저는 학교에 가요.", "Ман ба мактаб меравам."),
    ("저는 책을 읽어요.", "Ман китоб мехонам."),
    ("오늘 공부해요.", "Имрӯз мехонам."),
]

HARD_SENTENCES = [
    ("저는 한국어를 열심히 공부해요.", "Ман забони кореягиро бо ҷидду ҷаҳд меомӯзам."),
    ("친구와 함께 학교에 가요.", "Ман ҳамроҳи дӯстам ба мактаб меравам."),
    ("저녁에 가족과 같이 밥을 먹어요.", "Шом бо оила якҷоя хӯрок мехӯрам."),
    ("한국어를 배우는 것이 재미있어요.", "Омӯхтани забони кореягӣ шавқовар аст."),
    ("매일 한국어 단어를 외워요.", "Ҳар рӯз калимаҳои кореягиро аз ёд мекунам."),
]


# =========================================================
# GRAMMAR
# =========================================================

EASY_GRAMMAR = [
    ("Ман донишҷӯ ҳастам.", "저는 학생이에요."),
    ("Ман дӯст ҳастам.", "저는 친구예요."),
    ("Ман об менӯшам.", "저는 물을 마셔요."),
    ("Ман хӯрок мехӯрам.", "저는 밥을 먹어요."),
]

MEDIUM_GRAMMAR = [
    ("Дӯст меояд.", "친구가 와요."),
    ("Ман ба мактаб меравам.", "저는 학교에 가요."),
    ("Ман китоб мехонам.", "저는 책을 읽어요."),
    ("Ман кор мекунам.", "저는 일해요."),
    ("Ман забони кореягӣ мехонам.", "저는 한국어를 공부해요."),
]

HARD_GRAMMAR = [
    ("Ман ҳар рӯз забони кореягиро меомӯзам.",
     "저는 매일 한국어를 공부해요."),

    ("Ман ҳамроҳи дӯстам ба мактаб меравам.",
     "저는 친구와 함께 학교에 가요."),

    ("Ман мехоҳам забони кореягиро хуб омӯзам.",
     "저는 한국어를 잘 배우고 싶어요."),

    ("Ман ҳар рӯз калимаҳои навро аз ёд мекунам.",
     "저는 매일 새로운 단어를 외워요."),
]


# =========================================================
# DATA BY DIFFICULTY
# =========================================================

def get_words(difficulty):

    if difficulty == "easy":
        return EASY_WORDS

    if difficulty == "medium":
        return EASY_WORDS + MEDIUM_WORDS

    return EASY_WORDS + MEDIUM_WORDS + HARD_WORDS


def get_sentences(difficulty):

    if difficulty == "easy":
        return EASY_SENTENCES

    if difficulty == "medium":
        return EASY_SENTENCES + MEDIUM_SENTENCES

    return EASY_SENTENCES + MEDIUM_SENTENCES + HARD_SENTENCES


def get_grammar(difficulty):

    if difficulty == "easy":
        return EASY_GRAMMAR

    if difficulty == "medium":
        return EASY_GRAMMAR + MEDIUM_GRAMMAR

    return EASY_GRAMMAR + MEDIUM_GRAMMAR + HARD_GRAMMAR


# =========================================================
# OPTIONS
# =========================================================

def make_options(correct, pool, count=4):

    pool = list(dict.fromkeys(pool))

    wrong = [
        item
        for item in pool
        if item != correct
    ]

    random.shuffle(wrong)

    options = wrong[:count - 1]

    options.append(correct)

    random.shuffle(options)

    return options


# =========================================================
# QUESTION 1
# =========================================================

def generate_word_question(difficulty):

    words = get_words(difficulty)

    korean, tajik = random.choice(words)

    meanings = [x[1] for x in words]

    options = make_options(
        tajik,
        meanings
    )

    return {
        "type": "Кореягӣ → Тоҷикӣ",
        "question": "Маънои ин калима чист?",
        "display": korean,
        "correct": tajik,
        "options": options,
        "audio": korean,
        "difficulty": difficulty
    }


# =========================================================
# QUESTION 2
# =========================================================

def generate_reverse_word_question(difficulty):

    words = get_words(difficulty)

    korean, tajik = random.choice(words)

    korean_words = [x[0] for x in words]

    options = make_options(
        korean,
        korean_words
    )

    return {
        "type": "Тоҷикӣ → Кореягӣ",
        "question": "Ба кореягӣ чӣ мешавад?",
        "display": tajik,
        "correct": korean,
        "options": options,
        "audio": korean,
        "difficulty": difficulty
    }


# =========================================================
# QUESTION 3
# =========================================================

def generate_sentence_question(difficulty):

    sentences = get_sentences(difficulty)

    korean, tajik = random.choice(sentences)

    meanings = [x[1] for x in sentences]

    options = make_options(
        tajik,
        meanings
    )

    return {
        "type": "Ҷумла → Тоҷикӣ",
        "question": "Тарҷумаи ҷумла чист?",
        "display": korean,
        "correct": tajik,
        "options": options,
        "audio": korean,
        "difficulty": difficulty
    }


# =========================================================
# QUESTION 4
# =========================================================

def generate_reverse_sentence_question(difficulty):

    sentences = get_sentences(difficulty)

    korean, tajik = random.choice(sentences)

    korean_sentences = [
        x[0]
        for x in sentences
    ]

    options = make_options(
        korean,
        korean_sentences
    )

    return {
        "type": "Тоҷикӣ → Ҷумлаи кореягӣ",
        "question": "Ҷавоби дурусти кореягиро интихоб кун:",
        "display": tajik,
        "correct": korean,
        "options": options,
        "audio": korean,
        "difficulty": difficulty
    }


# =========================================================
# QUESTION 5
# =========================================================

def generate_grammar_question(difficulty):

    grammar = get_grammar(difficulty)

    tajik, korean = random.choice(grammar)

    korean_sentences = [
        x[1]
        for x in grammar
    ]

    options = make_options(
        korean,
        korean_sentences
    )

    return {
        "type": "Грамматика",
        "question": "Ҷавоби дурусти кореягиро интихоб кун:",
        "display": tajik,
        "correct": korean,
        "options": options,
        "audio": korean,
        "difficulty": difficulty
    }


# =========================================================
# QUESTION 6
# =========================================================

def generate_true_false_question(difficulty):

    words = get_words(difficulty)

    korean, tajik = random.choice(words)

    correct_translation = random.choice([True, False])

    if correct_translation:

        shown = tajik
        answer = "Дуруст"

    else:

        other = [
            x[1]
            for x in words
            if x[1] != tajik
        ]

        shown = random.choice(other)
        answer = "Нодуруст"

    return {
        "type": "Дуруст / Нодуруст",
        "question": f"Оё тарҷума дуруст аст?",
        "display": f"{korean} = {shown}",
        "correct": answer,
        "options": [
            "Дуруст",
            "Нодуруст"
        ],
        "audio": korean,
        "difficulty": difficulty
    }


# =========================================================
# QUESTION 7
# =========================================================

def generate_missing_word_question(difficulty):

    sentences = get_sentences(difficulty)

    korean, tajik = random.choice(sentences)

    words = korean.split()

    if len(words) < 2:
        return generate_word_question(difficulty)

    index = random.randrange(
        len(words)
    )

    correct = words[index]

    display_words = words.copy()

    display_words[index] = "_____"

    all_words = [
        x[0]
        for x in get_words(difficulty)
    ]

    options = make_options(
        correct,
        all_words
    )

    return {
        "type": "Ҷои холӣ",
        "question": "Калимаи гумшударо интихоб кун:",
        "display": " ".join(display_words),
        "correct": correct,
        "options": options,
        "audio": korean,
        "difficulty": difficulty
    }


# =========================================================
# MAIN GENERATOR
# =========================================================

def generate_question(difficulty):

    generators = [
        generate_word_question,
        generate_reverse_word_question,
        generate_sentence_question,
        generate_reverse_sentence_question,
        generate_grammar_question,
        generate_true_false_question,
        generate_missing_word_question,
    ]

    generator = random.choice(generators)

    return generator(difficulty)


# =========================================================
# AUDIO
# =========================================================

async def generate_audio(text, filepath):

    communicate = edge_tts.Communicate(
        text=text,
        voice="ko-KR-SunHiNeural",
        rate="-5%",
        pitch="+0Hz"
    )

    await communicate.save(filepath)


def make_audio(text):

    filename = (
        hashlib.md5(
            text.encode("utf-8")
        ).hexdigest()
        + ".mp3"
    )

    filepath = os.path.join(
        AUDIO_DIR,
        filename
    )

    if not os.path.exists(filepath):

        asyncio.run(
            generate_audio(
                text,
                filepath
            )
        )

    return filepath


# =========================================================
# STYLE — ФОНРО ДАСТ НАМЕЗАНЕМ
# =========================================================

STYLE = """
<style>

* {
    box-sizing: border-box;
}

body {
    margin: 0;
    font-family: Arial, sans-serif;
    background:
        radial-gradient(circle at top, #243b70, #090b13 55%);
    color: white;
    min-height: 100vh;
}

.container {
    width: min(1100px, 94%);
    margin: auto;
    padding: 30px 0 60px;
}

.nav {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 25px;
}

.logo {
    font-size: 26px;
    font-weight: 800;
}

.nav a {
    color: white;
    text-decoration: none;
    margin-left: 10px;
    padding: 10px 15px;
    border-radius: 14px;
    background: rgba(255,255,255,.10);
}

.card {
    background: rgba(255,255,255,.10);
    border: 1px solid rgba(255,255,255,.14);
    backdrop-filter: blur(20px);
    border-radius: 25px;
    padding: 25px;
    margin-bottom: 20px;
    box-shadow: 0 15px 50px rgba(0,0,0,.25);
}

h1 {
    font-size: 42px;
    margin-bottom: 10px;
}

h2 {
    margin-top: 0;
}

.subtitle {
    color: #c9cce0;
    font-size: 18px;
}

.grid {
    display: grid;
    grid-template-columns:
        repeat(auto-fit, minmax(210px, 1fr));
    gap: 16px;
}

.lesson {
    display: block;
    text-decoration: none;
    color: white;
    background: rgba(255,255,255,.09);
    border: 1px solid rgba(255,255,255,.12);
    border-radius: 22px;
    padding: 22px;
    transition: .2s;
}

.lesson:hover {
    transform: translateY(-4px);
    background: rgba(255,255,255,.15);
}

.lesson .emoji {
    font-size: 38px;
}

button,
.btn {
    border: 0;
    cursor: pointer;
    display: inline-block;
    padding: 14px 20px;
    border-radius: 16px;
    background: white;
    color: #111;
    text-decoration: none;
    font-size: 16px;
    font-weight: bold;
    margin-top: 10px;
}

button:hover,
.btn:hover {
    transform: scale(1.02);
}

.option {
    width: 100%;
    text-align: left;
    margin: 8px 0;
    background: rgba(255,255,255,.10);
    color: white;
    border: 1px solid rgba(255,255,255,.15);
}

.option:hover {
    background: rgba(255,255,255,.18);
}

.korean {
    font-size: 38px;
    font-weight: bold;
    text-align: center;
    margin: 25px 0;
}

.progress {
    width: 100%;
    height: 15px;
    background: rgba(255,255,255,.12);
    border-radius: 20px;
    overflow: hidden;
}

.progress-bar {
    height: 100%;
    background: white;
    border-radius: 20px;
}

.xp {
    font-size: 20px;
    margin-bottom: 10px;
}

.correct {
    color: #75ff9d;
    font-size: 24px;
}

.wrong {
    color: #ff7777;
    font-size: 24px;
}

.level-card {
    text-align: center;
}

.level-button {
    text-align: center;
    cursor: pointer;
}

.level-button h2 {
    font-size: 30px;
}

.easy {
    border: 2px solid rgba(100,255,150,.35);
}

.medium {
    border: 2px solid rgba(255,210,80,.35);
}

.hard {
    border: 2px solid rgba(255,90,90,.35);
}

.small {
    color: #aaaec0;
}

@media(max-width:600px) {

    h1 {
        font-size: 32px;
    }

    .korean {
        font-size: 30px;
    }

    .nav {
        flex-direction: column;
        align-items: flex-start;
        gap: 15px;
    }

}

</style>
"""


# =========================================================
# NAV
# =========================================================

def nav_html():

    user = get_user()

    if user:

        return f"""
        <div class="nav">

            <div class="logo">
                🇰🇷 Korean TJ
            </div>

            <div>

                <a href="/">🏠</a>

                <a href="/questions">
                    🧠
                </a>

                <a href="/progress">
                    📊
                </a>

                <a href="/logout">
                    🚪
                </a>

            </div>

        </div>
        """

    return """
    <div class="nav">

        <div class="logo">
            🇰🇷 Korean TJ
        </div>

        <div>

            <a href="/login">
                Ворид шудан
            </a>

            <a href="/register">
                Регистрация
            </a>

        </div>

    </div>
    """


# =========================================================
# HOME
# =========================================================

@app.route("/")
def home():

    user = get_user()

    if not user:

        return render_template_string(
            STYLE + """

            <div class="container">

                {{ nav|safe }}

                <div class="card">

                    <h1>
                        🇰🇷 Korean TJ
                    </h1>

                    <p class="subtitle">
                        Забони кореягиро осон омӯз!
                    </p>

                    <div class="grid">

                        <a class="lesson" href="/alphabet">
                            <div class="emoji">🔤</div>
                            <h3>Ҳангул</h3>
                            <p>Алифбои кореягӣ</p>
                        </a>

                        <a class="lesson" href="/words">
                            <div class="emoji">📚</div>
                            <h3>Луғат</h3>
                        </a>

                        <a class="lesson" href="/grammar">
                            <div class="emoji">📖</div>
                            <h3>Грамматика</h3>
                        </a>

                        <a class="lesson" href="/questions">
                            <div class="emoji">🧠</div>
                            <h3>Саволҳо</h3>
                        </a>

                    </div>

                    <br>

                    <a class="btn" href="/register">
                        🚀 Оғози омӯзиш
                    </a>

                </div>

            </div>

            """,
            nav=nav_html()
        )

    level = get_level(user["xp"])
    progress = get_progress(user["xp"])

    return render_template_string(
        STYLE + """

        <div class="container">

            {{ nav|safe }}

            <div class="card">

                <h1>
                    Салом, {{ username }} 👋
                </h1>

                <p class="subtitle">
                    Давом деҳ — ҳар ҷавоби дуруст XP медиҳад!
                </p>

                <div class="xp">
                    ⭐ Level {{ level }}
                    — {{ xp }} XP
                </div>

                <div class="progress">

                    <div
                        class="progress-bar"
                        style="width: {{ progress }}%;"
                    ></div>

                </div>

                <br>

                <a class="btn" href="/questions">
                    🧠 Оғози тест
                </a>

            </div>

            <div class="grid">

                <a class="lesson" href="/alphabet">
                    <div class="emoji">🔤</div>
                    <h3>Ҳангул</h3>
                </a>

                <a class="lesson" href="/words">
                    <div class="emoji">📚</div>
                    <h3>Луғат</h3>
                </a>

                <a class="lesson" href="/grammar">
                    <div class="emoji">📖</div>
                    <h3>Грамматика</h3>
                </a>

                <a class="lesson" href="/difficulty">
                    <div class="emoji">🎯</div>
                    <h3>Сатҳи омӯзиш</h3>
                </a>

                <a class="lesson" href="/progress">
                    <div class="emoji">📊</div>
                    <h3>Пешрафт</h3>
                </a>

            </div>

        </div>

        """,
        nav=nav_html(),
        username=user["username"],
        level=level,
        xp=user["xp"],
        progress=progress
    )


# =========================================================
# DIFFICULTY
# =========================================================

@app.route("/difficulty", methods=["GET", "POST"])
def difficulty():

    user = get_user()

    if not user:
        return redirect(url_for("login"))

    if request.method == "POST":

        selected = request.form.get(
            "difficulty",
            "easy"
        )

        if selected not in [
            "easy",
            "medium",
            "hard"
        ]:
            selected = "easy"

        conn = get_db()

        conn.execute(
            """
            UPDATE users
            SET difficulty = ?
            WHERE id = ?
            """,
            (
                selected,
                user["id"]
            )
        )

        conn.commit()
        conn.close()

        return redirect(url_for("questions"))

    current = user["difficulty"] or "easy"

    return render_template_string(
        STYLE + """

        <div class="container">

            {{ nav|safe }}

            <div class="card">

                <h1>
                    🎯 Сатҳи омӯзиш
                </h1>

                <p class="subtitle">
                    Сатҳро интихоб кун.
                </p>

                <form method="POST">

                    <button
                        class="lesson level-button easy"
                        name="difficulty"
                        value="easy"
                        type="submit"
                    >
                        <h2>🟢 Easy</h2>
                        <p>
                            Барои шурӯъкунандагон
                        </p>
                        <p>
                            ⭐ +5 XP
                        </p>
                    </button>

                    <br>

                    <button
                        class="lesson level-button medium"
                        name="difficulty"
                        value="medium"
                        type="submit"
                    >
                        <h2>🟡 Medium</h2>
                        <p>
                            Барои сатҳи миёна
                        </p>
                        <p>
                            ⭐ +10 XP
                        </p>
                    </button>

                    <br>

                    <button
                        class="lesson level-button hard"
                        name="difficulty"
                        value="hard"
                        type="submit"
                    >
                        <h2>🔴 Hard</h2>
                        <p>
                            Барои саволҳои душвор
                        </p>
                        <p>
                            ⭐ +20 XP
                        </p>
                    </button>

                </form>

                <p class="small">
                    Сатҳи ҳозира:
                    <b>{{ current }}</b>
                </p>

            </div>

        </div>

        """,
        nav=nav_html(),
        current=current
    )


# =========================================================
# REGISTER
# =========================================================

@app.route("/register", methods=["GET", "POST"])
def register():

    error = ""

    if request.method == "POST":

        username = request.form["username"].strip()
        password = request.form["password"]

        if len(username) < 3:

            error = "Username бояд камаш 3 ҳарф бошад."

        elif len(password) < 4:

            error = "Парол бояд камаш 4 аломат бошад."

        else:

            conn = get_db()

            try:

                conn.execute(
                    """
                    INSERT INTO users
                    (username, password)
                    VALUES (?, ?)
                    """,
                    (
                        username,
                        generate_password_hash(password)
                    )
                )

                conn.commit()

                user = conn.execute(
                    """
                    SELECT *
                    FROM users
                    WHERE username = ?
                    """,
                    (username,)
                ).fetchone()

                session["user_id"] = user["id"]

                conn.close()

                return redirect(url_for("home"))

            except sqlite3.IntegrityError:

                conn.close()

                error = (
                    "Ин username аллакай истифода мешавад."
                )

    return render_template_string(
        STYLE + """

        <div class="container">

            {{ nav|safe }}

            <div class="card">

                <h1>
                    🚀 Регистрация
                </h1>

                {% if error %}

                    <p class="wrong">
                        {{ error }}
                    </p>

                {% endif %}

                <form method="POST">

                    <input
                        name="username"
                        placeholder="Username"
                        required
                    >

                    <input
                        type="password"
                        name="password"
                        placeholder="Парол"
                        required
                    >

                    <button type="submit">
                        Создать аккаунт
                    </button>

                </form>

            </div>

        </div>

        """,
        nav=nav_html(),
        error=error
    )


# =========================================================
# LOGIN
# =========================================================

@app.route("/login", methods=["GET", "POST"])
def login():

    error = ""

    if request.method == "POST":

        username = request.form["username"].strip()
        password = request.form["password"]

        conn = get_db()

        user = conn.execute(
            """
            SELECT *
            FROM users
            WHERE username = ?
            """,
            (username,)
        ).fetchone()

        conn.close()

        if user and check_password_hash(
            user["password"],
            password
        ):

            session["user_id"] = user["id"]

            return redirect(url_for("home"))

        error = "Username ё парол нодуруст аст."

    return render_template_string(
        STYLE + """

        <div class="container">

            {{ nav|safe }}

            <div class="card">

                <h1>
                    🔐 Ворид шудан
                </h1>

                {% if error %}

                    <p class="wrong">
                        {{ error }}
                    </p>

                {% endif %}

                <form method="POST">

                    <input
                        name="username"
                        placeholder="Username"
                        required
                    >

                    <input
                        type="password"
                        name="password"
                        placeholder="Парол"
                        required
                    >

                    <button type="submit">
                        Ворид шудан
                    </button>

                </form>

            </div>

        </div>

        """,
        nav=nav_html(),
        error=error
    )


# =========================================================
# LOGOUT
# =========================================================

@app.route("/logout")
def logout():

    session.clear()

    return redirect(url_for("home"))


# =========================================================
# QUESTIONS
# =========================================================

@app.route("/questions")
def questions():

    user = get_user()

    if not user:
        return redirect(url_for("login"))

    difficulty_level = user["difficulty"] or "easy"

    question = generate_question(
        difficulty_level
    )

    session["current_question"] = question

    return render_template_string(
        STYLE + """

        <div class="container">

            {{ nav|safe }}

            <div class="card">

                <div class="small">
                    Сатҳ:
                    {% if difficulty == "easy" %}
                        🟢 Easy
                    {% elif difficulty == "medium" %}
                        🟡 Medium
                    {% else %}
                        🔴 Hard
                    {% endif %}
                </div>

                <h2>
                    {{ question }}
                </h2>

                <div class="korean">
                    {{ display }}
                </div>

                <button
                    onclick="playAudio('{{ audio }}')"
                >
                    🔊 Гӯш кардан
                </button>

                <form
                    method="POST"
                    action="/answer"
                >

                    {% for option in options %}

                        <button
                            class="option"
                            type="submit"
                            name="answer"
                            value="{{ option }}"
                        >
                            {{ option }}
                        </button>

                    {% endfor %}

                </form>

            </div>

        </div>

        <script>

        function playAudio(text) {

            const audio =
                new Audio(
                    "/speak?text=" +
                    encodeURIComponent(text)
                );

            audio.play().catch(function() {

                alert(
                    "Овоз пахш нашуд. Интернетро санҷ."
                );

            });

        }

        </script>

        """,
        nav=nav_html(),
        difficulty=difficulty_level,
        question=question["question"],
        display=question["display"],
        options=question["options"],
        audio=question["audio"]
    )


# =========================================================
# ANSWER
# =========================================================

@app.route("/answer", methods=["POST"])
def answer():

    user = get_user()

    if not user:
        return redirect(url_for("login"))

    question = session.get(
        "current_question"
    )

    if not question:
        return redirect(
            url_for("questions")
        )

    user_answer = request.form["answer"]

    correct_answer = question["correct"]

    is_correct = (
        user_answer == correct_answer
    )

    difficulty = question.get(
        "difficulty",
        "easy"
    )

    xp = get_xp_for_question(
        difficulty
    )

    if is_correct:

        add_xp(
            user["id"],
            xp
        )

        conn = get_db()

        conn.execute(
            """
            UPDATE users
            SET streak = streak + 1
            WHERE id = ?
            """,
            (user["id"],)
        )

        conn.commit()
        conn.close()

    else:

        conn = get_db()

        conn.execute(
            """
            UPDATE users
            SET streak = 0
            WHERE id = ?
            """,
            (user["id"],)
        )

        conn.commit()
        conn.close()

    conn = get_db()

    conn.execute(
        """
        INSERT INTO questions_history
        (
            user_id,
            question,
            correct_answer,
            user_answer,
            correct,
            difficulty
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            user["id"],
            question["display"],
            correct_answer,
            user_answer,
            1 if is_correct else 0,
            difficulty
        )
    )

    conn.commit()
    conn.close()

    return render_template_string(
        STYLE + """

        <div class="container">

            {{ nav|safe }}

            <div class="card">

                {% if correct %}

                    <div class="correct">
                        ✅ Дуруст!
                    </div>

                    <h2>
                        +{{ xp }} XP ⭐
                    </h2>

                    <p>
                        🔥 Streak:
                        {{ streak }}
                    </p>

                {% else %}

                    <div class="wrong">
                        ❌ Нодуруст
                    </div>

                    <h3>
                        Ҷавоби дуруст:
                    </h3>

                    <div class="korean">
                        {{ answer }}
                    </div>

                {% endif %}

                <br>

                <a
                    class="btn"
                    href="/questions"
                >
                    ➡️ Саволи дигар
                </a>

            </div>

        </div>

        """,
        nav=nav_html(),
        correct=is_correct,
        xp=xp,
        streak=get_user()["streak"],
        answer=correct_answer
    )


# =========================================================
# PROGRESS
# =========================================================

@app.route("/progress")
def progress_page():

    user = get_user()

    if not user:
        return redirect(url_for("login"))

    conn = get_db()

    total = conn.execute(
        """
        SELECT COUNT(*)
        FROM questions_history
        WHERE user_id = ?
        """,
        (user["id"],)
    ).fetchone()[0]

    correct = conn.execute(
        """
        SELECT COUNT(*)
        FROM questions_history
        WHERE user_id = ?
        AND correct = 1
        """,
        (user["id"],)
    ).fetchone()[0]

    conn.close()

    accuracy = 0

    if total > 0:
        accuracy = round(
            correct / total * 100
        )

    level = get_level(
        user["xp"]
    )

    progress = get_progress(
        user["xp"]
    )

    return render_template_string(
        STYLE + """

        <div class="container">

            {{ nav|safe }}

            <div class="card">

                <h1>
                    📊 Пешрафт
                </h1>

                <h2>
                    ⭐ Level {{ level }}
                </h2>

                <div class="xp">
                    {{ xp }} XP
                </div>

                <div class="progress">

                    <div
                        class="progress-bar"
                        style="width: {{ progress }}%;"
                    ></div>

                </div>

                <br>

                <div class="grid">

                    <div class="lesson">
                        <div class="emoji">🧠</div>
                        <h3>{{ total }}</h3>
                        <p>Саволҳо</p>
                    </div>

                    <div class="lesson">
                        <div class="emoji">✅</div>
                        <h3>{{ correct }}</h3>
                        <p>Дуруст</p>
                    </div>

                    <div class="lesson">
                        <div class="emoji">🎯</div>
                        <h3>{{ accuracy }}%</h3>
                        <p>Дақиқӣ</p>
                    </div>

                    <div class="lesson">
                        <div class="emoji">🔥</div>
                        <h3>{{ streak }}</h3>
                        <p>Streak</p>
                    </div>

                </div>

            </div>

        </div>

        """,
        nav=nav_html(),
        level=level,
        xp=user["xp"],
        progress=progress,
        total=total,
        correct=correct,
        accuracy=accuracy,
        streak=user["streak"]
    )


# =========================================================
# SPEAK
# =========================================================

@app.route("/speak")
def speak():

    text = request.args.get(
        "text",
        ""
    ).strip()

    if not text:
        return "Матн нест", 400

    try:

        filepath = make_audio(text)

        return send_file(
            filepath,
            mimetype="audio/mpeg"
        )

    except Exception as e:

        return f"Хатои овоз: {e}", 500


# =========================================================
# ALPHABET
# =========================================================

@app.route("/alphabet")
def alphabet():

    vowels = [
        ("ㅏ", "a"),
        ("ㅑ", "ya"),
        ("ㅓ", "eo"),
        ("ㅕ", "yeo"),
        ("ㅗ", "o"),
        ("ㅜ", "u"),
        ("ㅡ", "eu"),
        ("ㅣ", "i"),
    ]

    consonants = [
        ("ㄱ", "g/k"),
        ("ㄴ", "n"),
        ("ㄷ", "d/t"),
        ("ㄹ", "r/l"),
        ("ㅁ", "m"),
        ("ㅂ", "b/p"),
        ("ㅅ", "s"),
        ("ㅇ", "ng"),
        ("ㅈ", "j"),
        ("ㅊ", "ch"),
        ("ㅋ", "k"),
        ("ㅌ", "t"),
        ("ㅍ", "p"),
        ("ㅎ", "h"),
    ]

    return render_template_string(
        STYLE + """

        <div class="container">

            {{ nav|safe }}

            <div class="card">

                <h1>
                    🔤 Ҳангул
                </h1>

                <h2>
                    Садонокҳо
                </h2>

                <div class="grid">

                {% for item in vowels %}

                    <div class="lesson">

                        <div class="korean">
                            {{ item[0] }}
                        </div>

                        <p>
                            {{ item[1] }}
                        </p>

                        <button
                            onclick="playAudio('{{ item[0] }}')"
                        >
                            🔊
                        </button>

                    </div>

                {% endfor %}

                </div>

            </div>

            <div class="card">

                <h2>
                    Ҳамсадоҳо
                </h2>

                <div class="grid">

                {% for item in consonants %}

                    <div class="lesson">

                        <div class="korean">
                            {{ item[0] }}
                        </div>

                        <p>
                            {{ item[1] }}
                        </p>

                        <button
                            onclick="playAudio('{{ item[0] }}')"
                        >
                            🔊
                        </button>

                    </div>

                {% endfor %}

                </div>

            </div>

        </div>

        <script>

        function playAudio(text) {

            const audio =
                new Audio(
                    "/speak?text=" +
                    encodeURIComponent(text)
                );

            audio.play();

        }

        </script>

        """,
        nav=nav_html(),
        vowels=vowels,
        consonants=consonants
    )


# =========================================================
# WORDS
# =========================================================

@app.route("/words")
def words():

    words = (
        EASY_WORDS
        + MEDIUM_WORDS
        + HARD_WORDS
    )

    return render_template_string(
        STYLE + """

        <div class="container">

            {{ nav|safe }}

            <div class="card">

                <h1>
                    📚 Луғат
                </h1>

                <div class="grid">

                {% for korean, tajik in words %}

                    <div class="lesson">

                        <div class="korean">
                            {{ korean }}
                        </div>

                        <h3>
                            {{ tajik }}
                        </h3>

                        <button
                            onclick="playAudio('{{ korean }}')"
                        >
                            🔊 Гӯш кардан
                        </button>

                    </div>

                {% endfor %}

                </div>

            </div>

        </div>

        <script>

        function playAudio(text) {

            const audio =
                new Audio(
                    "/speak?text=" +
                    encodeURIComponent(text)
                );

            audio.play();

        }

        </script>

        """,
        nav=nav_html(),
        words=words
    )


# =========================================================
# GRAMMAR
# =========================================================

@app.route("/grammar")
def grammar():

    return render_template_string(
        STYLE + """

        <div class="container">

            {{ nav|safe }}

            <div class="card">

                <h1>
                    📖 Грамматика
                </h1>

                <h2>
                    은 / 는
                </h2>

                <p>
                    Мавзӯи ҷумла.
                </p>

                <p>
                    나는 학생이에요.
                    — Ман донишҷӯ ҳастам.
                </p>

                <h2>
                    이 / 가
                </h2>

                <p>
                    Нишондиҳандаи субъект.
                </p>

                <p>
                    친구가 와요.
                    — Дӯст меояд.
                </p>

                <h2>
                    을 / 를
                </h2>

                <p>
                    Нишондиҳандаи объект.
                </p>

                <p>
                    밥을 먹어요.
                    — Хӯрок мехӯрам.
                </p>

                <h2>
                    이에요 / 예요
                </h2>

                <p>
                    Барои "будан / ҳастам".
                </p>

                <p>
                    학생이에요.
                    — Донишҷӯ ҳастам.
                </p>

                <p>
                    친구예요.
                    — Дӯст ҳастам.
                </p>

                <h2>
                    아요 / 어요
                </h2>

                <p>
                    Шакли хушмуомила.
                </p>

                <p>
                    가요 — меравам
                </p>

                <p>
                    먹어요 — мехӯрам
                </p>

                <p>
                    마셔요 — менӯшам
                </p>

                <p>
                    공부해요 — мехонам
                </p>

            </div>

        </div>

        """,
        nav=nav_html()
    )


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":

    print()
    print("=" * 50)
    print("🇰🇷 KOREAN TJ STARTED")
    print("🌐 http://127.0.0.1:5000")
    print("=" * 50)
    print()

app.run(
    host="0.0.0.0",
    port=5000
)