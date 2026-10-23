
import os
import re
import time
import sqlite3
from flask import (
    Flask, render_template, request,
    redirect, url_for, session
)
from werkzeug.security import (
    generate_password_hash, check_password_hash
)
from PyPDF2 import PdfReader
import nltk
from nltk.corpus import stopwords
from nltk.tokenize import sent_tokenize


# --------------------------------------------------
# 1. FLASK APPLICATION CONFIGURATION
# --------------------------------------------------

app = Flask(__name__)
app.secret_key = os.environ.get(
    "SECRET_KEY",
    "change-this-secret-key-before-deployment"
)

DATABASE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "users.db"
)


# --------------------------------------------------
# 2. NLTK RESOURCES
# --------------------------------------------------

def initialize_nltk():
    resources = [
        ("tokenizers/punkt", "punkt"),
        ("tokenizers/punkt_tab", "punkt_tab"),
        ("corpora/stopwords", "stopwords")
    ]

    for resource_path, package_name in resources:
        try:
            nltk.data.find(resource_path)
        except LookupError:
            nltk.download(package_name, quiet=True)


initialize_nltk()


# --------------------------------------------------
# 3. SQLITE DATABASE
# --------------------------------------------------

def get_db_connection():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def create_database():
    conn = get_db_connection()

    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                email TEXT NOT NULL UNIQUE,
                password TEXT NOT NULL
            )
        """)
        conn.commit()
    finally:
        conn.close()


# --------------------------------------------------
# 4. USER REGISTRATION
# --------------------------------------------------

@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        username = request.form.get(
            "username", ""
        ).strip()

        email = request.form.get(
            "email", ""
        ).strip().lower()

        password = request.form.get("password", "")
        confirm_password = request.form.get(
            "confirm_password", ""
        )

        if not username or not email or not password:
            return render_template(
                "signup.html",
                error="Please fill in all required fields."
            )

        if password != confirm_password:
            return render_template(
                "signup.html",
                error="Passwords do not match."
            )

        conn = get_db_connection()

        try:
            existing_user = conn.execute(
                """
                SELECT id FROM users
                WHERE username = ? OR email = ?
                """,
                (username, email)
            ).fetchone()

            if existing_user:
                return render_template(
                    "signup.html",
                    error="Username or email already exists."
                )

            hashed_password = generate_password_hash(
                password
            )

            conn.execute(
                """
                INSERT INTO users
                (username, email, password)
                VALUES (?, ?, ?)
                """,
                (username, email, hashed_password)
            )

            conn.commit()

            return redirect(url_for("login"))

        except sqlite3.IntegrityError:
            return render_template(
                "signup.html",
                error="Username or email already exists."
            )

        finally:
            conn.close()

    return render_template("signup.html")


# --------------------------------------------------
# 5. USER LOGIN
# --------------------------------------------------

@app.route("/", methods=["GET", "POST"])
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get(
            "username", ""
        ).strip()

        password = request.form.get("password", "")

        conn = get_db_connection()

        try:
            user = conn.execute(
                """
                SELECT * FROM users
                WHERE username = ?
                """,
                (username,)
            ).fetchone()
        finally:
            conn.close()

        if user and check_password_hash(
            user["password"], password
        ):
            session.clear()
            session["user_id"] = user["id"]
            session["username"] = user["username"]

            return redirect(url_for("home"))

        return render_template(
            "login.html",
            error="Invalid username or password."
        )

    return render_template("login.html")


# --------------------------------------------------
# 6. LOGOUT
# --------------------------------------------------

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# --------------------------------------------------
# 7. DASHBOARD
# --------------------------------------------------

@app.route("/home")
def home():
    if "user_id" not in session:
        return redirect(url_for("login"))

    return render_template(
        "home.html",
        username=session["username"]
    )


# --------------------------------------------------
# 8. PDF TEXT EXTRACTION
# --------------------------------------------------

def extract_text(pdf_file):
    reader = PdfReader(pdf_file)

    if reader.is_encrypted:
        raise ValueError(
            "Password-protected PDFs are not supported."
        )

    extracted_pages = []

    for page in reader.pages:
        page_text = page.extract_text() or ""
        extracted_pages.append(page_text)

    return "\n".join(extracted_pages)


# --------------------------------------------------
# 9. TEXT PREPROCESSING
# --------------------------------------------------

def preprocess_text(text):
    text = text.replace("\x00", " ")
    text = text.replace("\u00a0", " ")

    text = re.sub(
        r"https?://\S+|www\.\S+",
        " ",
        text,
        flags=re.IGNORECASE
    )

    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"[^a-zA-Z0-9\s.,:%()/\-]", " ", text)

    try:
        stop_words = set(stopwords.words("english"))
    except LookupError:
        stop_words = set()

    words = text.lower().split()

    cleaned_words = [
        word for word in words
        if word not in stop_words
    ]

    return " ".join(cleaned_words)


# --------------------------------------------------
# 10. CATEGORY KEYWORDS
# --------------------------------------------------

categories = {
    "Installation": [
        "install", "installation", "setup",
        "connect", "assemble", "configure",
        "mount", "unpacking", "inlet hose"
    ],

    "Safety": [
        "warning", "danger", "caution",
        "safety", "hazard", "electric shock",
        "fire", "injury", "precaution",
        "grounded", "risk of injury"
    ],

    "Maintenance": [
        "maintenance", "clean", "cleaning",
        "replace", "service", "repair",
        "inspect", "regular cleaning",
        "periodic maintenance"
    ],

    "Troubleshooting": [
        "troubleshooting", "problem", "error",
        "fault", "reset", "not working",
        "failure", "does not work",
        "if the appliance", "solution"
    ],

    "Specifications": [
        "voltage", "power", "capacity",
        "frequency", "watt", "weight",
        "dimensions", "temperature",
        "electrical rating", "rated power"
    ]
}


# --------------------------------------------------
# 11. CLEAN EXTRACTED MANUAL TEXT
# --------------------------------------------------

def clean_manual_text(text):
    text = text.replace("\x00", " ")
    text = text.replace("\u00a0", " ")

    cleaned_lines = []

    for line in text.splitlines():
        line = re.sub(r"\s+", " ", line).strip()

        if not line:
            continue

        # Remove website addresses
        if re.fullmatch(
            r"(https?://\S+|www\.\S+)",
            line,
            flags=re.IGNORECASE
        ):
            continue

        # Remove page-number-only lines
        if re.fullmatch(
            r"[-–—\s]*\d{1,4}[-–—\s]*",
            line
        ):
            continue

        # Remove common copyright and contents lines
        if re.search(
            r"table of contents|all rights reserved|"
            r"copyright\s*©?",
            line,
            flags=re.IGNORECASE
        ):
            continue

        # Remove lines dominated by contents-page dots
        if re.search(r"\.{3,}", line):
            continue

        cleaned_lines.append(line)

    return "\n".join(cleaned_lines)


# --------------------------------------------------
# 12. CHECK SENTENCE QUALITY
# --------------------------------------------------

def sentence_is_useful(sentence):
    sentence = sentence.strip()
    words = sentence.split()

    if len(words) < 7 or len(words) > 65:
        return False

    letter_count = sum(
        character.isalpha()
        for character in sentence
    )

    if letter_count < 20:
        return False

    if letter_count / max(len(sentence), 1) < 0.55:
        return False

    # Ignore incomplete fragments
    if not re.search(r"[.!?]$", sentence):
        return False

    return True


# --------------------------------------------------
# 13. CATEGORY-WISE SUMMARIZATION
# --------------------------------------------------

def get_category_summary(
    text, keywords, max_sentences=2
):
    try:
        sentences = sent_tokenize(text)
    except LookupError:
        sentences = re.split(
            r"(?<=[.!?])\s+",
            text
        )

    ranked_sentences = []
    seen_sentences = set()

    for index, sentence in enumerate(sentences):
        sentence = re.sub(
            r"\s+", " ", sentence
        ).strip()

        if not sentence_is_useful(sentence):
            continue

        normalized = sentence.lower()

        # Avoid duplicate sentences
        if normalized in seen_sentences:
            continue

        seen_sentences.add(normalized)

        score = 0

        for keyword in keywords:
            pattern = (
                r"\b" + re.escape(keyword.lower()) + r"\b"
            )

            if re.search(pattern, normalized):
                score += 2 if " " in keyword else 1

        if score > 0:
            ranked_sentences.append(
                (score, index, sentence)
            )

    # Select the most relevant sentences
    ranked_sentences.sort(
        key=lambda item: (-item[0], item[1])
    )

    selected = ranked_sentences[:max_sentences]

    # Preserve original document order
    selected.sort(key=lambda item: item[1])

    if not selected:
        return (
            "No clear information found for this category."
        )

    return " ".join(
        item[2] for item in selected
    )


def summarize_categories(text):
    cleaned_text = clean_manual_text(text)
    results = {}

    for category, keywords in categories.items():
        results[category] = get_category_summary(
            cleaned_text,
            keywords,
            max_sentences=2
        )

    return results


# --------------------------------------------------
# 14. ANALYZE UPLOADED PDF
# --------------------------------------------------

@app.route("/analyze", methods=["POST"])
def analyze():
    if "user_id" not in session:
        return redirect(url_for("login"))

    start_time = time.time()

    pdf_file = request.files.get("pdf")

    if not pdf_file or not pdf_file.filename:
        return render_template(
            "home.html",
            username=session["username"],
            error="Please select a PDF file."
        )

    if not pdf_file.filename.lower().endswith(".pdf"):
        return render_template(
            "home.html",
            username=session["username"],
            error="Invalid file. Please upload a PDF."
        )

    try:
        # Step 1: Extract text
        text = extract_text(pdf_file.stream)

        if not text.strip():
            return render_template(
                "home.html",
                username=session["username"],
                error=(
                    "No readable text found. "
                    "This PDF may be scanned or empty."
                )
            )

        # Step 2: Preprocess the text
        cleaned_text = preprocess_text(text)

        if not cleaned_text.strip():
            return render_template(
                "home.html",
                username=session["username"],
                error="No useful text found in the document."
            )

        # Step 3: Generate readable category summaries
        category_summaries = summarize_categories(text)

        # Step 4: Measure processing time
        process_time = round(
            time.time() - start_time, 2
        )

        # Step 5: Display the results
        return render_template(
            "home.html",
            username=session["username"],
            category_summaries=category_summaries,
            process_time=process_time
        )

    except Exception:
        app.logger.exception(
            "Error while processing uploaded PDF"
        )

        return render_template(
            "home.html",
            username=session["username"],
            error=(
                "Unable to process this PDF. "
                "Please check the file and try again."
            )
        )


# --------------------------------------------------
# 15. RUN APPLICATION
# --------------------------------------------------

if __name__ == "__main__":
    create_database()
    app.run(debug=True)
