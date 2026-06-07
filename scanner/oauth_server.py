"""OAuth server for Longbridge - catches callback, saves token."""
import json, os, urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler
import requests

CLIENT_ID = "d4ec1a5c-07eb-45bf-9d95-b94e33690b00"
PORT = 60355
TOKEN_FILE = os.path.expanduser("~/.longbridge/openapi/tokens/ccass_token.json")

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        code = params.get("code", [None])[0]
        
        if code:
            resp = requests.post(
                "https://openapi.longbridge.com/oauth2/token",
                json={
                    "grant_type": "authorization_code",
                    "code": code,
                    "client_id": CLIENT_ID,
                    "redirect_uri": f"http://localhost:{PORT}/callback",
                },
                headers={"Content-Type": "application/json"}
            )
            if resp.status_code == 200:
                data = resp.json()
                os.makedirs(os.path.dirname(TOKEN_FILE), exist_ok=True)
                with open(TOKEN_FILE, "w") as f:
                    json.dump(data, f, indent=2)
                self.send_response(200)
                self.send_header("Content-type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(b"<h1>OK! Token saved.</h1><p>You can close this window.</p>")
                print(f"TOKEN_SAVED")
            else:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(f"Token exchange failed: {resp.text}".encode())
                print(f"TOKEN_FAILED:{resp.status_code}")
        else:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"Missing code")
        
    def log_message(self, format, *args):
        pass  # suppress logs

AUTH_URL = f"https://openapi.longbridge.com/oauth2/authorize?client_id={CLIENT_ID}&redirect_uri=http://localhost:{PORT}/callback&response_type=code&scope=4+6+10+11"
print(f"AUTH_URL:{AUTH_URL}")
print("READY")
HTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
