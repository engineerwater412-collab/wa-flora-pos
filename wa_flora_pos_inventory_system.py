from flask import Flask, render_template_string, request, redirect, url_for, flash
import sqlite3
import pandas as pd
import os

app = Flask(__name__)
app.secret_key = "secret123"

DATABASE = "wa_flora_store.db"
UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

# ---------------------- ROUTES ----------------------

@app.route("/")
def home():
    return redirect(url_for("products"))

@app.route("/products", methods=["GET", "POST"])
def products():
    db = get_db()
    if request.method == "POST":  # Adding a new product
        if "file" in request.files and request.files["file"].filename != "":
            # Handle CSV/Excel upload
            file = request.files["file"]
            filepath = os.path.join(UPLOAD_FOLDER, file.filename)
            file.save(filepath)

            try:
                if filepath.endswith(".csv"):
                    df = pd.read_csv(filepath)
                else:
                    df = pd.read_excel(filepath)

                for _, row in df.iterrows():
                    # Check supplier exists
                    supplier = db.execute("SELECT id FROM Suppliers WHERE name=?", (row["Supplier"],)).fetchone()
                    if not supplier:
                        db.execute("INSERT INTO Suppliers (name, contact, phone) VALUES (?, '', '')", (row["Supplier"],))
                        supplier_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
                    else:
                        supplier_id = supplier["id"]

                    # Check product exists
                    product = db.execute("SELECT id FROM Products WHERE name=?", (row["Product"],)).fetchone()
                    if not product:
                        db.execute("INSERT INTO Products (name, category, base_unit, supplier_id) VALUES (?, ?, ?, ?)",
                                   (row["Product"], row["Category"], row["Base Unit"], supplier_id))
                        product_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
                    else:
                        product_id = product["id"]

                    # Insert variant
                    cursor = db.execute("INSERT INTO ProductVariants (product_id, variant_name, retail_price, wholesale_price) VALUES (?, ?, ?, ?)",
                                        (product_id, row["Variant Name"], row["Retail Price"], row.get("Wholesale Price")))
                    variant_id = cursor.lastrowid

                    # Insert inventory
                    db.execute("INSERT INTO Inventory (variant_id, stock_qty, min_stock) VALUES (?, ?, ?)",
                               (variant_id, row.get("Stock Qty", 0), row.get("Min Stock", 0)))

                db.commit()
                flash("✅ Products & variants imported successfully!")
            except Exception as e:
                flash(f"❌ Import failed: {e}")

            return redirect(url_for("products"))

    products = db.execute("SELECT * FROM Products").fetchall()
    suppliers = db.execute("SELECT * FROM Suppliers").fetchall()
    variants = db.execute("SELECT * FROM ProductVariants").fetchall()
    inventory = {inv["variant_id"]: inv for inv in db.execute("SELECT * FROM Inventory").fetchall()}

    return render_template_string(PRODUCTS_HTML, products=products, suppliers=suppliers, variants=variants, inventory=inventory)

# ---------------------- HTML TEMPLATES ----------------------

PRODUCTS_HTML = """
<!doctype html>
<html>
<head>
  <title>Wa Flora - Products</title>
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css">
</head>
<body class="p-4">
  <div class="container">
    <h2 class="mb-4">📦 Products & Variants</h2>

    {% with messages = get_flashed_messages() %}
      {% if messages %}
        <div class="alert alert-success">{{ messages[0] }}</div>
      {% endif %}
    {% endwith %}

    <!-- Add Product Button -->
    <button class="btn btn-primary mb-3" data-bs-toggle="modal" data-bs-target="#addProductModal">➕ Add Product</button>

    <!-- Upload CSV/Excel -->
    <form method="post" enctype="multipart/form-data" class="mb-3">
      <div class="input-group">
        <input type="file" class="form-control" name="file" accept=".csv,.xlsx" required>
        <button class="btn btn-success">📤 Upload CSV/Excel</button>
      </div>
      <small class="text-muted">Format: Product, Category, Base Unit, Supplier, Variant Name, Retail Price, Wholesale Price, Stock Qty, Min Stock</small>
    </form>

    <div class="row">
      {% for p in products %}
      <div class="col-md-6">
        <div class="card mb-3">
          <div class="card-body">
            <h5>{{ p['name'] }}</h5>
            <p><b>Category:</b> {{ p['category'] }} | <b>Unit:</b> {{ p['base_unit'] }}</p>

            <hr>
            <h6>Variants:</h6>
            <ul>
              {% for v in variants if v['product_id'] == p['id'] %}
                <li>
                  {{ v['variant_name'] }} —
                  Retail: KES {{ '%.2f'|format(v['retail_price']) }}
                  {% if v['wholesale_price'] %}
                    | Wholesale: KES {{ '%.2f'|format(v['wholesale_price']) }}
                  {% endif %}
                  <small class="text-muted"> | Stock: {{ inventory.get(v['id'], {}).get('stock_qty', 0) }}</small>
                </li>
              {% endfor %}
            </ul>
          </div>
        </div>
      </div>
      {% endfor %}
    </div>
  </div>

<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
"""

# ---------------------- RUN ----------------------
if __name__ == "__main__":
    app.run(debug=True)
