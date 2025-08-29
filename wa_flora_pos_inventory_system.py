from flask import Flask, render_template_string, request, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
import os

app = Flask(__name__)

# Use Render's DATABASE_URL if available, otherwise default to local SQLite
app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL", "sqlite:///wa_flora_pos.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

# Product model
class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    category = db.Column(db.String(100))
    base_unit = db.Column(db.String(50))
    retail_price = db.Column(db.Float)
    wholesale_price = db.Column(db.Float)
    stock = db.Column(db.Float, default=0)

# Home
@app.route("/")
def home():
    return "Wa Flora POS with PostgreSQL is running!"

# Example: add a product
@app.route("/add_product", methods=["GET", "POST"])
def add_product():
    if request.method == "POST":
        name = request.form["name"]
        category = request.form["category"]
        base_unit = request.form["base_unit"]
        retail_price = float(request.form["retail_price"])
        wholesale_price = float(request.form["wholesale_price"])
        stock = float(request.form["stock"])

        new_product = Product(
            name=name,
            category=category,
            base_unit=base_unit,
            retail_price=retail_price,
            wholesale_price=wholesale_price,
            stock=stock
        )
        db.session.add(new_product)
        db.session.commit()
        return redirect(url_for("list_products"))

    return '''
        <form method="POST">
            Name: <input type="text" name="name"><br>
            Category: <input type="text" name="category"><br>
            Unit: <input type="text" name="base_unit"><br>
            Retail Price: <input type="number" step="0.01" name="retail_price"><br>
            Wholesale Price: <input type="number" step="0.01" name="wholesale_price"><br>
            Stock: <input type="number" step="0.01" name="stock"><br>
            <input type="submit" value="Add Product">
        </form>
    '''

# List products
@app.route("/products")
def list_products():
    products = Product.query.all()
    return "<br>".join([f"{p.name} - {p.stock} {p.base_unit}" for p in products])

if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run()
