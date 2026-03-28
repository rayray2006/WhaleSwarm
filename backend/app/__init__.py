"""Flask application factory."""
import logging
from flask import Flask, jsonify
from flask_cors import CORS

from app.config import Config
from app.utils.logger import setup_logging


def create_app(config: Config = None) -> Flask:
    if config is None:
        config = Config.from_env()

    setup_logging()
    app = Flask(__name__)
    CORS(app, resources={r"/api/*": {"origins": "*"}})

    app.config["APP_CONFIG"] = config

    # Register storage
    from app.storage.neo4j_storage import Neo4jStorage
    storage = Neo4jStorage(config)
    app.extensions["neo4j_storage"] = storage

    # Register blueprints
    from app.api.graph import graph_bp
    from app.api.simulation import simulation_bp
    from app.api.report import report_bp

    app.register_blueprint(graph_bp, url_prefix="/api/graph")
    app.register_blueprint(simulation_bp, url_prefix="/api/simulation")
    app.register_blueprint(report_bp, url_prefix="/api/report")

    @app.route("/health")
    def health():
        return jsonify({"status": "healthy"})

    @app.before_request
    def log_request():
        pass

    @app.after_request
    def log_response(response):
        return response

    return app
