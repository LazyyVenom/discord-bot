"""Resource sharing commands."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from champak.services.resources import (
    InvalidResource,
    add_resource,
    list_resource_categories,
    random_resource,
)
from champak.ui import embeds


class Resources(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def category_autocomplete(self, interaction: discord.Interaction, current: str):
        async with self.bot.session() as session:
            names = await list_resource_categories(session)
        matches = [n for n in names if current.lower() in n.lower()][:25]
        return [app_commands.Choice(name=n, value=n) for n in matches]

    @app_commands.command(name="resource", description="Get a random dev resource")
    @app_commands.describe(category="Narrow it to one topic")
    @app_commands.autocomplete(category=category_autocomplete)
    async def resource(
        self, interaction: discord.Interaction, category: str | None = None
    ):
        async with self.bot.session() as session:
            found = await random_resource(session, category)

        if found is None:
            scope = f" in **{category}**" if category else ""
            await interaction.response.send_message(
                f"No resources found{scope}. Add one with `/addresource`.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(embed=embeds.resource_embed(found))

    @app_commands.command(name="addresource", description="Share a dev resource")
    @app_commands.describe(
        title="What it's called",
        url="Link, starting with https://",
        category="Topic, e.g. python",
        description="Optional one-liner",
    )
    @app_commands.checks.cooldown(1, 60.0)
    async def addresource(
        self,
        interaction: discord.Interaction,
        title: str,
        url: str,
        category: str,
        description: str | None = None,
    ):
        async with self.bot.session() as session:
            try:
                created = await add_resource(
                    session, title=title, url=url, category=category,
                    description=description, added_by=interaction.user.name,
                )
            except InvalidResource as exc:
                await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
                return

            embed = embeds.resource_embed(created)

        await interaction.response.send_message(content="✅ Added.", embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Resources(bot))
