# --- MERGED AND USABLE DISCORD BOT ---
# This script combines the functionality of an AI/Currency bot and a Horoscope bot.
# FINAL VERSION

# --- Consolidated Imports ---
import os
import discord
import requests
import re
import google.generativeai as genai
import asyncio
import time
import json
import datetime
from discord import ui
from discord.ext import commands, tasks
from dotenv import load_dotenv

# --- Unified Configuration & Environment Loading ---
# Load environment variables from a .env file.
# Your .env file should contain:
# DISCORD_BOT_TOKEN="YOUR_DISCORD_BOT_TOKEN"
# GEMINI_API_KEY="YOUR_GEMINI_API_KEY"
# BOT_OWNER_ID="YOUR_DISCORD_USER_ID"
load_dotenv()

# Bot and API Credentials
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
BOT_OWNER_ID_STR = os.getenv("BOT_OWNER_ID")

# Bot Settings
COMMAND_PREFIX = '!'
USER_DATA_FILE = "abc.txt" # For Horoscope bot user data

# --- Sanity Checks for Environment Variables ---
if not DISCORD_BOT_TOKEN:
    print("FATAL ERROR: DISCORD_BOT_TOKEN not found in .env file. Please set it.")
    exit(1)
if not GEMINI_API_KEY:
    print("FATAL ERROR: GEMINI_API_KEY not found in .env file. Please set it. AI features will be disabled.")
if not BOT_OWNER_ID_STR:
    print("Warning: BOT_OWNER_ID not found in .env file. Owner-only commands will be disabled.")

# Convert owner_id from .env to an integer.
try:
    owner_id_int = int(BOT_OWNER_ID_STR) if BOT_OWNER_ID_STR else None
except ValueError:
    print(f"Warning: Invalid BOT_OWNER_ID '{BOT_OWNER_ID_STR}'. It must be a number. Owner-only commands will be disabled.")
    owner_id_int = None

# --- API & Global Variable Setup ---
# Configure the Gemini API
if GEMINI_API_KEY:
    try:
        genai.configure(api_key=GEMINI_API_KEY)
    except Exception as e:
        print(f"Fatal Error: Could not configure Gemini API: {e}")
        GEMINI_API_KEY = None # Disable AI features if config fails
else:
    model = None

# Frankfurter.dev API endpoint for currency exchange rates
BASE_CURRENCY_API_URL = "https://api.frankfurter.dev/v1/latest"

# Gemini AI settings
DEFAULT_MODEL = 'gemini-1.5-flash'
model = None  # This will store the initialized Gemini model object
last_gemini_call_time = 0
MIN_DELAY_BETWEEN_CALLS = 1.1  # In seconds

# --- Unified Discord Bot Setup ---
# Define all necessary intents from both files.
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True
intents.messages = True

# Initialize a single bot instance to handle all commands and events.
bot = commands.Bot(command_prefix=COMMAND_PREFIX, intents=intents, help_command=None, owner_id=owner_id_int)


# --- Horoscope Bot: UI Components ---

