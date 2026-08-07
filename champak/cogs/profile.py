"""Stats commands: profile, aura, leaderboard, categories."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from champak.services.questions import list_categories
from champak.services.resources import list_resource_categories
from champak.services.users import get_or_create_user, top_users
from champak.ui import embeds


class Profile(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="profile", description="See someone's stats")
    @app_commands.describe(member="Whose profile to show (defaults to you)")
    async def profile(
        self, interaction: discord.Interaction, member: discord.Member | None = None
    ):
        target = member or interaction.user
        async with self.bot.session() as session:
            user = await get_or_create_user(session, str(target.id), target.name)
            embed = embeds.profile_embed(user, target.display_avatar.url)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="aura", description="Check aura points")
    @app_commands.describe(member="Whose aura to check (defaults to you)")
    async def aura(
        self, interaction: discord.Interaction, member: discord.Member | None = None
    ):
        target = member or interaction.user
        async with self.bot.session() as session:
            user = await get_or_create_user(session, str(target.id), target.name)
            points = user.aura_points
        await interaction.response.send_message(
            f"🔥 {target.mention} has **{points}** aura."
        )

    @app_commands.command(name="leaderboard", description="Top 10 by aura")
    @app_commands.checks.cooldown(1, 30.0, key=lambda i: i.channel_id)
    async def leaderboard(self, interaction: discord.Interaction):
        async with self.bot.session() as session:
            users = await top_users(session, limit=10)
        await interaction.response.send_message(embed=embeds.leaderboard_embed(users))

    @app_commands.command(name="categories", description="List every category")
    async def categories(self, interaction: discord.Interaction):
        async with self.bot.session() as session:
            question_cats = await list_categories(session)
            resource_cats = await list_resource_categories(session)
        await interaction.response.send_message(
            embed=embeds.categories_embed(question_cats, resource_cats)
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Profile(bot))
