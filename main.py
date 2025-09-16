#main.py

import os
import asyncio
import discord

from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

# Récupération du token et de l'ID de guild depuis .env
TOKEN = os.getenv("TOKEN")
GUILD_ID_STR = os.getenv("GUILDID")

# Vérification basique
if not TOKEN:
    print("Erreur : Le TOKEN n'est pas défini dans le fichier .env")
    exit(1)

if not GUILD_ID_STR:
    print("Erreur : Le GUILDID n'est pas défini dans le fichier .env")
    exit(1)

try:
    GUILD_ID = int(GUILD_ID_STR)
except ValueError:
    print("Erreur : GUILDID n'est pas un nombre valide.")
    exit(1)

# Intents : activez ce dont vous avez besoin
intents = discord.Intents.default()
intents.message_content = True
# Pour compter correctement les membres, activez l'intent.members
# et cochez-le dans le portail développeur
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"Bot connecté en tant que {bot.user}")

    # Lancement de la tâche asynchrone pour mettre à jour le statut
    bot.loop.create_task(update_status_periodically())

    # Tentative de synchronisation des commandes slash
    try:
        # On synchronise uniquement sur la guilde définie (sync quasi-instantanée)
        guild = discord.Object(id=GUILD_ID)
        synced = await bot.tree.sync(guild=guild)
        print(f"Sync réussi ! {len(synced)} commande(s) synchronisée(s).")
    except Exception as e:
        print(f"Erreur lors de la synchronisation : {e}")

async def update_status_periodically():
    """Boucle pour mettre à jour le statut du bot à intervalle régulier."""
    while True:
        guild = bot.get_guild(GUILD_ID)
        if guild is not None:
            member_count = guild.member_count  # Nombre total de membres
            # Choix du type d'activité : watching, playing, listening, etc.
            await bot.change_presence(activity=discord.CustomActivity(name=f'👹 Joue à Atlas|Demon Slayer Rp'))
        else:
            print(f"Impossible de trouver la guilde avec l'ID {GUILD_ID}.")
        await asyncio.sleep(60)

async def main():
    cogs_list = [
        "cogs.ticket",
    ]

    # Chargement des cogs
    for cog in cogs_list:
        try:
            await bot.load_extension(cog)
            print(f"Extension chargée : {cog}")
        except discord.ext.commands.ExtensionFailed as e:
            print(f"Erreur de chargement pour {cog}: Échec de l'extension. Détails: {str(e)}")
        except Exception as e:
           print(f"Erreur de chargement pour {cog}: Erreur générale. Détails: {str(e)}")

    await bot.start(TOKEN)

if __name__ == "__main__":
    asyncio.run(main())