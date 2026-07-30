from flask import Flask, request, jsonify, render_template_string
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from ai_assistant.assistant import ask

app = Flask(__name__)

HTML = """
<!DOCTYPE html>
<html>
<head><title>NBA AI Assistant</title></head>
<body style="font-family:sans-serif;max-width:700px;margin:40px auto;padding:20px">
<h1>NBA Data AI Assistant</h1>
<form method="post">
  <input name="q" style="width:80%;padding:8px" placeholder="Ask about NBA teams and games...">
  <button type="submit" style="padding:8px 16px">Ask</button>
</form>
{% if answer %}
  <div style="margin-top:20px;padding:15px;background:#f5f5f5;border-radius:8px">{{ answer }}</div>
{% endif %}
</body>
</html>
"""

@app.route("/", methods=["GET", "POST"])
def home():
    answer = None
    if request.method == "POST":
        q = request.form.get("q", "").strip()
        if q:
            answer = ask(q)
    return render_template_string(HTML, answer=answer)

@app.route("/api", methods=["POST"])
def api():
    data = request.get_json(force=True)
    q = data.get("question", "").strip()
    if not q:
        return jsonify({"error": "missing question"}), 400
    return jsonify({"question": q, "answer": ask(q)})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
