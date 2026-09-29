import os
from threading import Thread

import discord
from discord import app_commands
from flask import Flask

# =========================
# CONFIG
# =========================

TOKEN = os.environ["DISCORD_TOKEN"]
PORT = int(os.environ.get("PORT", 10000))

# =========================
# MINI INTERFACE WEB
# =========================

web_app = Flask(__name__)

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
                font-family: Arial, sans-serif;
                text-align: center;
                padding-top: 80px;
            }

            .box {
                display: inline-block;
                background: #222;
                padding: 30px;
                border-radius: 20px;
                box-shadow: 0 0 20px #000;
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
            <p class="ok">🟢 Bot is running</p>
            <p>Discord : connecté</p>
            <p>Caméra : en attente</p>
        </div>
    </body>
    </html>
    """

def run_web():
    web_app.run(
        host="0.0.0.0",
        port=PORT
    )

# =========================
# DISCORD BOT
# =========================

class CameraBot(discord.Client):

    def __init__(self):
        intents = discord.Intents.default()
        super().__init__(intents=intents)

        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        await self.tree.sync()


client = CameraBot()


@client.event
async def on_ready():
    print(f"Connecté en tant que {client.user}")


@client.tree.command(
    name="photo",
    description="Prend une photo avec l'ESP32-CAM"
)
async def photo(interaction: discord.Interaction):

    await interaction.response.send_message(
        "📷 Commande reçue ! La caméra sera connectée prochainement."
    )


@client.tree.command(
    name="10",
    description="Récupère les 10 dernières secondes"
)
async def video_10(interaction: discord.Interaction):

    await interaction.response.send_message(
        "🎥 Commande reçue ! Le système vidéo sera connecté prochainement."
    )


@client.tree.command(
    name="direct",
    description="Démarre le direct de la caméra"
)
async def direct(interaction: discord.Interaction):

    await interaction.response.send_message(
        "📹 Direct demandé !"
    )


@client.tree.command(
    name="stop",
    description="Arrête le direct"
)
async def stop(interaction: discord.Interaction):

    await interaction.response.send_message(
        "⏹️ Direct arrêté."
    )


# =========================
# LANCEMENT
# =========================

if __name__ == "__main__":

    # Lance la petite interface web
    Thread(
        target=run_web,
        daemon=True
    ).start()

    # Lance le bot Discord
    client.run(TOKEN)
