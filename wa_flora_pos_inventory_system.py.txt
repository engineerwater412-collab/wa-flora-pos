Wa Flora General Store POS & Inventory System (Single-file Flask App)

---------------------------------------------------------------

Features implemented (aligned to your workflow):

1) Inventory Management

- New Product Registration with variants & pricing (retail/wholesale)

- Receiving New Stock with supplier, purchase price, StockLedger

- Moving-average cost tracking per variant

2) Sales Process (Retail & Wholesale)

- POS cart for retail sales (barcode/name search, variable quantity)

- Payment: Cash, M-Pesa (stub), and Credit

- Discounts, change due, printable receipts

3) Credit Management

- Credit ledger creation on credit sales

- Record credit payments; mark transactions Paid when cleared

4) Reporting

- Sales report (by period, product, cashier(fake)/user, payment method)

- Inventory report (stock levels, low-stock alerts, stock movement history)

- Credit report (outstanding by customer, aging buckets)

- Profit & Loss: Gross profit using moving-average COGS captured at sale time

---------------------------------------------------------------

RUN:  python wa_flora_pos_inventory_system.py

Then open: http://127.0.0.1:5000

---------------------------------------------------------------

from future import annotations import os import sqlite3 from datetime import datetime, date, timedelta from decimal import Decimal, ROUND_HALF_UP from typing import Optional, Dict, Any, List, Tuple

from flask import Flask, g, render_template_string, request, redirect, url_for, flash, jsonify

APP_TITLE = "Wa Flora POS & Inventory" DB_PATH = os.environ.get("WA_FLORA_DB", os.path.join(os.path.dirname(file), "wa_flora.db"))

app = Flask(name) app.secret_key = os.environ.get("WA_FLORA_SECRET", "dev-secret-change-me")

-----------------------------

DB Helpers

-----------------------------

def get_db(): if 'db' not in g: g.db = sqlite3.connect(DB_PATH) g.db.row_factory = sqlite3.Row return g.db

@app.teardown_appcontext def close_db(exception=None): db = g.pop('db', None) if db is not None: db.close()

def d(qty): return Decimal(str(qty)).quantize(Decimal('0.0001'))

def init_db(): db = get_db() cur = db.cursor()

cur.executescript(
    """
    PRAGMA foreign_keys = ON;

    CREATE TABLE IF NOT EXISTS Users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        role TEXT NOT NULL CHECK(role IN ('admin','cashier'))
    );

    CREATE TABLE IF NOT EXISTS Suppliers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        phone TEXT,
        notes TEXT
    );

    CREATE TABLE IF NOT EXISTS Products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        category TEXT,
        base_unit TEXT NOT NULL,
        supplier_id INTEGER,
        barcode TEXT,
        FOREIGN KEY (supplier_id) REFERENCES Suppliers(id)
    );

    CREATE TABLE IF NOT EXISTS ProductVariants (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_id INTEGER NOT NULL,
        variant_name TEXT NOT NULL, -- e.g., "1 kg", "500 g", "25 kg"
        unit_multiplier REAL NOT NULL, -- e.g., 1.0 for 1kg, 0.5 for 500g relative to base
        retail_price REAL NOT NULL DEFAULT 0,
        wholesale_price REAL DEFAULT NULL,
        barcode TEXT,
        UNIQUE(product_id, variant_name),
        FOREIGN KEY (product_id) REFERENCES Products(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS Inventory (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        variant_id INTEGER NOT NULL UNIQUE,
        stock_qty REAL NOT NULL DEFAULT 0, -- in variant units
        avg_cost REAL NOT NULL DEFAULT 0, -- moving-average cost per variant unit
        min_stock REAL NOT NULL DEFAULT 0, -- for low-stock alerts
        FOREIGN KEY (variant_id) REFERENCES ProductVariants(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS StockLedger (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        variant_id INTEGER NOT NULL,
        txn_type TEXT NOT NULL CHECK(txn_type IN ('RECEIVE','ADJUST','SALE')),
        qty REAL NOT NULL,
        unit_cost REAL NOT NULL, -- purchase cost for RECEIVE, avg_cost at sale time for SALE
        total_cost REAL NOT NULL,
        supplier_id INTEGER,
        notes TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY (variant_id) REFERENCES ProductVariants(id),
        FOREIGN KEY (supplier_id) REFERENCES Suppliers(id)
    );

    CREATE TABLE IF NOT EXISTS Customers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        phone TEXT,
        address TEXT
    );

    CREATE TABLE IF NOT EXISTS Sales (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        receipt_no TEXT UNIQUE NOT NULL,
        sale_datetime TEXT NOT NULL,
        cashier TEXT NOT NULL,
        payment_method TEXT NOT NULL CHECK(payment_method IN ('CASH','MPESA','CREDIT')),
        subtotal REAL NOT NULL,
        discount REAL NOT NULL DEFAULT 0,
        total REAL NOT NULL,
        cash_received REAL,
        change_due REAL,
        customer_id INTEGER,
        FOREIGN KEY (customer_id) REFERENCES Customers(id)
    );

    CREATE TABLE IF NOT EXISTS SaleItems (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sale_id INTEGER NOT NULL,
        variant_id INTEGER NOT NULL,
        qty REAL NOT NULL,
        unit_price REAL NOT NULL,
        line_total REAL NOT NULL,
        cogs REAL NOT NULL, -- qty * avg_cost at time of sale
        FOREIGN KEY (sale_id) REFERENCES Sales(id) ON DELETE CASCADE,
        FOREIGN KEY (variant_id) REFERENCES ProductVariants(id)
    );

    CREATE TABLE IF NOT EXISTS CreditLedger (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sale_id INTEGER NOT NULL,
        customer_id INTEGER NOT NULL,
        original_amount REAL NOT NULL,
        outstanding REAL NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('OUTSTANDING','PAID')),
        created_at TEXT NOT NULL,
        FOREIGN KEY (sale_id) REFERENCES Sales(id) ON DELETE CASCADE,
        FOREIGN KEY (customer_id) REFERENCES Customers(id)
    );

    CREATE TABLE IF NOT EXISTS CreditPayments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        credit_id INTEGER NOT NULL,
        amount REAL NOT NULL,
        method TEXT NOT NULL CHECK(method IN ('CASH','MPESA')),
        paid_at TEXT NOT NULL,
        FOREIGN KEY (credit_id) REFERENCES CreditLedger(id) ON DELETE CASCADE
    );
    """
)

# Seed a default admin/cashier and a default supplier if empty
cur.execute("SELECT COUNT(*) AS c FROM Users")
if cur.fetchone()["c"] == 0:
    cur.execute("INSERT INTO Users (username, role) VALUES (?,?)", ("admin","admin"))
    cur.execute("INSERT INTO Users (username, role) VALUES (?,?)", ("cashier","cashier"))

