# Respond only to mentions in server channels and ignore direct messages.

import os
import discord
from discord.ext import commands
from dotenv import load_dotenv
import google.generativeai as genai
import asyncio
import time

# --- Configuration ---
# Load environment variables from .env file
load_dotenv()

# Get API keys from environment variables
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Check if essential environment variables are set
if not DISCORD_BOT_TOKEN:
    print("Error: DISCORD_BOT_TOKEN not found in .env file. Please set it.")
    exit(1) # Exit the script if critical config is missing
if not GEMINI_API_KEY:
    print("Error: GEMINI_API_KEY not found in .env file. Please set it.")
    exit(1)

# Configure the Gemini API
genai.configure(api_key=GEMINI_API_KEY)

# --- Global Variables ---
# You can change this to your preferred model, e.g., 'gemini-pro'
DEFAULT_MODEL = 'gemini-1.5-flash'
model = None      # Stores the initialized GoogleGenerativeAI.GenerativeModel object

# Basic rate limiting for Gemini API calls to prevent 429 errors
last_gemini_call_time = 0
MIN_DELAY_BETWEEN_CALLS = 1.1 # Minimum delay in seconds between consecutive Gemini calls.
                              # Adjust based on your Gemini API quota (e.g., 60 RPM = 1 sec delay,
                              # adding 0.1 for safety).

# --- Discord Bot Setup ---
# Set up Discord intents (crucial for reading message content)
# You MUST enable "Message Content Intent" in your Discord Developer Portal -> Bot section!
intents = discord.Intents.default()
intents.message_content = True # Required to read message content
intents.members = True         # Optional: if your bot needs to access member info

# Initialize the Discord client
client = discord.Client(intents=intents)

# --- Discord Bot Events ---
@client.event
async def on_ready():
    """
    Called when the bot successfully connects to Discord.
    Initializes the Gemini model here.
    """
    # We use 'global' here because we are ASSIGNING a new value to model,
    # which is a global variable.
    global model

    print(f'Bot is ready! Logged in as {client.user}')
    print(f'Bot ID: {client.user.id}')

    # Attempt to initialize the default Gemini model
    if DEFAULT_MODEL:
        try:
            model = genai.GenerativeModel(DEFAULT_MODEL)
            print(f"Successfully initialized Gemini model: {DEFAULT_MODEL}")
        except Exception as e:
            print(f"Error initializing Gemini model '{DEFAULT_MODEL}': {e}")
            print("Please double-check the model's availability or your API key.")
            model = None # Ensure model is None if initialization fails
    else:
        print("No default model specified. Bot will not be able to generate responses.")


@client.event
async def on_message(message):
    """
    Called when a message is sent. Handles AI responses only in server channels when mentioned.
    """
    # We use 'global' here because we are ASSIGNING a new value to last_gemini_call_time later in the function.
    global last_gemini_call_time

    # Ignore messages from the bot itself to prevent infinite loops
    if message.author == client.user:
        return

    # --- Check if the message is in a server channel or a DM ---
    # If the message IS a direct message, instruct the user to use a server channel.
    if isinstance(message.channel, discord.DMChannel):
        try:
            # Don't reply if the DM is empty or just whitespace
            if message.content.strip():
                await message.channel.send("Please mention me in a server channel for AI prompts. I don't respond to DMs.")
        except discord.errors.Forbidden:
            # This is unlikely in DMs but is good practice for error handling.
            print(f"Could not send a DM to {message.author}")
        return # Stop processing messages from DMs

    # --- Process Server Channel conversation ---

    # Process message only if the bot is mentioned
    if client.user.mentioned_in(message):
        # Check if the bot has successfully loaded a Gemini model
        if model is None:
            print(f"Warning: Received mention from {message.author} but Gemini model is not initialized.")
            await message.reply("My AI brain is currently offline. Please ask an administrator to restart me.")
            return

        # Extract the user's message, removing the bot's mention (e.g., "@BotName hello" -> "hello")
        user_message = message.content.replace(f'<@{client.user.id}>', '').strip()

        if not user_message:
            await message.reply("Hey there! Mention me with a question or prompt, and I'll do my best to help!")
            return

        # --- Rate Limiting Check ---
        current_time = time.time()
        time_since_last_call = current_time - last_gemini_call_time

        if time_since_last_call < MIN_DELAY_BETWEEN_CALLS:
            remaining_time = MIN_DELAY_BETWEEN_CALLS - time_since_last_call
            await message.reply(f"Whoa there, one question at a time! Please wait {remaining_time:.1f} seconds before asking again to avoid hitting API limits.")
            return

        # --- Gemini API Call ---
        try:
            # Indicate that the bot is thinking
            async with message.channel.typing():
                print(f"Sending prompt to Gemini from {message.author} in server {message.guild.name}: '{user_message}'")
                # Use the async version of the function: generate_content_async
                response = await model.generate_content_async(user_message)

                ai_response_text = response.text
                print(f"Received response from Gemini (length: {len(ai_response_text)} chars).")

                last_gemini_call_time = time.time()

                # Split the response into chunks if it's too long for a single Discord message
                if len(ai_response_text) > 2000:
                    chunks = [ai_response_text[i:i + 1990] for i in range(0, len(ai_response_text), 1990)]
                    for i, chunk in enumerate(chunks):
                        if i == 0:
                            await message.reply(chunk)
                        else:
                            await message.channel.send(chunk)
                        await asyncio.sleep(1) # Small delay between chunks
                else:
                    await message.reply(ai_response_text)

        except Exception as e:
            print(f"Error processing message: {e}") # Log the full error for debugging

            # Handle specific Gemini API errors gracefully for the user
            error_message_str = str(e)
            if "Quota exceeded" in error_message_str:
                await message.reply("Oops! I'm getting a lot of questions right now and hit a rate limit. Please try again in about a minute.")
            elif "not found" in error_message_str or "not supported" in error_message_str:
                await message.reply("It seems my AI model had a serious issue and went offline. An administrator will need to restart me or fix my brain!")
                print("Gemini model became unavailable/unsupported. Bot restart needed for re-initialization.")
            else:
                await message.reply("Apologies, I encountered an unexpected error while trying to generate a response. Please try again later or contact an administrator.")

# --- Run the Bot ---
# This line starts the bot and connects it to Discord
client.run(DISCORD_BOT_TOKEN)
