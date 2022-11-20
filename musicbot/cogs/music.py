from discord.ext import commands
import discord
import asyncio
import youtube_dl
import logging
import math
from urllib import request
from ..video import Video

# TODO: abstract FFMPEG options into their own file?
FFMPEG_BEFORE_OPTS = '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5'
"""
Параметры командной строки, передаваемые в `ffmpeg` перед `-i`..

См. https://stackoverflow.com/questions/43218292/youtubedl-read-error-with-discord-py/44490434#44490434 для получения дополнительной информации.
Кроме того, https://ffmpeg.org/ffmpeg-protocols.html для справки о параметрах командной строки.
"""


async def audio_playing(ctx):
    """Проверяет, воспроизводится ли звук в данный момент, прежде чем продолжить."""
    client = ctx.guild.voice_client
    if client and client.channel and client.source:
        return True
    else:
        raise commands.CommandError("В настоящее время аудио не воспроизводится.")


async def in_voice_channel(ctx):
    """Проверяет, что отправитель команды находится в том же голосовом канале, что и бот."""
    voice = ctx.author.voice
    bot_voice = ctx.guild.voice_client
    if voice and bot_voice and voice.channel and bot_voice.channel and voice.channel == bot_voice.channel:
        return True
    else:
        raise commands.CommandError(
            "Для этого вам нужно быть в канале.")


async def is_audio_requester(ctx):
    """Проверяет, что отправитель команды запросил песню."""
    music = ctx.bot.get_cog("Music")
    state = music.get_state(ctx.guild)
    permissions = ctx.channel.permissions_for(ctx.author)
    if permissions.administrator or state.is_requester(ctx.author):
        return True
    else:
        raise commands.CommandError(
            "Для этого вам нужно быть заказчиком песни.")