cur.execute("SELECT COUNT(*) AS c FROM Suppliers")
if cur.fetchone()["c"] == 0:
    cur.execute("INSERT INTO Suppliers (name, phone) VALUES (?,?)", ("Default Supplier",""))

db.commit()

-----------------------------

Utility functions

-----------------------------

def now_ts(): return datetime.now().strftime('%Y-%m-%d %H:%M:%S')

def gen_receipt_no(db: sqlite3.Connection) -> str: dt = datetime.now().strftime('%Y%m%d') cur = db.execute("SELECT COUNT(*)+1 AS seq FROM Sales WHERE date(sale_datetime) = date('now')") seq = cur.fetchone()["seq"] return f"WF-{dt}-{seq:04d}"

def get_variant(db, variant_id: int) -> sqlite3.Row: cur = db.execute( """ SELECT v.*, p.name as product_name, p.base_unit, p.category FROM ProductVariants v JOIN Products p ON p.id = v.product_id WHERE v.id = ? """, (variant_id,) ) return cur.fetchone()

def ensure_inventory_row(db, variant_id: int): cur = db.execute("SELECT id FROM Inventory WHERE variant_id = ?", (variant_id,)) if not cur.fetchone(): db.execute("INSERT INTO Inventory (variant_id, stock_qty, avg_cost, min_stock) VALUES (?,?,?,?)", (variant_id, 0, 0, 0)) db.commit()

def update_moving_average_on_receive(db, variant_id: int, qty: Decimal, unit_cost: Decimal, supplier_id: Optional[int], notes: str = ""): ensure_inventory_row(db, variant_id) inv = db.execute("SELECT stock_qty, avg_cost FROM Inventory WHERE variant_id = ?", (variant_id,)).fetchone() old_qty = d(inv["stock_qty"]) if inv else d(0) old_cost = d(inv["avg_cost"]) if inv else d(0)

new_total_cost = (old_qty * old_cost) + (qty * unit_cost)
new_qty = old_qty + qty
new_avg = (new_total_cost / new_qty).quantize(Decimal('0.0001')) if new_qty > 0 else d(0)

db.execute("UPDATE Inventory SET stock_qty = ?, avg_cost = ? WHERE variant_id = ?",
           (float(new_qty), float(new_avg), variant_id))

db.execute(
    "INSERT INTO StockLedger (variant_id, txn_type, qty, unit_cost, total_cost, supplier_id, notes, created_at)\n         VALUES (?,?,?,?,?,?,?,?)",
    (variant_id, 'RECEIVE', float(qty), float(unit_cost), float(qty*unit_cost), supplier_id, notes, now_ts())
)

def deduct_stock_on_sale(db, variant_id: int, qty: Decimal) -> Decimal: """Deduct from inventory and record SALE in StockLedger using current avg_cost. Returns the COGS (qty * avg_cost_at_sale).""" ensure_inventory_row(db, variant_id) inv = db.execute("SELECT stock_qty, avg_cost FROM Inventory WHERE variant_id = ?", (variant_id,)).fetchone() stock_qty = d(inv["stock_qty"]) if inv else d(0) avg_cost = d(inv["avg_cost"]) if inv else d(0) if qty > stock_qty: raise ValueError("Insufficient stock") new_qty = stock_qty - qty db.execute("UPDATE Inventory SET stock_qty = ? WHERE variant_id = ?", (float(new_qty), variant_id)) cogs = (qty * avg_cost).quantize(Decimal('0.0001')) db.execute( "INSERT INTO StockLedger (variant_id, txn_type, qty, unit_cost, total_cost, supplier_id, notes, created_at)\n         VALUES (?,?,?,?,?,?,?,?)", (variant_id, 'SALE', float(-qty), float(avg_cost), float(-cogs), None, 'Sale', now_ts()) ) return cogs

-----------------------------

Templates (Jinja) — minimal UI with Bootstrap

-----------------------------

