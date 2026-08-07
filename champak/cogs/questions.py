"""The /ask command and the button-driven answer flow."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands

from champak.services import questions as qsvc
from champak.services.users import get_or_create_user
from champak.ui import embeds
from champak.ui.views import AnswerView

log = logging.getLogger(__name__)


class Questions(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # The buttons call through the client; point that at this cog.
        bot.handle_answer = self.handle_answer

    def _limits(self) -> dict:
        return {
            "max_attempts": self.bot.config.max_attempts,
            "cooldown": timedelta(hours=self.bot.config.answer_cooldown_hours),
        }

    async def category_autocomplete(self, interaction: discord.Interaction, current: str):
        async with self.bot.session() as session:
            names = await qsvc.list_categories(session)
        matches = [n for n in names if current.lower() in n.lower()][:25]
        return [app_commands.Choice(name=n, value=n) for n in matches]

    @app_commands.command(name="ask", description="Get a question to answer")
    @app_commands.describe(category="Narrow it to one topic")
    @app_commands.autocomplete(category=category_autocomplete)
    @app_commands.checks.cooldown(1, 10.0)
    async def ask(self, interaction: discord.Interaction, category: str | None = None):
        now = datetime.now(timezone.utc)
        async with self.bot.session() as session:
            user = await get_or_create_user(
                session, str(interaction.user.id), interaction.user.name
            )
            pick = await qsvc.pick_question(
                session, user.id, category, now, **self._limits()
            )

            if pick.question is None:
                await interaction.response.send_message(
                    embed=embeds.no_question_embed(pick, category), ephemeral=True
                )
                return

            await interaction.response.send_message(
                embed=embeds.question_embed(pick.question, interaction.user.display_name),
                view=AnswerView(pick.question.id, interaction.user.id),
            )

    async def handle_answer(
        self, interaction: discord.Interaction, question_id: int, letter: str
    ) -> None:
        now = datetime.now(timezone.utc)
        async with self.bot.session() as session:
            question = await qsvc.get_question(session, question_id)
            if question is None:
                await interaction.response.send_message(
                    "That question no longer exists.", ephemeral=True
                )
                return

            user = await get_or_create_user(
                session, str(interaction.user.id), interaction.user.name
            )
            result = await qsvc.submit_answer(
                session, user=user, question=question, chosen=letter,
                now=now, **self._limits(),
            )

            if isinstance(result, qsvc.Rejected):
                await interaction.response.send_message(
                    embed=embeds.rejection_embed(result.eligibility), ephemeral=True
                )
                return

            await interaction.response.send_message(
                embed=embeds.outcome_embed(result, question), ephemeral=True
            )

        # Retire the buttons so the message cannot be clicked again.
        try:
            await interaction.message.edit(view=None)
        except (discord.HTTPException, AttributeError):
            log.debug("could not clear buttons on message", exc_info=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Questions(bot))