class Music(commands.Cog):
    """Команды бота, помогающие воспроизводить музыку."""

    def __init__(self, bot, config):
        self.bot = bot
        self.config = config[__name__.split(".")[
            -1]]  # получить имя модуля, найти запись в конфигурации
        self.states = {}
        self.bot.add_listener(self.on_reaction_add, "on_reaction_add")

    def get_state(self, guild):
        """Получает состояние для `guild`, создавая его, если оно не существует."""
        if guild.id in self.states:
            return self.states[guild.id]
        else:
            self.states[guild.id] = GuildState()
            return self.states[guild.id]

    @commands.command(aliases=["stop"])
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def leave(self, ctx):
        """Покидает голосовой канал, если в данный момент находится в нем."""
        client = ctx.guild.voice_client
        state = self.get_state(ctx.guild)
        if client and client.channel:
            await client.disconnect()
            state.playlist = []
            state.now_playing = None
        else:
            raise commands.CommandError("Не в голосовом канале.")

    @commands.command(aliases=["resume", "p"])
    @commands.guild_only()
    @commands.check(audio_playing)
    @commands.check(in_voice_channel)
    @commands.check(is_audio_requester)
    async def pause(self, ctx):
        """Приостанавливает воспроизведение любого воспроизводимого звука."""
        client = ctx.guild.voice_client
        self._pause_audio(client)

    def _pause_audio(self, client):
        if client.is_paused():
            client.resume()
        else:
            client.pause()

    @commands.command(aliases=["vol", "v"])
    @commands.guild_only()
    @commands.check(audio_playing)
    @commands.check(in_voice_channel)
    @commands.check(is_audio_requester)
    async def volume(self, ctx, volume: int):
        """Изменение громкости воспроизводимого в данный момент аудио (значения 0-250)."""
        state = self.get_state(ctx.guild)

        # убедитесь, что объем неотрицателен
        if volume < 0:
            volume = 0

        max_vol = self.config["max_volume"]
        if max_vol > -1:  # проверьте, установлен ли максимальный объем
            # объем зажима до [0, max_vol]
            if volume > max_vol:
                volume = max_vol

        client = ctx.guild.voice_client

        state.volume = float(volume) / 100.0
        client.source.volume = state.volume  # обновить громкость аудио источника, чтобы она соответствовала

    @commands.command()
    @commands.guild_only()
    @commands.check(audio_playing)
    @commands.check(in_voice_channel)
    async def skip(self, ctx):
        """Пропускает текущую воспроизводимую песню или голосует за ее пропуск."""
        state = self.get_state(ctx.guild)
        client = ctx.guild.voice_client
        if ctx.channel.permissions_for(
                ctx.author).administrator or state.is_requester(ctx.author):
            # немедленно пропустить, если запросчик или администратор
            client.stop()
        elif self.config["vote_skip"]:
            # голосовать, чтобы пропустить песню
            channel = client.channel
            self._vote_skip(channel, ctx.author)
            # объявить голосование
            users_in_channel = len([
                member for member in channel.members if not member.bot
            ])  # не считайте ботов
            required_votes = math.ceil(
                self.config["vote_skip_ratio"] * users_in_channel)
            await ctx.send(
                f"{ctx.author.mention} проголосовал за пропуск ({len(state.skip_votes)}/{required_votes} голоса)"
            )
        else:
            raise commands.CommandError("Извините, пропуск голосования отключен.")

    def _vote_skip(self, channel, member):
        """Проголосуйте за `member`, чтобы пропустить воспроизведение песни."""
        logging.info(f"{member.name} голоса для пропуска")
        state = self.get_state(channel.guild)
        state.skip_votes.add(member)
        users_in_channel = len([
            member for member in channel.members if not member.bot
        ])  # не считайте ботов
        if (float(len(state.skip_votes)) /
                users_in_channel) >= self.config["vote_skip_ratio"]:
            # достаточно членов проголосовало за пропуск, поэтому пропустите песню
            logging.info(f"Достаточно голосов, пропускаю...")
            channel.guild.voice_client.stop()

    def _play_song(self, client, state, song):
        state.now_playing = song
        state.skip_votes = set()  # очистить пропущенные голоса
        source = discord.PCMVolumeTransformer(
            discord.FFmpegPCMAudio(song.stream_url, before_options=FFMPEG_BEFORE_OPTS), volume=state.volume)

        def after_playing(err):
            if len(state.playlist) > 0:
                next_song = state.playlist.pop(0)
                self._play_song(client, state, next_song)
            else:
                asyncio.run_coroutine_threadsafe(client.disconnect(),
                                                 self.bot.loop)

        client.play(source, after=after_playing)

    @commands.command(aliases=["np"])
    @commands.guild_only()
    @commands.check(audio_playing)
    async def nowplaying(self, ctx):
        """Отображает информацию о текущей композиции."""
        state = self.get_state(ctx.guild)
        message = await ctx.send("", embed=state.now_playing.get_embed())
        await self._add_reaction_controls(message)

    @commands.command(aliases=["q", "playlist"])
    @commands.guild_only()
    @commands.check(audio_playing)
    async def queue(self, ctx):
        """Отображение текущей очереди воспроизведения."""
        state = self.get_state(ctx.guild)
        await ctx.send(self._queue_text(state.playlist))

    def _queue_text(self, queue):
        """Возвращает блок текста, описывающий заданную очередь песен."""
        if len(queue) > 0:
            message = [f"{len(queue)} песни в очереди:"]
            message += [
                f"  {index+1}. **{song.title}** (по просьбе **{song.requested_by.name}**)"
                for (index, song) in enumerate(queue)
            ]  # добавлять отдельные песни
            return "\n".join(message)
        else:
            return "Очередь воспроизведения пуста."

    @commands.command(aliases=["cq"])
    @commands.guild_only()
    @commands.check(audio_playing)
    @commands.has_permissions(administrator=True)
    async def clearqueue(self, ctx):
        """Очистка очереди воспроизведения без выхода из канала."""
        state = self.get_state(ctx.guild)
        state.playlist = []

    @commands.command(aliases=["jq"])
    @commands.guild_only()
    @commands.check(audio_playing)
    @commands.has_permissions(administrator=True)
    async def jumpqueue(self, ctx, song: int, new_index: int):
        """Перемещает композицию с индексом на `new_index` в очереди."""
        state = self.get_state(ctx.guild)  # получить состояние для этой гильдии
        if 1 <= song <= len(state.playlist) and 1 <= new_index:
            song = state.playlist.pop(song - 1)  # взять песню в индекс...
            state.playlist.insert(new_index - 1, song)  # и вставьте его.

            await ctx.send(self._queue_text(state.playlist))
        else:
            raise commands.CommandError("Вы должны использовать действительный индекс.")

    @commands.command(brief="Воспроизводит аудио из <url>.")
    @commands.guild_only()
    async def play(self, ctx, *, url):
        """Воспроизводит аудио, размещенное по адресу <url> (или выполняет поиск по адресу <url> и воспроизводит первый результат)."""

        client = ctx.guild.voice_client
        state = self.get_state(ctx.guild)  # получить состояние гильдии

        if client and client.channel:
            try:
                video = Video(url, ctx.author)
            except youtube_dl.DownloadError as e:
                logging.warn(f"Ошибка при загрузке видео: {e}")
                await ctx.send(
                    "Произошла ошибка при загрузке вашего видео, извините.")
                return
            state.playlist.append(video)
            message = await ctx.send(
                "Добавлено в очередь", embed=video.get_embed())
            await self._add_reaction_controls(message)
        else:
            if ctx.author.voice is not None and ctx.author.voice.channel is not None:
                channel = ctx.author.voice.channel
                try:
                    video = Video(url, ctx.author)
                except youtube_dl.DownloadError as e:
                    await ctx.send(
                        "Произошла ошибка при загрузке вашего видео, извините.")
                    return
                client = await channel.connect()
                self._play_song(client, state, video)
                message = await ctx.send("", embed=video.get_embed())
                await self._add_reaction_controls(message)
                logging.info(f"Сейчас играет '{video.title}'")
            else:
                raise commands.CommandError(
                    "Для этого вам нужно находиться в голосовом канале.")

    async def on_reaction_add(self, reaction, user):
        """Отвечает на реакции, добавленные к сообщениям бота, позволяя реакциям управлять воспроизведением."""
        message = reaction.message
        if user != self.bot.user and message.author == self.bot.user:
            await message.remove_reaction(reaction, user)
            if message.guild and message.guild.voice_client:
                user_in_channel = user.voice and user.voice.channel and user.voice.channel == message.guild.voice_client.channel
                permissions = message.channel.permissions_for(user)
                guild = message.guild
                state = self.get_state(guild)
                if permissions.administrator or (
                        user_in_channel and state.is_requester(user)):
                    client = message.guild.voice_client
                    if reaction.emoji == "⏯":
                        # пауза аудио
                        self._pause_audio(client)
                    elif reaction.emoji == "⏭":
                        # пропустить аудио
                        client.stop()
                    elif reaction.emoji == "⏮":
                        state.playlist.insert(
                            0, state.now_playing
                        )  # вставка текущей песни в начало списка воспроизведения
                        client.stop()  # skip ahead
                elif reaction.emoji == "⏭" and self.config["vote_skip"] and user_in_channel and message.guild.voice_client and message.guild.voice_client.channel:
                    # убедитесь, что кнопка skip была нажата, что пропуск голосов
                    # включен, пользователь находится в канале, и бот находится
                    # в голосовом канале
                    voice_channel = message.guild.voice_client.channel
                    self._vote_skip(voice_channel, user)
                    # объявить голосование
                    channel = message.channel
                    users_in_channel = len([
                        member for member in voice_channel.members
                        if not member.bot
                    ])  # don't count bots
                    required_votes = math.ceil(
                        self.config["vote_skip_ratio"] * users_in_channel)
                    await channel.send(
                        f"{user.mention} проголосовал за пропуск ({len(state.skip_votes)}/{required_votes} голосов)"
                    )

    async def _add_reaction_controls(self, message):
        """Добавляет "панель управления" реакциями на сообщение, которую можно использовать для управления ботом."""
        CONTROLS = ["⏮", "⏯", "⏭"]
        for control in CONTROLS:
            await message.add_reaction(control)


class GuildState:
    """Класс-помощник, управляющий состоянием каждой гильдии."""

    def __init__(self):
        self.volume = 1.0
        self.playlist = []
        self.skip_votes = set()
        self.now_playing = None

    def is_requester(self, user):
        return self.now_playing.requested_by == user