BASE_HTML = """ <!doctype html>

<html lang=\"en\">
<head>
  <meta charset=\"utf-8\">
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
  <title>{{ title or 'Wa Flora POS' }}</title>
  <link href=\"https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css\" rel=\"stylesheet\">
  <style>
    body{ padding-bottom: 4rem; }
    .wf-card{ border-radius: 1rem; box-shadow: 0 6px 18px rgba(0,0,0,0.06); }
    .table-sm td, .table-sm th{ padding: .35rem; }
    .sticky-actions{ position: sticky; bottom: 0; background: #fff; padding: .75rem; box-shadow: 0 -4px 12px rgba(0,0,0,.05); }
    @media print{ .no-print{ display: none !important; } .print-area{ margin:0; } }
  </style>
</head>
<body>
<nav class=\"navbar navbar-expand-lg navbar-dark bg-dark mb-4\">
  <div class=\"container-fluid\">
    <a class=\"navbar-brand\" href=\"{{ url_for('dashboard') }}\">Wa Flora POS</a>
    <button class=\"navbar-toggler\" type=\"button\" data-bs-toggle=\"collapse\" data-bs-target=\"#nav\">\n      <span class=\"navbar-toggler-icon\"></span>\n    </button>
    <div class=\"collapse navbar-collapse\" id=\"nav\">
      <ul class=\"navbar-nav me-auto\">
        <li class=\"nav-item\"><a class=\"nav-link\" href=\"{{ url_for('products') }}\">Products</a></li>
        <li class=\"nav-item\"><a class=\"nav-link\" href=\"{{ url_for('receive_stock') }}\">Receive Stock</a></li>
        <li class=\"nav-item\"><a class=\"nav-link\" href=\"{{ url_for('pos') }}\">POS</a></li>
        <li class=\"nav-item\"><a class=\"nav-link\" href=\"{{ url_for('credit_payments') }}\">Credit</a></li>
        <li class=\"nav-item dropdown\">
          <a class=\"nav-link dropdown-toggle\" role=\"button\" data-bs-toggle=\"dropdown\">Reports</a>
          <ul class=\"dropdown-menu\">
            <li><a class=\"dropdown-item\" href=\"{{ url_for('report_sales') }}\">Sales</a></li>
            <li><a class=\"dropdown-item\" href=\"{{ url_for('report_inventory') }}\">Inventory</a></li>
            <li><a class=\"dropdown-item\" href=\"{{ url_for('report_credit') }}\">Credit</a></li>
            <li><a class=\"dropdown-item\" href=\"{{ url_for('report_pnl') }}\">Profit & Loss</a></li>
          </ul>
        </li>
      </ul>
    </div>
  </div>
</nav>
<div class=\"container\">
  {% with messages = get_flashed_messages() %}
    {% if messages %}
      <div class=\"alert alert-info\">{{ messages|join(', ') }}</div>
    {% endif %}
  {% endwith %}
  {% block content %}{% endblock %}
</div>
<script src=\"https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js\"></script>
<script>
function formatMoney(n){ return new Intl.NumberFormat('en-KE',{style:'currency', currency:'KES'}).format(n); }
</script>
</body>
</html>
"""DASH_HTML = """ {% extends 'base.html' %} {% block content %}

<div class=\"wf-card p-4\">
  <h3 class=\"mb-3\">Dashboard</h3>
  <div class=\"row g-3\">
    <div class=\"col-md-3\"><div class=\"card p-3\"><div>Today Sales</div><div class=\"fs-4\">KES {{ '%.2f'|format(kpis.today_sales) }}</div></div></div>
    <div class=\"col-md-3\"><div class=\"card p-3\"><div>Today Gross Profit</div><div class=\"fs-4\">KES {{ '%.2f'|format(kpis.today_gp) }}</div></div></div>
    <div class=\"col-md-3\"><div class=\"card p-3\"><div>Stock Value (at cost)</div><div class=\"fs-4\">KES {{ '%.2f'|format(kpis.stock_value) }}</div></div></div>
    <div class=\"col-md-3\"><div class=\"card p-3\"><div>Credit Outstanding</div><div class=\"fs-4\">KES {{ '%.2f'|format(kpis.credit_outstanding) }}</div></div></div>
  </div>
</div>
{% endblock %}
"""PRODUCTS_HTML = """ {% extends 'base.html' %} {% block content %}

<div class=\"wf-card p-4\">
  <div class=\"d-flex justify-content-between align-items-center mb-3\">
    <h3>Products</h3>
    <button class=\"btn btn-primary\" data-bs-toggle=\"modal\" data-bs-target=\"#newProduct\">Add New Product</button>
  </div>
  <input class=\"form-control mb-3\" placeholder=\"Search...\" oninput=\"const v=this.value.toLowerCase();document.querySelectorAll('.prod-row').forEach(r=>r.style.display=r.dataset.q.includes(v)?'':'none');\">
  <table class=\"table table-striped table-sm\">
    <thead><tr><th>Product</th><th>Category</th><th>Base Unit</th><th>Variants</th></tr></thead>
    <tbody>
      {% for p in products %}
        <tr class=\"prod-row\" data-q=\"{{ (p['name'] ~ ' ' ~ (p['category'] or ''))|lower }}\">
          <td>{{ p['name'] }}</td>
          <td>{{ p['category'] or '' }}</td>
          <td>{{ p['base_unit'] }}</td>
          <td>
            <ul class=\"mb-0\">
              {% for v in variants[p['id']] %}
                <li>
                  {{ v['variant_name'] }} — Retail: KES {{ '%.2f'|format(v['retail_price']) }}{% if v['wholesale_price'] %} | Wholesale: KES {{ '%.2f'|format(v['wholesale_price']) }}{% endif %}
                  <small class=\"text-muted\"> | Stock: {{ inventory.get(v['id'], {}).get('stock_qty', 0) }}</small>
                </li>
              {% endfor %}
            </ul>
          </td>
        </tr>
      {% endfor %}
    </tbody>
  </table>
</div><!-- New Product Modal --><div class=\"modal fade\" id=\"newProduct\" tabindex=\"-1\">
  <div class=\"modal-dialog modal-lg\">
    <div class=\"modal-content\">
      <form method=\"post\" action=\"{{ url_for('add_product') }}\">
        <div class=\"modal-header\"><h5 class=\"modal-title\">Add New Product</h5><button type=\"button\" class=\"btn-close\" data-bs-dismiss=\"modal\"></button></div>
        <div class=\"modal-body\">
          <div class=\"row g-2\">
            <div class=\"col-md-4\"><label class=\"form-label\">Product Name</label><input name=\"name\" class=\"form-control\" required></div>
            <div class=\"col-md-3\"><label class=\"form-label\">Category</label><input name=\"category\" class=\"form-control\"></div>
            <div class=\"col-md-2\"><label class=\"form-label\">Base Unit</label><input name=\"base_unit\" class=\"form-control\" placeholder=\"kg, l, pc\" required></div>
            <div class=\"col-md-3\"><label class=\"form-label\">Default Supplier</label><select name=\"supplier_id\" class=\"form-select\">{% for s in suppliers %}<option value=\"{{s['id']}}\">{{s['name']}}</option>{% endfor %}</select></div>
          </div>
          <hr>
          <h6>Variants</h6>
          <p class=\"text-muted\">Add one per line: <code>Variant Name | unit_multiplier | retail_price | wholesale_price (optional)</code><br>Example: <code>1 kg | 1 | 210 | 200</code></p>
          <textarea name=\"variants\" class=\"form-control\" rows=\"5\" placeholder=\"1 kg | 1 | 210 | 200\n500 g | 0.5 | 110\"></textarea>
        </div>
        <div class=\"modal-footer\"><button class=\"btn btn-secondary\" data-bs-dismiss=\"modal\">Cancel</button><button class=\"btn btn-primary\" type=\"submit\">Save</button></div>
      </form>
    </div>
  </div>
</div>
{% endblock %}
"""RECEIVE_HTML = """ {% extends 'base.html' %} {% block content %}

<div class=\"wf-card p-4\">
  <h3>Receive Stock</h3>
  <form method=\"post\" action=\"{{ url_for('receive_stock') }}\" class=\"row g-2\">
    <div class=\"col-md-4\">
      <label class=\"form-label\">Variant</label>
      <select name=\"variant_id\" class=\"form-select\" required>
        {% for v in variants %}
          <option value=\"{{ v['id'] }}\">{{ v['product_name'] }} — {{ v['variant_name'] }}</option>
        {% endfor %}
      </select>
    </div>
    <div class=\"col-md-2\"><label class=\"form-label\">Quantity</label><input step=\"0.0001\" type=\"number\" name=\"qty\" class=\"form-control\" required></div>
    <div class=\"col-md-2\"><label class=\"form-label\">Purchase Price / unit</label><input step=\"0.0001\" type=\"number\" name=\"unit_cost\" class=\"form-control\" required></div>
    <div class=\"col-md-3\"><label class=\"form-label\">Supplier</label>
      <select name=\"supplier_id\" class=\"form-select\">{% for s in suppliers %}<option value=\"{{s['id']}}\">{{s['name']}}</option>{% endfor %}</select>
    </div>
    <div class=\"col-md-12\"><label class=\"form-label\">Notes</label><input name=\"notes\" class=\"form-control\"></div>
    <div class=\"col-md-12\"><button class=\"btn btn-primary\" type=\"submit\">Receive</button></div>
  </form>  <hr>
  <h5>Recent Stock Movements</h5>
  <table class=\"table table-sm\">
    <thead><tr><th>Date</th><th>Variant</th><th>Type</th><th>Qty</th><th>Unit Cost</th><th>Total</th><th>Supplier</th><th>Notes</th></tr></thead>
    <tbody>
      {% for lg in ledger %}
        <tr>
          <td>{{ lg['created_at'] }}</td>
          <td>{{ lg['product_name'] }} — {{ lg['variant_name'] }}</td>
          <td>{{ lg['txn_type'] }}</td>
          <td>{{ lg['qty'] }}</td>
          <td>{{ '%.2f'|format(lg['unit_cost']) }}</td>
          <td>{{ '%.2f'|format(lg['total_cost']) }}</td>
          <td>{{ lg['supplier_name'] or '' }}</td>
          <td>{{ lg['notes'] or '' }}</td>
        </tr>
      {% endfor %}
    </tbody>
  </table>
</div>
{% endblock %}
"""POS_HTML = """ {% extends 'base.html' %} {% block content %}

<div class=\"wf-card p-4\">
  <h3>Point of Sale</h3>
  <form method=\"post\" action=\"{{ url_for('pos_add_item') }}\" class=\"row g-2 no-print\">
    <div class=\"col-md-6\">
      <input name=\"query\" class=\"form-control\" placeholder=\"Search by name or barcode...\" autofocus>
    </div>
    <div class=\"col-md-3\">
      <select name=\"variant_id\" class=\"form-select\">
        <option value=\"\">or select variant...</option>
        {% for v in variants %}
          <option value=\"{{v['id']}}\">{{ v['product_name'] }} — {{ v['variant_name'] }} (KES {{ '%.2f'|format(v['retail_price']) }})</option>
        {% endfor %}
      </select>
    </div>
    <div class=\"col-md-2\"><input type=\"number\" step=\"0.0001\" name=\"qty\" class=\"form-control\" placeholder=\"Qty\" value=\"1\"></div>
    <div class=\"col-md-1\"><button class=\"btn btn-primary w-100\">Add</button></div>
  </form>  <form method=\"post\" action=\"{{ url_for('pos_checkout') }}\" id=\"checkoutForm\">
  <div class=\"table-responsive\">
    <table class=\"table table-sm align-middle mt-3\">
      <thead><tr><th>Item</th><th class=\"text-end\">Price</th><th class=\"text-end\">Qty</th><th class=\"text-end\">Total</th><th class=\"no-print\"></th></tr></thead>
      <tbody>
        {% for line in cart %}
          <tr>
            <td>{{ line['product_name'] }} — {{ line['variant_name'] }}</td>
            <td class=\"text-end\">{{ '%.2f'|format(line['unit_price']) }}</td>
            <td class=\"text-end\">{{ line['qty'] }}</td>
            <td class=\"text-end\">{{ '%.2f'|format(line['qty']*line['unit_price']) }}</td>
            <td class=\"no-print\"><a href=\"{{ url_for('pos_remove_item', idx=loop.index0) }}\" class=\"btn btn-sm btn-outline-danger\">×</a></td>
          </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
  <div class=\"row g-2 align-items-end\">
    <div class=\"col-md-3\"><label class=\"form-label\">Discount (KES)</label><input name=\"discount\" type=\"number\" step=\"0.01\" class=\"form-control\" value=\"{{ discount or 0 }}\"></div>
    <div class=\"col-md-3\"><label class=\"form-label\">Customer (for credit)</label><select name=\"customer_id\" class=\"form-select\"><option value>—</option>{% for c in customers %}<option value=\"{{c['id']}}\">{{c['name']}}{% if c['phone'] %} ({{c['phone']}}){% endif %}</option>{% endfor %}</select></div>
    <div class=\"col-md-3\"><label class=\"form-label\">Payment Method</label><select name=\"payment_method\" class=\"form-select\" required><option>CASH</option><option>MPESA</option><option>CREDIT</option></select></div>
    <div class=\"col-md-3\"><label class=\"form-label\">Cash Received (if CASH)</label><input name=\"cash_received\" type=\"number\" step=\"0.01\" class=\"form-control\"></div>
  </div>
  <div class=\"sticky-actions mt-3 no-print\">
    <div class=\"d-flex justify-content-between\">
      <div>
        <div>Subtotal: <strong>KES {{ '%.2f'|format(subtotal) }}</strong></div>
        <div>Discount: <strong>KES {{ '%.2f'|format(discount or 0) }}</strong></div>
        <div>Total: <strong>KES {{ '%.2f'|format(total) }}</strong></div>
      </div>
      <div>
        <button class=\"btn btn-success btn-lg\">Finalize Sale</button>
      </div>
    </div>
  </div>
  </form>{% if receipt %} <hr> <div class="print-area"> <h5>Receipt #{{ receipt['receipt_no'] }}</h5> <div>Date: {{ receipt['sale_datetime'] }} | Cashier: {{ receipt['cashier'] }}</div> <table class="table table-sm mt-2"> <thead><tr><th>Item</th><th class="text-end">Qty</th><th class="text-end">Price</th><th class="text-end">Total</th></tr></thead> <tbody> {% for it in receipt_items %} <tr> <td>{{ it['product_name'] }} — {{ it['variant_name'] }}</td> <td class="text-end">{{ it['qty'] }}</td> <td class="text-end">{{ '%.2f'|format(it['unit_price']) }}</td> <td class="text-end">{{ '%.2f'|format(it['line_total']) }}</td> </tr> {% endfor %} </tbody> </table> <div>Subtotal: KES {{ '%.2f'|format(receipt['subtotal']) }}</div> <div>Discount: KES {{ '%.2f'|format(receipt['discount']) }}</div> <h5>Total: KES {{ '%.2f'|format(receipt['total']) }}</h5> <div>Payment: {{ receipt['payment_method'] }}{% if receipt['payment_method']=='CASH' %} | Cash Received: KES {{ '%.2f'|format(receipt['cash_received'] or 0) }} | Change: KES {{ '%.2f'|format(receipt['change_due'] or 0) }}{% endif %}</div> {% if receipt['payment_method']=='CREDIT' %} <div class="text-danger"><strong>Payment Status: Credit</strong> | <strong>Balance Due: KES {{ '%.2f'|format(receipt['total']) }}</strong></div> {% endif %} </div> <button class="btn btn-outline-secondary no-print mt-2" onclick="window.print()">Print Receipt</button> {% endif %}

</div>
{% endblock %}
"""CREDIT_HTML = """ {% extends 'base.html' %} {% block content %}

<div class=\"wf-card p-4\">
  <div class=\"d-flex justify-content-between align-items-center\">
    <h3>Credit Payments</h3>
    <button class=\"btn btn-primary\" data-bs-toggle=\"modal\" data-bs-target=\"#newCustomer\">New Customer</button>
  </div>  <table class=\"table table-sm mt-3\">
    <thead><tr><th>Customer</th><th>Sale</th><th>Date</th><th>Original</th><th>Outstanding</th><th>Status</th><th></th></tr></thead>
    <tbody>
      {% for c in credits %}
        <tr>
          <td>{{ c['customer_name'] }}</td>
          <td>{{ c['receipt_no'] }}</td>
          <td>{{ c['created_at'] }}</td>
          <td>{{ '%.2f'|format(c['original_amount']) }}</td>
          <td>{{ '%.2f'|format(c['outstanding']) }}</td>
          <td>{{ c['status'] }}</td>
          <td>
            {% if c['status']=='OUTSTANDING' %}
            <form method=\"post\" action=\"{{ url_for('pay_credit', credit_id=c['id']) }}\" class=\"d-flex gap-2\">
              <input name=\"amount\" type=\"number\" step=\"0.01\" class=\"form-control\" placeholder=\"Amount\" required>
              <select name=\"method\" class=\"form-select\"><option>CASH</option><option>MPESA</option></select>
              <button class=\"btn btn-success\">Record</button>
            </form>
            {% endif %}
          </td>
        </tr>
      {% endfor %}
    </tbody>
  </table>
</div><!-- New Customer Modal --><div class=\"modal fade\" id=\"newCustomer\" tabindex=\"-1\">
  <div class=\"modal-dialog\">
    <div class=\"modal-content\">
      <form method=\"post\" action=\"{{ url_for('add_customer') }}\">
        <div class=\"modal-header\"><h5 class=\"modal-title\">Add Customer</h5><button type=\"button\" class=\"btn-close\" data-bs-dismiss=\"modal\"></button></div>
        <div class=\"modal-body\">
          <input name=\"name\" class=\"form-control mb-2\" placeholder=\"Name\" required>
          <input name=\"phone\" class=\"form-control mb-2\" placeholder=\"Phone\">
          <input name=\"address\" class=\"form-control mb-2\" placeholder=\"Address\">
        </div>
        <div class=\"modal-footer\"><button class=\"btn btn-secondary\" data-bs-dismiss=\"modal\">Cancel</button><button class=\"btn btn-primary\" type=\"submit\">Save</button></div>
      </form>
    </div>
  </div>
</div>
{% endblock %}
"""REPORT_SALES_HTML = """ {% extends 'base.html' %} {% block content %}

<div class=\"wf-card p-4\">
  <h3>Sales Report</h3>
  <form class=\"row g-2 no-print\" method=\"get\">
    <div class=\"col-md-3\"><label class=\"form-label\">From</label><input type=\"date\" name=\"start\" value=\"{{start}}\" class=\"form-control\"></div>
    <div class=\"col-md-3\"><label class=\"form-label\">To</label><input type=\"date\" name=\"end\" value=\"{{end}}\" class=\"form-control\"></div>
    <div class=\"col-md-3\"><label class=\"form-label\">Payment</label><select name=\"pm\" class=\"form-select\"><option value=\"\">All</option><option{% if pm=='CASH' %} selected{% endif %}>CASH</option><option{% if pm=='MPESA' %} selected{% endif %}>MPESA</option><option{% if pm=='CREDIT' %} selected{% endif %}>CREDIT</option></select></div>
    <div class=\"col-md-3\"><label class=\"form-label\">Cashier</label><input name=\"cashier\" value=\"{{ cashier or '' }}\" class=\"form-control\" placeholder=\"admin/cashier\"></div>
    <div class=\"col-md-12\"><button class=\"btn btn-primary\">Filter</button></div>
  </form>  <h6 class=\"mt-3\">Summary</h6>
  <div>Total Sales: KES {{ '%.2f'|format(summary.total) }} | Gross Profit: KES {{ '%.2f'|format(summary.gp) }}</div>  <h6 class=\"mt-3\">By Item</h6>
  <table class=\"table table-sm\">
    <thead><tr><th>Item</th><th class=\"text-end\">Qty</th><th class=\"text-end\">Sales</th><th class=\"text-end\">COGS</th><th class=\"text-end\">GP</th></tr></thead>
    <tbody>
      {% for r in by_item %}
      <tr><td>{{ r['product_name'] }} — {{ r['variant_name'] }}</td><td class=\"text-end\">{{ '%.4f'|format(r['qty']) }}</td><td class=\"text-end\">{{ '%.2f'|format(r['sales']) }}</td><td class=\"text-end\">{{ '%.2f'|format(r['cogs']) }}</td><td class=\"text-end\">{{ '%.2f'|format(r['sales']-r['cogs']) }}</td></tr>
      {% endfor %}
    </tbody>
  </table>
</div>
{% endblock %}
"""REPORT_INVENTORY_HTML = """ {% extends 'base.html' %} {% block content %}

<div class=\"wf-card p-4\">
  <h3>Inventory Report</h3>
  <table class=\"table table-sm\">
    <thead><tr><th>Item</th><th class=\"text-end\">Stock</th><th class=\"text-end\">Avg Cost</th><th class=\"text-end\">Stock Value</th><th>Alert</th></tr></thead>
    <tbody>
      {% for r in rows %}
        <tr class=\"{% if r['stock_qty'] <= r['min_stock'] %}table-warning{% endif %}\">
          <td>{{ r['product_name'] }} — {{ r['variant_name'] }}</td>
          <td class=\"text-end\">{{ '%.4f'|format(r['stock_qty']) }}</td>
          <td class=\"text-end\">{{ '%.4f'|format(r['avg_cost']) }}</td>
          <td class=\"text-end\">{{ '%.2f'|format(r['stock_qty']*r['avg_cost']) }}</td>
          <td>{% if r['stock_qty'] <= r['min_stock'] %}Low Stock{% endif %}</td>
        </tr>
      {% endfor %}
    </tbody>
  </table>  <h5 class=\"mt-4\">Stock Movements (last 100)</h5>
  <table class=\"table table-sm\">
    <thead><tr><th>Date</th><th>Item</th><th>Type</th><th class=\"text-end\">Qty</th><th class=\"text-end\">Unit Cost</th><th class=\"text-end\">Total</th><th>Supplier</th></tr></thead>
    <tbody>
      {% for lg in ledger %}
        <tr>
          <td>{{ lg['created_at'] }}</td>
          <td>{{ lg['product_name'] }} — {{ lg['variant_name'] }}</td>
          <td>{{ lg['txn_type'] }}</td>
          <td class=\"text-end\">{{ lg['qty'] }}</td>
          <td class=\"text-end\">{{ '%.2f'|format(lg['unit_cost']) }}</td>
          <td class=\"text-end\">{{ '%.2f'|format(lg['total_cost']) }}</td>
          <td>{{ lg['supplier_name'] or '' }}</td>
        </tr>
      {% endfor %}
    </tbody>
  </table>
</div>
{% endblock %}
"""REPORT_CREDIT_HTML = """ {% extends 'base.html' %} {% block content %}

<div class=\"wf-card p-4\">
  <h3>Credit Report</h3>
  <div>Total Outstanding: <strong>KES {{ '%.2f'|format(total_outstanding) }}</strong></div>
  <h6 class=\"mt-3\">Aging</h6>
  <ul>
    <li>0-30 days: KES {{ '%.2f'|format(aging['0-30']) }}</li>
    <li>31-60 days: KES {{ '%.2f'|format(aging['31-60']) }}</li>
    <li>61-90 days: KES {{ '%.2f'|format(aging['61-90']) }}</li>
    <li>90+ days: KES {{ '%.2f'|format(aging['90+']) }}</li>
  </ul>
  <table class=\"table table-sm\">
    <thead><tr><th>Customer</th><th>Receipt</th><th>Date</th><th class=\"text-end\">Outstanding</th></tr></thead>
    <tbody>
      {% for r in rows %}
        <tr><td>{{ r['customer_name'] }}</td><td>{{ r['receipt_no'] }}</td><td>{{ r['created_at'] }}</td><td class=\"text-end\">{{ '%.2f'|format(r['outstanding']) }}</td></tr>
      {% endfor %}
    </tbody>
  </table>
</div>
{% endblock %}
"""REPORT_PNL_HTML = """ {% extends 'base.html' %} {% block content %}

<div class=\"wf-card p-4\">
  <h3>Profit & Loss (Gross)</h3>
  <form class=\"row g-2 no-print\" method=\"get\">
    <div class=\"col-md-4\"><label class=\"form-label\">From</label><input type=\"date\" name=\"start\" value=\"{{start}}\" class=\"form-control\"></div>
    <div class=\"col-md-4\"><label class=\"form-label\">To</label><input type=\"date\" name=\"end\" value=\"{{end}}\" class=\"form-control\"></div>
    <div class=\"col-md-4\"><button class=\"btn btn-primary\">Run</button></div>
  </form>
  <div class=\"mt-3\">
    <div>Sales: KES {{ '%.2f'|format(total_sales) }}</div>
    <div>COGS: KES {{ '%.2f'|format(total_cogs) }}</div>
    <h5>Gross Profit: KES {{ '%.2f'|format(total_sales - total_cogs) }}</h5>
  </div>
</div>
{% endblock %}
"""-----------------------------

