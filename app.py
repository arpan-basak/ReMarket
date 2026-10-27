"""Small, server-rendered ReMarket demonstration site."""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import quote

import httpx
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader, select_autoescape
from starlette.middleware.sessions import SessionMiddleware


ROOT = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("REMARKET_DB", ROOT / "remarket.db"))
UPLOADS = ROOT / "static" / "uploads"
CRAFTPROOF_REMOTE_BASE = "https://craftproof-backend.onrender.com"
CRAFTPROOF_LOCAL_BASE = "http://127.0.0.1:8002"
SALE_API_KEY = os.environ.get("REMARKET_SALE_API_KEY", "")
AUTH_SESSION_VERSION = 1  # Older cookies were created before explicit sign-in was required.
CATEGORIES = [
    "Paintings", "Prints", "Ceramics", "Sculpture",
    "Photography", "Textiles", "Other",
]
CONDITIONS = ["Like New", "Good", "Fair"]
SAMPLE_ITEMS = [
    ("Vintage Raleigh Commuter Bike", "Sunlit Hills Original Acrylic Painting",
     "Original acrylic landscape on canvas with warm hills and a soft peach sky.",
     "Paintings", "Good", 16500, "North Campus Quad", "art-sunlit-hills.png"),
    ("Fujifilm X-T30 Mirrorless Camera", "Blue Forms Framed Linocut Print",
     "Hand-pulled abstract linocut in layered blue ink, presented in a natural wood frame.",
     "Prints", "Like New", 42000, "Engineering Hall", "art-blue-forms.png"),
    ("Custom Mechanical Keyboard", "Hand-Thrown Stoneware Vase",
     "Sculptural handmade vase with an ivory speckled glaze and a gently asymmetric shape.",
     "Ceramics", "Like New", 9500, "Dorm Quad", "art-stoneware-vase.png"),
    ("Sony WH-1000XM4 Headphones", "Woven Sunset Wall Hanging",
     "Handwoven textile artwork in terracotta, rust, and cream with a natural fringe.",
     "Textiles", "Good", 14000, "Central Library", "art-woven-sunset.png"),
]
SAMPLE_GALLERIES = {
    "Sunlit Hills Original Acrylic Painting": ["art-sunlit-hills.png", "art-sunlit-hills-detail.png"],
    "Blue Forms Framed Linocut Print": ["art-blue-forms.png", "art-blue-forms-detail.png"],
    "Hand-Thrown Stoneware Vase": ["art-stoneware-vase.png", "art-stoneware-vase-detail.png"],
    "Woven Sunset Wall Hanging": ["art-woven-sunset.png", "art-woven-sunset-detail.png"],
    # Preserve gallery photos for any legacy sample that was already sold.
    "Vintage Raleigh Commuter Bike": ["asset-02.jpg", "asset-06.jpg"],
    "Fujifilm X-T30 Mirrorless Camera": ["asset-03.jpg", "asset-08.jpg", "asset-09.jpg", "asset-10.jpg", "asset-11.jpg"],
    "Custom Mechanical Keyboard": ["asset-04.jpg", "asset-16.jpg", "asset-17.jpg"],
    "Sony WH-1000XM4 Headphones": ["asset-05.jpg", "asset-07.jpg"],
}


def get_secret() -> str:
    configured = os.environ.get("REMARKET_SESSION_SECRET")
    if configured:
        return configured
    secret_file = ROOT / ".secret_key"
    if secret_file.exists():
        return secret_file.read_text(encoding="utf-8").strip()
    value = secrets.token_urlsafe(48)
    secret_file.write_text(value, encoding="utf-8")
    return value


app = FastAPI(title="ReMarket", version="0.1.0")
app.add_middleware(
    SessionMiddleware,
    secret_key=get_secret(),
    max_age=None,  # Keep sign-in only for the current browser session.
    same_site="lax",
    https_only=os.environ.get("REMARKET_HTTPS_ONLY") == "1",
)
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
templates = Environment(
    loader=FileSystemLoader(ROOT / "templates"),
    autoescape=select_autoescape(["html", "xml"]),
)
templates.filters["money"] = lambda cents: f"${cents / 100:,.0f}" if cents % 100 == 0 else f"${cents / 100:,.2f}"
templates.filters["date"] = lambda value: value[:10] if value else ""


