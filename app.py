import os
import re
import sys
import ssl
import bcrypt
import jwt
import datetime
import requests
import certifi
import uuid
import base64
import math
import smtplib
from email.mime.text import MIMEText
from io import BytesIO
from PIL import Image
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, jsonify, flash, send_from_directory, abort
from flask_cors import CORS
from werkzeug.utils import secure_filename
from pymongo import MongoClient
from dotenv import load_dotenv
from bson.objectid import ObjectId
from bson.errors import InvalidId

if sys.platform == 'win32':
    ssl._create_default_https_context = ssl._create_unverified_context

load_dotenv()

app = Flask(__name__)
CORS(app)
app.secret_key = os.getenv("JWT_SECRET")

MONGO_URI = os.getenv("MONGO_URI")
JWT_SECRET = os.getenv("JWT_SECRET")
IMGBB_API_KEY = os.getenv("IMGBB_API_KEY")
SQUADCO_SECRET_KEY = os.getenv("SQUADCO_SECRET_KEY")

MAIL_SERVER = os.getenv("MAIL_SERVER")
MAIL_PORT = int(os.getenv("MAIL_PORT", "587") or "587")
MAIL_USE_TLS = os.getenv("MAIL_USE_TLS", "true").lower() == "true"
MAIL_USERNAME = os.getenv("MAIL_USERNAME")
MAIL_PASSWORD = os.getenv("MAIL_PASSWORD")
ORDER_NOTIFY_EMAIL = "demmierex@gmail.com"

def send_order_notification(order_data):
    """Best-effort email to the store owner when a payment is confirmed. Never blocks or fails the order itself."""
    if not (MAIL_SERVER and MAIL_USERNAME and MAIL_PASSWORD):
        return
    try:
        items_text = "\n".join(
            f"- {item.get('name', 'Item')} x{item.get('quantity', 1)} (₦{item.get('price', 0):,.0f})"
            for item in order_data.get("items", [])
        ) or "No items listed"
        body = (
            f"New order received!\n\n"
            f"Reference: {order_data.get('paymentReference')}\n"
            f"Customer: {order_data.get('customerName')}\n"
            f"Phone: {order_data.get('customerPhone')}\n"
            f"WhatsApp: {order_data.get('customerWhatsapp')}\n"
            f"Email: {order_data.get('customerEmail')}\n"
            f"Amount: ₦{order_data.get('amount', 0):,.0f}\n\n"
            f"Items:\n{items_text}\n\n"
            f"Delivery: {order_data.get('deliveryAddress')}, {order_data.get('state')}, {order_data.get('country')}\n"
            f"Size: {order_data.get('size')}  Color: {order_data.get('color')}"
        )
        msg = MIMEText(body)
        msg["Subject"] = f"New Order - {order_data.get('paymentReference')}"
        msg["From"] = MAIL_USERNAME
        msg["To"] = ORDER_NOTIFY_EMAIL
        with smtplib.SMTP(MAIL_SERVER, MAIL_PORT, timeout=10) as server:
            if MAIL_USE_TLS:
                server.starttls()
            server.login(MAIL_USERNAME, MAIL_PASSWORD)
            server.sendmail(MAIL_USERNAME, [ORDER_NOTIFY_EMAIL], msg.as_string())
    except Exception as e:
        print(f"Order notification email failed: {e}")

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

MAX_IMAGE_DIMENSION = 1600
IMAGE_JPEG_QUALITY = 80

def compress_image(file_data):
    """Downscale and re-encode an uploaded image as JPEG to cut its file size before hosting it."""
    try:
        img = Image.open(BytesIO(file_data))
        img = img.convert("RGB")
        if max(img.size) > MAX_IMAGE_DIMENSION:
            img.thumbnail((MAX_IMAGE_DIMENSION, MAX_IMAGE_DIMENSION), Image.LANCZOS)
        buffer = BytesIO()
        img.save(buffer, format="JPEG", quality=IMAGE_JPEG_QUALITY, optimize=True)
        return buffer.getvalue()
    except Exception:
        return file_data

def upload_image(file):
    if not IMGBB_API_KEY:
        return "https://via.placeholder.com/400x500/f0f0f0/9E9E9E?text=LADEY"
    try:
        file_data = compress_image(file.read())
        encoded_image = base64.b64encode(file_data).decode('utf-8')
        response = requests.post("https://api.imgbb.com/1/upload", data={"key": IMGBB_API_KEY, "image": encoded_image})
        result = response.json()
        if result.get("success"): return result["data"]["url"]
        return None
    except: return None