App routes

-----------------------------

@app.before_request def _before(): init_db()

@app.route('/') def dashboard(): db = get_db() # today kpis today = date.today().strftime('%Y-%m-%d') k1 = db.execute("SELECT COALESCE(SUM(total),0) AS s FROM Sales WHERE date(sale_datetime)=?", (today,)).fetchone()["s"] k2 = db.execute("SELECT COALESCE(SUM(line_total - cogs),0) AS gp FROM SaleItems si JOIN Sales s ON s.id=si.sale_id WHERE date(s.sale_datetime)=?", (today,)).fetchone()["gp"] k3 = db.execute("SELECT COALESCE(SUM(stock_qty*avg_cost),0) AS v FROM Inventory").fetchone()["v"] k4 = db.execute("SELECT COALESCE(SUM(outstanding),0) AS o FROM CreditLedger WHERE status='OUTSTANDING'").fetchone()["o"] return render_template_string(DASH_HTML, title=APP_TITLE, kpis={"today_sales":k1, "today_gp":k2, "stock_value":k3, "credit_outstanding":k4})

---------- Products ----------

@app.route('/products') def products(): db = get_db() ps = db.execute("SELECT * FROM Products ORDER BY name").fetchall() vs = db.execute("SELECT v.*, p.name as product_name FROM ProductVariants v JOIN Products p ON p.id=v.product_id ORDER BY p.name, v.id").fetchall() inv_rows = db.execute("SELECT * FROM Inventory").fetchall() suppliers = db.execute("SELECT * FROM Suppliers ORDER BY name").fetchall() variants_by_p = {} inventory = {r['variant_id']:{'stock_qty':r['stock_qty'],'avg_cost':r['avg_cost'],'min_stock':r['min_stock']} for r in inv_rows} for v in vs: variants_by_p.setdefault(v['product_id'], []).append(v) return render_template_string(PRODUCTS_HTML, products=ps, variants=variants_by_p, inventory=inventory, suppliers=suppliers)

