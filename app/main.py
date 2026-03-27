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


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    # Register blueprints
    app.register_blueprint(api)

    # Initialize database
    with app.app_context():
        init_db()

    return app


app = create_app()

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
