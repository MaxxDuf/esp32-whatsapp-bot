import os
from flask import Flask, request, jsonify

app = Flask(__name__)

@app.route("/")
def home():
    return "🤖 Bot ESP32-CAM en ligne !"

@app.route("/test")
def test():
    return jsonify({
        "status": "ok",
        "message": "Le serveur fonctionne !"
    })

@app.route("/command", methods=["POST"])
def command():
    data = request.get_json(silent=True) or {}
    cmd = data.get("command", "")

    if cmd == "/photo":
        return jsonify({
            "status": "ok",
            "action": "photo",
            "message": "Commande photo reçue 📷"
        })

    if cmd == "/10":
        return jsonify({
            "status": "ok",
            "action": "video",
            "duration": 10,
            "message": "Commande vidéo 10 secondes reçue 🎥"
        })

    if cmd == "/direct":
        return jsonify({
            "status": "ok",
            "action": "live",
            "message": "Commande direct reçue 📹"
        })

    return jsonify({
        "status": "error",
        "message": "Commande inconnue"
    }), 400


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