@app.route('/products/new', methods=['POST']) def add_product(): db = get_db() name = request.form['name'].strip() category = request.form.get('category') base_unit = request.form['base_unit'] supplier_id = int(request.form.get('supplier_id') or 1) cur = db.execute("INSERT INTO Products (name, category, base_unit, supplier_id) VALUES (?,?,?,?)", (name, category, base_unit, supplier_id)) pid = cur.lastrowid # parse variants variants_text = request.form.get('variants','').strip() if variants_text: for line in variants_text.splitlines(): if not line.strip(): continue parts = [p.strip() for p in line.split('|')] if len(parts) < 3: continue vname = parts[0] try: mult = float(parts[1]) retail = float(parts[2]) wholesale = float(parts[3]) if len(parts) >= 4 and parts[3] != '' else None except Exception: continue db.execute("INSERT INTO ProductVariants (product_id, variant_name, unit_multiplier, retail_price, wholesale_price) VALUES (?,?,?,?,?)", (pid, vname, mult, retail, wholesale)) db.commit() flash("Product and variants saved.") return redirect(url_for('products'))

---------- Receive Stock ----------

@app.route('/inventory/receive', methods=['GET','POST']) def receive_stock(): db = get_db() if request.method == 'POST': variant_id = int(request.form['variant_id']) qty = d(request.form['qty']) unit_cost = d(request.form['unit_cost']) supplier_id = int(request.form.get('supplier_id') or 1) notes = request.form.get('notes','') update_moving_average_on_receive(db, variant_id, qty, unit_cost, supplier_id, notes) db.commit() flash("Stock received.") return redirect(url_for('receive_stock'))

