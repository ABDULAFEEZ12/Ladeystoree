import os
import sys
import ssl
import bcrypt
import jwt
import datetime
import requests
import certifi
import uuid
import base64
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

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def upload_image(file):
    if not IMGBB_API_KEY:
        return "https://via.placeholder.com/400x500/f0f0f0/9E9E9E?text=LADEY"
    try:
        file_data = file.read()
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
        
        new_arrival = products_collection.find_one({"category": "New Arrivals"})
        bundle_deal = products_collection.find_one({"category": "Bundle Deals"})
        top = products_collection.find_one({"category": "Tops"})
        
        new_arrivals_image = new_arrival.get("image") if new_arrival else None
        bundle_deals_image = bundle_deal.get("image") if bundle_deal else None
        tops_image = top.get("image") if top else None
        
    except:
        products = []
        new_arrivals_image = None
        bundle_deals_image = None
        tops_image = None
    
    return render_template("home.html", 
                          products=products,
                          new_arrivals_image=new_arrivals_image,
                          bundle_deals_image=bundle_deals_image,
                          tops_image=tops_image)

@app.route("/new-arrivals")
def new_arrivals():
    try:
        thirty_days_ago = datetime.datetime.utcnow() - datetime.timedelta(days=30)
        products = convert_cursor(products_collection.find({"$or": [{"created_at": {"$gte": thirty_days_ago}}, {"created_at": {"$exists": False}}]}).sort("created_at", -1))
    except: products = []
    return render_template("new-arrivals.html", products=products, category_name="New Arrivals")

# ✅ NEW: Bundle Deals route
@app.route("/bundledeals")
def bundledeals():
    try: products = convert_cursor(products_collection.find({"category": "Bundle Deals"}))
    except: products = []
    return render_template("bundledeals.html", products=products, category_name="Bundle Deals")

# Old dresses route redirects to bundledeals
@app.route("/dresses")
def dresses():
    return redirect(url_for("bundledeals"))

@app.route("/tops")
def tops():
    try: products = convert_cursor(products_collection.find({"category": "Tops"}))
    except: products = []
    return render_template("tops.html", products=products, category_name="Tops")

@app.route("/jeans")
def jeans():
    try: products = convert_cursor(products_collection.find({"category": "Jeans/Denims"}))
    except: products = []
    return render_template("jeans.html", products=products, category_name="Jeans/Denims")

@app.route("/jumpsuit")
def jumpsuit():
    try: products = convert_cursor(products_collection.find({"category": "Jumpsuit"}))
    except: products = []
    return render_template("jumpsuit.html", products=products, category_name="Jumpsuit")

@app.route("/mom-shorts")
def mom_shorts():
    try: products = convert_cursor(products_collection.find({"category": "Mom Shorts"}))
    except: products = []
    return render_template("mom-shorts.html", products=products, category_name="Mom Shorts")

@app.route("/bum-shorts")
def bum_shorts():
    try: products = convert_cursor(products_collection.find({"category": "Bum Shorts"}))
    except: products = []
    return render_template("bum-shorts.html", products=products, category_name="Bum Shorts")

@app.route("/joggers")
def joggers():
    try: products = convert_cursor(products_collection.find({"category": "Joggers"}))
    except: products = []
    return render_template("joggers.html", products=products, category_name="Joggers")

@app.route("/jogger-shorts")
def jogger_shorts():
    try: products = convert_cursor(products_collection.find({"category": "Jogger Shorts"}))
    except: products = []
    return render_template("jogger-shorts.html", products=products, category_name="Jogger Shorts")

@app.route("/2-piece-sets")
def two_piece_sets():
    try: products = convert_cursor(products_collection.find({"category": "2-Piece Sets"}))
    except: products = []
    return render_template("2-piece-sets.html", products=products, category_name="2-Piece Sets")

@app.route("/combos")
def combos():
    try: products = convert_cursor(products_collection.find({"category": "Combos"}))
    except: products = []
    return render_template("combos.html", products=products, category_name="Combos")

@app.route("/bags")
def bags():
    try: products = convert_cursor(products_collection.find({"category": "Bags"}))
    except: products = []
    return render_template("bags.html", products=products, category_name="Bags")

@app.route("/others")
def others():
    try: products = convert_cursor(products_collection.find({"category": "Others"}))
    except: products = []
    return render_template("others.html", products=products, category_name="Others")

@app.route("/about")
def about(): return render_template("about.html")

@app.route("/collection")
def collection():
    try: products = convert_cursor(products_collection.find())
    except: products = []
    return render_template("collection.html", products=products, category_name="All Collection")

@app.route("/shop")
def shop():
    try: products = convert_cursor(products_collection.find())
    except: products = []
    return render_template("shop.html", products=products)

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

@app.route("/save-order", methods=["POST"])
def save_order():
    data = request.get_json()
    if not data: return jsonify({"message": "Invalid request"}), 400
    reference = data.get("reference", f"LADEY_{uuid.uuid4().hex[:8].upper()}")
    order_data = {
        "paymentReference": reference,
        "customerName": data.get("customerName", "Unknown"),
        "customerPhone": data.get("customerPhone", ""),
        "customerWhatsapp": data.get("customerWhatsapp", ""),
        "customerEmail": data.get("customerEmail", ""),
        "deliveryAddress": data.get("deliveryAddress", ""),
        "state": data.get("state", ""),
        "size": data.get("size", ""),
        "color": data.get("color", ""),
        "items": data.get("items", []),
        "amount": float(data.get("totalAmount", 0)),
        "paymentMethod": data.get("paymentMethod", "SquadCo"),
        "status": "Pending",
        "createdAt": datetime.datetime.utcnow()
    }
    try:
        orders_collection.insert_one(order_data)
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
        response = redirect(url_for("admin_dashboard"))
        response.set_cookie("admin_token", token, httponly=True, secure=False, samesite="Lax", max_age=60*60*24*7)
        flash("Login successful!", "success")
        return response
    return render_template("admin_login.html")

