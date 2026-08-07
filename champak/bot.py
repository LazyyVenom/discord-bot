"""Discord client setup, cog loading, and the global error boundary."""

from __future__ import annotations

import asyncio
import logging

import discord
from discord import app_commands
from discord.ext import commands

from champak.config import Config, ConfigError, load_config
from champak.db.session import create_engine_for, init_db, make_session_factory
from champak.logging_setup import configure_logging
from champak.ui.views import AnswerButton

log = logging.getLogger(__name__)

COGS = (
    "champak.cogs.questions",
    "champak.cogs.profile",
    "champak.cogs.resources",
    "champak.cogs.admin",
    "champak.cogs.meta",
)


class ChampakBot(commands.Bot):
    def __init__(self, config: Config):
        # No prefix commands exist any more, but commands.Bot still wants a
        # prefix; this one is unreachable because message_content is off.
        super().__init__(
            command_prefix=commands.when_mentioned,
            intents=discord.Intents.default(),
            help_command=None,
        )
        self.config = config
        self.engine = create_engine_for(config.db_url)
        self.session_factory = make_session_factory(self.engine)

    def session(self):
        return self.session_factory()

    async def setup_hook(self) -> None:
        await init_db(self.engine)
        self.add_dynamic_items(AnswerButton)

        for module in COGS:
            await self.load_extension(module)
            log.info("loaded %s", module)

        if self.config.guild_id:
            # Guild-scoped sync is instant; global sync can take an hour.
            guild = discord.Object(id=self.config.guild_id)
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            log.info("synced %d commands to guild %s", len(synced), self.config.guild_id)
        else:
            synced = await self.tree.sync()
            log.warning(
                "synced %d commands globally; set GUILD_ID for instant updates",
                len(synced),
            )

        self.tree.on_error = self.on_app_command_error

    async def close(self) -> None:
        await super().close()
        await self.engine.dispose()

    async def on_ready(self) -> None:
        log.info("online as %s (id %s)", self.user, self.user.id)
        await self.change_presence(activity=discord.Game(name="/ask"))

    async def on_app_command_completion(
        self, interaction: discord.Interaction, command: app_commands.Command
    ) -> None:
        # Without this, only answers were logged, so a /ask that was refused
        # or returned nothing left no trace and looked like the bot ignoring
        # the user.
        log.info(
            "/%s by %s (%s) in #%s",
            command.qualified_name,
            interaction.user,
            interaction.user.id,
            getattr(interaction.channel, "name", interaction.channel_id),
        )

    def is_admin(self, interaction: discord.Interaction) -> bool:
        perms = getattr(interaction.user, "guild_permissions", None)
        if perms is not None and perms.manage_guild:
            return True
        role_id = self.config.admin_role_id
        if role_id is None:
            return False
        roles = getattr(interaction.user, "roles", ())
        return any(role.id == role_id for role in roles)

    async def handle_answer(self, interaction, question_id: int, letter: str) -> None:
        """Replaced by the questions cog on load."""
        await interaction.response.send_message(
            "The question system is still starting up. Try again in a moment.",
            ephemeral=True,
        )

    async def on_app_command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        name = interaction.command.qualified_name if interaction.command else "?"
        who = f"{interaction.user} ({interaction.user.id})"

        # Handled rejections are logged too: a silently-refused command is
        # indistinguishable from a broken one when you are reading logs.
        if isinstance(error, app_commands.CommandOnCooldown):
            message = f"Slow down — try again in {error.retry_after:.0f}s."
            log.info("/%s refused for %s: cooldown %.0fs", name, who, error.retry_after)
        elif isinstance(error, app_commands.MissingPermissions):
            message = "You do not have permission to do that."
            log.info("/%s refused for %s: missing permissions", name, who)
        elif isinstance(error, app_commands.CheckFailure):
            message = "You cannot use that command here."
            log.info("/%s refused for %s: check failed", name, who)
        else:
            # Never surface str(error): it can carry internals.
            log.exception("unhandled error in /%s",
                          interaction.command.name if interaction.command else "?",
                          exc_info=error)
            message = "Something broke on my end. It has been logged."

        try:
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)
        except discord.HTTPException:
            log.exception("could not deliver the error message")


async def _run_async(config: Config) -> None:
    bot = ChampakBot(config)
    async with bot:
        await bot.start(config.token)


def run() -> None:
    try:
        config = load_config()
    except ConfigError as exc:
        raise SystemExit(f"Configuration error: {exc}") from None

    configure_logging(config.logging_level)
    try:
        asyncio.run(_run_async(config))
    except KeyboardInterrupt:
        log.info("stopped by user")
