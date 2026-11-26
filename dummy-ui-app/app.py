"""Dummy UI app for trying Devops-Konnekt. Standard library only.

Listens on port 8080 (override with the PORT environment variable) and logs every request with a correlation ID
(taken from the X-Correlation-ID header, or generated), so you can try the
"Search by correlation ID" box in Devops-Konnekt.

  /        the page
  /health  returns ok
  /error   logs an ERROR line and returns HTTP 500 (the pod keeps running)
"""
import os
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.environ.get("PORT", "8080"))   # inside the container it stays 8080

# ---- To make the pod CRASH on start, add a bug here, rebuild the image and restart the pod. ----
# For example, uncomment the next line:
# print({"qty": 5}["price"])
# ------------------------------------------------------------------------------------------------

PAGE = b"""<!doctype html>
<html><head><meta charset="utf-8"><title>Dummy UI</title>
<style>
  body { font-family: system-ui, sans-serif; background:#0b0b0d; color:#f5f5f7; display:grid; place-items:center; height:100vh; margin:0 }
  .card { background:#18181b; border:1px solid #333; border-radius:20px; padding:32px 40px; text-align:center }
  a { color:#d9b26a }
</style></head>
<body><div class="card">
  <h1>Dummy UI</h1>
  <p>This pod is running. Version 1.</p>
  <p><a href="/">Home</a> &middot; <a href="/health">Health</a> &middot; <a href="/error">Trigger an error</a></p>
</div></body></html>
"""


class Handler(BaseHTTPRequestHandler):
    def _reply(self, code: int, body: bytes, ctype: str = "text/html; charset=utf-8") -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        cid = self.headers.get("X-Correlation-ID") or str(uuid.uuid4())
        print(f"INFO correlation_id={cid} {self.command} {self.path}", flush=True)
        if self.path == "/health":
            self._reply(200, b"ok", "text/plain")
        elif self.path == "/error":
            print(f"ERROR correlation_id={cid} request failed: simulated error on /error", flush=True)
            self._reply(500, b"Simulated error. See the pod logs.", "text/plain")
        elif self.path == "/":
            self._reply(200, PAGE)
        else:
            self._reply(404, b"Not found", "text/plain")

    def log_message(self, *args) -> None:  # we write our own log lines above
        pass


if __name__ == "__main__":
    print(f"INFO dummy-ui starting on port {PORT}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
