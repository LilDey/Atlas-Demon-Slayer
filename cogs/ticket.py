# Ticket.py
# -*- coding: utf-8 -*-

import os
from io import BytesIO
from typing import Optional, Dict, List
from datetime import datetime

import aiohttp  # pour les webhooks
import discord
from discord.ext import commands
from discord import app_commands

# =========================
# 🔧 CONFIG
# =========================
GUILD_ID = int(os.getenv("GUILDID", 0))           # ta guilde
LOGS_CHANNEL_ID = 1406806852536107088             # salon logs (fallback)
TICKET_LOGS_WEBHOOK_URL = os.getenv("TICKET_LOGS_WEBHOOK_URL", "")  # URL webhook logs

CUSTOM_EMOJI_ID = 1398652125180854382             # emoji perso (ID)

# Catégories par type de ticket (remplace les 0 par tes vraies catégories)
TICKET_CATEGORIES: Dict[str, int] = {
    "Plainte": 1406833167385624646,
    "Question": 0,
    "Boutique": 0,
    "Candidature Staff": 0,
    "Candidature RP": 0,
    "Autre": 0,
}

ROLE_TO_PING: Optional[int] = None   # ex: 123456789012345678 ou None
BANNER_URL: Optional[str] = None     # image en haut de l'embed, ou None
EMBED_COLOR = discord.Color.dark_grey()

# Options du menu
REASON_OPTIONS = [
    ("Plainte", "Problème / plainte / restitution", "📣"),
    ("Question", "Question générale / aide", "❓"),
    ("Boutique", "Achat / don / boutique", "🛍️"),
    ("Candidature Staff", "Postuler au staff", "🛡️"),
    ("Candidature RP", "Postuler pour une naissance RP", "🎭"),
    ("Autre", "Autre demande", "🗂️"),
]

# =========================
# 🧠 États en mémoire
# =========================
class TicketState:
    def __init__(self, user_id: int, channel_id: int, reason: str):
        self.user_id = user_id
        self.channel_id = channel_id
        self.reason = reason
        # Chaque entrée : {"by": str, "content": str, "ts": datetime, "internal": bool, "is_attachment": bool}
        self.transcript: List[dict] = []
        self.opened_at = datetime.utcnow()

ACTIVE_TICKETS: Dict[int, TicketState] = {}
CHANNEL_TO_USER: Dict[int, int] = {}

# Historique global des commentaires (par joueur)
USER_COMMENTS: Dict[int, List[dict]] = {}  # {user_id: [{"by": str, "content": str, "ts": datetime, "channel_id": int}]}

# =========================
# 🛠️ Helpers
# =========================
def get_emoji_markup(bot: commands.Bot, guild: Optional[discord.Guild], emoji_id: int) -> str:
    if not emoji_id:
        return ""
    em = bot.get_emoji(emoji_id)
    if not em and guild:
        em = guild.get_emoji(emoji_id)
    return str(em) if em else ""

def build_open_panel_description(emoji_str: str) -> str:
    head = f"# {emoji_str} Ouvrir un ticket via le bot admin\n\n" if emoji_str else "# Ouvrir un ticket \n\n"
    body = (
        "**Comment ça marche ?**\n"
        "> 1️⃣ **Choisis la catégorie** de ton ticket dans le menu.\n"
        "> 2️⃣ Une fenêtre s’ouvrira → **explique ta demande** (100 caractères max).\n"
        "> 3️⃣ Tu recevras un **DM** du bot : continue la discussion là-bas.\n\n"
        "**Prévention**\n"
        "> • Si tes MP sont fermés, ouvre-les : **Paramètres utilisateur → Contenu et social → Messages privés.**"
    )
    return head + body

