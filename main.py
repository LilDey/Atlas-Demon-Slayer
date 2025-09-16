import os
import asyncio
import discord

from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("TOKEN")
GUILD_ID_STR = os.getenv("GUILDID")

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

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"Bot connecté en tant que {bot.user}")
    bot.loop.create_task(update_status_periodically())
    try:
        guild = discord.Object(id=GUILD_ID)
        synced = await bot.tree.sync(guild=guild)
        print(f"Sync réussi ! {len(synced)} commande(s) synchronisée(s).")
    except Exception as e:
        print(f"Erreur lors de la synchronisation : {e}")

async def update_status_periodically():
    while True:
        guild = bot.get_guild(GUILD_ID)
        if guild is not None:
            member_count = guild.member_count
            await bot.change_presence(activity=discord.CustomActivity(name=f'👹 Joue à Atlas|Demon Slayer Rp'))
        else:
            print(f"Impossible de trouver la guilde avec l'ID {GUILD_ID}.")
        await asyncio.sleep(60)

async def main():
    cogs_list = [
        "cogs.ticket",
    ]

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
