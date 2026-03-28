"""Production entrypoint — no shell needed, no $PORT expansion issues."""
import os
import subprocess
import sys

print("start.py: launching", flush=True)

# Run seed (non-fatal)
subprocess.run([sys.executable, "scripts/prod_seed.py"])

# Start gunicorn with PORT from environment
port = os.environ.get("PORT", "8000")
print(f"start.py: starting gunicorn on port {port}", flush=True)
os.execvp("gunicorn", ["gunicorn", "--bind", f"0.0.0.0:{port}", "--workers", "2", "--timeout", "120", "app.main:app"])
