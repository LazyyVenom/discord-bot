"""Every Discord embed the bot sends is built here."""

from __future__ import annotations

import discord

from champak.services.questions import AnswerOutcome, QuestionPick
from champak.services.scoring import AlreadySolved, Exhausted, TooSoon
from champak.services.users import accuracy

OPTION_LETTERS = ("A", "B", "C", "D")
DIFFICULTY_LABELS = {1: "Very easy", 2: "Easy", 3: "Medium", 4: "Hard", 5: "Brutal"}


def _timestamp(when) -> str:
    """Discord renders this as a live-updating relative time."""
    return f"<t:{int(when.timestamp())}:R>"


def question_embed(question, asker_name: str) -> discord.Embed:
    embed = discord.Embed(
        title=question.title,
        description=question.description or None,
        color=discord.Color.blurple(),
    )
    options = "\n".join(
        f"**{letter})** {getattr(question, f'option_{letter.lower()}')}"
        for letter in OPTION_LETTERS
    )
    embed.add_field(name="Options", value=options, inline=False)
    embed.add_field(name="Category", value=question.category, inline=True)
    embed.add_field(
        name="Difficulty",
        value=DIFFICULTY_LABELS.get(question.difficulty, str(question.difficulty)),
        inline=True,
    )
    embed.add_field(name="Worth", value=f"🔥 {question.points}", inline=True)
    embed.set_footer(text=f"Asked by {asker_name} · only they can answer")
    return embed


def outcome_embed(outcome: AnswerOutcome, question) -> discord.Embed:
    if outcome.is_correct:
        embed = discord.Embed(
            title="✅ Correct",
            description=f"Attempt {outcome.attempt_number} — **+{outcome.points_awarded}** aura.",
            color=discord.Color.green(),
        )
    elif outcome.attempts_remaining:
        plural = "attempt" if outcome.attempts_remaining == 1 else "attempts"
        embed = discord.Embed(
            title="❌ Not quite",
            description=(
                f"{outcome.attempts_remaining} {plural} left. "
                f"Try again {_timestamp(outcome.retry_at)}."
            ),
            color=discord.Color.orange(),
        )
        # Deliberately no correct option here: revealing it would make the
        # retry free.
        return embed
    else:
        embed = discord.Embed(
            title="❌ Out of attempts",
            description="No aura this time.",
            color=discord.Color.red(),
        )

    correct_text = getattr(question, f"option_{outcome.correct_option.lower()}")
    embed.add_field(
        name="Answer",
        value=f"**{outcome.correct_option})** {correct_text}",
        inline=False,
    )
    embed.add_field(name="Why", value=outcome.explanation, inline=False)
    return embed


def rejection_embed(eligibility) -> discord.Embed:
    if isinstance(eligibility, AlreadySolved):
        text = "You have already answered this one correctly."
    elif isinstance(eligibility, Exhausted):
        text = "You have used all three attempts on this question."
    elif isinstance(eligibility, TooSoon):
        text = f"Too soon — you can try this again {_timestamp(eligibility.retry_at)}."
    else:
        text = "You cannot answer this question right now."
    return discord.Embed(title="⏳ Hold on", description=text,
                         color=discord.Color.greyple())


def no_question_embed(pick: QuestionPick, category: str | None) -> discord.Embed:
    scope = f" in **{category}**" if category else ""
    if pick.reason == "all_cooling_down" and pick.retry_at is not None:
        text = f"Everything{scope} is on cooldown. Next one unlocks {_timestamp(pick.retry_at)}."
    elif pick.reason == "all_done":
        text = f"You have finished everything{scope}. Try another category."
    else:
        text = f"No questions found{scope}."
    return discord.Embed(title="🎯 Nothing to ask", description=text,
                         color=discord.Color.greyple())


def profile_embed(user, avatar_url: str | None) -> discord.Embed:
    embed = discord.Embed(title=f"{user.username}", color=discord.Color.gold())
    embed.add_field(name="🔥 Aura", value=str(user.aura_points), inline=True)
    embed.add_field(
        name="✅ Correct",
        value=f"{user.correct_answers}/{user.total_answers}",
        inline=True,
    )
    embed.add_field(name="🎯 Accuracy", value=f"{accuracy(user):.1f}%", inline=True)
    if avatar_url:
        embed.set_thumbnail(url=avatar_url)
    return embed


def leaderboard_embed(users) -> discord.Embed:
    embed = discord.Embed(title="🏆 Aura Leaderboard", color=discord.Color.purple())
    if not users:
        embed.description = "Nobody has scored yet. Be first with `/ask`."
        return embed

    medals = ("🥇", "🥈", "🥉")
    lines = [
        f"{medals[i] if i < 3 else f'`{i + 1}.`'} **{u.username}** — "
        f"🔥 {u.aura_points} ({u.correct_answers} correct)"
        for i, u in enumerate(users)
    ]
    embed.description = "\n".join(lines)
    return embed


def resource_embed(resource) -> discord.Embed:
    embed = discord.Embed(
        title=resource.title,
        description=resource.description or None,
        url=resource.url,
        color=discord.Color.green(),
    )
    embed.add_field(name="Category", value=resource.category, inline=True)
    if resource.added_by:
        embed.add_field(name="Added by", value=resource.added_by, inline=True)
    return embed


def categories_embed(question_cats, resource_cats) -> discord.Embed:
    embed = discord.Embed(title="📋 Categories", color=discord.Color.blurple())
    embed.add_field(
        name="Questions",
        value=", ".join(question_cats) or "none yet",
        inline=False,
    )
    embed.add_field(
        name="Resources",
        value=", ".join(resource_cats) or "none yet",
        inline=False,
    )
    return embed


def help_embed() -> discord.Embed:
    embed = discord.Embed(
        title="Champak Chacha",
        description="Answer questions, earn aura, climb the board.",
        color=discord.Color.blurple(),
    )
    embed.add_field(
        name="Questions",
        value=(
            "`/ask [category]` — get a question and answer it with the buttons\n"
            "Three attempts per question, 24h apart. "
            "Full points first try, half on the second, a quarter on the third."
        ),
        inline=False,
    )
    embed.add_field(
        name="Resources",
        value="`/resource [category]` — a random dev resource\n"
              "`/addresource` — share one",
        inline=False,
    )
    embed.add_field(
        name="Stats",
        value="`/profile [user]` · `/aura [user]` · `/leaderboard` · `/categories`",
        inline=False,
    )
    return embed