@app.route("/admin/dashboard")
@token_required
def admin_dashboard(current_admin):
    try:
        products = convert_cursor(products_collection.find())
        orders = convert_cursor(orders_collection.find().sort("createdAt", -1))
        messages = convert_cursor(messages_collection.find().sort("createdAt", -1))
    except:
        products, orders, messages = [], [], []
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
        order.setdefault('size', '—')
        order.setdefault('color', '—')
        order.setdefault('amount', 0)
        order.setdefault('status', 'Pending')
        order.setdefault('paymentReference', '—')
    return render_template("admin.html", products=products, orders=orders, messages=messages)

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
        return redirect(url_for("admin_dashboard"))
    return render_template("admin_register.html")

@app.route("/admin/edit-product/<product_id>", methods=["GET", "POST"])
@token_required
def edit_product(current_admin, product_id):
    obj_id = safe_objectid(product_id)
    if not obj_id: flash("Invalid ID.", "error"); return redirect(url_for("admin_dashboard"))
    product = products_collection.find_one({"_id": obj_id})
    if not product: flash("Not found.", "error"); return redirect(url_for("admin_dashboard"))
    if request.method == "POST":
        name, price, category, stock, description = request.form.get("name","").strip(), request.form.get("price"), request.form.get("category","").strip(), request.form.get("stock"), request.form.get("description","").strip()
        valid, msg = validate_product_data(name, price, stock, category)
        if not valid: flash(msg, "error"); return redirect(url_for("edit_product", product_id=product_id))
        update_data = {"name": name, "price": float(price), "category": category, "stock": int(stock), "description": description}
        if 'image' in request.files and request.files['image'].filename:
            file = request.files['image']
            if not allowed_file(file.filename): flash("Invalid file.", "error"); return redirect(url_for("edit_product", product_id=product_id))
            url = upload_image(file)
            if url: update_data["image"] = url
            else: flash("Upload failed.", "error"); return redirect(url_for("edit_product", product_id=product_id))
        products_collection.update_one({"_id": obj_id}, {"$set": update_data})
        flash("Updated!", "success")
        return redirect(url_for("admin_dashboard"))
    return render_template("edit_product.html", product=convert_doc(product))

@app.route("/admin/add-product", methods=["POST"])
@token_required
def add_product(current_admin):
    name, price, description, stock, category = request.form.get("name","").strip(), request.form.get("price"), request.form.get("description","").strip(), request.form.get("stock"), request.form.get("category","").strip()
    valid, msg = validate_product_data(name, price, stock, category)
    if not valid: flash(msg, "error"); return redirect(url_for("admin_dashboard"))
    if 'image' not in request.files: flash("No image.", "error"); return redirect(url_for("admin_dashboard"))
    file = request.files['image']
    if not file.filename: flash("No file.", "error"); return redirect(url_for("admin_dashboard"))
    if not allowed_file(file.filename): flash("Invalid type.", "error"); return redirect(url_for("admin_dashboard"))
    url = upload_image(file)
    if not url: flash("Upload failed.", "error"); return redirect(url_for("admin_dashboard"))
    products_collection.insert_one({"name": name, "price": float(price), "image": url, "description": description, "stock": int(stock), "category": category, "created_at": datetime.datetime.utcnow()})
    flash("Added!", "success")
    return redirect(url_for("admin_dashboard"))

@app.route("/admin/delete-product/<product_id>")
@token_required
def delete_product(current_admin, product_id):
    obj_id = safe_objectid(product_id)
    if not obj_id: flash("Invalid ID.", "error"); return redirect(url_for("admin_dashboard"))
    products_collection.delete_one({"_id": obj_id})
    flash("Deleted!", "success")
    return redirect(url_for("admin_dashboard"))

@app.route("/admin/update-order/<reference>", methods=["POST"])
@token_required
def update_order(current_admin, reference):
    status = request.form.get("status")
    if not status: flash("Status required.", "error"); return redirect(url_for("admin_dashboard"))
    orders_collection.update_one({"paymentReference": reference}, {"$set": {"status": status}})
    flash("Updated!", "success")
    return redirect(url_for("admin_dashboard"))

@app.route("/admin/delete-order/<reference>")
@token_required
def delete_order(current_admin, reference):
    result = orders_collection.delete_one({"paymentReference": reference})
    if result.deleted_count == 0: flash("Order not found.", "error")
    else: flash("Order deleted.", "success")
    return redirect(url_for("admin_dashboard"))

@app.route("/admin/clear-orders")
@token_required
def clear_orders(current_admin):
    result = orders_collection.delete_many({})
    flash(f"Deleted {result.deleted_count} orders.", "success")
    return redirect(url_for("admin_dashboard"))

@app.errorhandler(404)
def page_not_found(e): return render_template("404.html"), 404

@app.errorhandler(500)
def internal_server_error(e): return render_template("500.html"), 500

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
