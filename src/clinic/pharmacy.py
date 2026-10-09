"""Medicine store: catalogue, cart and bill payment.

Payment here is a DEMO: no real gateway is called and no card/UPI details are collected.
Prices are always calculated on the server from the database, never trusted from the browser.
"""
from datetime import datetime

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field

from src.clinic import database as db
from src.clinic.routes import current_user, render, templates

router = APIRouter()

DELIVERY_FEE = 40
FREE_DELIVERY_ABOVE = 500
MAX_QTY = 10
PAYMENT_METHODS = {"upi": "UPI", "card": "Debit / Credit card", "cod": "Cash on delivery"}
CATEGORY_KEYS = {"medicines": "Medicines", "creams": "Creams & Gels"}

# name, category, description, price (rupees)
SEED_MEDICINES = [
    ("Paracetamol 500 mg", "Medicines", "Strip of 15 tablets. For fever and mild pain.", 30),
    ("Cetirizine 10 mg", "Medicines", "Strip of 10 tablets. For allergy, sneezing and runny nose.", 25),
    ("ORS Powder", "Medicines", "Pack of 5 sachets. Replaces fluids during diarrhoea or vomiting.", 60),
    ("Antacid Chewable Tablets", "Medicines", "Strip of 15 tablets. For acidity and heartburn.", 35),
    ("Dry Cough Syrup", "Medicines", "100 ml bottle. Soothes dry, irritating cough.", 85),
    ("Vitamin C 500 mg", "Medicines", "Strip of 15 chewable tablets. Daily immunity support.", 70),
    ("Multivitamin Tablets", "Medicines", "Bottle of 30 tablets. Daily vitamins and minerals.", 180),
    ("Throat Lozenges", "Medicines", "Pack of 10. Relief from sore throat.", 40),
    ("Antiseptic Cream", "Creams & Gels", "20 g tube. For cuts, scrapes and minor wounds.", 55),
    ("Antifungal Cream", "Creams & Gels", "15 g tube. For itching, ringworm and fungal rashes.", 75),
    ("Pain Relief Gel", "Creams & Gels", "30 g tube. For muscle and joint pain.", 110),
    ("Calamine Lotion", "Creams & Gels", "100 ml bottle. Calms rashes, itching and sunburn.", 90),
    ("Moisturising Cream", "Creams & Gels", "100 g jar. For dry and rough skin.", 150),
    ("Sunscreen SPF 50", "Creams & Gels", "50 g tube. Broad-spectrum sun protection.", 320),
    ("Aloe Vera Soothing Gel", "Creams & Gels", "100 g tube. Cools and soothes irritated skin.", 120),
]

_ready = False


