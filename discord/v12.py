# --- MINIMAL MUSIC BOT VERSION ---
# This script retains only the essential setup and music functionality.

# --- Consolidated Imports ---
import os
import discord
import requests
import re
import asyncio
import time
import urllib.parse
from discord.ext import commands
from dotenv import load_dotenv
import io

# --- Unified Configuration & Environment Loading ---
load_dotenv()

# Bot and API Credentials
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")

# Bot Settings
COMMAND_PREFIX = '!'

# --- Sanity Checks for Environment Variables ---
if not DISCORD_BOT_TOKEN:
    print("FATAL ERROR: DISCORD_BOT_TOKEN not found in .env file. Please set it.")
    exit(1)

# --- API & Global Variable Setup ---
# Hardcoded API URLs for music features
API_DOWNLOAD_URLS = {
    'joox': 'https://music.wjhe.top/api/music/joox/url',
    # Removed other services as they are unused in search/download
}
API_SEARCH_URLS = {
    'joox': 'https://music.wjhe.top/api/music/joox/search',
    # Removed other services as they are unused in search/download
}

# Cache for search results (user_id: [song1, song2, ...])
search_results_cache = {}

# --- Unified Discord Bot Setup ---
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True
intents.messages = True

# Removed owner_id since owner-only commands are removed
bot = commands.Bot(command_prefix=COMMAND_PREFIX, intents=intents, help_command=None) 


# --- Unified Bot Event Handlers ---

@bot.event
async def on_ready():
    print(f'Bot is ready! Logged in as {bot.user.name} (ID: {bot.user.id})')
    print(f"Command Prefix: '{COMMAND_PREFIX}'")
    print('------')

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return
    if isinstance(message.channel, discord.DMChannel):
        try:
            await message.channel.send("I operate in server channels.")
        except discord.errors.Forbidden:
            print(f"Could not send a DM reply to {message.author}")
        return
    
    # Process commands like !s and !d
    await bot.process_commands(message)


# --- Music Bot Logic ---

@bot.command(name='help')
async def help_command(ctx):
    embed = discord.Embed(title=f"{bot.user.name} Music Help", 
                          description="This bot provides music search and download functionality.", 
                          color=discord.Color.dark_green())
    embed.add_field(name=f"🎵 Music Commands (Prefix: `{COMMAND_PREFIX}`)", 
                    value=(f"**Search for a song:** `{COMMAND_PREFIX}s [query]`\n" 
                           f"**Download a song (Lowest Quality):** `{COMMAND_PREFIX}d [number]`"), 
                    inline=False)
    embed.set_footer(text="Music only version.")
    await ctx.send(embed=embed)


@bot.command(name='s') 
async def search_song(ctx: commands.Context, *, query: str):
    """Searches for a song and displays the top 10 results."""
    user_id = ctx.author.id
    search_results_cache[user_id] = []
    
    async with ctx.typing():
        try:
            # Using joox API for search
            url = f"{API_SEARCH_URLS['joox']}?key={urllib.parse.quote(query)}"
            response = requests.get(url)
            response.raise_for_status()
            data = response.json()
            
            if not data.get('data', {}).get('data'):
                await ctx.send("No songs found for that query. Please try again.")
                return

            songs = data['data']['data'][:10]
            search_results_cache[user_id] = songs
            
            embed = discord.Embed(
                title="🎧 Search Results",
                description=f"Found **{len(songs)}** songs. Use `!d [number]` to download the song.", 
                color=discord.Color.dark_green()
            )
            
            for i, song in enumerate(songs):
                song_title = song.get('title', 'Unknown Title')
                artist_names = ', '.join([s.get('name') for s in song.get('singers', [])])
                embed.add_field(
                    name=f"{i+1}. {song_title}",
                    value=f"**Artist:** {artist_names}\n**Album:** {song.get('album', {}).get('name', 'N/A')}",
                    inline=False
                )
                
            await ctx.send(embed=embed)

        except Exception as e:
            print(f"Error in !s command: {e}")
            await ctx.send("Sorry, an error occurred while searching for music.")

@bot.command(name='d') 
async def download_song(ctx: commands.Context, song_number: int):
    """Downloads a song from the previous search results at the lowest available quality."""
    user_id = ctx.author.id
    if user_id not in search_results_cache or not search_results_cache[user_id]:
        await ctx.send("Please use `!s [query]` first to get a list of songs.")
        return
    
    if not 1 <= song_number <= len(search_results_cache[user_id]):
        await ctx.send("Invalid song number. Please choose a number from the search results.")
        return

    song = search_results_cache[user_id][song_number - 1]
    song_id = song.get('ID')
    song_title = song.get('title', 'song')
    song_artist = ', '.join([s.get('name') for s in song.get('singers', [])])

    # Find the lowest quality mp3 or m4a for download
    min_quality = float('inf')
    lowest_link = None
    
    for link in song.get('fileLinks', []):
        if link.get('format') in ['mp3', 'm4a']:
            current_quality = link.get('quality', float('inf')) 
            if current_quality < min_quality: # Logic to find the minimum quality
                min_quality = current_quality
                lowest_link = link
    
    if not lowest_link:
        await ctx.send("No compatible download format found for this song.")
        return

    quality = lowest_link.get('quality')
    file_format = lowest_link.get('format')
    
    download_url = f"{API_DOWNLOAD_URLS['joox']}?ID={song_id}&quality={quality}&format={file_format}"
    
    # --- CHANGE: Removed the specific quality text from this message ---
    await ctx.send(f"Downloading **{song_title}** by **{song_artist}**...")
    # -----------------------------------------------------------------

    try:
        # NOTE: Synchronous blocking call - kept as per original structure.
        response = requests.get(download_url)
        response.raise_for_status()

        audio_data = io.BytesIO(response.content)
        audio_file = discord.File(fp=audio_data, filename=f"{song_title}_{song_artist}.{file_format}")
        
        await ctx.send(file=audio_file)
        await ctx.send(f"✅ Download complete!")

    except Exception as e:
        print(f"Error downloading song: {e}")
        await ctx.send("Sorry, I encountered an error while downloading the song.")

# --- Main Execution Block ---
if __name__ == '__main__':
    try:
        bot.run(DISCORD_BOT_TOKEN)
    except discord.LoginFailure:
        print("FATAL ERROR: Invalid Discord bot token. Please check your .env file.")
    except Exception as e:
        print(f"An unexpected error occurred while starting the bot: {e}")