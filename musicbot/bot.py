import discord
import logging
import sys
from discord.ext import commands
from .cogs import music, error, meta, tips
from . import config

cfg = config.load_config()

bot = commands.Bot(command_prefix=cfg["prefix"])


@bot.event
async def on_ready():
    logging.info(f"Logged in as {bot.user.name}")


COGS = [music.Music, error.CommandErrorHandler, meta.Meta, tips.Tips]


def add_cogs(bot):
    for cog in COGS:
        bot.add_cog(cog(bot, cfg))  # Инициализируйте cog и добавьте его в бота


def run():
    add_cogs(bot)
    if cfg["token"] == "":
        raise ValueError(
            "Не был предоставлен токен. Пожалуйста, убедитесь, что config.toml содержит маркер бота."
        )
        sys.exit(1)
    bot.run(cfg["token"])
