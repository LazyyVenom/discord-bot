"""Admin-only question authoring."""

from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from champak.db.import_questions import import_key_for
from champak.db.models import Question
from champak.ui import embeds

log = logging.getLogger(__name__)

VALID_OPTIONS = ("A", "B", "C", "D")


class AddQuestionModal(discord.ui.Modal, title="Add a question"):
    body = discord.ui.TextInput(
        label="Question",
        style=discord.TextStyle.paragraph,
        placeholder="The question. Leave a blank line to add extra detail below it.",
        max_length=1800,
    )
    category = discord.ui.TextInput(label="Category", placeholder="dsa", max_length=50)
    options = discord.ui.TextInput(
        label="Options (one per line, exactly 4)",
        style=discord.TextStyle.paragraph,
        placeholder="O(n)\nO(log n)\nO(n log n)\nO(1)",
        max_length=900,
    )
    # Discord allows five inputs at most, so the answer letter and the
    # difficulty share this one. Adding a sixth TextInput raises ValueError.
    answer = discord.ui.TextInput(
        label="Correct option + difficulty, e.g. B 4",
        placeholder="B 4",
        max_length=5,
    )
    explanation = discord.ui.TextInput(
        label="Explanation",
        style=discord.TextStyle.paragraph,
        max_length=900,
    )

    def __init__(self, bot: commands.Bot):
        super().__init__()
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction):
        title, _, description = str(self.body).partition("\n\n")
        title = title.strip()
        description = description.strip() or None

        lines = [line.strip() for line in str(self.options).splitlines() if line.strip()]
        if len(lines) != 4:
            await interaction.response.send_message(
                f"❌ Give exactly 4 options, one per line. I counted {len(lines)}.",
                ephemeral=True,
            )
            return

        parts = str(self.answer).strip().upper().split()
        letter = parts[0] if parts else ""
        if letter not in VALID_OPTIONS:
            await interaction.response.send_message(
                f"❌ Correct option must be A, B, C or D — got {self.answer!s}.",
                ephemeral=True,
            )
            return

        raw_difficulty = parts[1] if len(parts) > 1 else "3"
        if not raw_difficulty.isdigit() or not 1 <= int(raw_difficulty) <= 5:
            await interaction.response.send_message(
                f"❌ Difficulty must be 1-5 — got {raw_difficulty!r}.", ephemeral=True
            )
            return
        level = int(raw_difficulty)

        explanation = str(self.explanation).strip()
        if not explanation:
            await interaction.response.send_message(
                "❌ An explanation is required.", ephemeral=True
            )
            return

        question = Question(
            title=title,
            description=description,
            category=str(self.category).strip().lower(),
            difficulty=level,
            points=level * 10,
            option_a=lines[0], option_b=lines[1],
            option_c=lines[2], option_d=lines[3],
            correct_option=letter,
            explanation=explanation,
            asked_by=interaction.user.name,
            import_key=import_key_for(title),
        )

        async with self.bot.session() as session:
            session.add(question)
            try:
                await session.commit()
            except Exception:
                await session.rollback()
                log.exception("could not save question")
                await interaction.response.send_message(
                    "❌ Could not save that — an identical question may already exist.",
                    ephemeral=True,
                )
                return
            embed = embeds.question_embed(question, interaction.user.display_name)

        await interaction.response.send_message(
            content=f"✅ Added as question #{question.id}.", embed=embed, ephemeral=True
        )


class Admin(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="addquestion", description="Add a question (admins only)")
    async def addquestion(self, interaction: discord.Interaction):
        if not self.bot.is_admin(interaction):
            await interaction.response.send_message(
                "That command is for admins only.", ephemeral=True
            )
            return
        await interaction.response.send_modal(AddQuestionModal(self.bot))


async def setup(bot: commands.Bot):
    await bot.add_cog(Admin(bot))
