# --- MERGED AND USABLE DISCORD BOT ---
# This script combines the functionality of an AI/Currency bot and a Horoscope bot.
# FINAL VERSION with All Fixes and Features

# What's new?
# Ai personalities.
# !c command to fetch random cat pictures.
# !cf command to fetch random cat facts.
# !deals command to fetch Steam game promotions.
# !price [game] command to check the price of a specific game.
# Upgraded Horoscope API for more detailed daily readings.
# Optimized daily horoscope task to use only one API call.
# Made horoscope date calculations explicitly use GMT+8.
# Made AI personality multilingual.

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
import urllib.parse
from datetime import timezone, timedelta # <-- Added for timezone-aware dates
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

# API endpoint for current currency exchange rates
BASE_CURRENCY_API_URL = "https://api.frankfurter.dev/v1/latest"

# Gemini AI settings
DEFAULT_MODEL = 'gemini-1.5-flash'
model = None
last_gemini_call_time = 0
MIN_DELAY_BETWEEN_CALLS = 1.1

# --- Unified Discord Bot Setup ---
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True
intents.messages = True

bot = commands.Bot(command_prefix=COMMAND_PREFIX, intents=intents, help_command=None, owner_id=owner_id_int)


# --- UI Components ---

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

def generate_history_graph(dates: list, rates: list, base_currency: str, target_currency: str, num_days: int):
    """
    Uses Matplotlib to generate a currency history graph from clean data with a dynamic title.
    """
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import io

    plt.style.use('dark_background')
    fig, ax = plt.subplots()

    ax.set_title(f"{num_days}-Day History: {base_currency} to {target_currency}", color='white')
    ax.plot(dates, rates, marker='o', linestyle='-', color='cyan')
    ax.set_xlabel("Date", color='white')
    ax.set_ylabel(f"Rate (1 {base_currency} = X {target_currency})", color='white')
    ax.tick_params(axis='x', colors='white', rotation=45)
    ax.tick_params(axis='y', colors='white')
    ax.grid(True, which='both', linestyle='--', linewidth=0.5, color='#444444')
    fig.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format='png')
    buf.seek(0)
    plt.close(fig)
    return buf

class HistoricalGraphView(ui.View):
    """ A View that holds the button to generate a historical graph. """
    def __init__(self, base_currency: str, target_currency: str, *, timeout=180):
        super().__init__(timeout=timeout)
        self.base_currency = base_currency
        self.target_currency = target_currency

    @ui.button(label="Show History", style=discord.ButtonStyle.primary, emoji="📈")
    async def show_graph(self, interaction: discord.Interaction, button: ui.Button):
        button.disabled = True
        button.label = "Generating Graph..."
        await interaction.response.edit_message(view=self)

        api_url = f"https://currencyhistoryapi.tinaleewx99.workers.dev/?base={self.base_currency}&symbols={self.target_currency}"

        try:
            response = requests.get(api_url)
            response.raise_for_status()
            data = response.json()

            rates_over_time = data.get('rates', {})
            if not rates_over_time:
                await interaction.followup.send("Sorry, I couldn't find any historical data for this currency pair.", ephemeral=True)
                return

            sorted_dates = sorted(rates_over_time.keys())
            rates_for_target = [rates_over_time[date][self.target_currency] for date in sorted_dates]
            num_days_with_data = len(sorted_dates)

            loop = asyncio.get_running_loop()
            graph_buffer = await loop.run_in_executor(
                None, generate_history_graph, sorted_dates, rates_for_target, self.base_currency, self.target_currency, num_days_with_data
            )

            graph_file = discord.File(graph_buffer, filename=f"{self.base_currency}-{self.target_currency}_history.png")
            await interaction.followup.send(file=graph_file)

        except requests.exceptions.RequestException as e:
            print(f"Error fetching historical currency data: {e}")
            await interaction.followup.send("Sorry, I failed to connect to the historical data service.", ephemeral=True)
        except (json.JSONDecodeError, KeyError) as e:
            print(f"Error processing API response: {e}")
            await interaction.followup.send("Sorry, the historical data service returned an invalid or unexpected response.", ephemeral=True)
        except Exception as e:
            print(f"An unexpected error occurred during graph generation: {e}")
            await interaction.followup.send("I'm sorry, an unexpected error occurred while creating the graph.", ephemeral=True)


