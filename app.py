
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
    raise RuntimeError("La variable CAMERA_SECRET est absente sur Render.")


# ============================================================
# FLASK
# ============================================================

web_app = Flask(__name__)


# ============================================================
# VARIABLES
# ============================================================

camera_lock = Lock()

active_capture = None
capture_timer = None


# ============================================================
# AUTHENTIFICATION CAMERA
# ============================================================

def camera_authorized():

    secret = request.headers.get("X-Camera-Secret", "")

    return hmac.compare_digest(
        secret,
        CAMERA_SECRET
    )


# ============================================================
# NOTIFICATION DISCORD
# ============================================================

async def envoyer_message_erreur(channel_id, message):

    channel = client.get_channel(channel_id)

    if channel is None:
        channel = await client.fetch_channel(channel_id)

    await channel.send(
        f"⚠️ **PROBLEME AVEC LA CAMERA**\n\n{message}"
    )


def envoyer_erreur_discord(channel_id, message):

    if channel_id is None:
        return

    try:

        future = asyncio.run_coroutine_threadsafe(
            envoyer_message_erreur(channel_id, message),
            client.loop
        )

        future.result(timeout=20)

    except Exception as e:

        print(f"Erreur notification Discord : {e}")


# ============================================================
# FIN DE CAPTURE
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
        print("Capture terminee avec succes.")


