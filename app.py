import os
from flask import Flask

app = Flask(__name__)

@app.route("/")
def home():
    return "🤖 Bot ESP32-CAM en ligne !"

@app.route("/test")
def test():
    return "Test OK"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
