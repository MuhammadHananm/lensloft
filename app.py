import os
import io
from datetime import datetime

from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv

from models import db, User, Photo, Like, Comment, Save

# ---------- AI / IMAGE ----------
from PIL import Image, ImageStat
from textblob import TextBlob

# ---------- AZURE BLOB ----------
from azure.storage.blob import BlobServiceClient

# ---------- NLTK SAFE ----------
try:
    import nltk
    nltk.data.find("corpora/brown")
except LookupError:
    import nltk
    nltk.download("brown", quiet=True)
    nltk.download("punkt", quiet=True)

# ---------- ENV ----------
load_dotenv()

# ---------- APP ----------
app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "super-secret-key")

# ---------- DATABASE ----------
def parse_azure_pg(conn):
    try:
        parts = dict(p.split("=", 1) for p in conn.split(";") if "=" in p)
        return (
            f"postgresql://{parts['User Id']}:{parts['Password']}"
            f"@{parts['Server']}:{parts.get('Port','5432')}/{parts['Database']}"
            "?sslmode=require"
        )
    except Exception:
        return conn


db_uri = os.getenv("SQLALCHEMY_DATABASE_URI")
if not db_uri and os.getenv("AZURE_POSTGRESQL_CONNECTIONSTRING"):
    db_uri = parse_azure_pg(os.getenv("AZURE_POSTGRESQL_CONNECTIONSTRING"))

if not db_uri:
    os.makedirs(app.instance_path, exist_ok=True)
    db_uri = f"sqlite:///{os.path.join(app.instance_path,'app.db')}"
    print("ℹ SQLite fallback enabled")

app.config["SQLALCHEMY_DATABASE_URI"] = db_uri
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db.init_app(app)

with app.app_context():
    db.create_all()

# ---------- LOGIN ----------
login_manager = LoginManager()
login_manager.login_view = "login"
login_manager.init_app(app)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# ---------- STORAGE ----------
LOCAL_UPLOADS = True
UPLOAD_FOLDER = os.path.join(app.root_path, "static", "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

AZURE_CONN = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
AZURE_CONTAINER = os.getenv("AZURE_CONTAINER_NAME")
blob_service = None
if AZURE_CONN:
    blob_service = BlobServiceClient.from_connection_string(AZURE_CONN)

# ---------- HELPERS ----------
def analyze_image(img):
    tags = []
    if img.mode != "RGB":
        img = img.convert("RGB")

    w, h = img.size
    tags.append("HD" if w * h > 1_000_000 else "SD")

    brightness = ImageStat.Stat(img.convert("L")).mean[0]
    if brightness > 150:
        tags.append("Bright ☀️")
    elif brightness < 80:
        tags.append("Dark 🌙")
    else:
        tags.append("Neutral ☁️")

    r, g, b = img.resize((1, 1)).getpixel((0, 0))
    if r > g and r > b:
        tags.append("Warm 🔴")
    elif b > r and b > g:
        tags.append("Cool 🔵")
    else:
        tags.append("Balanced 🎨")

    return " | ".join(tags)

# ---------- ROUTES ----------
@app.route("/")
def home():
    if current_user.is_authenticated:
        return redirect(url_for("feed"))
    return redirect(url_for("login"))

@app.route("/feed")
@login_required
def feed():
    q = request.args.get("q")
    if q:
        s = f"%{q}%"
        photos = Photo.query.join(User).filter(
            (Photo.title.ilike(s)) |
            (Photo.caption.ilike(s)) |
            (User.username.ilike(s))
        ).all()
    else:
        photos = Photo.query.order_by(Photo.uploaded_at.desc()).all()
    return render_template("feed.html", photos=photos)

@app.route("/u/<username>")
@login_required
def profile(username):
    user = User.query.filter_by(username=username).first_or_404()
    photos = Photo.query.filter_by(user_id=user.id).all()
    saved = Photo.query.join(Save).filter(Save.user_id == user.id).all()
    liked = Photo.query.join(Like).filter(Like.user_id == user.id).all()
    return render_template(
        "profile.html",
        user=user,
        photos=photos,
        saved_photos=saved,
        liked_photos=liked
    )

@app.route("/upload", methods=["GET", "POST"])
@login_required
def creator_dashboard():
    if current_user.role != "creator":
        flash("Only creators allowed", "danger")
        return redirect(url_for("feed"))

    if request.method == "POST":
        file = request.files.get("photo")
        title = request.form.get("title")
        caption = request.form.get("caption")
        location = request.form.get("location")
        people = request.form.get("people")

        if not file or not title:
            flash("Missing fields", "danger")
            return redirect(request.url)

        img = Image.open(file)
        tags = analyze_image(img)
        img.thumbnail((1080, 1080))

        filename = secure_filename(file.filename)
        name = f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{filename}"

        if blob_service and AZURE_CONTAINER:
            mem = io.BytesIO()
            img.save(mem, format="JPEG", quality=85)
            mem.seek(0)
            blob = blob_service.get_blob_client(AZURE_CONTAINER, name)
            blob.upload_blob(mem, overwrite=True)
            file_url = blob.url
        else:
            path = os.path.join(UPLOAD_FOLDER, name)
            img.save(path, format="JPEG", quality=85)
            file_url = url_for("static", filename=f"uploads/{name}")

        photo = Photo(
            filename=file_url,
            title=title,
            caption=caption,
            location=location,
            people_present=people,
            auto_tags=tags,
            user_id=current_user.id
        )
        db.session.add(photo)
        db.session.commit()

        flash("Uploaded successfully", "success")
        return redirect(url_for("profile", username=current_user.username))

    return render_template("dashboard.html")

@app.route("/like/<int:photo_id>", methods=["POST"])
@login_required
def like(photo_id):
    obj = Like.query.filter_by(user_id=current_user.id, photo_id=photo_id).first()
    if obj:
        db.session.delete(obj)
        liked = False
    else:
        db.session.add(Like(user_id=current_user.id, photo_id=photo_id))
        liked = True
    db.session.commit()
    return jsonify(liked=liked)

@app.route("/save/<int:photo_id>", methods=["POST"])
@login_required
def save(photo_id):
    obj = Save.query.filter_by(user_id=current_user.id, photo_id=photo_id).first()
    if obj:
        db.session.delete(obj)
        saved = False
    else:
        db.session.add(Save(user_id=current_user.id, photo_id=photo_id))
        saved = True
    db.session.commit()
    return jsonify(saved=saved)

@app.route("/comment/<int:photo_id>", methods=["POST"])
@login_required
def comment(photo_id):
    text = request.form.get("text")
    if not text:
        return jsonify(success=False)

    polarity = TextBlob(text).sentiment.polarity
    if polarity < -0.3:
        return jsonify(success=False, message="Negative blocked")

    db.session.add(Comment(text=text, user_id=current_user.id, photo_id=photo_id))
    db.session.commit()
    return jsonify(success=True)

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        user = User(
            username=request.form["username"],
            password=generate_password_hash(request.form["password"]),
            role=request.form.get("role", "consumer")
        )
        db.session.add(user)
        db.session.commit()
        return redirect(url_for("login"))
    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = User.query.filter_by(username=request.form["username"]).first()
        if user and check_password_hash(user.password, request.form["password"]):
            login_user(user)
            return redirect(url_for("feed"))
        flash("Invalid credentials", "danger")
    return render_template("login.html")

@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))

# ---------- LOCAL ----------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
