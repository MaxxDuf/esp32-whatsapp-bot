
import os
import io
import asyncio
import tempfile
import uuid
import hmac
from threading import Thread, Lock, Timer

import cv2
import discord
from discord import app_commands
from flask import Flask, request, jsonify


# ============================================================
# CONFIGURATION
# ============================================================

DISCORD_TOKEN = os.environ["DISCORD_TOKEN"]
CAMERA_SECRET = os.environ.get("CAMERA_SECRET", "")
PORT = int(os.environ.get("PORT", 10000))

if not CAMERA_SECRET:
    raise RuntimeError("CAMERA_SECRET est absent sur Render.")


# ============================================================
# FLASK ET VARIABLES
# ============================================================

web_app = Flask(__name__)

camera_lock = Lock()

active_capture = None
capture_timer = None


# ============================================================
# AUTHENTIFICATION
# ============================================================

def camera_authorized():
    secret = request.headers.get("X-Camera-Secret", "")

    return hmac.compare_digest(
        secret,
        CAMERA_SECRET
    )


# ============================================================
# ENVOI DE MESSAGES DISCORD
# ============================================================

async def envoyer_message(channel_id, message):

    channel = client.get_channel(channel_id)

    if channel is None:
        channel = await client.fetch_channel(channel_id)

    await channel.send(message)


def envoyer_message_sync(channel_id, message):

    if channel_id is None:
        return

    try:
        future = asyncio.run_coroutine_threadsafe(
            envoyer_message(channel_id, message),
            client.loop
        )

        future.result(timeout=25)

    except Exception as e:
        print(f"Erreur envoi Discord : {e}")


def envoyer_erreur_discord(channel_id, message):

    envoyer_message_sync(
        channel_id,
        "⚠️ **PROBLÈME AVEC LA CAMÉRA**\n\n" + message
    )


# ============================================================
# JOURNAL ESP32
# ============================================================

@web_app.route("/api/log", methods=["POST"])
def receive_log():

    if not camera_authorized():
        return jsonify({
            "error": "unauthorized"
        }), 401

    data = request.get_json(silent=True) or {}

    message = str(data.get("message", "")).strip()

    if not message:
        return jsonify({
            "error": "empty log"
        }), 400

    with camera_lock:

        capture = active_capture

        if capture is None or capture["type"] != "photo":
            return jsonify({
                "error": "no active photo"
            }), 409

        channel_id = capture["channel_id"]

    print("JOURNAL ESP32 :", message)

    envoyer_message_sync(
        channel_id,
        "🖥️ **ESP32 — Journal de fonctionnement**\n"
        "```text\n"
        + message[:1800]
        + "\n```"
    )

    return jsonify({
        "success": True
    })


# ============================================================
# GESTION DES CAPTURES
# ============================================================

def terminer_capture():

    global active_capture
    global capture_timer

    with camera_lock:

        capture = active_capture
        timer = capture_timer

        active_capture = None
        capture_timer = None

    if timer is not None:
        timer.cancel()

    return capture


def terminer_capture_avec_erreur(message):

    capture = terminer_capture()

    if capture is None:
        return

    print("ERREUR CAPTURE :", message)

    envoyer_erreur_discord(
        capture["channel_id"],
        message
    )


def terminer_capture_succes():

    capture = terminer_capture()

    if capture is not None:
        print("Capture terminée avec succès.")

        envoyer_message_sync(
            capture["channel_id"],
            "✅ **Mission terminée !**\n"
            "La photo a été reçue par Render et publiée sur Discord."
        )


# ============================================================
# DELAI MAXIMAL
# ============================================================

def verifier_timeout(capture_id):

    global active_capture
    global capture_timer

    with camera_lock:

        if active_capture is None:
            return

        if active_capture["id"] != capture_id:
            return

        capture = active_capture

        active_capture = None
        capture_timer = None

    print("DELAI DE CAPTURE DEPASSE")

    envoyer_erreur_discord(
        capture["channel_id"],
        "⏱️ **Délai dépassé**\n"
        "Le relais ESP32 n'a pas terminé la capture dans le temps prévu.\n"
        "Cela peut venir d'une perte de Wi-Fi, d'une caméra inaccessible, "
        "d'un blocage du relais ou d'un problème de transfert."
    )


