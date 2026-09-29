```python
import os
import io
import asyncio
from threading import Thread, Lock

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
# VARIABLES CAMERA
# ============================================================

camera_lock = Lock()

photo_requested = False
photo_channel_id = None


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
        <meta name="viewport" content="width=device-width, initial-scale=1">

        <style>
            body {
                background: #111;
                color: white;
                font-family: Arial;
                text-align: center;
                padding-top: 80px;
            }

            .box {
                display: inline-block;
                background: #222;
                padding: 30px;
                border-radius: 20px;
            }

            .ok {
                color: #00ff88;
                font-size: 22px;
            }
        </style>
    </head>

    <body>

        <div class="box">

            <h1>🤖 ESP32-CAM Bot</h1>

            <p class="ok">
                🟢 Bot is running
            </p>

            <p>
                Discord : connecté
            </p>

            <p>
                Caméra : relais ESP32
            </p>

        </div>

    </body>
    </html>
    """


# ============================================================
# VERIFICATION SECRET
# ============================================================

def camera_authorized():

    secret = request.headers.get("X-Camera-Secret")

    return secret == CAMERA_SECRET


# ============================================================
# COMMANDE POUR LE WROOM
# ============================================================

@web_app.route("/api/command", methods=["GET"])
def get_command():

    global photo_requested

    if not camera_authorized():

        return jsonify({
            "error": "unauthorized"
        }), 401


    with camera_lock:

        if photo_requested:

            photo_requested = False

            print("📷 Commande PHOTO envoyée au WROOM")

            return jsonify({
                "command": "photo"
            })


    return jsonify({
        "command": "none"
    })


# ============================================================
# RECEPTION PHOTO DU WROOM
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

        print("❌ Aucun salon Discord associé")

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

        print(
            "✅ Photo envoyée sur Discord"
        )

        photo_channel_id = None

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
# BOT PRET
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

        if photo_requested:

            await interaction.response.send_message(
                "⏳ Une photo est déjà en cours."
            )

            return


        photo_requested = True

        photo_channel_id = interaction.channel_id


    await interaction.response.send_message(
        "📷 Demande envoyée à la caméra..."
    )


    print(
        f"📷 /photo demandé dans le salon "
        f"{interaction.channel_id}"
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
# COMMANDES TEMPORAIRES
# ============================================================

@client.tree.command(
    name="10",
    description="Récupère les 10 dernières secondes"
)
async def video_10(
    interaction: discord.Interaction
):

    await interaction.response.send_message(
        "🎥 Fonction vidéo pas encore activée."
    )


@client.tree.command(
    name="direct",
    description="Démarre le direct de la caméra"
)
async def direct(
    interaction: discord.Interaction
):

    await interaction.response.send_message(
        "📹 Fonction direct pas encore activée."
    )


@client.tree.command(
    name="stop",
    description="Arrête le direct"
)
async def stop(
    interaction: discord.Interaction
):

    await interaction.response.send_message(
        "⏹️ Direct pas encore activé."
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

    print("🚀 Démarrage du serveur...")

    Thread(
        target=run_web,
        daemon=True
    ).start()

    client.run(
        DISCORD_TOKEN
    )
```