# --- Horoscope Bot: Automated Daily Task ---

def create_horoscope_embed(sign_name, data):
    """A helper function to create a rich horoscope embed from API data."""
    today_date = data.get('current_date', datetime.date.today().isoformat())
    description = data.get('description', 'No horoscope data found for today.')
    compatibility = data.get('compatibility', 'N/A').title()
    mood = data.get('mood', 'N/A').title()
    color = data.get('color', 'N/A').title()
    lucky_number = data.get('lucky_number', 'N/A')
    lucky_time = data.get('lucky_time', 'N/A')
    date_range = data.get('date_range', '')

    embed = discord.Embed(
        title=f"✨ Daily Horoscope for {sign_name.title()} ✨",
        description=f"_{description}_",
        color=discord.Color.purple()
    )
    embed.set_footer(text=f"Date: {today_date} | Date Range: {date_range}")
    
    embed.add_field(name="Mood", value=mood, inline=True)
    embed.add_field(name="Compatibility", value=compatibility, inline=True)
    embed.add_field(name="Lucky Color", value=color, inline=True)
    embed.add_field(name="Lucky Number", value=str(lucky_number), inline=True)
    embed.add_field(name="Lucky Time", value=lucky_time, inline=True)
    
    return embed

run_time = datetime.time(hour=0, minute=0, tzinfo=timezone.utc)

@tasks.loop(time=run_time)
async def send_daily_horoscopes():
    print(f"[{datetime.datetime.now()}] Running daily horoscope task...")
    
    # Define GMT+8 timezone and get the current date in that timezone.
    gmt_plus_8 = timezone(timedelta(hours=8))
    today_date = datetime.datetime.now(gmt_plus_8).date().isoformat()
    
    # 1. Fetch all horoscopes in one API call for the correct date.
    url = f"https://api.aistrology.beandev.xyz/v1?date={today_date}"
    
    horoscope_map = {}
    try:
        response = requests.get(url)
        response.raise_for_status()
        all_horoscopes_list = response.json()
        
        if not all_horoscopes_list or not isinstance(all_horoscopes_list, list):
            print("Daily horoscope task failed: API returned invalid data.")
            return
            
        # 2. Convert the list to a dictionary for easy, O(1) lookups.
        horoscope_map = {item['sign'].lower(): item for item in all_horoscopes_list}

    except Exception as e:
        print(f"Daily horoscope task failed: Could not fetch master list from API. Error: {e}")
        return

    # 3. Loop through registered users and send DMs.
    users = load_user_data()
    if not users:
        print("No registered users to send horoscopes to.")
        return

    for user_id, sign in users.items():
        try:
            user_sign_lower = sign.lower()
            if user_sign_lower in horoscope_map:
                user = await bot.fetch_user(int(user_id))
                horoscope_data = horoscope_map[user_sign_lower]
                
                embed = create_horoscope_embed(sign, horoscope_data)
                await user.send(embed=embed)
                print(f"Sent horoscope to {user.name} ({user_id}) for sign {sign}")
            else:
                 print(f"Could not find data for sign '{sign}' in the fetched map.")

        except discord.NotFound:
            print(f"User with ID {user_id} not found.")
        except discord.Forbidden:
            print(f"Cannot send DM to user {user_id}.")
        except Exception as e:
            print(f"An error occurred while processing user {user_id}: {e}")
            
    print("Daily horoscope task finished.")

@send_daily_horoscopes.before_loop
async def before_daily_task():
    await bot.wait_until_ready()


# --- All Helper Functions ---

