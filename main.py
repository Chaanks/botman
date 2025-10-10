"""Main entry point for Bot Manager application."""

from botman.web.server import serve

if __name__ == "__main__":
    serve(host="100.115.85.125", port=5173)