@contextmanager
def db():
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def password_hash(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 260_000)
    return f"{salt.hex()}:{digest.hex()}"


def check_password(password: str, stored: str) -> bool:
    try:
        salt, digest = stored.split(":", 1)
        candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 260_000)
        return hmac.compare_digest(candidate, bytes.fromhex(digest))
    except (ValueError, TypeError):
        return False


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    UPLOADS.mkdir(parents=True, exist_ok=True)
    with db() as con:
        con.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY,
                seller_id INTEGER NOT NULL REFERENCES users(id),
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                category TEXT NOT NULL,
                condition TEXT NOT NULL,
                price_cents INTEGER NOT NULL CHECK(price_cents > 0),
                location TEXT NOT NULL,
                image_path TEXT,
                craftproof_code TEXT,
                status TEXT NOT NULL DEFAULT 'active',
                is_sample INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY,
                product_id INTEGER NOT NULL UNIQUE REFERENCES products(id),
                seller_id INTEGER NOT NULL REFERENCES users(id),
                buyer_id INTEGER NOT NULL REFERENCES users(id),
                price_cents INTEGER NOT NULL,
                certificate_code TEXT,
                buyer_name TEXT,
                status TEXT NOT NULL DEFAULT 'completed',
                completed_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_products_status ON products(status);
            CREATE INDEX IF NOT EXISTS idx_orders_buyer ON orders(buyer_id);
        """)
        # Keep existing local databases usable. Legacy ID columns, if present,
        # are ignored by the certificate-and-name integration.
        order_columns = {row["name"] for row in con.execute("PRAGMA table_info(orders)")}
        for column in ("certificate_code", "buyer_name"):
            if column not in order_columns:
                con.execute(f"ALTER TABLE orders ADD COLUMN {column} TEXT")
        con.execute(
            """UPDATE orders SET buyer_name=(SELECT name FROM users WHERE users.id=orders.buyer_id)
               WHERE buyer_name IS NULL"""
        )
        if con.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
            con.execute(
                "INSERT INTO users(name,email,password_hash,created_at) VALUES(?,?,?,?)",
                ("Maya Lin", "demo@remarket.local", password_hash("demo12345"), now()),
            )
            seller_id = con.execute("SELECT id FROM users WHERE email=?", ("demo@remarket.local",)).fetchone()[0]
            con.executemany(
                """INSERT INTO products(seller_id,title,description,category,condition,price_cents,location,image_path,is_sample,created_at)
                   VALUES(?,?,?,?,?,?,?,?,1,?)""",
                [(seller_id, *item[1:], now()) for item in SAMPLE_ITEMS],
            )
        # Refresh only untouched, active demo products. Sold listings and real
        # seller listings keep their titles for certificates and past orders.
        for old_title, title, description, category, _condition, _price, _location, image in SAMPLE_ITEMS:
            con.execute(
                """UPDATE products SET title=?, description=?, category=?, image_path=?
                   WHERE is_sample=1 AND title=? AND status='active'
                     AND craftproof_code IS NULL
                     AND NOT EXISTS (SELECT 1 FROM orders WHERE orders.product_id=products.id)""",
                (title, description, category, image, old_title),
            )
        if not con.execute("SELECT 1 FROM users WHERE email=?", ("buyer@remarket.local",)).fetchone():
            con.execute(
                "INSERT INTO users(name,email,password_hash,created_at) VALUES(?,?,?,?)",
                ("Sample Buyer", "buyer@remarket.local", password_hash("buyer12345"), now()),
            )


init_db()


def user_for(request: Request):
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    if request.session.get("auth_version") != AUTH_SESSION_VERSION:
        request.session.clear()
        return None
    with db() as con:
        return con.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()


def csrf_for(request: Request) -> str:
    if "csrf" not in request.session:
        request.session["csrf"] = secrets.token_urlsafe(24)
    return request.session["csrf"]


def require_csrf(request: Request, value: str) -> None:
    expected = request.session.get("csrf", "")
    if not expected or not hmac.compare_digest(expected, value):
        raise HTTPException(status_code=403, detail="Invalid form token. Refresh the page and try again.")


def require_user(request: Request):
    user = user_for(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Sign in to continue")
    return user


def render(request: Request, name: str, **context) -> HTMLResponse:
    current_user = user_for(request)
    message = request.session.pop("message", None)
    html = templates.get_template(name).render(
        request=request,
        user=current_user,
        csrf=csrf_for(request),
        message=message,
        categories=CATEGORIES,
        conditions=CONDITIONS,
        **context,
    )
    return HTMLResponse(html)


def redirect(path: str, message: str | None = None, request: Request | None = None):
    if message and request:
        request.session["message"] = message
    return RedirectResponse(path, status_code=303)


def safe_next(path: str) -> str:
    return path if path.startswith("/") and not path.startswith("//") and "\\" not in path else "/account"


def product_row(con: sqlite3.Connection, product_id: int):
    return con.execute(
        """SELECT p.*, u.name AS seller_name
           FROM products p JOIN users u ON u.id=p.seller_id WHERE p.id=?""",
        (product_id,),
    ).fetchone()


def craftproof_bases(request: Request) -> list[str]:
    configured = os.environ.get("CRAFTPROOF_BASE_URL", "").rstrip("/")
    if configured:
        return [configured]
    if request.url.hostname in ("127.0.0.1", "localhost"):
        return [CRAFTPROOF_LOCAL_BASE, CRAFTPROOF_REMOTE_BASE]
    return [CRAFTPROOF_REMOTE_BASE]


def certificate_data(request: Request, code: str):
    bases = craftproof_bases(request)
    if not re.fullmatch(r"[A-Za-z0-9-]{4,64}", code):
        return None, "Certificate code has an invalid format.", bases[0]
    missing_count = 0
    for base in bases:
        try:
            response = httpx.get(
                f"{base}/api/verify/{quote(code)}",
                timeout=3 if base == CRAFTPROOF_LOCAL_BASE else 20,
            )
            if response.status_code == 404:
                missing_count += 1
                continue
            response.raise_for_status()
            return response.json(), None, base
        except (httpx.HTTPError, ValueError):
            continue
    error = ("CraftProof has no record for this code." if missing_count == len(bases)
             else "CraftProof is unavailable right now. Try again later.")
    return None, error, bases[-1]


@app.get("/", response_class=HTMLResponse)
def home(request: Request, q: str = "", category: str = "", condition: str = "", sort: str = "newest"):
    clauses = ["p.status='active'"]
    args: list[str] = []
    if q.strip():
        clauses.append("(p.title LIKE ? OR p.description LIKE ?)")
        args += [f"%{q.strip()}%", f"%{q.strip()}%"]
    if category in CATEGORIES:
        clauses.append("p.category=?")
        args.append(category)
    if condition in CONDITIONS:
        clauses.append("p.condition=?")
        args.append(condition)
    order = "p.created_at DESC, p.id DESC"
    if sort == "price-low":
        order = "p.price_cents ASC, p.id DESC"
    elif sort == "price-high":
        order = "p.price_cents DESC, p.id DESC"
    with db() as con:
        products = con.execute(
            f"""SELECT p.*, u.name AS seller_name FROM products p JOIN users u ON u.id=p.seller_id
                WHERE {' AND '.join(clauses)} ORDER BY {order}""", args
        ).fetchall()
    return render(request, "home.html", products=products, q=q, category=category, condition=condition, sort=sort)


@app.get("/api", response_class=HTMLResponse)
def api_guide(request: Request):
    return render(request, "api.html", api_base=str(request.base_url).rstrip("/"),
                  api_key_configured=bool(SALE_API_KEY))


@app.get("/products/{product_id}", response_class=HTMLResponse)
def product_detail(request: Request, product_id: int):
    with db() as con:
        product = product_row(con, product_id)
        if product is None:
            raise HTTPException(404, "Listing not found")
        similar = con.execute(
            "SELECT * FROM products WHERE status='active' AND category=? AND id<>? ORDER BY id DESC LIMIT 4",
            (product["category"], product_id),
        ).fetchall()
    certificate = None
    certificate_error = None
    certificate_base = None
    if product["craftproof_code"]:
        certificate, certificate_error, certificate_base = certificate_data(request, product["craftproof_code"])
    registered_title = certificate.get("piece", {}).get("title") if isinstance(certificate, dict) and isinstance(certificate.get("piece"), dict) else None
    certificate_mismatch = bool(
        isinstance(registered_title, str)
        and " ".join(registered_title.split()).casefold() != " ".join(product["title"].split()).casefold()
    )
    gallery = SAMPLE_GALLERIES.get(product["title"], []) if product["is_sample"] else []
    return render(request, "product.html", product=product, similar=similar, gallery=gallery,
                  certificate=certificate, certificate_error=certificate_error,
                  certificate_base=certificate_base, certificate_mismatch=certificate_mismatch)


@app.get("/sell", response_class=HTMLResponse)
def sell_page(request: Request):
    if not user_for(request):
        return redirect("/login?next=/sell")
    return render(request, "sell.html", error=None, values={})


def save_image(upload: UploadFile | None) -> str | None:
    if upload is None or not upload.filename:
        return None
    data = upload.file.read(5_000_001)
    if len(data) > 5_000_000:
        raise ValueError("Photo must be under 5 MB.")
    formats = [(b"\xff\xd8\xff", ".jpg"), (b"\x89PNG\r\n\x1a\n", ".png"), (b"RIFF", ".webp")]
    extension = next((ext for magic, ext in formats if data.startswith(magic)), None)
    if extension == ".webp" and data[8:12] != b"WEBP":
        extension = None
    if extension is None:
        raise ValueError("Use a JPG, PNG, or WebP photo.")
    filename = f"{uuid.uuid4().hex}{extension}"
    (UPLOADS / filename).write_bytes(data)
    return f"/static/uploads/{filename}"


@app.post("/sell", response_class=HTMLResponse)
def create_listing(
    request: Request,
    csrf: str = Form(...),
    title: str = Form(...),
    description: str = Form(...),
    category: str = Form(...),
    condition: str = Form(...),
    price: str = Form(...),
    location: str = Form(...),
    craftproof_code: str = Form(""),
    photo: UploadFile | None = File(None),
):
    require_csrf(request, csrf)
    user = require_user(request)
    values = dict(title=title, description=description, category=category, condition=condition,
                  price=price, location=location, craftproof_code=craftproof_code)
    try:
        price_decimal = Decimal(price)
        if not price_decimal.is_finite() or price_decimal <= 0 or price_decimal > 1_000_000:
            raise ValueError("Enter a price between $0.01 and $1,000,000.")
        cents = int(price_decimal * 100)
        if Decimal(cents) / 100 != price_decimal:
            raise ValueError("Use at most two decimal places for the price.")
        if not 4 <= len(title.strip()) <= 100 or not 10 <= len(description.strip()) <= 2000:
            raise ValueError("Add a title (4–100 characters) and description (10–2000 characters).")
        if category not in CATEGORIES or condition not in CONDITIONS:
            raise ValueError("Choose a valid category and condition.")
        if not 2 <= len(location.strip()) <= 100:
            raise ValueError("Add a pickup location (2–100 characters).")
        code = craftproof_code.strip().upper()
        if code and not re.fullmatch(r"[A-Z0-9-]{4,64}", code):
            raise ValueError("CraftProof code must contain 4–64 letters, digits, or hyphens.")
        image = save_image(photo)
    except (InvalidOperation, ValueError) as exc:
        return render(request, "sell.html", error=str(exc), values=values)
    with db() as con:
        cursor = con.execute(
            """INSERT INTO products(seller_id,title,description,category,condition,price_cents,location,image_path,craftproof_code,created_at)
               VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (user["id"], title.strip(), description.strip(), category, condition, cents,
             location.strip(), image, code or None, now()),
        )
        product_id = cursor.lastrowid
    return redirect(f"/products/{product_id}", "Your listing is live.", request)


