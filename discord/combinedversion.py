# Corrected & Combined AI and Currency Exchange Discord Bot

import os
import discord
import requests
import re
import google.generativeai as genai
import asyncio
import time
from discord.ext import commands
from dotenv import load_dotenv

# --- Configuration ---
# Load environment variables from a .env file.
# Make sure your .env file has DISCORD_BOT_TOKEN and GEMINI_API_KEY.
load_dotenv()

DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
COMMAND_PREFIX = '!'

# --- Sanity Checks for Environment Variables ---
if not DISCORD_BOT_TOKEN:
    print("Error: DISCORD_BOT_TOKEN not found in .env file. Please set it.")
    exit(1)
if not GEMINI_API_KEY:
    print("Error: GEMINI_API_KEY not found in .env file. Please set it.")
    exit(1)

# --- API Configuration ---
# Configure the Gemini API
try:
    genai.configure(api_key=GEMINI_API_KEY)
except Exception as e:
    print(f"Fatal Error: Could not configure Gemini API: {e}")
    exit(1)

# Frankfurter.dev API endpoint for currency exchange rates
BASE_CURRENCY_API_URL = "https://api.frankfurter.dev/v1/latest"

# --- Global Variables & Settings ---
# Gemini AI settings
DEFAULT_MODEL = 'gemini-1.5-flash'
model = None  # This will store the initialized Gemini model object
last_gemini_call_time = 0
MIN_DELAY_BETWEEN_CALLS = 1.1 # In seconds. Helps prevent 429 Too Many Requests errors.

# --- Discord Bot Setup ---
# Define the necessary intents. message_content is crucial.
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True # Optional, but can be useful

# Initialize the bot using commands.Bot to handle both prefixed commands and events.
# We disable the default help command to create our own custom one.
bot = commands.Bot(command_prefix=COMMAND_PREFIX, intents=intents, help_command=None)

# --- Helper Functions ---

async def fetch_exchange_rates(base_currency: str, target_currency: str = None):
    """
    Fetches exchange rates from the Frankfurter API.
    Args:
        base_currency (str): The base currency code (e.g., "USD").
        target_currency (str, optional): The target currency code (e.g., "EUR").
    Returns:
        dict: API response data or None if an error occurs.
    """
    params = {'base': base_currency.upper()}
    if target_currency:
        params['to'] = target_currency.upper()

    try:
        response = requests.get(BASE_CURRENCY_API_URL, params=params)
        response.raise_for_status()  # Raises an HTTPError for bad responses (4xx or 5xx)
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error fetching exchange rates from API: {e}")
        return None

# --- Core Bot Event Handlers ---

@bot.event
async def on_ready():
    """
    Called when the bot successfully connects to Discord.
    Initializes the Gemini model and prints status.
    """
    global model
    print(f'Bot is ready! Logged in as {bot.user} (ID: {bot.user.id})')
    print(f"Command Prefix: '{COMMAND_PREFIX}' | Mention: @{bot.user.name}")
    print('------')

    # Initialize the Gemini model
    try:
        model = genai.GenerativeModel(DEFAULT_MODEL)
        print(f"Successfully initialized Gemini model: {DEFAULT_MODEL}")
    except Exception as e:
        print(f"CRITICAL: Error initializing Gemini model '{DEFAULT_MODEL}': {e}")
        print("AI functionality will be disabled.")
        model = None

@bot.event
async def on_message(message):
    """
    The main event handler that processes every message the bot can see.
    It routes messages to the correct function based on a clear priority.
    """
    # 1. Ignore messages from the bot itself to prevent loops
    if message.author == bot.user:
        return

    # 2. Handle Direct Messages
    if isinstance(message.channel, discord.DMChannel):
        if message.content.strip():
            try:
                await message.channel.send(
                    "I operate in server channels. Please use `!` commands or mention me there."
                )
            except discord.errors.Forbidden:
                print(f"Could not send a DM reply to {message.author}")
        return

    # 3. Prioritize AI mentions over any command processing
    if bot.user.mentioned_in(message):
        await handle_gemini_mention(message)
        return

    # **FIX:** This logic block correctly handles registered commands vs. dynamic commands.
    # 4. Check for registered commands (like !help) first.
    ctx = await bot.get_context(message)
    if ctx.valid:
        await bot.process_commands(message)
        return

    # 5. If not a registered command, it might be a dynamic currency command.
    if message.content.startswith(COMMAND_PREFIX):
        await handle_currency_command(message)
        return

# --- Logic Handler Functions ---

