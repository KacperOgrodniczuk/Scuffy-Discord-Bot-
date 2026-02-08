import discord
from discord.ext import commands
from discord import PCMVolumeTransformer
from dotenv import load_dotenv
import yt_dlp as youtube_dl
import asyncio
import os

#TODO
#Add the ability to delete songs from que
#Limit the amount of songs you can que up with a playlist (yt-music test wanted to download like 2000 songs, should not be more than 20.)
#Make sure you can only use music bot commands if you're connected to the channel the bot is in.
#Make the bot cleanup the downloads automatically at some point and priorotise files that aren't played often/recently. (idk like when the queue ends or something).
#Add the ability to check what song you are listening to now.
#Expand the queue command to also show currently playing song.
#Make the bot leave after idling in a channel for a few minutes.


load_dotenv()
auth_token = os.getenv("AUTH_TOKEN")

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)

queues = {}
youtube_dl_instances = {}
locks = {}

# Set up YouTube download options for audio
youtube_dl_opts = {
    'format': 'bestaudio/best',
    'outtmpl': 'downloads/%(id)s.%(ext)s',
    'noplaylist': True,
    'ignoreerrors': True,
    'cookiesfrombrowser': ('firefox',),
    'http_headers': {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/121.0.0.0 Firefox/121.0',
    'Accept-Language': 'en-US,en;q=0.9',
    'Referer': 'https://www.youtube.com/',
}
}

# Ensure the downloads directory exists and is located in the correct folder.
os.chdir(os.path.dirname(os.path.abspath(__file__)))
os.makedirs("downloads", exist_ok=True)

# Functions ------------------------------------------------------------------------------------

#Look for the file
def search_for_file(video_id):
    # Return the path to a downloaded file based on YouTube video ID
    for ext in ('mp3', 'webm', 'm4a', 'opus'):
        file_path = os.path.join("downloads", f"{video_id}.{ext}")
        if os.path.exists(file_path):
            return file_path
    
    return None

def get_queue(guild_id):
    # Return the queue for the specific server, or create a new one if it doesn't exist
    if guild_id not in queues:
        queues[guild_id] = []
    return queues[guild_id]

def get_youtube_dl_instance(guild_id):
    # If no instance exists for this guild, create a new one.
    if guild_id not in youtube_dl_instances:
        youtube_dl_instances[guild_id] = youtube_dl.YoutubeDL(youtube_dl_opts)
    return youtube_dl_instances[guild_id]

def get_lock(guild_id):
    if guild_id not in locks:
        locks[guild_id] = asyncio.Lock()
    return locks[guild_id]


async def download_audio(url, guild_id):
    ydl = get_youtube_dl_instance(guild_id)
    loop = asyncio.get_running_loop()
    
    try:
        info = await loop.run_in_executor(None, lambda: ydl.extract_info(url, download=True))
        video_id = info.get('id')
        if video_id:
            file_path = search_for_file(video_id)
            return file_path, info.get('title', 'Unknown')
    except Exception as e:
        print(f"Download failed: {e}")
    return None, None

async def obtain_audio_info(url, guild_id):
    ydl = get_youtube_dl_instance(guild_id)
    loop = asyncio.get_running_loop()
    
    try:
        info = await loop.run_in_executor(None, lambda: ydl.extract_info(url, download=False))
        video_id = info.get("id")
        if video_id:
            title = info.get("title", "Unknown")
            return video_id, title
    except Exception as e:
        print(f"Download failed: {e}")


async def play_next(ctx):
    """Play the next song in the guild queue"""
    voice_client = ctx.voice_client
    guild_id = ctx.guild.id
    queue = get_queue(guild_id)

    if not queue:
        return

    next_song = queue.pop(0)
    url = next_song['url']
    video_id = next_song.get('id')
    title = next_song.get('title', 'Unknown')

    # Check if file already exists
    file_path = search_for_file(video_id)
    if not file_path:
        file_path, title = await download_audio(url, guild_id)
        if not file_path:
            await ctx.send(f"Failed to download {title}. Skipping...")
            await play_next(ctx)
            return

    await ctx.send(f"Now playing: {title}")

    audio_source = PCMVolumeTransformer(discord.FFmpegPCMAudio(file_path), volume=0.1)

    def after_play(error):
        if error:
            print(f"Error playing {title}: {error}")
        fut = asyncio.run_coroutine_threadsafe(play_next(ctx), bot.loop)
        try:
            fut.result()
        except Exception as e:
            print(f"Error scheduling next song: {e}")

    if not voice_client.is_playing():
        voice_client.play(audio_source, after=after_play)


