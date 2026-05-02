from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager
from flask_mail import Mail
from config import Config

db = SQLAlchemy()
migrate = Migrate()
login = LoginManager()
login.login_view = 'auth.login'
login.login_message = 'Please log in to access this page.'
mail = Mail()

def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    db.init_app(app)
    migrate.init_app(app, db)
    login.init_app(app)
    mail.init_app(app)

    # Register Blueprints
    from app.routes.auth.auth import auth_bp
    from app.routes.dashboard.dashboard import dashboard_bp
    from app.routes.production.production import production_bp
    from app.routes.analytics.analytics import analytics_bp
    from app.routes.marketplace.marketplace import marketplace_bp
    from app.routes.community.community import community_bp
    from app.routes.admin.admin import admin_bp

    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(dashboard_bp, url_prefix='/dashboard')
    app.register_blueprint(production_bp, url_prefix='/production')
    app.register_blueprint(analytics_bp, url_prefix='/analytics')
    app.register_blueprint(marketplace_bp, url_prefix='/marketplace')
    app.register_blueprint(community_bp, url_prefix='/community')
    app.register_blueprint(admin_bp, url_prefix='/admin')

    # Main index / Landing page route
    @app.route('/')
    def index():
        from flask import render_template
        from app.models import Product
        # Fetch latest marketplace products for landing preview
        preview_products = Product.query.filter_by(
            is_available=True
        ).filter(Product.stock > 0).order_by(
            Product.created_at.desc()
        ).limit(4).all()
        return render_template(
            'landing.html',
            title='PoultryConnect — Smart Farming, Better Living',
            preview_products=preview_products,
        )

    return app

from app import models