try:
    client = MongoClient(MONGO_URI, tls=True, tlsCAFile=certifi.where(), tlsAllowInvalidCertificates=True, serverSelectionTimeoutMS=5000)
    client.admin.command('ping')
except:
    client = MongoClient(MONGO_URI, tls=True, tlsAllowInvalidCertificates=True)

db = client["ladeystoree"]
products_collection = db["products"]
orders_collection = db["orders"]
admins_collection = db["admins"]
messages_collection = db["messages"]

PRODUCTS_PER_PAGE = 10

def paginate_products(query, page, sort=None):
    """Fetch one page of products matching query. Returns (products, page, total_pages, total_count)."""
    total = products_collection.count_documents(query)
    total_pages = max(1, math.ceil(total / PRODUCTS_PER_PAGE))
    page = min(max(1, page), total_pages)
    cursor = products_collection.find(query)
    if sort:
        cursor = cursor.sort(*sort)
    cursor = cursor.skip((page - 1) * PRODUCTS_PER_PAGE).limit(PRODUCTS_PER_PAGE)
    return convert_cursor(cursor), page, total_pages, total

def safe_objectid(id_str):
    try: return ObjectId(id_str)
    except: return None

def convert_doc(doc):
    if not doc: return doc
    doc["_id"] = str(doc["_id"])
    return doc

def convert_cursor(cursor):
    return [convert_doc(doc) for doc in cursor]

def validate_product_data(name, price, stock, category):
    if not name or not name.strip(): return False, "Product name is required."
    try:
        if float(price) < 0: return False, "Price cannot be negative."
    except: return False, "Price must be a valid number."
    try:
        if int(stock) < 0: return False, "Stock cannot be negative."
    except: return False, "Stock must be a valid integer."
    if not category or not category.strip(): return False, "Category is required."
    return True, ""

def format_currency(amount):
    try: return "₦{:,.2f}".format(float(amount))
    except: return "₦0.00"

app.jinja_env.globals.update(format_currency=format_currency)

def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.cookies.get("admin_token")
        if not token:
            flash("Please log in to access the admin area.", "error")
            return redirect(url_for("admin_login_page"))
        try:
            data = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
            admin_id = safe_objectid(data.get("id"))
            if not admin_id: raise InvalidId
            current_admin = admins_collection.find_one({"_id": admin_id})
            if not current_admin:
                flash("Admin account not found.", "error")
                return redirect(url_for("admin_login_page"))
        except:
            flash("Invalid or expired session.", "error")
            return redirect(url_for("admin_login_page"))
        return f(current_admin, *args, **kwargs)
    return decorated

# ==========================
# PUBLIC ROUTES
# ==========================
@app.route("/")
def home():
    try:
        products = convert_cursor(products_collection.find().limit(8))
        bundle_deal = products_collection.find_one({"category": "Bundle Deals"})
        top = products_collection.find_one({"category": "Tops"})
        bundle_deals_image = bundle_deal.get("image") if bundle_deal else None
        tops_image = top.get("image") if top else None
    except:
        products = []
        bundle_deals_image = None
        tops_image = None
    return render_template("home.html", products=products, bundle_deals_image=bundle_deals_image, tops_image=tops_image)

def render_product_page(template, query, category_name, sort=None, endpoint=None, **extra_context):
    page = request.args.get("page", 1, type=int)
    try:
        products, page, total_pages, total = paginate_products(query, page, sort=sort)
    except:
        products, page, total_pages, total = [], 1, 1, 0
    pagination_args = {k: v for k, v in request.args.items() if k != "page"}
    return render_template(template, products=products, category_name=category_name,
                            page=page, total_pages=total_pages, total_products=total,
                            endpoint=endpoint or request.endpoint, pagination_args=pagination_args,
                            **extra_context)

@app.route("/bundledeals")
def bundledeals():
    return render_product_page("bundledeals.html", {"category": "Bundle Deals"}, "Bundle Deals")

@app.route("/dresses")
def dresses():
    return redirect(url_for("bundledeals"))

# ✅ FIXED: Case-insensitive category matching for all category routes
@app.route("/tops")
def tops():
    return render_product_page("tops.html", {"category": {"$regex": "^tops$", "$options": "i"}}, "Tops")

JEANS_QUERY = {"category": {"$regex": "^jeans", "$options": "i"}}

