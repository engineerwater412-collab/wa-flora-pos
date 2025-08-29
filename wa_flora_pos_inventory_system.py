from flask import Flask, render_template_string, request, redirect
from flask_sqlalchemy import SQLAlchemy
import os

app = Flask(__name__)

# Get DATABASE_URL from Render environment variable
DATABASE_URL = os.environ.get("DATABASE_URL")
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URL
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

# Database model
class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    wholesale_price = db.Column(db.Float, nullable=False)
    retail_price = db.Column(db.Float, nullable=False)

# Create tables if they don’t exist
with app.app_context():
    db.create_all()

# Routes
@app.route("/")
def home():
    return redirect("/products")

@app.route("/products")
def products():
    products = Product.query.all()
    return render_template_string("""
    <h1>Product List</h1>
    <a href='/add_product'>Add Product</a>
    <ul>
    {% for product in products %}
        <li>{{ product.name }} - Wholesale: {{ product.wholesale_price }} | Retail: {{ product.retail_price }}</li>
    {% endfor %}
    </ul>
    """, products=products)

@app.route("/add_product", methods=["GET", "POST"])
def add_product():
    if request.method == "POST":
        name = request.form["name"]
        wholesale = float(request.form["wholesale"])
        retail = float(request.form["retail"])
        product = Product(name=name, wholesale_price=wholesale, retail_price=retail)
        db.session.add(product)
        db.session.commit()
        return redirect("/products")
    return render_template_string("""
    <h1>Add Product</h1>
    <form method="post">
        Name: <input type="text" name="name"><br>
        Wholesale Price: <input type="number" step="0.01" name="wholesale"><br>
        Retail Price: <input type="number" step="0.01" name="retail"><br>
        <input type="submit" value="Add">
    </form>
    """)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
