"""
Authentication middleware for LiquidityOS.
JWT-based, role-scoped (buyer/seller/ops).
"""

import jwt
import os
from functools import wraps
from flask import request, jsonify, g

SECRET_KEY = os.environ.get("JWT_SECRET", "dev-secret-change-in-production")
ALGORITHM = "HS256"


def create_token(user_id: str, role: str) -> str:
    """Create a JWT token for a user."""
    import time
    payload = {
        "sub": user_id,
        "role": role,  # 'buyer', 'seller', 'ops'
        "iat": int(time.time()),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    """Decode and validate a JWT token."""
    return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])


def require_auth(*allowed_roles):
    """Decorator to require authentication with role checking."""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            auth_header = request.headers.get("Authorization", "")
            if not auth_header.startswith("Bearer "):
                return jsonify({"error": {"code": "UNAUTHORIZED", "message": "Missing or invalid Authorization header"}}), 401

            token = auth_header[7:]
            try:
                payload = decode_token(token)
            except jwt.InvalidTokenError as e:
                return jsonify({"error": {"code": "INVALID_TOKEN", "message": str(e)}}), 401

            if allowed_roles and payload.get("role") not in allowed_roles:
                return jsonify({"error": {"code": "FORBIDDEN", "message": f"Required role: {', '.join(allowed_roles)}"}}), 403

            g.current_user_id = payload["sub"]
            g.current_role = payload["role"]
            return f(*args, **kwargs)
        return decorated_function
    return decorator