def get_jeans_waist_sizes():
    """Jeans products are named like 'Waist 28' - pull the distinct waist numbers straight from product names."""
    try:
        names = products_collection.find(JEANS_QUERY).distinct("name")
        sizes = {m.group(0) for n in names if n for m in [re.search(r"\d+", n)] if m}
        return sorted(sizes, key=int)
    except:
        return []

@app.route("/jeans")
def jeans():
    waist_sizes = get_jeans_waist_sizes()
    query = dict(JEANS_QUERY)
    waist = request.args.get("waist", "").strip()
    if waist and waist in waist_sizes:
        query["name"] = {"$regex": r"\bwaist\s*" + re.escape(waist) + r"\b", "$options": "i"}
    else:
        waist = ""
    return render_product_page("jeans.html", query, "Jeans/Denims", selected_waist=waist, waist_sizes=waist_sizes)

@app.route("/denims")
def denims():
    return render_product_page("denims.html", {"category": {"$regex": "^denims$", "$options": "i"}}, "Denims")

@app.route("/jumpsuit")
def jumpsuit():
    return render_product_page("jumpsuit.html", {"category": {"$regex": "^jumpsuit$", "$options": "i"}}, "Jumpsuit")

@app.route("/mom-shorts")
def mom_shorts():
    return render_product_page("mom-shorts.html", {"category": {"$regex": "^mom shorts$", "$options": "i"}}, "Mom Shorts")

@app.route("/bum-shorts")
def bum_shorts():
    return render_product_page("bum-shorts.html", {"category": {"$regex": "^bum shorts$", "$options": "i"}}, "Bum Shorts")

@app.route("/joggers")
def joggers():
    return render_product_page("joggers.html", {"category": {"$regex": "^joggers$", "$options": "i"}}, "Joggers")

@app.route("/jogger-shorts")
def jogger_shorts():
    return render_product_page("jogger-shorts.html", {"category": {"$regex": "^jogger shorts$", "$options": "i"}}, "Jogger Shorts")

@app.route("/2-piece-sets")
def two_piece_sets():
    return render_product_page("2-piece-sets.html", {"category": {"$regex": "^2-piece sets$", "$options": "i"}}, "2-Piece Sets")

@app.route("/combos")
def combos():
    return render_product_page("combos.html", {"category": {"$regex": "^combos$", "$options": "i"}}, "Combos")

@app.route("/bags")
def bags():
    return render_product_page("bags.html", {"category": {"$regex": "^bags$", "$options": "i"}}, "Bags")

@app.route("/others")
def others():
    return render_product_page("others.html", {"category": {"$regex": "^others$", "$options": "i"}}, "Others")

@app.route("/about")
def about(): return render_template("about.html")

@app.route("/collection")
def collection():
    return render_product_page("collection.html", {}, "All Collection")

@app.route("/shop")
def shop():
    return render_product_page("shop.html", {}, None)

@app.route("/cart")
def cart(): return render_template("cart.html")

@app.route("/contact")
def contact(): return render_template("contact.html")

@app.route("/product/<product_id>")
def product_detail(product_id):
    obj_id = safe_objectid(product_id)
    if not obj_id: abort(404)
    product = products_collection.find_one({"_id": obj_id})
    if not product: abort(404)
    product = convert_doc(product)
    product["id"] = product["_id"]
    related_products = []
    if product.get("category"):
        related_products = convert_cursor(products_collection.find({"_id": {"$ne": obj_id}, "category": product["category"]}).limit(4))
    return render_template("product.html", product=product, related_products=related_products)

@app.route("/checkout")
def checkout(): return render_template("checkout.html")

@app.route("/order-confirmed")
def order_confirmed(): return render_template("order-confirmed.html")

def verify_squad_transaction(reference):
    """Ask SquadCo whether a transaction actually succeeded. Returns the transaction data dict, or None if it can't be confirmed."""
    if not SQUADCO_SECRET_KEY or not reference:
        return None
    headers = {"Authorization": f"Bearer {SQUADCO_SECRET_KEY}"}
    try:
        resp = requests.get(f"https://api-d.squadco.com/transaction/verify/{reference}", headers=headers, timeout=15)
        if resp.status_code != 200:
            return None
        result = resp.json()
        return result.get("data")
    except Exception as e:
        print(f"SquadCo verify error: {e}")
        return None