@app.post("/products/{product_id}/buy")
def buy(request: Request, product_id: int, csrf: str = Form(...)):
    require_csrf(request, csrf)
    user = user_for(request)
    if not user:
        return redirect(f"/login?next=/products/{product_id}")
    with db() as con:
        product = product_row(con, product_id)
        if product is None:
            raise HTTPException(404, "Listing not found")
        if product["seller_id"] == user["id"]:
            return redirect(f"/products/{product_id}", "You cannot buy your own listing.", request)
        if product["status"] != "active":
            return redirect(f"/products/{product_id}", "This item is no longer available.", request)
        updated = con.execute("UPDATE products SET status='sold' WHERE id=? AND status='active'", (product_id,))
        if updated.rowcount != 1:
            raise HTTPException(409, "Item has already sold")
        cursor = con.execute(
            """INSERT INTO orders(product_id,seller_id,buyer_id,price_cents,
                   certificate_code,buyer_name,completed_at)
               VALUES(?,?,?,?,?,?,?)""",
            (product_id, product["seller_id"], user["id"], product["price_cents"],
             product["craftproof_code"], user["name"], now()),
        )
    return redirect(f"/orders/{cursor.lastrowid}")


@app.get("/orders/{order_id}", response_class=HTMLResponse)
def order_page(request: Request, order_id: int):
    user = user_for(request)
    if not user:
        return redirect("/login")
    with db() as con:
        order = con.execute(
            """SELECT o.*, p.title, p.image_path,
                      s.name AS seller_name
               FROM orders o JOIN products p ON p.id=o.product_id
               JOIN users s ON s.id=o.seller_id
               WHERE o.id=?""", (order_id,)
        ).fetchone()
    if order is None or user["id"] not in (order["seller_id"], order["buyer_id"]):
        raise HTTPException(404, "Order not found")
    return render(request, "order.html", order=order)


