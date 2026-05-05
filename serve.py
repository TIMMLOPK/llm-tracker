#!/usr/bin/env python3
"""Simple HTTP server for the LLM Tracker dashboard."""
import http.server
import socketserver
import os
import sys

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
DIRECTORY = os.path.dirname(os.path.abspath(__file__))

class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIRECTORY, **kwargs)
    
    def end_headers(self):
        # CORS and caching headers
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
        super().end_headers()
    
    def log_message(self, format, *args):
        pass  # Suppress log noise

if __name__ == '__main__':
    with socketserver.TCPServer(("0.0.0.0", PORT), Handler) as httpd:
        print(f"🌐 LLM Tracker dashboard running at http://0.0.0.0:{PORT}")
        httpd.serve_forever()