@app.route("/create-payment-link", methods=["POST"])
def create_payment_link():
    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid request"}), 400

    amount = data.get("amount", 0)
    email = data.get("email", "customer@ladeystoree.com")
    name = data.get("name", "Customer")
    reference = data.get("reference")

    if not reference:
        return jsonify({"error": "Missing order reference"}), 400
    if not SQUADCO_SECRET_KEY:
        return jsonify({"error": "Payment not configured"}), 500

    try:
        response = requests.post(
            "https://api-d.squadco.com/transaction/initiate",
            headers={
                "Authorization": f"Bearer {SQUADCO_SECRET_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "amount": float(amount) * 100,
                "email": email,
                "customer_name": name,
                "currency": "NGN",
                "initiate_type": "inline",
                "pass_charge": True,
                "transaction_ref": reference,
                "callback_url": "https://ladeystoree.com/order-confirmed"
            }
        )

        result = response.json()
        print(f"SquadCo response: {result}")
        checkout_url = result.get("data", {}).get("checkout_url")

        if checkout_url:
            return jsonify({"payment_url": checkout_url})
        else:
            return jsonify({"error": "Could not create payment link", "detail": result}), 502

    except Exception as e:
        print(f"SquadCo error: {e}")
        return jsonify({"error": "Payment service unavailable"}), 502

@app.route("/save-order", methods=["POST"])
def save_order():
    data = request.get_json()
    if not data: return jsonify({"message": "Invalid request"}), 400
    reference = data.get("reference")
    if not reference:
        return jsonify({"message": "Missing order reference"}), 400

    # Idempotent: if this reference was already recorded as paid, don't re-verify or duplicate it.
    existing = orders_collection.find_one({"paymentReference": reference})
    if existing and existing.get("status") == "Paid":
        return jsonify({"message": "Order already recorded", "reference": reference})

    transaction = verify_squad_transaction(reference)
    if not transaction or str(transaction.get("transaction_status", "")).lower() != "success":
        return jsonify({"message": "Payment could not be verified. Order was not recorded.", "verified": False}), 402

    expected_kobo = float(data.get("totalAmount", 0)) * 100
    paid_kobo = float(transaction.get("transaction_amount") or 0)
    if expected_kobo > 0 and paid_kobo < expected_kobo * 0.99:
        return jsonify({"message": "Paid amount does not match order total. Order was not recorded.", "verified": False}), 402

    # Attach each item's current product image so admin can see what was bought at a glance.
    enriched_items = []
    for item in data.get("items", []):
        product_id = safe_objectid(item.get("id", ""))
        image = None
        if product_id:
            product = products_collection.find_one({"_id": product_id}, {"image": 1})
            if product:
                image = product.get("image")
        enriched_items.append({**item, "image": image})

    order_data = {
        "paymentReference": reference,
        "customerName": data.get("customerName", "Unknown"),
        "customerPhone": data.get("customerPhone", ""),
        "customerWhatsapp": data.get("customerWhatsapp", ""),
        "customerEmail": data.get("customerEmail", ""),
        "deliveryAddress": data.get("deliveryAddress", ""),
        "state": data.get("state", ""),
        "country": data.get("country", "Nigeria"),
        "size": data.get("size", ""),
        "color": data.get("color", ""),
        "items": enriched_items,
        "amount": float(data.get("totalAmount", 0)),
        "paymentMethod": data.get("paymentMethod", "SquadCo"),
        "status": "Paid",
        "createdAt": datetime.datetime.utcnow()
    }
    try:
        orders_collection.update_one({"paymentReference": reference}, {"$set": order_data}, upsert=True)
        for item in enriched_items:
            product_id = safe_objectid(item.get("id", ""))
            qty = int(item.get("quantity") or 1)
            if not product_id or qty <= 0:
                continue
            # Only decrement if enough stock is on record; otherwise clamp to 0 rather than go negative.
            result = products_collection.update_one(
                {"_id": product_id, "stock": {"$gte": qty}},
                {"$inc": {"stock": -qty}}
            )
            if result.matched_count == 0:
                products_collection.update_one({"_id": product_id}, {"$set": {"stock": 0}})
        send_order_notification(order_data)
        return jsonify({"message": "Order saved", "reference": reference})
    except Exception as e:
        return jsonify({"message": "Failed", "error": str(e)}), 500

