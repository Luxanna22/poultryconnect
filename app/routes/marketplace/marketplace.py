from flask import Blueprint, render_template
from flask_login import login_required

marketplace_bp = Blueprint('marketplace', __name__)

@marketplace_bp.route('/')
@login_required
def index():
    return render_template('marketplace/marketplace.html', title='Marketplace')

@marketplace_bp.route('/product/<int:id>')
def product_detail(id):
    return render_template('marketplace/product_detail.html', title='Product Details')