# ======================= database =======================
def _ensure():
    """Create the store tables (and seed the catalogue) the first time they are needed."""
    global _ready
    if _ready:
        return
    with db.get_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS medicines (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                category TEXT NOT NULL,
                description TEXT NOT NULL,
                price INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS cart_items (
                user_id INTEGER NOT NULL REFERENCES users(id),
                medicine_id INTEGER NOT NULL REFERENCES medicines(id),
                qty INTEGER NOT NULL,
                PRIMARY KEY (user_id, medicine_id)
            );
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id),
                subtotal INTEGER NOT NULL,
                delivery INTEGER NOT NULL,
                total INTEGER NOT NULL,
                address TEXT NOT NULL,
                payment_method TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS order_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL REFERENCES orders(id),
                medicine_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                unit_price INTEGER NOT NULL,
                qty INTEGER NOT NULL
            );
            """
        )
        if conn.execute("SELECT COUNT(*) FROM medicines").fetchone()[0] == 0:
            conn.executemany(
                "INSERT OR IGNORE INTO medicines (name, category, description, price)"
                " VALUES (?, ?, ?, ?)",
                SEED_MEDICINES,
            )
    _ready = True


def list_medicines(category: str | None = None):
    _ensure()
    with db.get_conn() as conn:
        if category:
            rows = conn.execute(
                "SELECT * FROM medicines WHERE category = ? ORDER BY id", (category,)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM medicines ORDER BY id").fetchall()
        return [dict(r) for r in rows]


def get_medicine(medicine_id: int):
    _ensure()
    with db.get_conn() as conn:
        row = conn.execute("SELECT * FROM medicines WHERE id = ?", (medicine_id,)).fetchone()
        return dict(row) if row else None


def _totals(lines):
    for line in lines:
        line["line_total"] = line["price"] * line["qty"]
    subtotal = sum(line["line_total"] for line in lines)
    delivery = 0 if (subtotal == 0 or subtotal >= FREE_DELIVERY_ABOVE) else DELIVERY_FEE
    return {
        "lines": lines,
        "count": sum(line["qty"] for line in lines),
        "subtotal": subtotal,
        "delivery": delivery,
        "total": subtotal + delivery,
    }


_CART_SELECT = (
    "SELECT m.id AS medicine_id, m.name, m.category, m.price, c.qty"
    " FROM cart_items c JOIN medicines m ON m.id = c.medicine_id"
    " WHERE c.user_id = ? ORDER BY c.rowid"
)


def cart_summary(user_id: int):
    _ensure()
    with db.get_conn() as conn:
        rows = conn.execute(_CART_SELECT, (user_id,)).fetchall()
    return _totals([dict(r) for r in rows])


def cart_count(user_id: int) -> int:
    """Used by the navbar badge on every page, so it must never raise."""
    try:
        _ensure()
        with db.get_conn() as conn:
            return conn.execute(
                "SELECT COALESCE(SUM(qty), 0) FROM cart_items WHERE user_id = ?", (user_id,)
            ).fetchone()[0]
    except Exception:
        return 0


def cart_add(user_id: int, medicine_id: int, qty: int):
    _ensure()
    with db.get_conn() as conn:
        conn.execute(
            "INSERT INTO cart_items (user_id, medicine_id, qty) VALUES (?, ?, ?)"
            " ON CONFLICT(user_id, medicine_id)"
            " DO UPDATE SET qty = MIN(qty + excluded.qty, ?)",
            (user_id, medicine_id, min(qty, MAX_QTY), MAX_QTY),
        )


def cart_set(user_id: int, medicine_id: int, qty: int):
    """qty <= 0 removes the item."""
    _ensure()
    with db.get_conn() as conn:
        if qty <= 0:
            conn.execute(
                "DELETE FROM cart_items WHERE user_id = ? AND medicine_id = ?",
                (user_id, medicine_id),
            )
        else:
            conn.execute(
                "INSERT INTO cart_items (user_id, medicine_id, qty) VALUES (?, ?, ?)"
                " ON CONFLICT(user_id, medicine_id) DO UPDATE SET qty = excluded.qty",
                (user_id, medicine_id, min(qty, MAX_QTY)),
            )


def create_order(user_id: int, address: str, method: str):
    """Turn the user's cart into an order and empty the cart. Returns the order id, or None
    if the cart is empty. BEGIN IMMEDIATE stops a double-click from creating two orders."""
    _ensure()
    with db.get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        rows = conn.execute(_CART_SELECT, (user_id,)).fetchall()
        if not rows:
            return None
        t = _totals([dict(r) for r in rows])
        status = "placed" if method == "cod" else "paid"
        cur = conn.execute(
            "INSERT INTO orders (user_id, subtotal, delivery, total, address, payment_method,"
            " status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (user_id, t["subtotal"], t["delivery"], t["total"], address, method, status,
             datetime.now().strftime("%d %b %Y, %I:%M %p")),
        )
        order_id = cur.lastrowid
        conn.executemany(
            "INSERT INTO order_items (order_id, medicine_id, name, unit_price, qty)"
            " VALUES (?, ?, ?, ?, ?)",
            [(order_id, l["medicine_id"], l["name"], l["price"], l["qty"]) for l in t["lines"]],
        )
        conn.execute("DELETE FROM cart_items WHERE user_id = ?", (user_id,))
        return order_id


def get_order(user_id: int, order_id: int):
    """Only returns the order if it belongs to this user."""
    _ensure()
    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM orders WHERE id = ? AND user_id = ?", (order_id, user_id)
        ).fetchone()
        if not row:
            return None
        items = conn.execute(
            "SELECT name, unit_price AS price, qty FROM order_items WHERE order_id = ? ORDER BY id",
            (order_id,),
        ).fetchall()
    order = dict(row)
    order["lines"] = [dict(i, line_total=i["price"] * i["qty"]) for i in items]
    return order


# Lets any template show the cart badge:  {{ cart_count(user.id) }}
templates.env.globals["cart_count"] = cart_count


# ======================= routes =======================
def _unauth():
    return JSONResponse({"error": "Please log in again."}, status_code=401)


def _cart_json(user_id: int):
    s = cart_summary(user_id)
    return {"count": s["count"], "subtotal": s["subtotal"],
            "delivery": s["delivery"], "total": s["total"]}


class CartIn(BaseModel):
    medicine_id: int
    qty: int = Field(1, ge=0, le=MAX_QTY)


@router.get("/medicines")
def medicines_page(request: Request, cat: str = ""):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    active = cat if cat in CATEGORY_KEYS else ""
    return render(request, "medicines.html", user=user,
                  medicines=list_medicines(CATEGORY_KEYS.get(active)),
                  active=active, cart=cart_summary(user["id"]))


@router.post("/api/cart/add")
def api_cart_add(request: Request, body: CartIn):
    user = current_user(request)
    if not user:
        return _unauth()
    if body.qty < 1 or not get_medicine(body.medicine_id):
        return JSONResponse({"error": "Medicine not found."}, status_code=400)
    cart_add(user["id"], body.medicine_id, body.qty)
    return _cart_json(user["id"])


@router.post("/api/cart/set")
def api_cart_set(request: Request, body: CartIn):
    user = current_user(request)
    if not user:
        return _unauth()
    if not get_medicine(body.medicine_id):
        return JSONResponse({"error": "Medicine not found."}, status_code=400)
    cart_set(user["id"], body.medicine_id, body.qty)
    return _cart_json(user["id"])


@router.get("/cart")
def cart_page(request: Request):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    return render(request, "cart.html", user=user, cart=cart_summary(user["id"]),
                  max_qty=MAX_QTY)


@router.get("/checkout")
def checkout_page(request: Request):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    cart = cart_summary(user["id"])
    if not cart["lines"]:
        return RedirectResponse("/medicines", status_code=303)
    return render(request, "checkout.html", user=user, cart=cart,
                  methods=PAYMENT_METHODS, error=None, form={})


@router.post("/checkout")
def checkout_pay(request: Request, address: str = Form(...),
                 payment_method: str = Form(...)):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    address = " ".join(address.split())  # tidy spaces / newlines
    error = None
    if payment_method not in PAYMENT_METHODS:
        error = "Please choose a payment method."
    elif not 10 <= len(address) <= 200:
        error = "Please enter your full delivery address (10 to 200 characters)."
    if error:
        cart = cart_summary(user["id"])
        if not cart["lines"]:
            return RedirectResponse("/medicines", status_code=303)
        return render(request, "checkout.html", status_code=400, user=user, cart=cart,
                      methods=PAYMENT_METHODS, error=error,
                      form={"address": address, "payment_method": payment_method})
    order_id = create_order(user["id"], address, payment_method)
    if order_id is None:  # cart was already emptied (e.g. double click)
        return RedirectResponse("/medicines", status_code=303)
    return RedirectResponse(f"/orders/{order_id}", status_code=303)


@router.get("/orders/{order_id}")
def order_page(request: Request, order_id: int):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    order = get_order(user["id"], order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return render(request, "order_done.html", user=user, order=order,
                  methods=PAYMENT_METHODS)