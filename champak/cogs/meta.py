"""The /help command."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from champak.ui import embeds


class Meta(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="help", description="What can this bot do?")
    async def help_command(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            embed=embeds.help_embed(), ephemeral=True
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Meta(bot))