@app.route("/send-message", methods=["POST"])
def send_message():
    data = request.get_json()
    if not data: return jsonify({"message": "Invalid request"}), 400
    message_data = {
        "name": data.get("name", "Unknown"),
        "email": data.get("email", ""),
        "subject": data.get("subject", ""),
        "message": data.get("message", ""),
        "createdAt": datetime.datetime.utcnow()
    }
    try:
        messages_collection.insert_one(message_data)
        return jsonify({"message": "Message sent successfully!"})
    except Exception as e:
        return jsonify({"message": "Failed to send message", "error": str(e)}), 500

@app.route("/order/<reference>")
def order_status(reference):
    order = orders_collection.find_one({"paymentReference": reference})
    if not order: abort(404)
    return render_template("order_status.html", order=convert_doc(order))

# ==========================
# ADMIN ROUTES
# ==========================
@app.route("/admin/seed")
def seed_admin():
    if admins_collection.find_one({"email": "admin@ladeystoree.com"}):
        return "Admin already exists.", 200
    hashed = bcrypt.hashpw("admin123".encode(), bcrypt.gensalt())
    admins_collection.insert_one({"email": "admin@ladeystoree.com", "password": hashed, "role": "admin", "created_at": datetime.datetime.utcnow()})
    return "✅ Admin created! DELETE THIS ROUTE.", 201

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login_page():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        admin = admins_collection.find_one({"email": email})
        if not admin or not bcrypt.checkpw(password.encode(), admin["password"]):
            flash("Invalid email or password.", "error")
            return redirect(url_for("admin_login_page"))
        token = jwt.encode({"id": str(admin["_id"]), "exp": datetime.datetime.utcnow() + datetime.timedelta(days=7)}, JWT_SECRET, algorithm="HS256")
        response = redirect(url_for("admin_products"))
        response.set_cookie("admin_token", token, httponly=True, secure=False, samesite="Lax", max_age=60*60*24*7)
        flash("Login successful!", "success")
        return response
    return render_template("admin_login.html")

@app.route("/admin/dashboard")
@token_required
def admin_dashboard(current_admin):
    return redirect(url_for("admin_products"))

@app.route("/admin/products")
@token_required
def admin_products(current_admin):
    try:
        products = convert_cursor(products_collection.find())
    except:
        products = []
    return render_template("admin_products.html", products=products)

@app.route("/admin/add-product-page")
@token_required
def admin_add_product_page(current_admin):
    return render_template("admin_add_product.html")

def _prepare_orders_for_admin(orders):
    for order in orders:
        if 'items' in order and isinstance(order['items'], list):
            order['orderItems'] = order.pop('items')
        else:
            order['orderItems'] = []
        order.setdefault('customerName', '—')
        order.setdefault('customerPhone', '—')
        order.setdefault('customerWhatsapp', '—')
        order.setdefault('customerEmail', '')
        order.setdefault('deliveryAddress', '—')
        order.setdefault('state', '—')
        order.setdefault('country', '—')
        order.setdefault('size', '—')
        order.setdefault('color', '—')
        order.setdefault('amount', 0)
        order.setdefault('status', 'Pending')
        order.setdefault('paymentReference', '—')
    return orders

@app.route("/admin/orders")
@token_required
def admin_orders(current_admin):
    try:
        orders = convert_cursor(orders_collection.find().sort("createdAt", -1))
    except:
        orders = []
    orders = _prepare_orders_for_admin(orders)
    return render_template("admin_orders.html", orders=orders)

@app.route("/admin/messages")
@token_required
def admin_messages(current_admin):
    try:
        messages = convert_cursor(messages_collection.find().sort("createdAt", -1))
    except:
        messages = []
    return render_template("admin_messages.html", messages=messages)

@app.route("/admin/logout")
def admin_logout():
    response = redirect(url_for("admin_login_page"))
    response.delete_cookie("admin_token")
    flash("Logged out.", "success")
    return response

@app.route("/admin/register", methods=["GET", "POST"])
@token_required
def admin_register(current_admin):
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")
        if not email or not password: flash("Required.", "error"); return redirect(url_for("admin_register"))
        if password != confirm: flash("Passwords don't match.", "error"); return redirect(url_for("admin_register"))
        if admins_collection.find_one({"email": email}): flash("Already exists.", "error"); return redirect(url_for("admin_register"))
        hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt())
        admins_collection.insert_one({"email": email, "password": hashed, "created_by": current_admin["email"], "role": "admin", "created_at": datetime.datetime.utcnow()})
        flash("Admin created!", "success")
        return redirect(url_for("admin_products"))
    return render_template("admin_register.html")

