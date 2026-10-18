"""Slash command for creating a local Seerr account (1 per Discord user)."""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from ..linking import LinkStatus

if TYPE_CHECKING:
    from ..bot import VaultRequestrr

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class RegisterModal(discord.ui.Modal, title="Create Local Seerr Account"):
    username = discord.ui.TextInput(
        label="Username",
        placeholder="Choose a username",
        min_length=3,
        max_length=32,
        required=True,
    )
    email = discord.ui.TextInput(
        label="Email Address",
        placeholder="you@example.com",
        max_length=120,
        required=True,
    )
    password = discord.ui.TextInput(
        label="Password",
        placeholder="Minimum 8 characters",
        min_length=8,
        max_length=64,
        required=True,
    )

    def __init__(self, bot: "VaultRequestrr") -> None:
        super().__init__()
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        discord_id = str(interaction.user.id)
        uname = self.username.value.strip()
        mail = self.email.value.strip()
        pwd = self.password.value

        if not _EMAIL_RE.match(mail):
            await interaction.followup.send(
                "❌ Please enter a valid email address.", ephemeral=True
            )
            return

        result = await self.bot.linker.register_local(
            discord_id=discord_id,
            username=uname,
            email=mail,
            password=pwd,
        )

        if result.status is LinkStatus.LINKED:
            await interaction.followup.send(
                f"✅ Local account **{uname}** (`{mail}`) has been created and linked to your Discord account!\n"
                f"You can now sign in at <{self.bot.seerr_url}> or use `/request` right here.",
                ephemeral=True,
            )
            return

        await interaction.followup.send(
            f"❌ {result.message or 'Could not create your local account.'}",
            ephemeral=True,
        )


class AccountCog(commands.Cog):
    def __init__(self, bot: "VaultRequestrr") -> None:
        self.bot = bot

    @app_commands.command(
        name="register",
        description="Create a local Seerr account and link it to your Discord (limit 1 per user)",
    )
    async def register(self, interaction: discord.Interaction) -> None:
        discord_id = str(interaction.user.id)

        existing_created = await self.bot.store.get_local_account(discord_id)
        if existing_created is not None:
            await interaction.response.send_message(
                f"❌ You have already created a local account (`{existing_created.username}`). "
                "Limit is one per Discord user.",
                ephemeral=True,
            )
            return

        existing_link = await self.bot.store.get(discord_id)
        if existing_link is not None:
            who = existing_link.plex_username or existing_link.email or f"#{existing_link.seerr_user_id}"
            await interaction.response.send_message(
                f"❌ Your Discord account is already linked to Seerr user **{who}**.",
                ephemeral=True,
            )
            return

        await interaction.response.send_modal(RegisterModal(self.bot))