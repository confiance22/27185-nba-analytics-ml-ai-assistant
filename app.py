import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from flask import Flask
app = Flask(__name__)

@app.route("/")
def home():
    return "<h1>NBA AI Assistant</h1><p>Server is running.</p>"

@app.route("/health")
def health():
    return "OK"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
