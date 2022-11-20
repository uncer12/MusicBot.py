import discord
import sys
import traceback
import logging
from discord.ext import commands


class CommandErrorHandler(commands.Cog):
    def __init__(self, bot, config):
        self.bot = bot
        self.config = config
        self.bot.add_listener(self.on_command_error, "on_command_error")

    async def on_command_error(self, ctx, error):
        if hasattr(ctx.command, "on_error"):
            return  # Не вмешивайтесь в пользовательские обработчики ошибок

        error = getattr(error, "original", error)  # получить исходную ошибку

        if isinstance(error, commands.CommandNotFound):
            return await ctx.send(
                f"Такой команды не существует. Пожалуйста, используйте `{self.bot.command_prefix}help` для получения списка команд."
            )

        if isinstance(error, commands.CommandError):
            return await ctx.send(
                f"Ошибка при выполнении команды `{ctx.command.name}`: {str(error)}")

        await ctx.send(
            "При выполнении этой команды произошла непредвиденная ошибка.")
        logging.warn("Игнорирование исключения в команде {}:".format(ctx.command))
        logging.warn("\n" + "".join(
            traceback.format_exception(
                type(error), error, error.__traceback__)))
