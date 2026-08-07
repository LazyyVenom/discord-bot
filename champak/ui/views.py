"""The A/B/C/D answer buttons.

These are DynamicItems rather than a plain View so the question id can live
in the custom_id. That makes them survive a bot restart: discord.py rebuilds
the handler from the custom_id instead of needing the original View object
to still be in memory.
"""

from __future__ import annotations

import re

import discord

CUSTOM_ID_TEMPLATE = r"cc:ans:(?P<qid>\d+):(?P<letter>[A-D]):(?P<uid>\d+)"
LETTERS = ("A", "B", "C", "D")


class AnswerButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=CUSTOM_ID_TEMPLATE,
):
    def __init__(self, question_id: int, letter: str, asker_id: int):
        self.question_id = question_id
        self.letter = letter
        self.asker_id = asker_id
        super().__init__(
            discord.ui.Button(
                label=letter,
                style=discord.ButtonStyle.secondary,
                custom_id=f"cc:ans:{question_id}:{letter}:{asker_id}",
            )
        )

    @classmethod
    async def from_custom_id(cls, interaction, item, match: re.Match[str]):
        return cls(int(match["qid"]), match["letter"], int(match["uid"]))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.asker_id:
            return True
        await interaction.response.send_message(
            "That is not your question — run `/ask` to get your own.",
            ephemeral=True,
        )
        return False

    async def callback(self, interaction: discord.Interaction):
        # The cog owns the answer flow; this keeps rules out of the UI layer.
        await interaction.client.handle_answer(
            interaction, self.question_id, self.letter
        )


class AnswerView(discord.ui.View):
    def __init__(self, question_id: int, asker_id: int):
        super().__init__(timeout=None)
        for letter in LETTERS:
            self.add_item(AnswerButton(question_id, letter, asker_id))