# Commands ------------------------------------------------------------------------------------- 

# Join a voice channel
@bot.command()
async def join(ctx):
    if ctx.author.voice:
        channel = await ctx.author.voice.channel
        await channel.connect()
        await ctx.send(f"Joined {channel}")
    else:
        await ctx.send("You need to be in a voice channel first.")

# Leave the voice channel
@bot.command()
async def leave(ctx):
    voice_client = ctx.voice_client
    if voice_client and voice_client.is_connected():
        await voice_client.disconnect()
        await ctx.send("Disconnected from the voice channel.")
    else:
        await ctx.send("I'm not connected to any voice channel.")

# Play music from a YouTube URL
@bot.command()
async def play(ctx, url):
    guild_id = ctx.guild.id
    queue = get_queue(guild_id)
    voice_client = ctx.voice_client
    lock = get_lock(guild_id)

    # Connect bot if not already in voice channel
    if not voice_client or not voice_client.is_connected():
        if ctx.author.voice:
            channel = ctx.author.voice.channel
            await channel.connect()
            voice_client = ctx.voice_client
        else:
            await ctx.send("You need to be in a voice channel first.")
            return

    async with lock:
        try:
            video_id, title = await obtain_audio_info(url, guild_id)

            if video_id is None:
                await ctx.send("Failed to get video info.")
                return

            # Add to queue using ID
            queue.append({
                'id': video_id,
                'title': title,
                'url': url
            })

            if not voice_client.is_playing():
                await play_next(ctx)
            else:
                await ctx.send(f"Added to queue: {title}")

        except Exception as e:
            await ctx.send(f"Error adding song: {e}")

# Delete a song from the queue based on its position
@bot.command()
async def delete(ctx, position: int):
    guild_id = ctx.guild.id
    queue = get_queue(guild_id)
    lock = get_lock(guild_id)

    async with lock:
        if 1 <= position <= len(queue):
            removed_song = queue.pop(position - 1)
            await ctx.send(f"Removed from queue: {removed_song['title']}")
        else:
            await ctx.send("Invalid position. Please provide a valid song number in the queue.")

# Skip the currently playing song
@bot.command()
async def skip(ctx):
    voice_client = ctx.voice_client

    if voice_client and voice_client.is_playing():
        voice_client.stop()

@bot.command()
async def clearQueue(ctx):
    guild_id = ctx.guild.id
    queue = get_queue(guild_id)

    if len(queue) > 0:
        queue.clear()
        await ctx.send("Queue cleared")
    else:
        await ctx.send("The queue is empty.")

@bot.command()
async def queue(ctx):
    guild_id = ctx.guild.id
    queue = get_queue(guild_id)

    queue_list = "\n".join([f"{index + 1}. {song['title']}" for index, song in enumerate(queue)])

    embed = discord.Embed(
        title="🎵 Current Song Queue 🎵",
        description=queue_list,
        color=discord.Color.blue())

    embed.set_footer(text=f"Total Songs: {len(queue)}")

    await ctx.send(embed=embed)

# Stop the currently playing audio
@bot.command()
async def stop(ctx):
    voice_client = ctx.voice_client
    guild_id = ctx.guild.id
    queue = get_queue(guild_id)

    queue.clear()
    if voice_client.is_connected():
        voice_client.stop()
        await voice_client.disconnect()
        await ctx.send("Stopped playing and cleared the queue.")
    else:
        await ctx.send("Nothing is playing right now.")

# Clean up downloads directory
@bot.command()
async def cleanup(ctx):
    for file in os.listdir("downloads"):
        file_path = os.path.join("downloads", file)
        os.remove(file_path)
    await ctx.send("Cleaned up downloaded files.")

@bot.command()
async def help(ctx):
    # Example list of commands
    commands = {
        "help": "Lists bot commands.",
        "play [URL]": "Adds a song to the queue",
        "delete [position]": "Deletes a song from the queue based on its position.",
        "skip": "Skips to the next song.",
        "clearQueue": "Clears the entire queue.",
        "queue": "Shows the current song queue.",
        "leave": "Makes the bot leave the voice channel.",
        "stop": "Clears the queue and makes the bot leave."
    }

    embed = discord.Embed(title="ℹ️ Help - List of Commands ℹ️", color=discord.Color.blue())
    for command, description in commands.items():
        embed.add_field(name=f"!{command}", value=description, inline=False)

    await ctx.send(embed=embed)

# Run the bot
bot.run(auth_token)
