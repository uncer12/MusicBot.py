from discord.ext import commands
import discord
import random


class Tips(commands.Cog):
    """Команды для предоставления советов по использованию бота."""

    def __init__(self, bot, config):
        self.bot = bot
        self.config = config[__name__.split(".")[-1]]
        self.tips = ["Только админы и заказчик песни могут сразу пропускать песни. Всем остальным придется голосовать!",
                     f"Вы можете ознакомиться с моим исходным кодом здесь: {self.config['discord_url']}"]

    @commands.command()
    async def tip(self, ctx):
        """Получите случайный совет по использованию бота."""
        index = random.randrange(len(self.tips))
        await ctx.send(f"**Совет #{index+1}:** {self.tips[index]}")