# ============================================================
# DELAI MAXIMAL DE CAPTURE
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

    if capture["type"] == "photo":

        message = (
            "⏱️ **Delai depasse**\n"
            "L'ESP32 n'a pas termine la prise ou l'envoi "
            "de la photo dans le temps imparti.\n"
            "Verifie sa connexion Wi-Fi et son fonctionnement."
        )

    else:

        message = (
            "⏱️ **Delai depasse**\n"
            "L'ESP32 n'a pas termine l'enregistrement ou "
            "l'envoi de la video dans le temps imparti."
        )

    envoyer_erreur_discord(
        capture["channel_id"],
        message
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
            Bot operationnel
        </p>

        <p>Discord : connecte</p>
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

        print("ERREUR : identification ESP32 refusee")

        terminer_capture_avec_erreur(
            "🔐 **Probleme d'identification**\n"
            "Render a refuse la connexion de l'ESP32 (HTTP 401).\n"
            "Le secret envoye par l'ESP32 ne correspond pas "
            "a CAMERA_SECRET configure sur Render.\n"
            "Verifie les deux valeurs."
        )

        return jsonify({
            "error": "unauthorized",
            "message": "Camera authentication failed"
        }), 401

    with camera_lock:

        if active_capture is None:

            return jsonify({
                "command": "none"
            })

        if active_capture["delivered"]:

            return jsonify({
                "command": "none"
            })

        active_capture["delivered"] = True

        capture_type = active_capture["type"]

    if capture_type == "photo":

        print("Commande PHOTO envoyee")

        return jsonify({
            "command": "photo"
        })

    if capture_type == "video":

        print("Commande VIDEO envoyee")

        return jsonify({
            "command": "video10"
        })

    return jsonify({
        "command": "none"
    })


# ============================================================
# RECEPTION DES ERREURS DE L'ESP32
# ============================================================

@web_app.route("/api/error", methods=["POST"])
def receive_error():

    if not camera_authorized():

        terminer_capture_avec_erreur(
            "🔐 **Probleme d'identification**\n"
            "L'ESP32 a ete refuse par Render (HTTP 401)."
        )

        return jsonify({
            "error": "unauthorized"
        }), 401

    data = request.get_json(silent=True) or {}

    code = str(data.get("code", "unknown"))
    detail = str(data.get("detail", "Aucun detail fourni"))

    erreurs = {

        "camera_connection":
            "📡 Impossible de se connecter au reseau Wi-Fi de la camera.",

        "camera_capture":
            "📷 La camera n'a pas reussi a prendre une photo.",

        "camera_http":
            "🌐 La camera a renvoye une erreur HTTP.",

        "render_connection":
            "🌐 Impossible de contacter le serveur Render.",

        "photo_download":
            "📥 Impossible de telecharger la photo depuis la camera.",

        "photo_upload":
            "📤 Impossible d'envoyer la photo vers Render.",

        "memory":
            "🧠 Memoire insuffisante sur l'ESP32.",

        "unknown":
            "❓ Une erreur inconnue s'est produite."
    }

    description = erreurs.get(
        code,
        erreurs["unknown"]
    )

    print(f"ERREUR ESP32 : {code} - {detail}")

    terminer_capture_avec_erreur(
        f"{description}\n\n"
        f"**Code :** `{code}`\n"
        f"**Detail technique :** `{detail[:500]}`"
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
            "🔐 **Probleme d'identification**\n"
            "Render a refuse l'envoi de la photo (HTTP 401).\n"
            "Verifie CAMERA_SECRET sur Render et dans l'ESP32."
        )

        return jsonify({
            "error": "unauthorized"
        }), 401

    image_data = request.get_data()

    if not image_data:

        terminer_capture_avec_erreur(
            "📷 **Photo vide**\n"
            "L'ESP32 a contacte Render, mais aucune image n'a ete recue."
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
            "📤 **Echec de l'envoi Discord**\n"
            "La photo a ete recue par Render, mais Discord "
            "n'a pas reussi a la publier.\n\n"
            f"**Detail :** `{str(e)[:500]}`"
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
            "🔐 **Probleme d'identification**\n"
            "Render a refuse l'envoi de la video (HTTP 401)."
        )

        return jsonify({
            "error": "unauthorized"
        }), 401

    video_data = request.get_data()

    if not video_data:

        terminer_capture_avec_erreur(
            "🎥 **Video vide**\n"
            "Aucune donnee video n'a ete recue."
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

    print(f"VIDEO RECUE : {len(video_data)} octets")

    mjpeg_path = None
    mp4_path = None

    try:

        # ----------------------------------------------------
        # FICHIER MJPEG TEMPORAIRE
        # ----------------------------------------------------

        with tempfile.NamedTemporaryFile(
            suffix=".mjpeg",
            delete=False
        ) as f:

            mjpeg_path = f.name
            f.write(video_data)

        # ----------------------------------------------------
        # CONVERSION MJPEG -> MP4
        # ----------------------------------------------------

        mp4_path = mjpeg_path.replace(
            ".mjpeg",
            ".mp4"
        )

        cap = cv2.VideoCapture(mjpeg_path)

        if not cap.isOpened():

            raise Exception(
                "Impossible de lire le fichier MJPEG."
            )

        width = int(
            cap.get(cv2.CAP_PROP_FRAME_WIDTH)
        )

        height = int(
            cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
        )

        if width <= 0:
            width = 640

        if height <= 0:
            height = 480

        fps = 1.6

        fourcc = cv2.VideoWriter_fourcc(*"mp4v")

        writer = cv2.VideoWriter(
            mp4_path,
            fourcc,
            fps,
            (width, height)
        )

        if not writer.isOpened():

            cap.release()

            raise Exception(
                "Impossible de creer le fichier MP4."
            )

        frames = 0

        while True:

            ok, frame = cap.read()

            if not ok:
                break

            writer.write(frame)
            frames += 1

        cap.release()
        writer.release()

        print(f"CONVERSION VIDEO : {frames} images")

        if frames == 0:

            raise Exception(
                "Aucune image exploitable dans la video."
            )

        # ----------------------------------------------------
        # ENVOI DISCORD
        # ----------------------------------------------------

        future = asyncio.run_coroutine_threadsafe(
            send_video_to_discord(
                channel_id,
                mp4_path
            ),
            client.loop
        )

        future.result(timeout=120)

        terminer_capture_succes()

        print("VIDEO ENVOYEE SUR DISCORD")

        return jsonify({
            "success": True,
            "frames": frames
        })

    except Exception as e:

        print("ERREUR VIDEO :", e)

        terminer_capture_avec_erreur(
            "🎥 **Echec du traitement video**\n"
            "Render n'a pas reussi a convertir ou envoyer la video.\n\n"
            f"**Detail :** `{str(e)[:500]}`"
        )

        return jsonify({
            "error": str(e)
        }), 500

    finally:

        if mjpeg_path:

            try:
                os.remove(mjpeg_path)
            except OSError:
                pass

        if mp4_path:

            try:
                os.remove(mp4_path)
            except OSError:
                pass


# ============================================================
# BOT DISCORD
# ============================================================

class CameraBot(discord.Client):

    def __init__(self):

        intents = discord.Intents.default()

        super().__init__(
            intents=intents
        )

        self.tree = app_commands.CommandTree(
            self
        )

    async def setup_hook(self):

        await self.tree.sync()

        print("Commandes Discord synchronisees")


client = CameraBot()


# ============================================================
# READY
# ============================================================

@client.event
async def on_ready():

    print(
        f"Connecte en tant que {client.user}"
    )


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
            "⏳ Une capture est deja en cours."
        )

        return

    await interaction.response.send_message(
        "📷 Demande de photo envoyee.\n"
        "J'attends la reponse de la camera..."
    )

    print(
        f"PHOTO DEMANDEE dans le salon {interaction.channel_id}"
    )


# ============================================================
# /10S
# ============================================================

@client.tree.command(
    name="10s",
    description="Enregistre 10 secondes de video"
)
async def video10(interaction: discord.Interaction):

    success = creer_capture(
        "video",
        interaction.channel_id
    )

    if not success:

        await interaction.response.send_message(
            "⏳ Une capture est deja en cours."
        )

        return

    await interaction.response.send_message(
        "🎥 Enregistrement de 10 secondes demande.\n"
        "J'attends la reponse de la camera..."
    )

    print(
        f"VIDEO DEMANDEE dans le salon {interaction.channel_id}"
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
        "📹 Le direct continu n'est pas encore active.\n"
        "Utilise /10s pour enregistrer 10 secondes."
    )


# ============================================================
# /STOP
# ============================================================

@client.tree.command(
    name="stop",
    description="Arrete le direct"
)
async def stop(interaction: discord.Interaction):

    await interaction.response.send_message(
        "⏹️ Aucun direct continu actif."
    )


# ============================================================
# ENVOI PHOTO DISCORD
# ============================================================

async def send_photo_to_discord(
    channel_id,
    image_data
):

    channel = client.get_channel(channel_id)

    if channel is None:

        channel = await client.fetch_channel(
            channel_id
        )

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

async def send_video_to_discord(
    channel_id,
    video_path
):

    channel = client.get_channel(channel_id)

    if channel is None:

        channel = await client.fetch_channel(
            channel_id
        )

    video_file = discord.File(
        video_path,
        filename="esp32cam_10s.mp4"
    )

    await channel.send(
        content="🎬 Video de 10 secondes",
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

    client.run(
        DISCORD_TOKEN
    )
