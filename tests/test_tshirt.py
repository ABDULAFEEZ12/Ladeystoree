"""T-shirt product (sizes M-XXXL, 13 colors) - catalog, product page, admin forms, stock and order handling.

No real database is touched: the Mongo collections are replaced with mocks, and the connection
string points at a closed local port so importing app.py can't reach the live cluster.
"""
import email
import os
import re
from unittest.mock import MagicMock, patch

os.environ["MONGO_URI"] = "mongodb://127.0.0.1:1/?serverSelectionTimeoutMS=200"
os.environ["JWT_SECRET"] = "test-secret"

import jwt
import pytest
from bson.objectid import ObjectId

import app as store

SIZES = ["M", "L", "XL", "XXL", "XXXL"]
COLORS = ["Black", "White", "Nude", "Yellow", "Purple", "Pink", "Brown", "Cream", "Wine", "Blue", "Green", "Lilac", "Red"]


def make_product(**overrides):
    # The price here is a test-only value; the real T-shirt price is entered by the store owner in admin.
    doc = {
        "_id": ObjectId(), "name": "T-Shirt", "price": 1000.0, "image": "https://example.com/t.jpg",
        "category": "T-Shirts", "sizes": SIZES, "sizeStock": {s: 5 for s in SIZES},
        "colors": COLORS, "stock": 25, "description": "",
    }
    doc.update(overrides)
    return doc


@pytest.fixture
def client():
    store.app.config["TESTING"] = True
    return store.app.test_client()


@pytest.fixture
def admin_client(client):
    token = jwt.encode({"id": str(ObjectId())}, "test-secret", algorithm="HS256")
    client.set_cookie("admin_token", token)
    with patch.object(store, "admins_collection") as admins:
        admins.find_one.return_value = {"_id": ObjectId(), "email": "admin@example.com"}
        yield client


def product_page(client, product):
    with patch.object(store, "products_collection") as products:
        products.find_one.return_value = dict(product)
        products.find.return_value.limit.return_value = []
        resp = client.get(f"/product/{product['_id']}")
    assert resp.status_code == 200
    return resp.get_data(as_text=True)


def test_size_and_color_constants():
    assert store.TSHIRT_SIZE_OPTIONS == SIZES
    assert store.TSHIRT_COLOR_OPTIONS == COLORS
    # existing numeric sizes and existing admin colors are untouched
    assert store.SIZE_OPTIONS == ['4', '6', '8', '10', '12', '14', '16', '18', '20']
    for c in ['Grey', 'Navy', 'Beige', 'Orange', 'Multi']:
        assert c in store.COLOR_OPTIONS
    assert set(COLORS) <= set(store.COLOR_OPTIONS)
    assert len(store.COLOR_OPTIONS) == len(set(store.COLOR_OPTIONS))


def test_parse_size_stock_reads_tshirt_and_numeric_sizes():
    form = {"size_qty_M": "3", "size_qty_XXXL": "2", "size_qty_L": "0", "size_qty_XL": "", "size_qty_6": "4", "size_qty_XXL": "abc"}
    assert store.parse_size_stock(form) == {"6": 4, "M": 3, "XXXL": 2}


def test_tshirt_product_page_has_every_size_and_color(client):
    html = product_page(client, make_product())
    for s in SIZES:
        assert f'data-size="{s}"' in html
    for c in COLORS:
        assert f'data-color="{c}"' in html
    assert "const colorRequired = true;" in html
    assert 'id="colorSelectError"' in html


def test_tshirt_with_no_inventory_entered_stays_selectable(client):
    html = product_page(client, make_product(sizeStock={}, stock=10))
    chips = re.findall(r'<button[^>]*size-chip[^>]*>', html)
    assert len(chips) == len(SIZES)
    assert not any("sold-out" in chip or "disabled" in chip for chip in chips)


def test_color_not_required_for_other_categories(client):
    html = product_page(client, make_product(category="Tops", sizes=["6"], sizeStock={"6": 2}, colors=["Black", "Red"]))
    assert "const colorRequired = false;" in html
    assert 'id="colorSelectError"' not in html


def test_tshirt_category_page_lists_product(client):
    product = make_product()
    product["_id"] = str(product["_id"])
    with patch.object(store, "paginate_products", return_value=([product], 1, 1, 1)) as paginate:
        resp = client.get("/t-shirts")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert f'/product/{product["_id"]}' in html
    assert 'data-has-sizes="1"' in html  # quick-add sends sized products to the product page
    query = paginate.call_args[0][0]
    assert query["category"]["$regex"] == "^t-shirts$" and query["category"]["$options"] == "i"


