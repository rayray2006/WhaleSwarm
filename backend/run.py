"""Flask server entry point."""
import os
import sys

# Ensure the .env file at the project root is found
_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_env_path = os.path.join(_root, ".env")
if os.path.exists(_env_path):
    os.environ.setdefault("DOTENV_PATH", _env_path)

from app import create_app
from app.config import Config

config = Config.from_env(dotenv_path=_env_path if os.path.exists(_env_path) else None)
app = create_app(config)

if __name__ == "__main__":
    app.run(
        host=config.flask_host,
        port=config.flask_port,
        debug=config.flask_debug,
    )
