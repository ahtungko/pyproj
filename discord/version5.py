# --- MERGED AND USABLE DISCORD BOT ---
# This script combines the functionality of an AI/Currency bot and a Horoscope bot.
# FINAL VERSION with All Fixes and Features

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

run_time = datetime.time(hour=0, minute=0, tzinfo=datetime.timezone.utc)

@tasks.loop(time=run_time)
async def send_daily_horoscopes():
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
            if isinstance(destination, (discord.User, discord.Member)):
                 await destination.send(embed=embed)
            else:
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