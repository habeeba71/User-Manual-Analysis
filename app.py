from flask import Flask, render_template, request, redirect, url_for, session
import sqlite3
from werkzeug.security import generate_password_hash, check_password_hash
import re
import time
import nltk
from PyPDF2 import PdfReader
from nltk.corpus import stopwords
from nltk.tokenize import sent_tokenize


app = Flask(__name__)

# Secret key for login sessions
app.secret_key = "electronics_manual_secret_key"


# ---------------- DATABASE ----------------





# Connect to SQLite database
def get_db_connection():
    conn = sqlite3.connect("users.db")
    conn.row_factory = sqlite3.Row
    return conn


# Create users table
def create_database():
    conn = get_db_connection()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            email TEXT NOT NULL UNIQUE,
            password TEXT NOT NULL
        )
    """)

    conn.commit()
    conn.close()



#--------------Extract text from the PDF--------------------


def extract_text(pdf_file):
    reader = PdfReader(pdf_file)
    text = ""

    for page in reader.pages:
        text += page.extract_text() or ""

    return text

    
def preprocess_text(text):
    text = text.lower()
    text = re.sub(r"[^a-z\s]", " ", text)

    words = text.split()
    stop_words = set(stopwords.words("english"))

    words = [word for word in words if word not in stop_words]

    return " ".join(words)

categories = {
    "Installation": [
        "install", "installation", "setup", "connect",
        "assemble", "configure", "mount"
    ],
    "Safety": [
        "warning", "danger", "caution", "safety",
        "hazard", "electric shock", "fire"
    ],
    "Maintenance": [
        "maintenance", "clean", "replace", "service",
        "repair", "inspect"
    ],
    "Troubleshooting": [
        "problem", "error", "fault", "reset",
        "troubleshooting", "not working", "failure"
    ],
    "Specifications": [
        "voltage", "power", "capacity", "frequency",
        "watt", "weight", "dimensions", "temperature"
    ]
}


def classify_text(text):
    results = {category: [] for category in categories}

    for sentence in sent_tokenize(text):
        sentence_lower = sentence.lower()

        scores = {
            category: sum(
                1 for keyword in keywords
                if re.search(
                    r"\b" + re.escape(keyword) + r"\b",
                    sentence_lower
                )
            )
            for category, keywords in categories.items()
        }

        best_category = max(scores, key=scores.get)

        if scores[best_category] > 0:
            results[best_category].append(sentence.strip())

    return results

def summarize(sentences, count=2):
    if not sentences:
        return "No relevant information found."

    return " ".join(sentences[:count])


# ---------------- LOGIN PAGE ----------------

@app.route("/")
def login():
    return render_template("login.html")


# ---------------- SIGN UP ----------------


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        username = request.form["username"]
        email = request.form["email"]
        password = request.form["password"]
        confirm_password = request.form["confirm_password"]

        if password != confirm_password:
            return render_template(
                "signup.html",
                error="Passwords do not match!"
            )

        conn = get_db_connection()

        try:
            existing_user = conn.execute(
                "SELECT * FROM users WHERE username = ? OR email = ?",
                (username, email)
            ).fetchone()

            if existing_user:
                return render_template(
                    "signup.html",
                    error="Username or email already exists!"
                )

            hashed_password = generate_password_hash(password)

            conn.execute(
                """INSERT INTO users (username, email, password)
                   VALUES (?, ?, ?)""",
                (username, email, hashed_password)
            )

            conn.commit()
            return redirect(url_for("login"))

        except sqlite3.IntegrityError:
            return render_template(
                "signup.html",
                error="Username or email already exists!"
            )

        finally:
            conn.close()

    return render_template("signup.html")


# ---------------- LOGIN PROCESS ----------------


@app.route("/login", methods=["POST"])
def login_user():
    username = request.form["username"]
    password = request.form["password"]

    conn = get_db_connection()
    try:
        user = conn.execute(
            "SELECT * FROM users WHERE username = ?",
            (username,)
        ).fetchone()
    finally:
        conn.close()

    if user and check_password_hash(user["password"], password):
        session["user_id"] = user["id"]
        session["username"] = user["username"]
        return redirect(url_for("home"))

    return render_template("login.html", error="Invalid username or password!")





# ---------------- HOME PAGE ----------------

@app.route("/home")
def home():

    if "user_id" not in session:
        return redirect(url_for("login"))

    return render_template(
        "home.html",
        username=session["username"]
    )








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
            error="Please upload a PDF file."
        )

    try:
        text = extract_text(pdf_file.stream)

        if not text.strip():
            raise ValueError(
                "No readable text found. The PDF may be scanned."
            )

        cleaned_text = preprocess_text(text)
        classified = classify_text(text)

        summaries = {
            category: summarize(sentences)
            for category, sentences in classified.items()
        }

        process_time = round(time.time() - start_time, 2)

        return render_template(
            "home.html",
            username=session["username"],
            summaries=summaries,
            process_time=process_time
        )

    except Exception as e:
        return render_template(
            "home.html",
            username=session["username"],
            error=str(e)
        )


# ---------------- LOGOUT ----------------

@app.route("/logout")
def logout():

    session.clear()

    return redirect(url_for("login"))


# ---------------- RUN APPLICATION ----------------

if __name__ == "__main__":
    create_database()
    app.run(debug=True)