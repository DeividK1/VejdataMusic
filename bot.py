import os
import re
from pathlib import Path
from typing import Optional

import discord
from discord.ext import commands
from dotenv import load_dotenv
import yt_dlp as youtube_dl

# ---------- Конфигурация ----------
# 1) Зареждане на .env (DISCORD_TOKEN и по желание FFMPEG_PATH)
load_dotenv(dotenv_path=Path(__file__).with_name('.env'))
TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN or len(TOKEN) < 20:
    raise RuntimeError("❌ DISCORD_TOKEN липсва или е невалиден. Провери .env")

# 2) Път до FFmpeg: взимаме от .env FFMPEG_PATH, иначе fallback към WinGet пътя ти
FFMPEG_PATH = os.getenv(
    "FFMPEG_PATH",
    r"C:\Users\admin\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.0-full_build\bin\ffmpeg.exe"
)

# 3) Опции за yt_dlp (стабилен аудио стрийм)
YTDL_OPTS = {
    "format": "bestaudio/best",
    "quiet": True,
    "noplaylist": True,        # избягваме автоматично плейлисти
    "default_search": "ytsearch",
    "extract_flat": False,
    "source_address": "0.0.0.0",  # помага срещу някои CDN проблеми
}
ytdl = youtube_dl.YoutubeDL(YTDL_OPTS)

# 4) FFmpeg опции – ключово за авто-повторно свързване при гличове
FFMPEG_BEFORE = "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"
FFMPEG_OPTIONS = "-vn"  # само аудио

# ---------- Discord бот ----------
intents = discord.Intents.default()
intents.message_content = True  # активирай в Developer Portal → Bot → Privileged Gateway Intents
bot = commands.Bot(command_prefix='!', intents=intents)

# малка помощна проверка дали е URL (ако не е, ще търсим в YouTube)
URL_RE = re.compile(r"^https?://", re.IGNORECASE)

# ---------- Помощни функции ----------
def make_source(audio_url: str) -> discord.FFmpegOpusAudio:
    """Създава FFmpeg източник с авто-reconnect флагове."""
    return discord.FFmpegOpusAudio(
        audio_url,
        executable=FFMPEG_PATH,
        before_options=FFMPEG_BEFORE,
        options=FFMPEG_OPTIONS
    )

def extract_first_entry(info: dict) -> dict:
    """Ако info е плейлист/резултати от търсене, вземи първия валиден елемент."""
    if info is None:
        raise RuntimeError("Няма информация от yt_dlp")
    if "entries" in info and info["entries"]:
        return info["entries"][0]
    return info

async def ensure_voice(ctx) -> discord.VoiceClient:
    """Осигурява, че ботът е в правилния гласов канал и е self-deaf."""
    voice = discord.utils.get(bot.voice_clients, guild=ctx.guild)
    author_channel = ctx.author.voice.channel
    if voice and voice.channel != author_channel:
        await voice.move_to(author_channel)
        return voice
    if not voice:
        voice = await author_channel.connect(self_deaf=True)
    return voice

# ---------- Събития ----------
@bot.event
async def on_ready():
    print(f"✅ Влязох като {bot.user}")

# ---------- Команди ----------
@bot.command(help="Пуска аудио от YouTube линк или търсене. Пример: !play <url|текст>")
@commands.cooldown(1, 2, commands.BucketType.guild)  # anti-spam
async def play(ctx, *, query: str):
    if not ctx.author.voice:
        await ctx.send("🎧 Влез първо в гласов канал!")
        return

    voice = await ensure_voice(ctx)

    try:
        search_term = query if URL_RE.search(query) else f"ytsearch:{query}"
        info = ytdl.extract_info(search_term, download=False)
        info = extract_first_entry(info)

        audio_url = info["url"]
        title = info.get("title") or query

        # ако вече свири – спираме предишното, за да избегнем наслагвания
        if voice.is_playing():
            voice.stop()

        source = make_source(audio_url)
        voice.play(
            source,
            after=lambda e: print("[player] done:", e) if e else print("[player] finished")
        )
        await ctx.send(f"🎶 Пускам: **{title}**")

    except youtube_dl.utils.DownloadError as e:
        await ctx.send("❌ Проблем с извличането от YouTube. Пробвай друг линк/търсене.")
        print("[yt_dlp] DownloadError:", e)
    except Exception as e:
        await ctx.send("❌ Грешка при възпроизвеждане (линк/FFmpeg/мрежа).")
        print("[play ERROR]", repr(e))

@bot.command(help="Пауза на текущото аудио")
async def pause(ctx):
    voice = discord.utils.get(bot.voice_clients, guild=ctx.guild)
    if voice and voice.is_playing():
        voice.pause()
        await ctx.send("⏸️ Пауза.")
    else:
        await ctx.send("❌ Нищо не свири.")

@bot.command(help="Продължава след пауза")
async def resume(ctx):
    voice = discord.utils.get(bot.voice_clients, guild=ctx.guild)
    if voice and voice.is_paused():
        voice.resume()
        await ctx.send("▶️ Продължавам.")
    else:
        await ctx.send("❌ Няма песен на пауза.")

@bot.command(help="Спира текущото аудио")
async def stop(ctx):
    voice = discord.utils.get(bot.voice_clients, guild=ctx.guild)
    if voice and voice.is_playing():
        voice.stop()
        await ctx.send("⏹️ Спряно.")
    else:
        await ctx.send("❌ Нищо не свири.")

@bot.command(help="Ботът напуска гласовия канал")
async def leave(ctx):
    voice = discord.utils.get(bot.voice_clients, guild=ctx.guild)
    if voice:
        await voice.disconnect(force=True)
        await ctx.send("👋 Напускам канала.")
    else:
        await ctx.send("❌ Не съм в гласов канал.")

# ---------- Старт ----------
if __name__ == "__main__":
    # полезно в лога при отстраняване на проблеми
    print("Using FFmpeg at:", FFMPEG_PATH)
    bot.run(TOKEN)
