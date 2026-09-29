import os
import discord
from discord import app_commands

TOKEN = os.environ["DISCORD_TOKEN"]

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


@client.tree.command(name="photo", description="Prend une photo avec l'ESP32-CAM")
async def photo(interaction: discord.Interaction):
    await interaction.response.send_message(
        "📷 Commande reçue ! La caméra sera connectée prochainement."
    )


@client.tree.command(name="10", description="Récupère les 10 dernières secondes")
async def video_10(interaction: discord.Interaction):
    await interaction.response.send_message(
        "🎥 Commande reçue ! Le système vidéo sera connecté prochainement."
    )


@client.tree.command(name="direct", description="Démarre le direct de la caméra")
async def direct(interaction: discord.Interaction):
    await interaction.response.send_message(
        "📹 Direct demandé !"
    )


@client.tree.command(name="stop", description="Arrête le direct")
async def stop(interaction: discord.Interaction):
    await interaction.response.send_message(
        "⏹️ Direct arrêté."
    )


client.run(TOKEN)
