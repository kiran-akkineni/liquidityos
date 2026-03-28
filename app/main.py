"""
LiquidityOS — AI-Native B2B Wholesale Liquidation Marketplace Infrastructure
Main application entry point.
"""

import os
import sys
import logging

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Configure logging before any app imports
logging.basicConfig(
    level=logging.DEBUG if os.environ.get("DEBUG") else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("liquidityos")

from flask import Flask, send_from_directory
from app.db import init_db
from app.routes.api import api

# Resolve frontend dist directory
FRONTEND_DIST = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                              "frontend", "dist")


def create_app(init_database=True):
    logger.info("Creating LiquidityOS app...")

    app = Flask(__name__, static_folder=None)
    app.config["JSON_SORT_KEYS"] = False

    # CORS
    @app.after_request
    def add_cors_headers(response):
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
        return response

    # Register API blueprint
    app.register_blueprint(api)
    logger.info("API blueprint registered")

    # Serve frontend static files in production
    has_frontend = os.path.isdir(FRONTEND_DIST)
    if has_frontend:
        logger.info("Serving frontend from %s", FRONTEND_DIST)

        @app.route("/", defaults={"path": ""})
        @app.route("/<path:path>")
        def serve_frontend(path):
            file_path = os.path.join(FRONTEND_DIST, path)
            if path and os.path.isfile(file_path):
                return send_from_directory(FRONTEND_DIST, path)
            return send_from_directory(FRONTEND_DIST, "index.html")
    else:
        logger.info("No frontend dist found at %s — API-only mode", FRONTEND_DIST)

    # Global error handlers
    @app.errorhandler(400)
    def bad_request(e):
        return {"error": {"code": "BAD_REQUEST", "message": str(e)}}, 400

    @app.errorhandler(404)
    def not_found(e):
        from flask import request
        if request.path.startswith("/v1/"):
            return {"error": {"code": "NOT_FOUND", "message": "Resource not found"}}, 404
        if has_frontend:
            return send_from_directory(FRONTEND_DIST, "index.html")
        return {"error": {"code": "NOT_FOUND", "message": "Resource not found"}}, 404

    @app.errorhandler(405)
    def method_not_allowed(e):
        return {"error": {"code": "METHOD_NOT_ALLOWED", "message": str(e)}}, 405

    @app.errorhandler(500)
    def internal_error(e):
        logger.error("Internal error: %s", e)
        return {"error": {"code": "INTERNAL_ERROR", "message": "An unexpected error occurred"}}, 500

    # Initialize database
    if init_database:
        try:
            with app.app_context():
                init_db()
        except Exception as e:
            logger.error("Failed to initialize database: %s", e, exc_info=True)
            raise

    logger.info("LiquidityOS app ready")
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
║  App:   http://localhost:{port}                             ║
╚═══════════════════════════════════════════════════════════╝
    """)
    app.run(host="0.0.0.0", port=port, debug=True)