variants = db.execute("SELECT v.*, p.name as product_name FROM ProductVariants v JOIN Products p ON p.id=v.product_id ORDER BY p.name, v.id").fetchall()
suppliers = db.execute("SELECT * FROM Suppliers ORDER BY name").fetchall()
ledger = db.execute(
    """SELECT sl.*, v.variant_name, p.name as product_name, s.name as supplier_name
        FROM StockLedger sl
        JOIN ProductVariants v ON v.id=sl.variant_id
        JOIN Products p ON p.id=v.product_id
        LEFT JOIN Suppliers s ON s.id=sl.supplier_id
        ORDER BY sl.id DESC LIMIT 50
    """).fetchall()
return render_template_string(RECEIVE_HTML, variants=variants, suppliers=suppliers, ledger=ledger)

---------- POS ----------

from flask import session app.config['SESSION_TYPE'] = 'filesystem'

@app.route('/pos') def pos(): db = get_db() cart = session.get('cart', []) discount = session.get('discount', 0.0) subtotal = sum([float(it['qty'])float(it['unit_price']) for it in cart]) total = max(0.0, subtotal - float(discount)) variants = db.execute("SELECT v., p.name as product_name FROM ProductVariants v JOIN Products p ON p.id=v.product_id ORDER BY p.name, v.id").fetchall() customers = db.execute("SELECT * FROM Customers ORDER BY name").fetchall() receipt = session.pop('last_receipt', None) receipt_items = session.pop('last_receipt_items', []) return render_template_string(POS_HTML, variants=variants, customers=customers, cart=cart, discount=discount, subtotal=subtotal, total=total, receipt=receipt, receipt_items=receipt_items)

