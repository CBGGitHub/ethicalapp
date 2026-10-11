"""Preview the website on this PC:  .venv\\Scripts\\python website\\serve.py   then open http://localhost:8080
(Opening index.html directly from the folder doesn't work for the online tools - browsers block them on file://.)"""
import http.server
import os
import sys

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
os.chdir(os.path.dirname(os.path.abspath(__file__)))


class Handler(http.server.SimpleHTTPRequestHandler):
    extensions_map = {**http.server.SimpleHTTPRequestHandler.extensions_map,
                      ".js": "text/javascript", ".mjs": "text/javascript", ".wasm": "application/wasm",
                      ".svg": "image/svg+xml", ".webp": "image/webp", ".json": "application/json"}

    def end_headers(self):
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()


print(f"Website preview: http://localhost:{PORT}   (Ctrl+C to stop)")
http.server.ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