@app.route("/admin/edit-product/<product_id>", methods=["GET", "POST"])
@token_required
def edit_product(current_admin, product_id):
    obj_id = safe_objectid(product_id)
    if not obj_id: flash("Invalid ID.", "error"); return redirect(url_for("admin_products"))
    product = products_collection.find_one({"_id": obj_id})
    if not product: flash("Not found.", "error"); return redirect(url_for("admin_products"))
    if request.method == "POST":
        name = request.form.get("name","").strip()
        price = request.form.get("price")
        category = request.form.get("category","").strip()
        stock = request.form.get("stock")
        description = request.form.get("description","").strip()
        sizes = request.form.getlist("size")
        colors = request.form.getlist("color")
        valid, msg = validate_product_data(name, price, stock, category)
        if not valid: flash(msg, "error"); return redirect(url_for("edit_product", product_id=product_id))
        update_data = {
            "name": name, "price": float(price), "category": category,
            "stock": int(stock), "description": description,
            "sizes": sizes, "colors": colors
        }
        if 'image' in request.files and request.files['image'].filename:
            file = request.files['image']
            if not allowed_file(file.filename): flash("Invalid file.", "error"); return redirect(url_for("edit_product", product_id=product_id))
            url = upload_image(file)
            if url: update_data["image"] = url
            else: flash("Upload failed.", "error"); return redirect(url_for("edit_product", product_id=product_id))
        products_collection.update_one({"_id": obj_id}, {"$set": update_data})
        flash("Updated!", "success")
        return redirect(url_for("admin_products"))
    return render_template("edit_product.html", product=convert_doc(product))

@app.route("/admin/add-product", methods=["POST"])
@token_required
def add_product(current_admin):
    name = request.form.get("name","").strip()
    price = request.form.get("price")
    description = request.form.get("description","").strip()
    stock = request.form.get("stock")
    category = request.form.get("category","").strip()
    sizes = request.form.getlist("size")
    colors = request.form.getlist("color")
    valid, msg = validate_product_data(name, price, stock, category)
    if not valid: flash(msg, "error"); return redirect(url_for("admin_add_product_page"))
    if 'image' not in request.files: flash("No image.", "error"); return redirect(url_for("admin_add_product_page"))
    file = request.files['image']
    if not file.filename: flash("No file.", "error"); return redirect(url_for("admin_add_product_page"))
    if not allowed_file(file.filename): flash("Invalid type.", "error"); return redirect(url_for("admin_add_product_page"))
    url = upload_image(file)
    if not url: flash("Upload failed.", "error"); return redirect(url_for("admin_add_product_page"))
    products_collection.insert_one({
        "name": name, "price": float(price), "image": url,
        "description": description, "stock": int(stock),
        "category": category, "sizes": sizes, "colors": colors,
        "created_at": datetime.datetime.utcnow()
    })
    flash("Added!", "success")
    return redirect(url_for("admin_products"))

@app.route("/admin/delete-product/<product_id>")
@token_required
def delete_product(current_admin, product_id):
    obj_id = safe_objectid(product_id)
    if not obj_id: flash("Invalid ID.", "error"); return redirect(url_for("admin_products"))
    products_collection.delete_one({"_id": obj_id})
    flash("Deleted!", "success")
    return redirect(url_for("admin_products"))

@app.route("/admin/update-order/<reference>", methods=["POST"])
@token_required
def update_order(current_admin, reference):
    status = request.form.get("status")
    if not status: flash("Status required.", "error"); return redirect(url_for("admin_orders"))
    orders_collection.update_one({"paymentReference": reference}, {"$set": {"status": status}})
    flash("Updated!", "success")
    return redirect(url_for("admin_orders"))

@app.route("/admin/delete-order/<reference>")
@token_required
def delete_order(current_admin, reference):
    result = orders_collection.delete_one({"paymentReference": reference})
    if result.deleted_count == 0: flash("Order not found.", "error")
    else: flash("Order deleted.", "success")
    return redirect(url_for("admin_orders"))

@app.route("/admin/clear-orders")
@token_required
def clear_orders(current_admin):
    result = orders_collection.delete_many({})
    flash(f"Deleted {result.deleted_count} orders.", "success")
    return redirect(url_for("admin_orders"))

@app.errorhandler(404)
def page_not_found(e): return render_template("404.html"), 404

@app.errorhandler(500)
def internal_server_error(e): return render_template("500.html"), 500

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