@app.route('/pos/add', methods=['POST']) def pos_add_item(): db = get_db() q = (request.form.get('query') or '').strip() variant_id = request.form.get('variant_id') qty = d(request.form.get('qty') or 1) if not variant_id and q: # try search by barcode or name row = db.execute("SELECT v., p.name as product_name FROM ProductVariants v JOIN Products p ON p.id=v.product_id WHERE v.barcode=? OR p.name||' '||v.variant_name LIKE ? LIMIT 1", (q, f"%{q}%")).fetchone() if not row: flash("Item not found") return redirect(url_for('pos')) else: row = db.execute("SELECT v., p.name as product_name FROM ProductVariants v JOIN Products p ON p.id=v.product_id WHERE v.id=?", (variant_id,)).fetchone() if not row: flash("Variant not found") return redirect(url_for('pos'))

item = {
    'variant_id': row['id'],
    'product_name': row['product_name'],
    'variant_name': row['variant_name'],
    'unit_price': float(row['retail_price']),
    'qty': float(qty)
}
cart = session.get('cart', [])
cart.append(item)
session['cart'] = cart
return redirect(url_for('pos'))

@app.route('/pos/remove/int:idx') def pos_remove_item(idx): cart = session.get('cart', []) if 0 <= idx < len(cart): cart.pop(idx) session['cart'] = cart return redirect(url_for('pos'))

@app.route('/pos/checkout', methods=['POST']) def pos_checkout(): db = get_db() cart: List[Dict[str,Any]] = session.get('cart', []) if not cart: flash("Cart is empty") return redirect(url_for('pos')) discount = d(request.form.get('discount') or 0) session['discount'] = float(discount) payment_method = request.form.get('payment_method') customer_id = request.form.get('customer_id') cashier = 'cashier'  # simple placeholder; integrate auth if needed

subtotal = d(sum(Decimal(str(it['qty']))*Decimal(str(it['unit_price'])) for it in cart))
total = (subtotal - discount).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

cash_received = None
change_due = None
if payment_method == 'CASH':
    cash_received = d(request.form.get('cash_received') or 0)
    if cash_received < total:
        flash("Cash received less than total.")
        return redirect(url_for('pos'))
    change_due = (cash_received - total).quantize(Decimal('0.01'))

if payment_method == 'CREDIT' and not customer_id:
    flash("Select customer for credit sale.")
    return redirect(url_for('pos'))

# Create sale
receipt_no = gen_receipt_no(db)
cur = db.execute(
    "INSERT INTO Sales (receipt_no, sale_datetime, cashier, payment_method, subtotal, discount, total, cash_received, change_due, customer_id)\n         VALUES (?,?,?,?,?,?,?,?,?,?)",
    (
        receipt_no, now_ts(), cashier, payment_method, float(subtotal), float(discount), float(total),
        float(cash_received) if cash_received is not None else None,
        float(change_due) if change_due is not None else None,
        int(customer_id) if customer_id else None
    )
)
sale_id = cur.lastrowid

# Handle items: deduct stock & compute COGS at current avg cost
items_for_receipt = []
try:
    for it in cart:
        variant_id = int(it['variant_id'])
        qty = d(it['qty'])
        unit_price = d(it['unit_price'])
        cogs = deduct_stock_on_sale(db, variant_id, qty)
        line_total = (qty * unit_price).quantize(Decimal('0.01'))
        db.execute("INSERT INTO SaleItems (sale_id, variant_id, qty, unit_price, line_total, cogs) VALUES (?,?,?,?,?,?)",
                   (sale_id, variant_id, float(qty), float(unit_price), float(line_total), float(cogs)))

        vrow = get_variant(db, variant_id)
        items_for_receipt.append({
            'product_name': vrow['product_name'],
            'variant_name': vrow['variant_name'],
            'qty': float(qty),
            'unit_price': float(unit_price),
            'line_total': float(line_total)
        })
except ValueError as e:
    db.rollback()
    flash(str(e))
    return redirect(url_for('pos'))

# Create Credit Ledger if needed
if payment_method == 'CREDIT':
    db.execute("INSERT INTO CreditLedger (sale_id, customer_id, original_amount, outstanding, status, created_at) VALUES (?,?,?,?,?,?)",
               (sale_id, int(customer_id), float(total), float(total), 'OUTSTANDING', now_ts()))

db.commit()

# Prepare receipt in session
sale = db.execute("SELECT * FROM Sales WHERE id=?", (sale_id,)).fetchone()
session['last_receipt'] = dict(sale)
session['last_receipt_items'] = items_for_receipt
session['cart'] = []
session['discount'] = 0.0
return redirect(url_for('pos'))

---------- Customers & Credit ----------

@app.route('/customers/new', methods=['POST']) def add_customer(): db = get_db() name = request.form['name'] phone = request.form.get('phone') address = request.form.get('address') db.execute("INSERT INTO Customers (name, phone, address) VALUES (?,?,?)", (name, phone, address)) db.commit() flash("Customer added") return redirect(url_for('credit_payments'))

@app.route('/credit') def credit_payments(): db = get_db() rows = db.execute( """SELECT cl.*, c.name as customer_name, s.receipt_no FROM CreditLedger cl JOIN Customers c ON c.id=cl.customer_id JOIN Sales s ON s.id=cl.sale_id ORDER BY cl.id DESC """ ).fetchall() return render_template_string(CREDIT_HTML, credits=rows)

@app.route('/credit/pay/int:credit_id', methods=['POST']) def pay_credit(credit_id): db = get_db() amount = d(request.form['amount']) method = request.form['method'] cl = db.execute("SELECT * FROM CreditLedger WHERE id=?", (credit_id,)).fetchone() if not cl or cl['status'] == 'PAID': flash("Invalid credit record") return redirect(url_for('credit_payments')) new_out = max(Decimal('0.00'), d(cl['outstanding']) - amount) db.execute("INSERT INTO CreditPayments (credit_id, amount, method, paid_at) VALUES (?,?,?,?)", (credit_id, float(amount), method, now_ts())) db.execute("UPDATE CreditLedger SET outstanding=?, status=? WHERE id=?", (float(new_out), 'PAID' if new_out == 0 else 'OUTSTANDING', credit_id)) db.commit() flash("Payment recorded") return redirect(url_for('credit_payments'))

---------- Reports ----------

@app.route('/reports/sales') def report_sales(): db = get_db() start = request.args.get('start') or (date.today()-timedelta(days=7)).strftime('%Y-%m-%d') end = request.args.get('end') or date.today().strftime('%Y-%m-%d') pm = request.args.get('pm') or '' cashier = request.args.get('cashier') or ''