@app.get("/account", response_class=HTMLResponse)
def account(request: Request, tab: str = "listings"):
    user = user_for(request)
    if not user:
        return redirect("/login?next=/account")
    with db() as con:
        listings = con.execute("SELECT * FROM products WHERE seller_id=? ORDER BY id DESC", (user["id"],)).fetchall()
        purchases = con.execute(
            """SELECT o.*, p.title, p.image_path, s.name AS other_name FROM orders o
               JOIN products p ON p.id=o.product_id JOIN users s ON s.id=o.seller_id
               WHERE o.buyer_id=? ORDER BY o.id DESC""", (user["id"],)
        ).fetchall()
        sales = con.execute(
            """SELECT o.*, p.title, p.image_path, b.name AS other_name FROM orders o
               JOIN products p ON p.id=o.product_id JOIN users b ON b.id=o.buyer_id
               WHERE o.seller_id=? ORDER BY o.id DESC""", (user["id"],)
        ).fetchall()
    return render(request, "account.html", listings=listings, purchases=purchases, sales=sales,
                  tab=tab if tab in ("listings", "purchases", "sales") else "listings")


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, next: str = "/account"):
    if next == "/" and "next" in request.query_params:
        return redirect("/")
    request.session.clear()
    return render(request, "auth.html", mode="login", error=None, next=safe_next(next))