def build_comments_embed(user_id: int, guild: Optional[discord.Guild], limit: int = 10) -> Optional[discord.Embed]:
    items = USER_COMMENTS.get(user_id, [])
    if not items:
        return None
    items_sorted = sorted(items, key=lambda x: x["ts"], reverse=True)[:limit]
    lines = []
    for it in items_sorted:
        when = it["ts"].strftime("%Y-%m-%d %H:%M")
        who = it["by"]
        txt = it["content"]
        ch = guild.get_channel(it["channel_id"]) if guild else None
        suffix = f" • #{ch.name}" if isinstance(ch, discord.TextChannel) else ""
        lines.append(f"• **{when} UTC** — par **{who}** : {txt}{suffix}")
    embed = discord.Embed(
        title=f"Historique des commentaires ({len(items)} au total)",
        description="\n".join(lines) if lines else "*Aucun commentaire*",
        color=discord.Color.blurple()
    )
    embed.set_footer(text="Commentaires ajoutés via /commentaire (notes internes)")
    return embed

# =========================
# 📨 Logs via Webhook — MONO-MESSAGE
# =========================
async def send_logs_via_webhook(bot: commands.Bot,
                                state: TicketState,
                                user: Optional[discord.User],
                                guild: discord.Guild,
                                channel: discord.TextChannel):
    """
    Envoie le transcript dans UN SEUL message :
      - 1 embed (description = transcript en bloc code)
      - si trop long, embed tronqué + pièce jointe .txt (toujours un seul message)
    Fallback: même logique dans LOGS_CHANNEL_ID.
    """
    # Construire le transcript (texte brut)
    lines: list[str] = []
    for m in state.transcript:
        ts = m["ts"].strftime("%Y-%m-%d %H:%M:%S")
        by = m["by"]
        content = (m.get("content") or "").strip()
        internal = m.get("internal", False)
        is_att = m.get("is_attachment", False)
        tag_note = " [note]" if internal else ""
        tag_file = " [fichier]" if is_att else ""
        lines.append(f"[{ts} UTC]{tag_note}{tag_file} {by}: {content}")

    full_text_only = "\n".join(lines)
    embed_body_full = f"```txt\n{full_text_only}\n```"
    MAX_DESC = 4000  # marge sous 4096

    def build_embed(desc: str, truncated: bool) -> discord.Embed:
        e = discord.Embed(
            title="🧾 Transcript Ticket",
            description=desc,
            color=discord.Color.dark_gray()
        )
        e.add_field(name="Joueur", value=(user.mention if user else str(state.user_id)), inline=True)
        e.add_field(name="Salon", value=f"#{channel.name}", inline=True)
        e.add_field(name="Raison", value=state.reason, inline=False)
        e.add_field(name="Ouvert (UTC)", value=state.opened_at.strftime("%Y-%m-%d %H:%M:%S"), inline=True)
        e.add_field(name="Fermé (UTC)", value=datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"), inline=True)
        e.add_field(name="Messages", value=str(len(state.transcript)), inline=True)
        if truncated:
            e.add_field(name="Note", value="Transcript tronqué dans l’embed. Le fichier joint contient l’intégralité.", inline=False)
        return e

    file_to_attach = None
    if len(embed_body_full) <= MAX_DESC:
        embed = build_embed(embed_body_full, truncated=False)
    else:
        # Tronquer en respectant les lignes
        used, acc = 0, []
        for line in (full_text_only + "\n").splitlines(True):
            if used + len(line) > MAX_DESC - 50:
                break
            acc.append(line)
            used += len(line)
        remaining_lines = max(0, len(full_text_only.splitlines()) - len("".join(acc).splitlines()))
        truncated_body = "".join(acc).rstrip() + f"\n… (+{remaining_lines} lignes masquées)"
        embed = build_embed(f"```txt\n{truncated_body}\n```", truncated=True)

        # Joindre le .txt complet
        buf = BytesIO()
        header = (
            f"Transcript Ticket — {guild.name}\n"
            f"Joueur: {user.name if user else state.user_id} | Salon: #{channel.name}\n"
            f"Raison: {state.reason}\n"
            f"Ouvert (UTC): {state.opened_at:%Y-%m-%d %H:%M:%S} | "
            f"Fermé (UTC): {datetime.utcnow():%Y-%m-%d %H:%M:%S}\n"
            f"Messages: {len(state.transcript)}\n"
            + "-"*50 + "\n"
        )
        buf.write((header + full_text_only + "\n").encode("utf-8"))
        buf.seek(0)
        file_to_attach = discord.File(buf, filename=f"ticket-{state.user_id}.txt")

    async def _send_via_webhook():
        async with aiohttp.ClientSession() as session:
            webhook = discord.Webhook.from_url(TICKET_LOGS_WEBHOOK_URL, session=session)
            if file_to_attach:
                await webhook.send(embed=embed, file=file_to_attach, username="Ticket Logs")
            else:
                await webhook.send(embed=embed, username="Ticket Logs")

    async def _fallback_to_channel():
        log_ch = bot.get_channel(LOGS_CHANNEL_ID)
        if not isinstance(log_ch, discord.TextChannel):
            return
        if file_to_attach:
            await log_ch.send(embed=embed, file=file_to_attach)
        else:
            await log_ch.send(embed=embed)

    if TICKET_LOGS_WEBHOOK_URL:
        try:
            await _send_via_webhook()
            return
        except Exception:
            await _fallback_to_channel()
    else:
        await _fallback_to_channel()

# =========================
# 🧩 UI Discord (Views / Modals)
# =========================
class ReasonModal(discord.ui.Modal, title="Ouvrir un ticket"):
    def __init__(self, reason_label: str):
        super().__init__()
        self.reason_label = reason_label
        self.raison = discord.ui.TextInput(
            label="Explique ta demande",
            placeholder="Rédige ta raison (max 100 caractères)...",
            style=discord.TextStyle.short,
            max_length=100,
            required=True
        )
        self.add_item(self.raison)

    async def on_submit(self, interaction: discord.Interaction):
        reason = self.reason_label
        detail = self.raison.value.strip()

        # Anti-doublon : un ticket à la fois par joueur
        existing = ACTIVE_TICKETS.get(interaction.user.id)
        if existing:
            existing_ch = interaction.guild.get_channel(existing.channel_id) if interaction.guild else None
            if isinstance(existing_ch, discord.TextChannel):
                return await interaction.response.send_message(
                    f"⚠️ Tu as déjà un ticket ouvert : {existing_ch.mention}. Merci d’utiliser celui-ci.",
                    ephemeral=True
                )
            else:
                ACTIVE_TICKETS.pop(interaction.user.id, None)

        category_id = TICKET_CATEGORIES.get(reason, 0)
        if not category_id:
            return await interaction.response.send_message("⚠️ Catégorie non configurée.", ephemeral=True)

        category = interaction.guild.get_channel(category_id)
        if not isinstance(category, discord.CategoryChannel):
            return await interaction.response.send_message("⚠️ Catégorie introuvable.", ephemeral=True)

        overwrites = {interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False)}
        if ROLE_TO_PING:
            role = interaction.guild.get_role(int(ROLE_TO_PING))
            if role:
                overwrites[role] = discord.PermissionOverwrite(
                    view_channel=True, send_messages=True, read_message_history=True
                )

        ch = await category.create_text_channel(
            name=f"ticket-{interaction.user.name}-{interaction.user.discriminator}",
            overwrites=overwrites,
            topic=f"Ticket de {interaction.user} — {reason} : {detail}"
        )

        state = TicketState(interaction.user.id, ch.id, f"{reason} — {detail}")
        ACTIVE_TICKETS[interaction.user.id] = state
        CHANNEL_TO_USER[ch.id] = interaction.user.id

        # Emoji dynamique
        emoji_str = get_emoji_markup(interaction.client, interaction.guild, CUSTOM_EMOJI_ID)

        # Message d'ouverture côté staff
        view = TicketAdminView()
        await ch.send(
            f"{emoji_str + ' ' if emoji_str else ''}**Nouveau ticket** — {interaction.user.mention}\n"
            f"**Catégorie :** {reason}\n"
            f"**Raison :** {detail}",
            view=view
        )

        # Récap des commentaires historiques pour ce joueur
        recap = build_comments_embed(interaction.user.id, interaction.guild, limit=10)
        if recap:
            await ch.send(embed=recap)

        # ---------- DM joueur (EN EMBED) ----------
        try:
            dm_embed = discord.Embed(
                title="✅ Ticket créé",
                description="Ton ticket a été ouvert. Tu peux répondre à ce message pour discuter avec le staff.",
                color=discord.Color.green()
            )
            dm_embed.add_field(name="Catégorie", value=reason, inline=True)
            dm_embed.add_field(name="Raison", value=detail or "*Non précisé*", inline=False)
            dm_embed.set_footer(text=f"{interaction.guild.name} • {datetime.utcnow().strftime('%d/%m/%Y %H:%M UTC')}")
            if BANNER_URL:
                dm_embed.set_image(url=BANNER_URL)
            await interaction.user.send(embed=dm_embed)
        except discord.Forbidden:
            await interaction.response.send_message("⚠️ Impossible d’envoyer un DM (MP fermés).", ephemeral=True)
            return

        await interaction.response.send_message("✅ Ticket créé. Vérifie tes DM.", ephemeral=True)


class ReasonSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label=label, description=desc, emoji=emoji)
            for (label, desc, emoji) in REASON_OPTIONS
        ]
        super().__init__(placeholder="Sélectionnez la catégorie…", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        choice = self.values[0]
        await interaction.response.send_modal(ReasonModal(choice))


class TicketOpenView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(ReasonSelect())


class TicketAdminView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Fermer le ticket", style=discord.ButtonStyle.red, emoji="🗑️")
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = CHANNEL_TO_USER.get(interaction.channel.id)
        if not user_id:
            return await interaction.response.send_message("Ticket introuvable.", ephemeral=True)

        state = ACTIVE_TICKETS.get(user_id)
        user = interaction.client.get_user(user_id) or await interaction.client.fetch_user(user_id)

        # Envoi des logs via webhook (mono-message)
        try:
            await send_logs_via_webhook(interaction.client, state, user, interaction.guild, interaction.channel)  # type: ignore
        except Exception:
            pass

        # ---------- DM de clôture (EN EMBED) ----------
        if user:
            try:
                dm_close = discord.Embed(
                    title="🗂️ Ticket fermé",
                    description="Merci d’avoir contacté le staff. N’hésite pas à rouvrir un ticket si besoin.",
                    color=discord.Color.dark_gray()
                )
                dm_close.add_field(name="Résumé", value=state.reason, inline=False)
                dm_close.set_footer(text=f"{interaction.guild.name} • {datetime.utcnow().strftime('%d/%m/%Y %H:%M UTC')}")
                if BANNER_URL:
                    dm_close.set_image(url=BANNER_URL)
                await user.send(embed=dm_close)
            except discord.Forbidden:
                pass

        # Nettoyage
        ACTIVE_TICKETS.pop(user_id, None)
        CHANNEL_TO_USER.pop(interaction.channel.id, None)
        await interaction.channel.delete(reason="Ticket fermé")

# =========================
# 🧩 Cog principal
# =========================
class Ticket(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # Commande texte admin pour poster le panneau
    @commands.command(name="ticket")
    @commands.has_permissions(administrator=True)
    async def ticket_panel(self, ctx: commands.Context):
        emoji_str = get_emoji_markup(self.bot, ctx.guild, CUSTOM_EMOJI_ID)
        desc = build_open_panel_description(emoji_str)

        embed = discord.Embed(description=desc, color=EMBED_COLOR)
        if BANNER_URL:
            embed.set_image(url=BANNER_URL)
        embed.set_footer(text=f"{ctx.guild.name} • {datetime.utcnow().strftime('%d/%m/%Y %H:%M UTC')}")
        await ctx.send(embed=embed, view=TicketOpenView())

    # Slash command guild-only (ajout de note interne)
    @app_commands.command(name="commentaire", description="Ajoute un commentaire interne au ticket (non envoyé au joueur).")
    @app_commands.checks.has_permissions(manage_messages=True)
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def commentaire(self, interaction: discord.Interaction, texte: str):
        if not isinstance(interaction.channel, discord.TextChannel):
            return await interaction.response.send_message("Utilise cette commande dans un salon de ticket.", ephemeral=True)

        user_id = CHANNEL_TO_USER.get(interaction.channel.id)
        if not user_id:
            return await interaction.response.send_message("Ce salon n'est pas lié à un ticket actif.", ephemeral=True)

        state = ACTIVE_TICKETS.get(user_id)
        if not state:
            return await interaction.response.send_message("Ticket introuvable.", ephemeral=True)

        USER_COMMENTS.setdefault(user_id, []).append({
            "by": str(interaction.user),
            "content": texte,
            "ts": datetime.utcnow(),
            "channel_id": interaction.channel.id
        })

        state.transcript.append({
            "by": f"{interaction.user} (note)",
            "content": texte,
            "ts": datetime.utcnow(),
            "internal": True,
            "is_attachment": False
        })

        await interaction.response.send_message("📝 Commentaire ajouté (note interne liée au joueur).", ephemeral=True)
        await interaction.channel.send(f"📝 **Note interne par {interaction.user.mention}** : {texte}")

    # -------- Relais messages DM <-> salon --------
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        # Joueur -> DM au bot
        if isinstance(message.channel, discord.DMChannel):
            state = ACTIVE_TICKETS.get(message.author.id)
            if not state:
                return
            guild = self.bot.get_guild(GUILD_ID)
            if not guild:
                return
            ch = guild.get_channel(state.channel_id)
            if not isinstance(ch, discord.TextChannel):
                return

            # texte
            if message.content:
                state.transcript.append({
                    "by": str(message.author),
                    "content": message.content,
                    "ts": datetime.utcnow(),
                    "internal": False,
                    "is_attachment": False
                })
                await ch.send(f"**{message.author} (joueur)** : {message.content}")

            # pièces jointes
            for att in message.attachments:
                state.transcript.append({
                    "by": str(message.author),
                    "content": att.url,
                    "ts": datetime.utcnow(),
                    "internal": False,
                    "is_attachment": True
                })
                await ch.send(att.url)

        # Staff -> salon ticket
        elif isinstance(message.channel, discord.TextChannel):
            user_id = CHANNEL_TO_USER.get(message.channel.id)
            if not user_id:
                return
            if message.content.startswith(("/", "!")):
                return

            user = self.bot.get_user(user_id) or await self.bot.fetch_user(user_id)
            state = ACTIVE_TICKETS.get(user_id)
            if not user or not state:
                return

            # texte
            if message.content:
                state.transcript.append({
                    "by": f"{message.author} (staff)",
                    "content": message.content,
                    "ts": datetime.utcnow(),
                    "internal": False,
                    "is_attachment": False
                })
                try:
                    await user.send(f"**{message.author} (staff)** : {message.content}")
                except discord.Forbidden:
                    await message.channel.send("⚠️ Impossible d’envoyer un DM au joueur (MP fermés).")

            # pièces jointes
            for att in message.attachments:
                state.transcript.append({
                    "by": f"{message.author} (staff)",
                    "content": att.url,
                    "ts": datetime.utcnow(),
                    "internal": False,
                    "is_attachment": True
                })
                try:
                    await user.send(att.url)
                except discord.Forbidden:
                    pass
                # inutile de renvoyer l'URL dans le salon (le message original a déjà la pièce jointe)

    @commands.Cog.listener()
    async def on_ready(self):
        # Vues persistantes
        try:
            self.bot.add_view(TicketOpenView())
            self.bot.add_view(TicketAdminView())
        except Exception:
            pass

async def setup(bot: commands.Bot):
    await bot.add_cog(Ticket(bot))