where = ["date(s.sale_datetime) BETWEEN ? AND ?"]
params: List[Any] = [start, end]
if pm:
    where.append("s.payment_method = ?")
    params.append(pm)
if cashier:
    where.append("s.cashier = ?")
    params.append(cashier)
where_sql = " AND ".join(where)

total = db.execute(f"SELECT COALESCE(SUM(s.total),0) AS t FROM Sales s WHERE {where_sql}", params).fetchone()["t"]
gp = db.execute(f"SELECT COALESCE(SUM(si.line_total - si.cogs),0) AS gp FROM SaleItems si JOIN Sales s ON s.id=si.sale_id WHERE {where_sql}", params).fetchone()["gp"]

by_item = db.execute(
    f"""
    SELECT p.name as product_name, v.variant_name, SUM(si.qty) as qty, SUM(si.line_total) as sales, SUM(si.cogs) as cogs
    FROM SaleItems si
    JOIN Sales s ON s.id=si.sale_id
    JOIN ProductVariants v ON v.id=si.variant_id
    JOIN Products p ON p.id=v.product_id
    WHERE {where_sql}
    GROUP BY si.variant_id
    ORDER BY sales DESC
    """,
    params
).fetchall()

return render_template_string(REPORT_SALES_HTML, start=start, end=end, pm=pm, cashier=cashier, summary={"total":total, "gp":gp}, by_item=by_item)

@app.route('/reports/inventory') def report_inventory(): db = get_db() rows = db.execute( """ SELECT v.id as variant_id, p.name as product_name, v.variant_name, i.stock_qty, i.avg_cost, i.min_stock FROM ProductVariants v JOIN Products p ON p.id=v.product_id LEFT JOIN Inventory i ON i.variant_id=v.id ORDER BY p.name, v.id """ ).fetchall() ledger = db.execute( """ SELECT sl.*, v.variant_name, p.name as product_name, s.name as supplier_name FROM StockLedger sl JOIN ProductVariants v ON v.id=sl.variant_id JOIN Products p ON p.id=v.product_id LEFT JOIN Suppliers s ON s.id=sl.supplier_id ORDER BY sl.id DESC LIMIT 100 """ ).fetchall() return render_template_string(REPORT_INVENTORY_HTML, rows=rows, ledger=ledger)

@app.route('/reports/credit')

def report_credit(): db = get_db() rows = db.execute( """SELECT cl.*, c.name as customer_name, s.receipt_no, s.sale_datetime FROM CreditLedger cl JOIN Customers c ON c.id=cl.customer_id JOIN Sales s ON s.id=cl.sale_id WHERE cl.status='OUTSTANDING' ORDER BY cl.id DESC """ ).fetchall() total_outstanding = sum([r['outstanding'] for r in rows]) aging = {'0-30':0.0,'31-60':0.0,'61-90':0.0,'90+':0.0} for r in rows: days = (date.today() - datetime.strptime(r['sale_datetime'][:10], '%Y-%m-%d').date()).days if days <= 30: aging['0-30'] += r['outstanding'] elif days <= 60: aging['31-60'] += r['outstanding'] elif days <= 90: aging['61-90'] += r['outstanding'] else: aging['90+'] += r['outstanding'] return render_template_string(REPORT_CREDIT_HTML, rows=rows, total_outstanding=total_outstanding, aging=aging)

@app.route('/reports/pnl')

def report_pnl(): db = get_db() start = request.args.get('start') or (date.today()-timedelta(days=30)).strftime('%Y-%m-%d') end = request.args.get('end') or date.today().strftime('%Y-%m-%d') total_sales = db.execute("SELECT COALESCE(SUM(total),0) AS s FROM Sales WHERE date(sale_datetime) BETWEEN ? AND ?", (start, end)).fetchone()["s"] total_cogs = db.execute( """SELECT COALESCE(SUM(si.cogs),0) AS c FROM SaleItems si JOIN Sales s ON s.id=si.sale_id WHERE date(s.sale_datetime) BETWEEN ? AND ?""", (start, end) ).fetchone()["c"] return render_template_string(REPORT_PNL_HTML, start=start, end=end, total_sales=total_sales, total_cogs=total_cogs)

--------- Jinja loader for our inline templates ---------

from jinja2 import DictLoader app.jinja_loader = DictLoader({ 'base.html': BASE_HTML, 'dashboard.html': DASH_HTML, })

-----------------------------

CLI helpers

-----------------------------

@app.cli.command('seed') def seed_data(): """Seed a few example products & variants for quick testing.""" db = get_db() # Create products p1 = db.execute("INSERT INTO Products (name, category, base_unit, supplier_id) VALUES (?,?,?,?)", ("Rice","Food","kg",1)).lastrowid db.execute("INSERT INTO ProductVariants (product_id, variant_name, unit_multiplier, retail_price, wholesale_price) VALUES (?,?,?,?,?)", (p1,"1 kg",1,210,200)) db.execute("INSERT INTO ProductVariants (product_id, variant_name, unit_multiplier, retail_price) VALUES (?,?,?,?)", (p1,"500 g",0.5,110)) p2 = db.execute("INSERT INTO Products (name, category, base_unit, supplier_id) VALUES (?,?,?,?)", ("Sugar","Food","kg",1)).lastrowid db.execute("INSERT INTO ProductVariants (product_id, variant_name, unit_multiplier, retail_price) VALUES (?,?,?,?)", (p2,"1 kg",1,160)) p3 = db.execute("INSERT INTO Products (name, category, base_unit, supplier_id) VALUES (?,?,?,?)", ("Maize Meal","Food","kg",1)).lastrowid db.execute("INSERT INTO ProductVariants (product_id, variant_name, unit_multiplier, retail_price) VALUES (?,?,?,?)", (p3,"2 kg",2,250)) db.commit() print("Seeded sample products.")

-----------------------------

Start app

-----------------------------

if name == 'main': with app.app_context(): init_db() app.add_url_rule('/dashboard', view_func=dashboard) app.add_url_rule('/products', view_func=products) app.add_url_rule('/inventory/receive', view_func=receive_stock, methods=['GET','POST']) app.add_url_rule('/pos', view_func=pos) app.add_url_rule('/pos/add', view_func=pos_add_item, methods=['POST']) app.add_url_rule('/pos/remove/int:idx', view_func=pos_remove_item) app.add_url_rule('/pos/checkout', view_func=pos_checkout, methods=['POST']) app.add_url_rule('/customers/new', view_func=add_customer, methods=['POST']) app.add_url_rule('/credit', view_func=credit_payments) app.add_url_rule('/credit/pay/int:credit_id', view_func=pay_credit, methods=['POST']) app.add_url_rule('/reports/sales', view_func=report_sales) app.add_url_rule('/reports/inventory', view_func=report_inventory) app.add_url_rule('/reports/credit', view_func=report_credit) app.add_url_rule('/reports/pnl', view_func=report_pnl) app.run(debug=True)