@app.post("/login", response_class=HTMLResponse)
def login(request: Request, csrf: str = Form(...), email: str = Form(...), password: str = Form(...), next: str = Form("/account")):
    require_csrf(request, csrf)
    with db() as con:
        user = con.execute("SELECT * FROM users WHERE email=?", (email.strip().lower(),)).fetchone()
    if user is None or not check_password(password, user["password_hash"]):
        return render(request, "auth.html", mode="login", error="Incorrect email or password.", next=next)
    request.session.clear()
    request.session["user_id"] = user["id"]
    request.session["auth_version"] = AUTH_SESSION_VERSION
    return redirect(safe_next(next))


@app.get("/register", response_class=HTMLResponse)
def register_page(request: Request, next: str = "/account"):
    request.session.clear()
    return render(request, "auth.html", mode="register", error=None, next=safe_next(next))


@app.post("/register", response_class=HTMLResponse)
def register(request: Request, csrf: str = Form(...), name: str = Form(...), email: str = Form(...), password: str = Form(...), next: str = Form("/account")):
    require_csrf(request, csrf)
    error = None
    if not 2 <= len(name.strip()) <= 80:
        error = "Name must be 2–80 characters."
    elif not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email.strip()) or len(email) > 254:
        error = "Enter a valid email address."
    elif len(password) < 8:
        error = "Password must be at least 8 characters."
    if error:
        return render(request, "auth.html", mode="register", error=error, next=safe_next(next))
    try:
        with db() as con:
            cursor = con.execute(
                "INSERT INTO users(name,email,password_hash,created_at) VALUES(?,?,?,?)",
                (name.strip(), email.strip().lower(), password_hash(password), now()),
            )
            user_id = cursor.lastrowid
    except sqlite3.IntegrityError:
        return render(request, "auth.html", mode="register", error="An account with this email already exists.", next=safe_next(next))
    request.session.clear()
    request.session["user_id"] = user_id
    request.session["auth_version"] = AUTH_SESSION_VERSION
    return redirect(safe_next(next), "Welcome to ReMarket.", request)


