
import os
import io
import asyncio
import tempfile
from threading import Thread, Lock

import cv2
import discord
from discord import app_commands
from flask import Flask, request, jsonify


# ============================================================
# CONFIGURATION
# ============================================================

DISCORD_TOKEN = os.environ["DISCORD_TOKEN"]
CAMERA_SECRET = os.environ["CAMERA_SECRET"]

PORT = int(os.environ.get("PORT", 10000))


# ============================================================
# FLASK
# ============================================================

web_app = Flask(__name__)


# ============================================================
# VARIABLES
# ============================================================

camera_lock = Lock()

photo_requested = False
photo_channel_id = None

video_requested = False
video_channel_id = None


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

        <h1>🤖 ESP32-CAM Bot</h1>

        <p style="color:#00ff88;font-size:22px;">
            🟢 Bot opérationnel
        </p>

        <p>
            Discord : connecté
        </p>

        <p>
            ESP32-CAM : relais WROOM
        </p>

    </body>
    </html>
    """


# ============================================================
# AUTHENTIFICATION CAMERA
# ============================================================

def camera_authorized():

    secret = request.headers.get("X-Camera-Secret")

    return secret == CAMERA_SECRET


# ============================================================
# COMMANDE WROOM
# ============================================================

@web_app.route("/api/command", methods=["GET"])
def get_command():

    global photo_requested
    global video_requested

    if not camera_authorized():

        return jsonify({
            "error": "unauthorized"
        }), 401


    with camera_lock:

        # PHOTO
        if photo_requested:

            photo_requested = False

            print("📷 Commande PHOTO envoyée")

            return jsonify({
                "command": "photo"
            })


        # VIDEO 10 SECONDES
        if video_requested:

            video_requested = False

            print("🎥 Commande VIDEO envoyée")

            return jsonify({
                "command": "video10"
            })


    return jsonify({
        "command": "none"
    })


# ============================================================
# RECEPTION PHOTO
# ============================================================

@web_app.route("/api/photo", methods=["POST"])
def receive_photo():

    global photo_channel_id

    if not camera_authorized():

        return jsonify({
            "error": "unauthorized"
        }), 401


    image_data = request.get_data()

    if not image_data:

        return jsonify({
            "error": "empty photo"
        }), 400


    print(
        f"📷 Photo reçue : {len(image_data)} octets"
    )


    channel_id = photo_channel_id

    if channel_id is None:

        return jsonify({
            "error": "no Discord channel"
        }), 400


    future = asyncio.run_coroutine_threadsafe(
        send_photo_to_discord(
            channel_id,
            image_data
        ),
        client.loop
    )


    try:

        future.result(timeout=30)

        photo_channel_id = None

        print("✅ Photo envoyée sur Discord")

        return jsonify({
            "success": True
        })


    except Exception as e:

        print(
            f"❌ Erreur Discord : {e}"
        )

        return jsonify({
            "error": str(e)
        }), 500


# ============================================================
# RECEPTION VIDEO
# ============================================================

@web_app.route("/api/video", methods=["POST"])
def receive_video():

    global video_channel_id

    if not camera_authorized():

        return jsonify({
            "error": "unauthorized"
        }), 401


    video_data = request.get_data()

    if not video_data:

        return jsonify({
            "error": "empty video"
        }), 400


    print(
        f"🎥 Données vidéo reçues : "
        f"{len(video_data)} octets"
    )


    channel_id = video_channel_id

    if channel_id is None:

        return jsonify({
            "error": "no Discord channel"
        }), 400


    # --------------------------------------------------------
    # FICHIER MJPEG TEMPORAIRE
    # --------------------------------------------------------

    with tempfile.NamedTemporaryFile(
        suffix=".mjpeg",
        delete=False
    ) as f:

        mjpeg_path = f.name

        f.write(video_data)


    # --------------------------------------------------------
    # CONVERSION MJPEG -> MP4
    # --------------------------------------------------------

    mp4_path = mjpeg_path.replace(
        ".mjpeg",
        ".mp4"
    )


    try:

        cap = cv2.VideoCapture(
            mjpeg_path
        )


        if not cap.isOpened():

            print(
                "❌ Impossible de lire le MJPEG"
            )

            return jsonify({
                "error": "cannot read mjpeg"
            }), 500


        width = int(
            cap.get(
                cv2.CAP_PROP_FRAME_WIDTH
            )
        )

        height = int(
            cap.get(
                cv2.CAP_PROP_FRAME_HEIGHT
            )
        )


        if width <= 0:
            width = 640

        if height <= 0:
            height = 480


        # 5 FPS
        fps = 5.0


        fourcc = cv2.VideoWriter_fourcc(
            *"mp4v"
        )


        writer = cv2.VideoWriter(
            mp4_path,
            fourcc,
            fps,
            (width, height)
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


        print(
            f"🎬 Conversion terminée : "
            f"{frames} images"
        )


        if frames == 0:

            return jsonify({
                "error": "no frames"
            }), 500


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


        video_channel_id = None


        print(
            "✅ Vidéo envoyée sur Discord"
        )


        return jsonify({
            "success": True,
            "frames": frames
        })


    except Exception as e:

        print(
            f"❌ Erreur vidéo : {e}"
        )

        return jsonify({
            "error": str(e)
        }), 500


    finally:

        try:
            os.remove(mjpeg_path)
        except:
            pass

        try:
            os.remove(mp4_path)
        except:
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

        print(
            "✅ Commandes Discord synchronisées"
        )


client = CameraBot()


# ============================================================
# READY
# ============================================================

@client.event
async def on_ready():

    print(
        f"✅ Connecté en tant que {client.user}"
    )


# ============================================================
# /PHOTO
# ============================================================

@client.tree.command(
    name="photo",
    description="Prend une photo avec l'ESP32-CAM"
)
async def photo(
    interaction: discord.Interaction
):

    global photo_requested
    global photo_channel_id


    with camera_lock:

        if photo_requested or video_requested:

            await interaction.response.send_message(
                "⏳ Une capture est déjà en cours."
            )

            return


        photo_requested = True

        photo_channel_id = interaction.channel_id


    await interaction.response.send_message(
        "📷 Demande de photo envoyée..."
    )


# ============================================================
# /10S
# ============================================================

@client.tree.command(
    name="10s",
    description="Enregistre 10 secondes de vidéo"
)
async def video10(
    interaction: discord.Interaction
):

    global video_requested
    global video_channel_id


    with camera_lock:

        if photo_requested or video_requested:

            await interaction.response.send_message(
                "⏳ Une capture est déjà en cours."
            )

            return


        video_requested = True

        video_channel_id = interaction.channel_id


    await interaction.response.send_message(
        "🎥 Enregistrement de 10 secondes demandé..."
    )


    print(
        f"🎥 /10s demandé dans le salon "
        f"{interaction.channel_id}"
    )


# ============================================================
# /DIRECT
# ============================================================

@client.tree.command(
    name="direct",
    description="Information sur le direct"
)
async def direct(
    interaction: discord.Interaction
):

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
async def stop(
    interaction: discord.Interaction
):

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

    channel = client.get_channel(
        channel_id
    )


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

    channel = client.get_channel(
        channel_id
    )


    if channel is None:

        channel = await client.fetch_channel(
            channel_id
        )


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
        port=PORT
    )


# ============================================================
# DEMARRAGE
# ============================================================

if __name__ == "__main__":

    print(
        "🚀 Démarrage du serveur..."
    )

    Thread(
        target=run_web,
        daemon=True
    ).start()

    client.run(
        DISCORD_TOKEN
    )