def test_category_sidebar_links_to_tshirts(client):
    with patch.object(store, "paginate_products", return_value=([], 1, 1, 0)):
        assert 'href="/t-shirts"' in client.get("/tops").get_data(as_text=True)


def test_admin_add_form_offers_tshirt_category_sizes_and_colors(admin_client):
    html = admin_client.get("/admin/add-product-page").get_data(as_text=True)
    assert '<option value="T-Shirts">T-Shirts</option>' in html
    for s in SIZES:
        assert f'name="size_qty_{s}"' in html
    for c in COLORS:
        assert f"<option>{c}</option>" in html
    assert 'name="size_qty_4"' in html  # numeric sizes still there


def test_admin_edit_form_shows_saved_tshirt_stock(admin_client):
    product = make_product(sizeStock={"M": 7, "XL": 3}, sizes=["M", "XL"], colors=["Black", "Lilac"])
    with patch.object(store, "products_collection") as products:
        products.find_one.return_value = dict(product)
        html = admin_client.get(f"/admin/edit-product/{product['_id']}").get_data(as_text=True)
    assert re.search(r'name="size_qty_M"[^>]*value="7"', html)
    assert re.search(r'name="size_qty_XL"[^>]*value="3"', html)
    assert "<option selected>Lilac</option>" in html and "<option >Cream</option>" in html
    assert '<option value="T-Shirts" selected>T-Shirts</option>' in html


def test_add_product_saves_tshirt_sizes_and_colors(admin_client):
    form = {"name": "T-Shirt", "price": "1500", "category": "T-Shirts", "description": "",
            "size_qty_M": "4", "size_qty_XXL": "2", "color": ["Black", "Wine"]}
    from io import BytesIO
    form["image"] = (BytesIO(b"x"), "t.jpg")
    with patch.object(store, "products_collection") as products, patch.object(store, "upload_image", return_value="https://example.com/t.jpg"):
        resp = admin_client.post("/admin/add-product", data=form, content_type="multipart/form-data")
    assert resp.status_code == 302
    saved = products.insert_one.call_args[0][0]
    assert saved["sizes"] == ["M", "XXL"] and saved["sizeStock"] == {"M": 4, "XXL": 2}
    assert saved["colors"] == ["Black", "Wine"] and saved["stock"] == 6 and saved["category"] == "T-Shirts"


def test_decrement_tracked_size_draws_down_size_and_total():
    pid = ObjectId()
    with patch.object(store, "products_collection") as products:
        products.find_one.return_value = {"sizeStock": {"M": 5}}
        products.update_one.return_value.matched_count = 1
        store.decrement_stock_for_items([{"id": str(pid), "quantity": 2, "size": "M", "color": "Black"}])
    filt, update = products.update_one.call_args[0]
    assert filt == {"_id": pid, "sizeStock.M": {"$gte": 2}}
    assert update == {"$inc": {"sizeStock.M": -2, "stock": -2}}


def test_decrement_without_size_inventory_does_not_create_sizestock():
    """Selling one size before per-size inventory is entered must not flip the other sizes to Sold Out."""
    pid = ObjectId()
    with patch.object(store, "products_collection") as products:
        products.find_one.return_value = {"_id": pid}  # no sizeStock recorded
        store.decrement_stock_for_items([{"id": str(pid), "quantity": 1, "size": "L", "color": "Pink"}])
    for call in products.update_one.call_args_list:
        assert "$set" not in call[0][1]
        assert not any(k.startswith("sizeStock") for k in call[0][1].get("$inc", {}))
    assert products.update_one.call_args[0][1] == {"$inc": {"stock": -1}}


def test_order_email_includes_size_and_color():
    order = {"paymentReference": "LADEY-TEST", "items": [{"name": "T-Shirt", "size": "XL", "color": "Wine", "quantity": 2, "price": 1000}]}
    with patch.object(store, "MAIL_SERVER", "smtp.example.com"), patch.object(store, "MAIL_USERNAME", "a@example.com"), \
         patch.object(store, "MAIL_PASSWORD", "x"), patch.object(store.smtplib, "SMTP") as smtp:
        store.send_order_notification(order)
    raw = smtp.return_value.__enter__.return_value.sendmail.call_args[0][2]
    body = email.message_from_string(raw).get_payload(decode=True).decode("utf-8")  # body is base64 because of the ₦ sign
    assert "T-Shirt (Size XL), Wine x2" in body