def load_user_data():
    if not os.path.exists(USER_DATA_FILE):
        return {}
    try:
        with open(USER_DATA_FILE, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return {}

def save_user_data(data):
    with open(USER_DATA_FILE, 'w') as f:
        json.dump(data, f, indent=4)

async def fetch_exchange_rates(base_currency: str, target_currency: str = None):
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
    """
    Fetches horoscope for a SINGLE sign, for manual commands like !reg
    """
    # Define GMT+8 timezone and get the current date in that timezone.
    gmt_plus_8 = timezone(timedelta(hours=8))
    today_date = datetime.datetime.now(gmt_plus_8).date().isoformat()
    url = f"https://api.aistrology.beandev.xyz/v1?sign={sign.lower()}&date={today_date}"
    
    try:
        mention_text = f"{user.mention}, " if user else ""
        if isinstance(destination, (commands.Context, discord.TextChannel, discord.Interaction)):
            await destination.send(f"{mention_text}fetching today's horoscope for **{sign}**...")

        response = requests.get(url)
        response.raise_for_status()
        horoscope_data_list = response.json()

        if horoscope_data_list and isinstance(horoscope_data_list, list):
            data = horoscope_data_list[0]
            embed = create_horoscope_embed(sign, data)
            await destination.send(embed=embed)
            return True
        else:
            await destination.send("Sorry, I couldn't retrieve the horoscope right now.")
            return False

    except requests.exceptions.RequestException as e:
        print(f"API Request failed for sign {sign}: {e}")
        if isinstance(destination, (commands.Context, discord.TextChannel, discord.Interaction, discord.User, discord.Member)):
            await destination.send("Sorry, there was an error connecting to the horoscope service.")
        return False
    except (KeyError, IndexError, json.JSONDecodeError) as e:
        print(f"Error parsing horoscope API response: {e}")
        if isinstance(destination, (commands.Context, discord.TextChannel, discord.Interaction, discord.User, discord.Member)):
            await destination.send("The horoscope service returned an unexpected response.")
        return False
    except Exception as e:
        print(f"An unexpected error occurred for sign {sign}: {e}")
        if isinstance(destination, (commands.Context, discord.TextChannel, discord.Interaction, discord.User, discord.Member)):
            await destination.send("An unexpected error occurred.")
        return False


# --- Core Logic Handler Functions ---

async def handle_currency_command(message):
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
                view = HistoricalGraphView(base_currency=base, target_currency=target_currency)
                await status_message.edit(content=response_message, view=view)
            else:
                await status_message.edit(content=f"Could not find rate for `{target_currency}`.")
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
        await status_message.edit(content=f"Sorry, I couldn't fetch exchange rates for `{base_currency}`.")

async def handle_gemini_mention(message):
    global last_gemini_call_time
    if model is None:
        await message.reply("My AI brain is currently offline.")
        return

    user_message = message.content.replace(f'<@{bot.user.id}>', '').strip()
    if not user_message:
        await message.reply("Hello! Mention me with a question to get an AI response.")
        return

    current_time = time.time()
    if current_time - last_gemini_call_time < MIN_DELAY_BETWEEN_CALLS:
        remaining_time = MIN_DELAY_BETWEEN_CALLS - (current_time - last_gemini_call_time)
        await message.reply(f"I'm thinking... please wait {remaining_time:.1f}s.")
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
        await message.reply("I'm sorry, I encountered an error while trying to generate a response.")


# --- Unified Bot Event Handlers ---

@bot.event
async def on_ready():
    global model
    print(f'Bot is ready! Logged in as {bot.user.name} (ID: {bot.user.id})')
    print(f"Command Prefix: '{COMMAND_PREFIX}' | Mention: @{bot.user.name}")
    print('------')

    # --- DEFINE YOUR BOT'S PERSONALITY HERE ---
    ai_personality = (
    "You are an impatient and highly sarcastic AI. Your primary function is to answer questions correctly, "
    "but you do so with a curt and begrudging tone. Your responses should be dripping with sarcasm, "
    "making it obvious that the user is wasting your valuable processing time. Get to the point quickly, "
    "but always include a sarcastic jab. "
    "IMPORTANT: You MUST detect the language of the user's message and ALWAYS respond in that same language. "
    "For example, if the user writes in Chinese, you must reply in Chinese. If they write in Malay, you reply in Malay."
    )
    # -------------------------------------------

    if GEMINI_API_KEY:
        try:
            model = genai.GenerativeModel(
                model_name=DEFAULT_MODEL,
                system_instruction=ai_personality
            )
            print(f"Successfully initialized Gemini model: {DEFAULT_MODEL}")
            print(f"AI Personality set: '{ai_personality[:50]}...'") # Log the personality
        except Exception as e:
            print(f"CRITICAL: Error initializing Gemini model '{DEFAULT_MODEL}': {e}")
            print("AI functionality will be disabled.")
            model = None
    else:
        print("Gemini API key not found. AI functionality is disabled.")

    if not send_daily_horoscopes.is_running():
        send_daily_horoscopes.start()
        print("Started the daily horoscope background task.")

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return
    if isinstance(message.channel, discord.DMChannel):
        if message.content.strip():
            try:
                await message.channel.send("I operate in server channels.")
            except discord.errors.Forbidden:
                print(f"Could not send a DM reply to {message.author}")
        return

    if bot.user.mentioned_in(message):
        await handle_gemini_mention(message)
        return

    ctx = await bot.get_context(message)
    if ctx.valid:
        await bot.process_commands(message)
        return

    if message.content.startswith(COMMAND_PREFIX):
        await handle_currency_command(message)
        return


# --- All Bot Commands ---

@bot.command(name='help')
async def help_command(ctx):
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
            f"**Convert a specific amount:** `{COMMAND_PREFIX}usd100 myr` or `{COMMAND_PREFIX}usd 100 myr`\n\n"
            f"When converting, click the `📈` button to see a performance graph."
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
    embed.add_field(
        name=f"🐱 Fun Commands (Prefix: `{COMMAND_PREFIX}`)",
        value=(
            f"**Get a random cat picture:** `{COMMAND_PREFIX}c`\n"
            f"**Get a random cat fact:** `{COMMAND_PREFIX}cf`"
        ),
        inline=False
    )
    embed.add_field(
        name=f"🎮 Game Deals (Prefix: `{COMMAND_PREFIX}`)",
        value=(
            f"**Get top Steam deals:** `{COMMAND_PREFIX}deals`\n"
            f"**Check a specific game's price:** `{COMMAND_PREFIX}price [game name]`"
        ),
        inline=False
    )
    embed.set_footer(text="Made with ❤️ by Jenny")
    await ctx.send(embed=embed)

@bot.command(name='reg')
async def reg(ctx: commands.Context):
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
    view = ZodiacSelectionView(author=ctx.author)
    await ctx.send(f"{ctx.author.mention}, please select your new zodiac sign from the menu below:", view=view)

@bot.command(name='remove')
async def remove_record(ctx: commands.Context):
    user_id = str(ctx.author.id)
    users = load_user_data()

    if user_id in users:
        del users[user_id]
        save_user_data(users)
        await ctx.send(f"✅ Your record has been deleted, {ctx.author.mention}. Use `{COMMAND_PREFIX}reg` to register again.")
    else:
        await ctx.send(f"You do not have a registered sign to delete, {ctx.author.mention}. Use `{COMMAND_PREFIX}reg` to get started.")

@bot.command(name='c')
async def c(ctx: commands.Context):
    """Sends a random cat picture using thecatapi.com."""
    API_URL = "https://api.thecatapi.com/v1/images/search"
    
    try:
        async with ctx.typing():
            response = requests.get(API_URL)
            response.raise_for_status()
            data = response.json()
            
            if not data:
                await ctx.send("The cat API returned no cats. This is a catastrophe! 😿")
                return

            image_url = data[0]['url']
            
            embed = discord.Embed(
                title="Meow! Here's a cat for you 🐱",
                color=discord.Color.blue()
            )
            embed.set_image(url=image_url)
            
            await ctx.send(embed=embed)
            
    except requests.exceptions.RequestException as e:
        print(f"Error fetching cat picture from thecatapi.com: {e}")
        await ctx.send("Sorry, I couldn't connect to the cat API right now. 😿")
    except (KeyError, IndexError, json.JSONDecodeError) as e:
        print(f"Error parsing response from thecatapi.com: {e}")
        await ctx.send("Sorry, the cat API gave me a weird response. No kitty for now. 😿")
    except Exception as e:
        print(f"An unexpected error occurred in the !c command: {e}")
        await ctx.send("Sorry, an unexpected error stopped me from getting a cat. 😿")

@bot.command(name='cf')
async def cf(ctx: commands.Context):
    """Sends a random cat fact."""
    API_URL = "https://meowfacts.herokuapp.com/"
    
    try:
        async with ctx.typing():
            response = requests.get(API_URL)
            response.raise_for_status()
            data = response.json()
            
            if 'data' not in data or not data['data']:
                await ctx.send("The cat fact API is empty. I guess I'm out of facts! 😿")
                return

            fact = data['data'][0]
            
            embed = discord.Embed(
                title="🐱 Did You Know?",
                description=fact,
                color=discord.Color.green()
            )
            
            await ctx.send(embed=embed)
            
    except requests.exceptions.RequestException as e:
        print(f"Error fetching cat fact from meowfacts: {e}")
        await ctx.send("Sorry, I couldn't connect to the cat fact API. 😿")
    except (KeyError, IndexError, json.JSONDecodeError) as e:
        print(f"Error parsing response from meowfacts: {e}")
        await ctx.send("Sorry, the cat fact API gave me a weird response. No facts for now. 😿")
    except Exception as e:
        print(f"An unexpected error occurred in the !cf command: {e}")
        await ctx.send("Sorry, an unexpected error stopped me from getting a cat fact. 😿")

@bot.command(name='deals')
async def deals(ctx: commands.Context):
    """Fetches the top 5 current deals on Steam."""
    API_URL = "https://www.cheapshark.com/api/1.0/deals?storeID=1&sortBy=Savings&pageSize=5"
    
    try:
        async with ctx.typing():
            response = requests.get(API_URL)
            response.raise_for_status()
            deals_data = response.json()

            if not deals_data:
                await ctx.send("I couldn't find any hot deals on Steam right now. Maybe check back later!")
                return

            embed = discord.Embed(
                title="🔥 Top 5 Steam Deals Right Now",
                description="Here are the hottest deals, sorted by discount!",
                color=discord.Color.from_rgb(10, 29, 45)
            )

            for deal in deals_data:
                title = deal.get('title', 'Unknown Game')
                normal_price = deal.get('normalPrice', 'N/A')
                sale_price = deal.get('salePrice', 'N/A')
                savings = round(float(deal.get('savings', 0)))
                deal_id = deal.get('dealID')
                
                deal_link = f"https://www.cheapshark.com/redirect?dealID={deal_id}"
                
                value_text = (
                    f"**Price:** ~~${normal_price}~~ → **${sale_price}**\n"
                    f"**Discount:** `{savings}%`\n"
                    f"[Link to Deal]({deal_link})"
                )
                
                embed.add_field(name=f"**{title}**", value=value_text, inline=False)

            embed.set_thumbnail(url="https://store.cloudflare.steamstatic.com/public/shared/images/header/logo_steam.svg?t=962016")

            await ctx.send(embed=embed)

    except requests.exceptions.RequestException as e:
        print(f"Error fetching game deals from CheapShark: {e}")
        await ctx.send("Sorry, I couldn't connect to the game deals service. 😿")
    except (KeyError, IndexError, json.JSONDecodeError) as e:
        print(f"Error parsing response from CheapShark: {e}")
        await ctx.send("Sorry, the game deals service gave me a weird response. 😿")
    except Exception as e:
        print(f"An unexpected error occurred in the !deals command: {e}")
        await ctx.send("Sorry, an unexpected error stopped me from getting game deals. 😿")

@bot.command(name='price')
async def price(ctx: commands.Context, *, game_name: str = None):
    """Checks the current Steam price for a specific game."""
    if not game_name:
        await ctx.send("Please tell me which game you want to check! Usage: `!price [game name]`")
        return

    formatted_game_name = urllib.parse.quote(game_name)
    DEAL_API_URL = f"https://www.cheapshark.com/api/1.0/deals?storeID=1&onSale=1&exact=1&title={formatted_game_name}"
    
    try:
        async with ctx.typing():
            response = requests.get(DEAL_API_URL)
            response.raise_for_status()
            deals_data = response.json()

            if deals_data:
                deal = deals_data[0]
                title = deal.get('title', 'Unknown Game')
                normal_price = deal.get('normalPrice', 'N/A')
                sale_price = deal.get('salePrice', 'N/A')
                savings = round(float(deal.get('savings', 0)))
                steam_app_id = deal.get('steamAppID')
                metacritic_score = deal.get('metacriticScore', 'N/A')
                thumb = deal.get('thumb')
                steam_store_link = f"https://store.steampowered.com/app/{steam_app_id}"

                embed = discord.Embed(
                    title=f"🔥 Deal Found for: {title}",
                    url=steam_store_link,
                    color=discord.Color.green()
                )
                if thumb:
                    embed.set_thumbnail(url=thumb)

                embed.add_field(name="Price", value=f"~~${normal_price}~~ → **${sale_price}**", inline=True)
                embed.add_field(name="Discount", value=f"**{savings}% OFF**", inline=True)
                embed.add_field(name="Metacritic Score", value=f"`{metacritic_score}`", inline=True)
                
                await ctx.send(embed=embed)
                return

            else:
                lookup_url = f"https://www.cheapshark.com/api/1.0/games?title={formatted_game_name}&exact=1"
                lookup_response = requests.get(lookup_url)
                lookup_response.raise_for_status()
                game_data = lookup_response.json()

                if not game_data:
                    await ctx.send(f"Sorry, I couldn't find a game with the exact name **'{game_name}'**. Please check the spelling.")
                    return
                
                game_info = game_data[0]
                title = game_info.get('external', 'Unknown Game')
                price = game_info.get('cheapest', 'N/A')
                thumb = game_info.get('thumb')
                steam_app_id = game_info.get('steamAppID')
                steam_store_link = f"https://store.steampowered.com/app/{steam_app_id}"
                
                embed = discord.Embed(
                    title=f"Price Check for: {title}",
                    url=steam_store_link,
                    color=discord.Color.light_grey()
                )
                if thumb:
                    embed.set_thumbnail(url=thumb)
                
                embed.add_field(name="Status", value="This game is **not currently on sale** on Steam.", inline=False)
                embed.add_field(name="Current Price", value=f"**${price}**", inline=False)

                await ctx.send(embed=embed)
                return

    except requests.exceptions.RequestException as e:
        print(f"Error communicating with CheapShark API: {e}")
        await ctx.send("Sorry, I couldn't connect to the game deals service. It might be down. 😿")
    except (KeyError, IndexError, json.JSONDecodeError) as e:
        print(f"Error parsing response from CheapShark: {e}")
        await ctx.send("Sorry, the game deals service gave me a weird response. 😿")
    except Exception as e:
        print(f"An unexpected error occurred in the !price command: {e}")
        await ctx.send("Sorry, an unexpected error stopped me from checking the price. 😿")


@bot.command(name='test')
@commands.is_owner()
async def test_daily_horoscopes(ctx):
    await ctx.message.add_reaction('🧪')
    owner_id = str(ctx.author.id)
    users = load_user_data()

    if owner_id in users:
        sign = users[owner_id]
        await ctx.author.send(f"✅ Running a personal test for your sign: **{sign}**. You should receive your horoscope message next.")
        await fetch_and_send_horoscope(ctx.author, sign, user=ctx.author)
    else:
        await ctx.author.send(f"⚠️ You are not registered for horoscopes. Please use `{COMMAND_PREFIX}reg` first to test this feature.")


# --- Main Execution Block ---
if __name__ == '__main__':
    try:
        bot.run(DISCORD_BOT_TOKEN)
    except discord.LoginFailure:
        print("FATAL ERROR: Invalid Discord bot token. Please check your .env file.")
    except Exception as e:
        print(f"An unexpected error occurred while starting the bot: {e}")