# ============================================================
# CREATION D'UNE CAPTURE
# ============================================================

def creer_capture(capture_type, channel_id):

    global active_capture
    global capture_timer

    with camera_lock:

        if active_capture is not None:
            return False

        capture_id = str(uuid.uuid4())

        active_capture = {
            "id": capture_id,
            "type": capture_type,
            "channel_id": channel_id,
            "delivered": False
        }

        delai = 90 if capture_type == "photo" else 180

        capture_timer = Timer(
            delai,
            verifier_timeout,
            args=(capture_id,)
        )

        capture_timer.daemon = True
        capture_timer.start()

    return True


# ============================================================
# PAGE PRINCIPALE
# ============================================================

@web_app.route("/")
def home():

    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>ESP32-CAM Bot</title>
    </head>
    <body style="
        background:#111;
        color:white;
        font-family:Arial;
        text-align:center;
        padding-top:60px;
    ">
        <h1>ESP32-CAM Bot</h1>
        <p style="color:#00ff88;font-size:22px;">
            Bot opérationnel
        </p>
        <p>Discord : connecté</p>
        <p>ESP32-CAM : relais WROOM</p>
    </body>
    </html>
    """


# ============================================================
# COMMANDE WROOM
# ============================================================

@web_app.route("/api/command", methods=["GET"])
def get_command():

    if not camera_authorized():

        print("ERREUR : identification ESP32 refusée")

        terminer_capture_avec_erreur(
            "🔐 **Problème d'identification**\n"
            "Render a refusé la connexion du relais (HTTP 401).\n"
            "Le secret envoyé par l'ESP32 ne correspond pas à CAMERA_SECRET "
            "configuré sur Render."
        )

        return jsonify({
            "error": "unauthorized"
        }), 401

    with camera_lock:

        if active_capture is None:
            return jsonify({"command": "none"})

        if active_capture["delivered"]:
            return jsonify({"command": "none"})

        active_capture["delivered"] = True
        capture_type = active_capture["type"]

    if capture_type == "photo":
        print("Commande PHOTO envoyée")
        return jsonify({"command": "photo"})

    if capture_type == "video":
        print("Commande VIDEO envoyée")
        return jsonify({"command": "video10"})

    return jsonify({"command": "none"})


# ============================================================
# ERREURS SIGNALEES PAR LE RELAIS
# ============================================================

@web_app.route("/api/error", methods=["POST"])
def receive_error():

    if not camera_authorized():

        terminer_capture_avec_erreur(
            "🔐 **Problème d'identification**\n"
            "Le relais ESP32 a été refusé par Render (HTTP 401)."
        )

        return jsonify({
            "error": "unauthorized"
        }), 401

    data = request.get_json(silent=True) or {}

    code = str(data.get("code", "unknown"))
    detail = str(data.get("detail", "Aucun détail fourni"))

    erreurs = {
        "camera_connection":
            "📡 Impossible de se connecter au Wi-Fi de la caméra.",

        "camera_capture":
            "📷 La caméra n'a pas réussi à prendre la photo.",

        "camera_http":
            "🌐 La caméra a renvoyé une erreur HTTP.",

        "render_connection":
            "🌐 Impossible de contacter Render.",

        "photo_download":
            "📥 Impossible de télécharger la photo depuis la caméra.",

        "photo_upload":
            "📤 Impossible d'envoyer la photo à Render.",

        "memory":
            "🧠 Mémoire insuffisante sur l'ESP32.",

        "home_wifi":
            "🏠 Impossible de retrouver le Wi-Fi maison.",

        "unknown":
            "❓ Une erreur inconnue s'est produite."
    }

    description = erreurs.get(code, erreurs["unknown"])

    print(f"ERREUR ESP32 : {code} - {detail}")

    terminer_capture_avec_erreur(
        f"{description}\n\n"
        f"**Code :** `{code}`\n"
        f"**Détail technique :** `{detail[:500]}`"
    )

    return jsonify({
        "success": True
    })


# ============================================================
# RECEPTION PHOTO
# ============================================================

@web_app.route("/api/photo", methods=["POST"])
def receive_photo():

    if not camera_authorized():

        terminer_capture_avec_erreur(
            "🔐 **Problème d'identification**\n"
            "Render a refusé l'envoi de la photo (HTTP 401)."
        )

        return jsonify({
            "error": "unauthorized"
        }), 401

    image_data = request.get_data()

    if not image_data:

        terminer_capture_avec_erreur(
            "📷 **Photo vide**\n"
            "Render n'a reçu aucune donnée image."
        )

        return jsonify({
            "error": "empty photo"
        }), 400

    with camera_lock:

        capture = active_capture

        if capture is None or capture["type"] != "photo":
            return jsonify({
                "error": "no active photo request"
            }), 409

        channel_id = capture["channel_id"]

    print(f"PHOTO RECUE : {len(image_data)} octets")

    try:

        future = asyncio.run_coroutine_threadsafe(
            send_photo_to_discord(
                channel_id,
                image_data
            ),
            client.loop
        )

        future.result(timeout=45)

        terminer_capture_succes()

        print("PHOTO ENVOYEE SUR DISCORD")

        return jsonify({
            "success": True
        })

    except Exception as e:

        print("ERREUR ENVOI PHOTO :", e)

        terminer_capture_avec_erreur(
            "📤 **Échec de l'envoi Discord**\n"
            "Render a reçu la photo, mais Discord n'a pas réussi à la publier.\n\n"
            f"**Détail technique :** `{str(e)[:500]}`"
        )

        return jsonify({
            "error": str(e)
        }), 500


# ============================================================
# RECEPTION VIDEO
# ============================================================

@web_app.route("/api/video", methods=["POST"])
def receive_video():

    if not camera_authorized():

        terminer_capture_avec_erreur(
            "🔐 **Problème d'identification**\n"
            "Render a refusé l'envoi de la vidéo (HTTP 401)."
        )

        return jsonify({
            "error": "unauthorized"
        }), 401

    video_data = request.get_data()

    if not video_data:

        terminer_capture_avec_erreur(
            "🎥 **Vidéo vide**\n"
            "Aucune donnée vidéo n'a été reçue."
        )

        return jsonify({
            "error": "empty video"
        }), 400

    with camera_lock:

        capture = active_capture

        if capture is None or capture["type"] != "video":
            return jsonify({
                "error": "no active video request"
            }), 409

        channel_id = capture["channel_id"]

    mjpeg_path = None
    mp4_path = None

    try:

        with tempfile.NamedTemporaryFile(
            suffix=".mjpeg",
            delete=False
        ) as f:

            mjpeg_path = f.name
            f.write(video_data)

        mp4_path = mjpeg_path.replace(".mjpeg", ".mp4")

        cap = cv2.VideoCapture(mjpeg_path)

        if not cap.isOpened():
            raise Exception("Impossible de lire le fichier MJPEG.")

        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

        if width <= 0:
            width = 640

        if height <= 0:
            height = 480

        writer = cv2.VideoWriter(
            mp4_path,
            cv2.VideoWriter_fourcc(*"mp4v"),
            1.6,
            (width, height)
        )

        if not writer.isOpened():
            cap.release()
            raise Exception("Impossible de créer le fichier MP4.")

        frames = 0

        while True:

            ok, frame = cap.read()

            if not ok:
                break

            writer.write(frame)
            frames += 1

        cap.release()
        writer.release()

        if frames == 0:
            raise Exception("Aucune image exploitable dans la vidéo.")

        future = asyncio.run_coroutine_threadsafe(
            send_video_to_discord(channel_id, mp4_path),
            client.loop
        )

        future.result(timeout=120)

        terminer_capture_succes()

        return jsonify({
            "success": True,
            "frames": frames
        })

    except Exception as e:

        terminer_capture_avec_erreur(
            "🎥 **Échec du traitement vidéo**\n"
            f"**Détail :** `{str(e)[:500]}`"
        )

        return jsonify({
            "error": str(e)
        }), 500

    finally:

        for path in (mjpeg_path, mp4_path):

            if path:
                try:
                    os.remove(path)
                except OSError:
                    pass


# ============================================================
# BOT DISCORD
# ============================================================

class CameraBot(discord.Client):

    def __init__(self):

        super().__init__(
            intents=discord.Intents.default()
        )

        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):

        await self.tree.sync()

        print("Commandes Discord synchronisées")


client = CameraBot()


@client.event
async def on_ready():

    print(f"Connecté en tant que {client.user}")


# ============================================================
# /PHOTO
# ============================================================

@client.tree.command(
    name="photo",
    description="Prend une photo avec l'ESP32-CAM"
)
async def photo(interaction: discord.Interaction):

    success = creer_capture(
        "photo",
        interaction.channel_id
    )

    if not success:

        await interaction.response.send_message(
            "⏳ Une capture est déjà en cours."
        )

        return

    await interaction.response.send_message(
        "📷 Demande de photo envoyée.\n"
        "Je vais afficher les étapes du relais au fur et à mesure "
        "qu'il retrouve Internet."
    )

    print(f"PHOTO DEMANDEE : salon {interaction.channel_id}")


# ============================================================
# /10S
# ============================================================

@client.tree.command(
    name="10s",
    description="Enregistre 10 secondes de vidéo"
)
async def video10(interaction: discord.Interaction):

    success = creer_capture(
        "video",
        interaction.channel_id
    )

    if not success:

        await interaction.response.send_message(
            "⏳ Une capture est déjà en cours."
        )

        return

    await interaction.response.send_message(
        "🎥 Enregistrement de 10 secondes demandé."
    )


# ============================================================
# /DIRECT
# ============================================================

@client.tree.command(
    name="direct",
    description="Information sur le direct"
)
async def direct(interaction: discord.Interaction):

    await interaction.response.send_message(
        "📹 Le direct continu n'est pas encore activé. "
        "Utilise /10s pour enregistrer 10 secondes."
    )


# ============================================================
# /STOP
# ============================================================

@client.tree.command(
    name="stop",
    description="Arrête le direct"
)
async def stop(interaction: discord.Interaction):

    await interaction.response.send_message(
        "⏹️ Aucun direct continu actif."
    )


# ============================================================
# ENVOI PHOTO DISCORD
# ============================================================

async def send_photo_to_discord(channel_id, image_data):

    channel = client.get_channel(channel_id)

    if channel is None:
        channel = await client.fetch_channel(channel_id)

    image_file = discord.File(
        io.BytesIO(image_data),
        filename="photo.jpg"
    )

    await channel.send(
        content="📷 Photo de l'ESP32-CAM",
        file=image_file
    )


# ============================================================
# ENVOI VIDEO DISCORD
# ============================================================

async def send_video_to_discord(channel_id, video_path):

    channel = client.get_channel(channel_id)

    if channel is None:
        channel = await client.fetch_channel(channel_id)

    video_file = discord.File(
        video_path,
        filename="esp32cam_10s.mp4"
    )

    await channel.send(
        content="🎬 Vidéo de 10 secondes",
        file=video_file
    )


# ============================================================
# SERVEUR WEB
# ============================================================

def run_web():

    web_app.run(
        host="0.0.0.0",
        port=PORT,
        threaded=True
    )


# ============================================================
# DEMARRAGE
# ============================================================

if __name__ == "__main__":

    print("Demarrage du serveur...")

    Thread(
        target=run_web,
        daemon=True
    ).start()

    client.run(DISCORD_TOKEN)
