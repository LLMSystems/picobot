"""Run the picobot FastAPI server locally."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from simplified_chatbot.server.app import create_app


def build_parser() -> argparse.ArgumentParser:
    """Create the command-line parser for the FastAPI server example."""
    parser = argparse.ArgumentParser(
        description="Run the picobot FastAPI server.",
    )
    parser.add_argument(
        "--config",
        default="example_config.json",
        help="Path to the chatbot config JSON file.",
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Host to bind the HTTP server (default: 0.0.0.0).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port to bind the HTTP server (default: 8000).",
    )
    parser.add_argument(
        "--db-path",
        default="sessions.db",
        help="Optional AioSQLite session DB path (default: ./sessions.db).",
    )
    parser.add_argument(
        "--alerts-config",
        default="alerts.yaml",
        help="Path to the alert rules YAML (default: ./alerts.yaml; "
             "alerts disabled if file is missing or empty).",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable uvicorn auto-reload for local development.",
    )
    return parser


def main() -> int:
    """Build the FastAPI app and start uvicorn."""
    parser = build_parser()
    args = parser.parse_args()

    try:
        import uvicorn
    except ImportError:
        print("uvicorn is not installed. Install it with: pip install uvicorn")
        return 1

    config_path = Path(args.config).expanduser().resolve()
    db_path = (
        Path(args.db_path).expanduser().resolve()
        if args.db_path is not None
        else None
    )
    app = create_app(
        config_path=config_path,
        db_path=db_path,
        alerts_config_path=args.alerts_config,
    )

    print("picobot FastAPI server")
    print(f"Config: {config_path}")
    if db_path is not None:
        print(f"Session DB: {db_path}")
    print(f"Listening on http://{args.host}:{args.port}")
    print("Endpoints:")
    print("  POST /chat")
    print("  GET  /chat/stream")

    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        reload=args.reload,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
