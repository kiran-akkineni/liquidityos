"""
LiquidityOS — AI-Native B2B Wholesale Liquidation Marketplace Infrastructure
Main application entry point.
"""

import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask
from app.db import init_db
from app.routes.api import api


def create_app(init_database=True):
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    # CORS — allow frontend dev server
    @app.after_request
    def add_cors_headers(response):
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
        return response

    # Register blueprints
    app.register_blueprint(api)

    # Global error handlers
    @app.errorhandler(400)
    def bad_request(e):
        return {"error": {"code": "BAD_REQUEST", "message": str(e)}}, 400

    @app.errorhandler(404)
    def not_found(e):
        return {"error": {"code": "NOT_FOUND", "message": "Resource not found"}}, 404

    @app.errorhandler(405)
    def method_not_allowed(e):
        return {"error": {"code": "METHOD_NOT_ALLOWED", "message": str(e)}}, 405

    @app.errorhandler(500)
    def internal_error(e):
        return {"error": {"code": "INTERNAL_ERROR", "message": "An unexpected error occurred"}}, 500

    # Initialize database
    if init_database:
        with app.app_context():
            init_db()

    return app


app = create_app(init_database=True)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    print(f"""
╔═══════════════════════════════════════════════════════════╗
║                    LiquidityOS v0.1.0                     ║
║     AI-Native B2B Wholesale Liquidation Infrastructure    ║
╠═══════════════════════════════════════════════════════════╣
║  API:   http://localhost:{port}/v1                          ║
║  Docs:  See LiquidityOS_Sections_5-7 for full API spec   ║
╚═══════════════════════════════════════════════════════════╝
    """)
    app.run(host="0.0.0.0", port=port, debug=True)