class ZodiacSelect(ui.Select):
    """ A dropdown menu for selecting a zodiac sign. """
    def __init__(self):
        options = [
            discord.SelectOption(label="Aries", emoji="♈"), discord.SelectOption(label="Taurus", emoji="♉"),
            discord.SelectOption(label="Gemini", emoji="♊"), discord.SelectOption(label="Cancer", emoji="♋"),
            discord.SelectOption(label="Leo", emoji="♌"), discord.SelectOption(label="Virgo", emoji="♍"),
            discord.SelectOption(label="Libra", emoji="♎"), discord.SelectOption(label="Scorpio", emoji="♏"),
            discord.SelectOption(label="Sagittarius", emoji="♐"), discord.SelectOption(label="Capricorn", emoji="♑"),
            discord.SelectOption(label="Aquarius", emoji="♒"), discord.SelectOption(label="Pisces", emoji="♓"),
        ]
        super().__init__(placeholder="Choose your zodiac sign...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        user_id = str(interaction.user.id)
        selected_sign = self.values[0]

        users = load_user_data()
        is_update = user_id in users
        users[user_id] = selected_sign
        save_user_data(users)

        confirmation_message = f"✅ Your zodiac sign has been updated to **{selected_sign}**!" if is_update else f"✅ Your zodiac sign has been registered as **{selected_sign}**!"
        await interaction.response.edit_message(content=confirmation_message, view=None)
        await fetch_and_send_horoscope(interaction.channel, selected_sign, user=interaction.user)

class ZodiacSelectionView(ui.View):
    """ A view that contains the ZodiacSelect dropdown. """
    def __init__(self, author: discord.User, *, timeout=120):
        super().__init__(timeout=timeout)
        self.author = author
        self.add_item(ZodiacSelect())

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author.id:
            await interaction.response.send_message("This selection menu is not for you.", ephemeral=True)
            return False
        return True

# --- Horoscope Bot: Automated Daily Task ---

# Define the time for the task to run.
# The user requested 8:00 AM in their local time (Malaysia, UTC+8).
# The tasks.loop function uses UTC time. 8:00 AM MYT is 00:00 UTC.
run_time = datetime.time(hour=0, minute=0, tzinfo=datetime.timezone.utc)

@tasks.loop(time=run_time)
async def send_daily_horoscopes():
    """
    A background task that sends daily horoscopes to all registered users.
    This is scheduled to run at 8:00 AM Malaysia Time (00:00 UTC) every day.
    """
    print(f"[{datetime.datetime.now()}] Running daily horoscope task for 8:00 AM MYT...")
    users = load_user_data()
    if not users:
        print("No registered users to send horoscopes to.")
        return

    for user_id, sign in users.items():
        try:
            user = await bot.fetch_user(int(user_id))
            if user:
                print(f"Sending horoscope to {user.name} ({user_id}) for sign {sign}")
                await fetch_and_send_horoscope(user, sign)
            else:
                print(f"Could not find user with ID: {user_id}")
        except discord.NotFound:
            print(f"User with ID {user_id} not found. They might have left a shared server.")
        except discord.Forbidden:
            print(f"Cannot send DM to user {user_id}. They might have DMs disabled.")
        except Exception as e:
            print(f"An error occurred while processing user {user_id}: {e}")
    print("Daily horoscope task finished.")

@send_daily_horoscopes.before_loop
async def before_daily_task():
    """ Ensures the bot is fully connected before the loop starts. """
    await bot.wait_until_ready()


# --- All Helper Functions ---

def load_user_data():
    """ Loads user data (zodiac signs) from the specified file. """
    if not os.path.exists(USER_DATA_FILE):
        return {}
    try:
        with open(USER_DATA_FILE, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return {}

def save_user_data(data):
    """ Saves zodiac sign data to the user data file. """
    with open(USER_DATA_FILE, 'w') as f:
        json.dump(data, f, indent=4)

async def fetch_exchange_rates(base_currency: str, target_currency: str = None):
    """ Fetches exchange rates from the Frankfurter API. """
    params = {'base': base_currency.upper()}
    if target_currency:
        params['to'] = target_currency.upper()
    try:
        response = requests.get(BASE_CURRENCY_API_URL, params=params)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error fetching exchange rates from API: {e}")
        return None

async def fetch_and_send_horoscope(destination, sign, user: discord.User = None):
    """ Fetches a horoscope and sends it to a user or channel. """
    url = f"https://horoscope-app-api.vercel.app/api/v1/get-horoscope/daily?sign={sign}&day=TODAY"
    try:
        mention_text = f"{user.mention}, " if user else ""
        if isinstance(destination, (commands.Context, discord.TextChannel, discord.Interaction)):
            await destination.send(f"{mention_text}fetching today's horoscope for **{sign}**...")

        response = requests.get(url)
        response.raise_for_status()
        horoscope_data = response.json()

        if horoscope_data.get('success') and 'data' in horoscope_data:
            data = horoscope_data['data']
            horoscope_text = data.get('horoscope_data', 'No horoscope data found for today.')
            embed = discord.Embed(
                title=f"✨ Daily Horoscope for {sign} ✨",
                description=horoscope_text,
                color=discord.Color.purple()
            )
            embed.set_footer(text=f"Date: {data.get('date')}")
            # For DMs, the destination object can send directly.
            if isinstance(destination, (discord.User, discord.Member)):
                 await destination.send(embed=embed)
            else: # For channels, use the original destination.send
                 await destination.send(embed=embed)
            return True
        else:
            await destination.send("Sorry, I couldn't retrieve the horoscope right now. Please try again later.")
            return False
    except requests.exceptions.RequestException as e:
        print(f"API Request failed for sign {sign}: {e}")
        if isinstance(destination, (commands.Context, discord.TextChannel, discord.Interaction, discord.User, discord.Member)):
            await destination.send("Sorry, there was an error connecting to the horoscope service.")
        return False
    except Exception as e:
        print(f"An unexpected error occurred for sign {sign}: {e}")
        if isinstance(destination, (commands.Context, discord.TextChannel, discord.Interaction, discord.User, discord.Member)):
            await destination.send("An unexpected error occurred. Please try again.")
        return False


# --- Core Logic Handler Functions ---

async def handle_currency_command(message):
    """ Parses and responds to dynamic currency commands (e.g., !usd, !eur100 jpy). """
    full_command_parts = message.content[len(COMMAND_PREFIX):].strip().split()
    if not full_command_parts:
        return

    base_currency, amount, target_currency = None, 1.0, None
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
        return

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
    """ Handles logic for generating an AI response when the bot is mentioned. """
    global last_gemini_call_time
    if model is None:
        await message.reply("My AI brain is currently offline. Please ask an administrator to check the logs.")
        return

    user_message = message.content.replace(f'<@{bot.user.id}>', '').strip()
    if not user_message:
        await message.reply("Hello! Mention me with a question to get an AI response.")
        return

    current_time = time.time()
    if current_time - last_gemini_call_time < MIN_DELAY_BETWEEN_CALLS:
        remaining_time = MIN_DELAY_BETWEEN_CALLS - (current_time - last_gemini_call_time)
        await message.reply(f"I'm thinking... please wait {remaining_time:.1f}s before asking another question.")
        return

    try:
        async with message.channel.typing():
            print(f"Sending prompt to Gemini from {message.author}: '{user_message}'")
            response = await model.generate_content_async(user_message)
            ai_response_text = response.text
            last_gemini_call_time = time.time()
            if len(ai_response_text) > 2000:
                chunks = [ai_response_text[i:i + 1990] for i in range(0, len(ai_response_text), 1990)]
                for i, chunk in enumerate(chunks):
                    if i == 0:
                        await message.reply(chunk)
                    else:
                        await message.channel.send(chunk)
                    await asyncio.sleep(1)
            else:
                await message.reply(ai_response_text)
    except Exception as e:
        print(f"Error processing Gemini prompt: {e}")
        await message.reply("I'm sorry, I encountered an error while trying to generate a response. Please try again.")


# --- Unified Bot Event Handlers ---

@bot.event
async def on_ready():
    """ Called when the bot successfully connects to Discord. Runs startup tasks. """
    global model
    print(f'Bot is ready! Logged in as {bot.user.name} (ID: {bot.user.id})')
    print(f"Command Prefix: '{COMMAND_PREFIX}' | Mention: @{bot.user.name}")
    print('------')

    # Task 1: Initialize the Gemini model
    if GEMINI_API_KEY:
        try:
            model = genai.GenerativeModel(DEFAULT_MODEL)
            print(f"Successfully initialized Gemini model: {DEFAULT_MODEL}")
        except Exception as e:
            print(f"CRITICAL: Error initializing Gemini model '{DEFAULT_MODEL}': {e}")
            print("AI functionality will be disabled.")
            model = None
    else:
        print("Gemini API key not found. AI functionality is disabled.")

    # Task 2: Start the daily horoscope background task
    if not send_daily_horoscopes.is_running():
        send_daily_horoscopes.start()
        print("Started the daily horoscope background task.")

@bot.event
async def on_message(message):
    """ Main event handler to process all messages and route them correctly. """
    if message.author == bot.user:
        return
    if isinstance(message.channel, discord.DMChannel):
        if message.content.strip():
            try:
                await message.channel.send("I operate in server channels. Please use `!` commands or mention me there.")
            except discord.errors.Forbidden:
                print(f"Could not send a DM reply to {message.author}")
        return

    # Priority 1: AI mentions
    if bot.user.mentioned_in(message):
        await handle_gemini_mention(message)
        return

    # Priority 2: Registered commands (e.g., !help, !reg, !mod, !remove)
    ctx = await bot.get_context(message)
    if ctx.valid:
        await bot.process_commands(message)
        return

    # Priority 3: Dynamic currency commands (e.g., !usd)
    if message.content.startswith(COMMAND_PREFIX):
        await handle_currency_command(message)
        return


# --- All Bot Commands ---

@bot.command(name='help')
async def help_command(ctx):
    """ Displays a formatted, combined help message for all bot functionalities. """
    embed = discord.Embed(
        title=f"{bot.user.name} Help",
        description="This bot provides AI Chat, Currency Exchange, and Horoscope functionalities.",
        color=discord.Color.purple()
    )
    embed.add_field(
        name="🤖 AI Chat Functionality",
        value=f"To chat with the AI, simply mention the bot (`@{bot.user.name}`) followed by your question.",
        inline=False
    )
    embed.add_field(
        name=f"💱 Currency Exchange (Prefix: `{COMMAND_PREFIX}`)",
        value=(
            f"**Get all rates for a currency:** `{COMMAND_PREFIX}usd`\n"
            f"**Get rates for a specific amount:** `{COMMAND_PREFIX}usd100` or `{COMMAND_PREFIX}usd 100`\n"
            f"**Convert to a specific currency:** `{COMMAND_PREFIX}usd myr`\n"
            f"**Convert a specific amount:** `{COMMAND_PREFIX}usd100 myr` or `{COMMAND_PREFIX}usd 100 myr`"
        ),
        inline=False
    )
    embed.add_field(
        name=f"✨ Daily Horoscope (Prefix: `{COMMAND_PREFIX}`)",
        value=(
            f"**Register your sign:** `{COMMAND_PREFIX}reg`\n"
            f"**Modify your sign:** `{COMMAND_PREFIX}mod`\n"
            f"**Remove your record:** `{COMMAND_PREFIX}remove`\n\n"
            f"Once registered, you will automatically receive your horoscope via DM every day!"
        ),
        inline=False
    )
    embed.set_footer(text="Made with ❤️ by Jenny")
    await ctx.send(embed=embed)

@bot.command(name='reg')
async def reg(ctx: commands.Context):
    """ Main command to register for horoscopes or get your daily reading. """
    user_id = str(ctx.author.id)
    users = load_user_data()
    if user_id in users:
        sign = users[user_id]
        await fetch_and_send_horoscope(ctx, sign, user=ctx.author)
        await ctx.send(f"*(Tip: Use `{COMMAND_PREFIX}mod` to update your sign.)*", delete_after=20)
    else:
        view = ZodiacSelectionView(author=ctx.author)
        await ctx.send(f"Welcome, {ctx.author.mention}! Please select your zodiac sign to register:", view=view)

@bot.command(name='mod')
async def mod(ctx: commands.Context):
    """ Allows a user to change their registered zodiac sign. """
    view = ZodiacSelectionView(author=ctx.author)
    await ctx.send(f"{ctx.author.mention}, please select your new zodiac sign from the menu below:", view=view)

@bot.command(name='remove')
async def remove_record(ctx: commands.Context):
    """ Deletes the user's saved zodiac sign from the record. """
    user_id = str(ctx.author.id)
    users = load_user_data()

    if user_id in users:
        del users[user_id]
        save_user_data(users)
        await ctx.send(f"✅ Your record has been deleted, {ctx.author.mention}. You will no longer receive daily horoscopes. Use `{COMMAND_PREFIX}reg` to register again.")
    else:
        await ctx.send(f"You do not have a registered sign to delete, {ctx.author.mention}. Use `{COMMAND_PREFIX}reg` to get started.")

@bot.command(name='test')
@commands.is_owner()
async def test_daily_horoscopes(ctx):
    """
    Manually triggers a private test of the horoscope function for the bot owner.
    This will only send a horoscope to the owner, not all registered users.
    """
    # 1. Acknowledge the command in the channel discreetly
    await ctx.message.add_reaction('🧪')

    owner_id = str(ctx.author.id)
    users = load_user_data()

    # 2. Check if the owner is registered for horoscopes
    if owner_id in users:
        sign = users[owner_id]
        # 3. Send a private confirmation and run the test only for the owner
        await ctx.author.send(f"✅ Running a personal test for your sign: **{sign}**. You should receive your horoscope message next.")
        await fetch_and_send_horoscope(ctx.author, sign, user=ctx.author)
    else:
        # 4. Handle the case where the owner hasn't registered yet
        await ctx.author.send(f"⚠️ You are not registered for horoscopes. Please use `{COMMAND_PREFIX}reg` first to test this feature.")


# --- Main Execution Block ---
if __name__ == '__main__':
    try:
        bot.run(DISCORD_BOT_TOKEN)
    except discord.LoginFailure:
        print("FATAL ERROR: Invalid Discord bot token. Please check your .env file and ensure DISCORD_BOT_TOKEN is correct.")
    except Exception as e:
        print(f"An unexpected error occurred while starting the bot: {e}")