@app.post("/logout")
def logout(request: Request):
    request.session.clear()
    response = redirect("/login")
    response.delete_cookie("session", path="/")
    return response


def require_sale_api_key(request: Request) -> None:
    if not SALE_API_KEY:
        raise HTTPException(503, "Sale API key is not configured")
    supplied = request.headers.get("authorization", "")
    expected = f"Bearer {SALE_API_KEY}"
    if not hmac.compare_digest(supplied, expected):
        raise HTTPException(401, "Valid bearer token required", headers={"WWW-Authenticate": "Bearer"})


def sale_payload(order: sqlite3.Row) -> dict:
    return {
        "order_id": f"RM-{order['id']:06d}",
        "certificate_code": order["certificate_code"],
        "item_title": order["item_title"],
        "buyer_name": order["buyer_name"],
        "status": order["status"],
        "completed_at": order["completed_at"],
    }


@app.get("/api/v1/sales")
def sales_api(request: Request, after_id: int = 0, limit: int = 100):
    require_sale_api_key(request)
    if after_id < 0 or not 1 <= limit <= 100:
        raise HTTPException(400, "Use after_id >= 0 and limit from 1 to 100")
    with db() as con:
        orders = con.execute(
            """SELECT o.*, p.title AS item_title FROM orders o
               JOIN products p ON p.id=o.product_id
               WHERE o.id > ? AND o.status='completed'
               AND o.certificate_code IS NOT NULL ORDER BY o.id ASC LIMIT ?""",
            (after_id, limit),
        ).fetchall()
    return {
        "sales": [sale_payload(order) for order in orders],
        "next_after_id": orders[-1]["id"] if orders else after_id,
    }


@app.get("/api/v1/sales/{order_id}")
def sale_api(request: Request, order_id: str):
    require_sale_api_key(request)
    match = re.fullmatch(r"RM-(\d+)", order_id, re.IGNORECASE)
    if not match:
        raise HTTPException(404, "Sale not found")
    with db() as con:
        order = con.execute(
            """SELECT o.*, p.title AS item_title FROM orders o
               JOIN products p ON p.id=o.product_id WHERE o.id=?""",
            (int(match.group(1)),),
        ).fetchone()
    if order is None:
        raise HTTPException(404, "Sale not found")
    return sale_payload(order)


@app.get("/health")
def health():
    return {"status": "ok"}
