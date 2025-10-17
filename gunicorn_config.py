import os
from pathlib import Path
from dotenv import load_dotenv

chdir = os.path.dirname(os.path.abspath(__file__))

env_path = Path(chdir) / ".env"
if env_path.exists():
    load_dotenv(dotenv_path=env_path)
else:
    print(f"⚠️  .env file not found at {env_path}")

flask_env = os.getenv("FLASK_ENV", "production").lower()

if flask_env == "development":
    bind = "127.0.0.1:8000"
else:
    bind = "0.0.0.0:8000"

workers = 4
threads = 2
loglevel = "info"
accesslog = "-"
errorlog = "-"

print(f"🚀 Gunicorn running in {flask_env} mode — bound to {bind}")
