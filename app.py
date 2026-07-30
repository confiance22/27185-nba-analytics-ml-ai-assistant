import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from flask import Flask, request, jsonify

app = Flask(__name__)

HTML = """
<!DOCTYPE html>
<html>
<head>
  <title>NBA AI Assistant</title>
  <style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body { font-family: 'Segoe UI', Arial, sans-serif; background: #f0f2f5; min-height: 100vh; display: flex; align-items: center; justify-content: center; }
    .card { background: white; max-width: 640px; width: 90%; padding: 40px; border-radius: 12px; box-shadow: 0 2px 12px rgba(0,0,0,0.1); }
    h1 { font-size: 24px; font-weight: 700; color: #1a1a2e; margin-bottom: 4px; }
    .sub { color: #666; font-size: 14px; margin-bottom: 24px; }
    .bar { display: flex; gap: 8px; }
    input { flex: 1; padding: 12px 16px; border: 1px solid #ddd; border-radius: 8px; font-size: 15px; outline: none; }
    input:focus { border-color: #1a1a2e; }
    button { padding: 12px 24px; background: #1a1a2e; color: white; border: none; border-radius: 8px; font-size: 15px; cursor: pointer; }
    button:hover { background: #16213e; }
    .answer { margin-top: 20px; padding: 16px; background: #f8f9fa; border-radius: 8px; line-height: 1.5; color: #333; }
    .error { color: #d32f2f; margin-top: 12px; font-size: 14px; }
  </style>
</head>
<body>
  <div class="card">
    <h1>NBA Data AI Assistant</h1>
    <p class="sub">Ask a question in plain English about NBA teams and games</p>
    <form method="post" class="bar">
      <input name="q" placeholder="e.g. How many teams are in the NBA?" required>
      <button type="submit">Ask</button>
    </form>
    {error}
    {answer}
  </div>
</body>
</html>
"""


def get_assistant():
    from ai_assistant.assistant import ask
    return ask


@app.route("/", methods=["GET", "POST"])
def home():
    error = ""
    answer = ""
    if request.method == "POST":
        q = request.form.get("q", "").strip()
        if q:
            try:
                ask = get_assistant()
                answer = f'<div class="answer">{ask(q)}</div>'
            except Exception as e:
                error = f'<div class="error">Error: {e}</div>'
    return HTML.format(answer=answer, error=error)


@app.route("/api", methods=["POST"])
def api():
    try:
        ask = get_assistant()
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    data = request.get_json(force=True)
    q = data.get("question", "").strip()
    if not q:
        return jsonify({"error": "missing question"}), 400
    return jsonify({"question": q, "answer": ask(q)})


@app.route("/health")
def health():
    return "OK"


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