async def handle_currency_command(message):
    """
    Parses and responds to dynamic currency commands (e.g., !usd, !eur100 jpy).
    """
    # **FIX:** The check for a valid context is no longer needed here,
    # as the on_message event now handles the routing correctly.
    full_command_parts = message.content[len(COMMAND_PREFIX):].strip().split()
    if not full_command_parts:
        return

    base_currency, amount, target_currency = None, 1.0, None

    # --- Refined Command Parsing Logic ---
    first_arg = full_command_parts[0]
    currency_amount_match = re.match(r'^([A-Z]{2,4})(\d*\.?\d*)?$', first_arg, re.IGNORECASE)

    if currency_amount_match:
        base_currency = currency_amount_match.group(1).upper()
        attached_amount_str = currency_amount_match.group(2)
        if attached_amount_str:
            try:
                amount = float(attached_amount_str)
            except ValueError:
                amount = 1.0
        
        if len(full_command_parts) > 1:
            second_arg = full_command_parts[1]
            if re.match(r'^\d+(\.\d+)?$', second_arg):
                try:
                    amount = float(second_arg)
                    if len(full_command_parts) > 2:
                        target_currency = full_command_parts[2].upper()
                except ValueError: pass
            else:
                target_currency = second_arg.upper()
    else:
        # If the regex doesn't match, it's not a currency command we should handle.
        return

    # --- Fetch and Display Currency Rates ---
    status_message = await message.channel.send(f"Fetching exchange rates for **{base_currency}**, please wait...")
    rates_data = await fetch_exchange_rates(base_currency, target_currency)

    if rates_data and rates_data.get('rates'):
        base = rates_data.get('base')
        date = rates_data.get('date')
        rates = rates_data.get('rates')
        
        header = f"**Exchange Rates for {amount:.2f} {base} (as of {date}):**\n"

        if target_currency:
            rate_for_one = rates.get(target_currency)
            if rate_for_one is not None:
                calculated_rate = rate_for_one * amount
                response_message = header + f"**{amount:.2f} {base} = {calculated_rate:.4f} {target_currency}**"
                await status_message.edit(content=response_message)
            else:
                await status_message.edit(content=f"Could not find rate for `{target_currency}`. Please ensure it's a valid currency code.")
        else:
            # Handle potentially long list of all currencies
            await status_message.edit(content=header)
            rate_lines = [f"  - {currency}: {(rate_val * amount):.4f}" for currency, rate_val in rates.items()]
            
            current_chunk = ""
            for line in rate_lines:
                if len(current_chunk) + len(line) + 1 > 1900:
                    await message.channel.send(f"```\n{current_chunk}\n```")
                    current_chunk = line
                else:
                    current_chunk += "\n" + line
            
            if current_chunk:
                await message.channel.send(f"```\n{current_chunk}\n```")

    else:
        await status_message.edit(content=f"Sorry, I couldn't fetch exchange rates for `{base_currency}`. This could be due to an invalid currency code or an API issue.")


async def handle_gemini_mention(message):
    """
    Handles logic for generating and sending an AI response when the bot is mentioned.
    """
    global last_gemini_call_time

    if model is None:
        await message.reply("My AI brain is currently offline. Please ask an administrator to check the logs.")
        return

    user_message = message.content.replace(f'<@{bot.user.id}>', '').strip()
    if not user_message:
        await message.reply("Hello! Mention me with a question to get an AI response.")
        return

    # --- Rate Limiting Check ---
    current_time = time.time()
    if current_time - last_gemini_call_time < MIN_DELAY_BETWEEN_CALLS:
        remaining_time = MIN_DELAY_BETWEEN_CALLS - (current_time - last_gemini_call_time)
        await message.reply(f"I'm thinking... please wait {remaining_time:.1f}s before asking another question.")
        return

    # --- Gemini API Call ---
    try:
        async with message.channel.typing():
            print(f"Sending prompt to Gemini from {message.author}: '{user_message}'")
            # Use the async version of the function
            response = await model.generate_content_async(user_message)
            ai_response_text = response.text
            last_gemini_call_time = time.time()

            # Split response into chunks if it's too long for a single Discord message
            if len(ai_response_text) > 2000:
                chunks = [ai_response_text[i:i + 1990] for i in range(0, len(ai_response_text), 1990)]
                for i, chunk in enumerate(chunks):
                    if i == 0:
                        await message.reply(chunk)
                    else:
                        await message.channel.send(chunk)
                    await asyncio.sleep(1) # Small delay between sending chunks
            else:
                await message.reply(ai_response_text)
    except Exception as e:
        print(f"Error processing Gemini prompt: {e}")
        await message.reply("I'm sorry, I encountered an error while trying to generate a response. Please try again.")

# --- Bot Commands ---

@bot.command(name='help')
async def help_command(ctx):
    """
    Displays a formatted help message for all bot functionalities.
    """
    embed = discord.Embed(
        title="Bot Help",
        description="This bot has two main functions: Currency Exchange and AI Chat.",
        color=discord.Color.blue()
    )
    
    embed.add_field(
        name="🤖 AI Chat Functionality",
        value=f"To chat with the AI, simply mention the bot (`@{bot.user.name}`) followed by your question.",
        inline=False
    )
    
    embed.add_field(
        name=f"💱 Currency Exchange (Prefix: `{COMMAND_PREFIX}`)",
        value=(
            f"**Get all rates for a currency:**\n`{COMMAND_PREFIX}usd`\n\n"
            f"**Get rates for a specific amount:**\n`{COMMAND_PREFIX}usd100` or `{COMMAND_PREFIX}usd 100`\n\n"
            f"**Convert to a specific currency:**\n`{COMMAND_PREFIX}usd myr`\n\n"
            f"**Convert a specific amount:**\n`{COMMAND_PREFIX}usd100 myr` or `{COMMAND_PREFIX}usd 100 myr`"
        ),
        inline=False
    )
    
    embed.set_footer(text="Author: Jenny")
    
    await ctx.send(embed=embed)

# --- Run the Bot ---
if __name__ == '__main__':
    try:
        bot.run(DISCORD_BOT_TOKEN)
    except discord.LoginFailure:
        print("FATAL ERROR: Invalid Discord bot token. Please check your .env file and ensure DISCORD_BOT_TOKEN is correct.")
    except Exception as e:
        print(f"An unexpected error occurred while starting the bot: {e}")
