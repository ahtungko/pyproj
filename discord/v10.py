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
# Made horoscope date calculations explicitly use GMT+8.
# Made AI personality multilingual.
# Added timezone support for horoscopes (!reg, !mod, !modtz).
# Upgraded timezone input to a user-friendly dropdown selection.
# Added backwards compatibility for old horoscope user data.
# Restored custom footer and text in !help command.
# Added !list command for horoscopes.
# Clarified dates shown in horoscope embed.
# Improved !reg flow and added support for non-integer timezones.
# Added owner-only !olist command to list registered users.
# Added !liverate command using Wise Sandbox API with dynamic timestamps.
# Fixed all bugs in !liverate command (timestamp rendering, argument parsing).
# !dict [word] command for English word definitions and audio pronunciations.
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
from datetime import timezone, timedelta
from discord import ui
from discord.ext import commands, tasks
from dotenv import load_dotenv
import io

# --- Unified Configuration & Environment Loading ---
load_dotenv()

# Bot and API Credentials
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
BOT_OWNER_ID_STR = os.getenv("BOT_OWNER_ID")
WISE_SANDBOX_TOKEN = os.getenv("WISE_SANDBOX_TOKEN")

# Bot Settings
COMMAND_PREFIX = '!'
USER_DATA_FILE = "abc.txt"

# --- Sanity Checks for Environment Variables ---
if not DISCORD_BOT_TOKEN:
    print("FATAL ERROR: DISCORD_BOT_TOKEN not found in .env file. Please set it.")
    exit(1)
if not GEMINI_API_KEY:
    print("FATAL ERROR: GEMINI_API_KEY not found in .env file. Please set it. AI features will be disabled.")
if not BOT_OWNER_ID_STR:
    print("Warning: BOT_OWNER_ID not found in .env file. Owner-only commands will be disabled.")
if not WISE_SANDBOX_TOKEN:
    print("Warning: WISE_SANDBOX_TOKEN not found. The !liverate command will be disabled.")

try:
    owner_id_int = int(BOT_OWNER_ID_STR) if BOT_OWNER_ID_STR else None
except ValueError:
    print(f"Warning: Invalid BOT_OWNER_ID '{BOT_OWNER_ID_STR}'. It must be a number. Owner-only commands will be disabled.")
    owner_id_int = None

# --- API & Global Variable Setup ---
if GEMINI_API_KEY:
    try:
        genai.configure(api_key=GEMINI_API_KEY)
    except Exception as e:
        print(f"Fatal Error: Could not configure Gemini API: {e}")
        GEMINI_API_KEY = None
else:
    model = None

BASE_CURRENCY_API_URL = "https://api.frankfurter.dev/v1/latest"
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

async def handle_timezone_selection(interaction: discord.Interaction, select_item: ui.Select, offset_str: str):
    user_id = str(interaction.user.id)
    users = load_user_data()
    user_data = users.get(user_id)
    sign = getattr(select_item.view, 'sign', None)

    if user_data and not sign:
        if isinstance(user_data, str):
             users[user_id] = {"sign": user_data, "timezone_offset": offset_str}
        else:
            user_data['timezone_offset'] = offset_str
    else:
        if not sign:
            await interaction.response.edit_message(content="Something went wrong. Please start over with `!reg`.", view=None)
            return
        users[user_id] = {"sign": sign, "timezone_offset": offset_str}
        
    save_user_data(users)

    for item in select_item.view.children:
        item.disabled = True

    await interaction.response.edit_message(content=f"✅ Your timezone has been set to **UTC{offset_str}**! All set.", view=select_item.view)

class TimezoneSelectA(ui.Select):
    def __init__(self):
        options = [discord.SelectOption(label=f"UTC{i:+d}", value=str(i)) for i in range(-12, 1)]
        super().__init__(placeholder="Timezones (UTC-12 to UTC+0)", options=options)
    
    async def callback(self, interaction: discord.Interaction):
        await handle_timezone_selection(interaction, self, self.values[0])

class TimezoneSelectB(ui.Select):
    def __init__(self):
        options = [discord.SelectOption(label=f"UTC{i:+d}", value=str(i)) for i in range(1, 15)]
        super().__init__(placeholder="Timezones (UTC+1 to UTC+14)", options=options)

    async def callback(self, interaction: discord.Interaction):
        await handle_timezone_selection(interaction, self, self.values[0])

class TimezoneSelectC(ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="UTC-09:30", value="-9.5"), discord.SelectOption(label="UTC-03:30", value="-3.5"),
            discord.SelectOption(label="UTC+03:30", value="3.5"), discord.SelectOption(label="UTC+04:30", value="4.5"),
            discord.SelectOption(label="UTC+05:30 (India)", value="5.5"), discord.SelectOption(label="UTC+05:45 (Nepal)", value="5.75"),
            discord.SelectOption(label="UTC+06:30 (Myanmar)", value="6.5"), discord.SelectOption(label="UTC+08:45 (W. Australia)", value="8.75"),
            discord.SelectOption(label="UTC+09:30 (C. Australia)", value="9.5"), discord.SelectOption(label="UTC+10:30 (Lord Howe Is.)", value="10.5"),
        ]
        super().__init__(placeholder="Non-Integer Timezones (India, etc.)", options=options)

    async def callback(self, interaction: discord.Interaction):
        await handle_timezone_selection(interaction, self, self.values[0])

class TimezoneSelectionView(ui.View):
    def __init__(self, author: discord.User, sign: str = None):
        super().__init__(timeout=120)
        self.author = author
        self.sign = sign
        self.add_item(TimezoneSelectA())
        self.add_item(TimezoneSelectB())
        self.add_item(TimezoneSelectC())

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author.id:
            await interaction.response.send_message("This selection menu is not for you.", ephemeral=True)
            return False
        return True

class ZodiacSelect(ui.Select):
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
        user_data = users.get(user_id)
        if user_data:
            if isinstance(user_data, str):
                users[user_id] = {"sign": selected_sign, "timezone_offset": "+0"}
            elif isinstance(user_data, dict):
                user_data['sign'] = selected_sign
            save_user_data(users)
            await interaction.response.edit_message(content=f"✅ Your zodiac sign has been updated to **{selected_sign}**!", view=None)
        else:
            view = TimezoneSelectionView(author=interaction.user, sign=selected_sign)
            await interaction.response.edit_message(content="Great! Now, please select your timezone offset from the dropdowns below.", view=view)

class ZodiacSelectionView(ui.View):
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
            graph_buffer = await loop.run_in_executor(None, generate_history_graph, sorted_dates, rates_for_target, self.base_currency, self.target_currency, num_days_with_data)
            graph_file = discord.File(graph_buffer, filename=f"{self.base_currency}-{self.target_currency}_history.png")
            await interaction.followup.send(file=graph_file)
        except Exception as e:
            print(f"An error occurred during graph generation: {e}")
            await interaction.followup.send("I'm sorry, an unexpected error occurred while creating the graph.", ephemeral=True)

# --- Horoscope Bot: Automated Daily Task ---

def create_horoscope_embed(sign_name, data, request_date):
    horoscope_date = data.get('current_date', 'N/A')
    description = data.get('description', 'No horoscope data found for today.')
    compatibility = data.get('compatibility', 'N/A').title()
    mood = data.get('mood', 'N/A').title()
    color = data.get('color', 'N/A').title()
    lucky_number = data.get('lucky_number', 'N/A')
    lucky_time = data.get('lucky_time', 'N/A')
    date_range = data.get('date_range', '')
    embed = discord.Embed(title=f"✨ Daily Horoscope for {sign_name.title()} ✨", description=f"_{description}_", color=discord.Color.purple())
    embed.set_footer(text=f"Horoscope For: {horoscope_date} | Your Date: {request_date} | Range: {date_range}")
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
    users = load_user_data()
    if not users:
        print("No registered users to send horoscopes to.")
        return
    for user_id, data in users.items():
        try:
            sign, offset_str = None, "+0"
            if isinstance(data, str):
                sign = data
            elif isinstance(data, dict):
                sign = data.get("sign")
                offset_str = data.get('timezone_offset', '+0')
            if not sign: continue
            user_timezone = timezone(timedelta(hours=float(offset_str)))
            user_today_date = datetime.datetime.now(user_timezone).date().isoformat()
            url = f"https://api.aistrology.beandev.xyz/v1?sign={sign.lower()}&date={user_today_date}"
            response = requests.get(url)
            response.raise_for_status()
            horoscope_data_list = response.json()
            if horoscope_data_list and isinstance(horoscope_data_list, list):
                horoscope_data = horoscope_data_list[0]
                user = await bot.fetch_user(int(user_id))
                embed = create_horoscope_embed(sign, horoscope_data, user_today_date)
                await user.send(embed=embed)
                print(f"Sent horoscope to {user.name} ({user_id}) for sign {sign}")
        except Exception as e:
            print(f"An error occurred while processing user {user_id}: {e}")
    print("Daily horoscope task finished.")

@send_daily_horoscopes.before_loop
async def before_daily_task(): await bot.wait_until_ready()

# --- All Helper Functions ---

def load_user_data():
    if not os.path.exists(USER_DATA_FILE): return {}
    try:
        with open(USER_DATA_FILE, 'r') as f: return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError): return {}

def save_user_data(data):
    with open(USER_DATA_FILE, 'w') as f: json.dump(data, f, indent=4)

async def fetch_exchange_rates(base_currency: str, target_currency: str = None):
    params = {'base': base_currency.upper()}
    if target_currency: params['to'] = target_currency.upper()
    try:
        response = requests.get(BASE_CURRENCY_API_URL, params=params)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error fetching exchange rates from API: {e}")
        return None

async def fetch_and_send_horoscope(destination, sign, user: discord.User = None):
    users, user_id = load_user_data(), str(user.id)
    user_data = users.get(user_id)
    offset_str = '+0'
    if isinstance(user_data, dict): offset_str = user_data.get('timezone_offset', '+0')
    user_timezone = timezone(timedelta(hours=float(offset_str)))
    today_date = datetime.datetime.now(user_timezone).date().isoformat()
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
            embed = create_horoscope_embed(sign, data, today_date)
            if hasattr(destination, 'send'): await destination.send(embed=embed)
            return True
        else:
            if hasattr(destination, 'send'): await destination.send("Sorry, I couldn't retrieve the horoscope right now.")
            return False
    except Exception as e:
        print(f"An error occurred in fetch_and_send_horoscope for sign {sign}: {e}")
        if hasattr(destination, 'send'): await destination.send("An unexpected error occurred while fetching your horoscope.")
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
            try: amount = float(attached_amount_str)
            except ValueError: amount = 1.0
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
    ai_personality = (
    "You are a helpful and friendly AI assistant. Your goal is to provide accurate, clear, and concise information. "
    "You should be polite and respectful in all your responses. "
    "IMPORTANT: You MUST detect the language of the user's message and ALWAYS respond in that same language. "
    "For example, if the user writes in Chinese, you must reply in Chinese. If they write in Malay, you reply in Malay."
    )

    if GEMINI_API_KEY:
        try:
            model = genai.GenerativeModel(model_name=DEFAULT_MODEL, system_instruction=ai_personality)
            print(f"Successfully initialized Gemini model: {DEFAULT_MODEL}")
        except Exception as e:
            print(f"CRITICAL: Error initializing Gemini model '{DEFAULT_MODEL}': {e}")
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
    embed = discord.Embed(title=f"{bot.user.name} Help", description="This bot provides AI Chat, Currency Exchange, and Horoscope functionalities.", color=discord.Color.purple())
    embed.add_field(name="🤖 AI Chat Functionality", value=f"To chat with the AI, simply mention the bot (`@{bot.user.name}`) followed by your question.", inline=False)
    embed.add_field(name=f"💱 Currency Exchange (Prefix: `{COMMAND_PREFIX}`)", value=(f"**Get Daily Rates:** `{COMMAND_PREFIX}usd`\n" f"**Convert (Daily Rate):** `{COMMAND_PREFIX}usd 100 myr`\n" f"**Convert (LIVE Rate):** `{COMMAND_PREFIX}liverate [amount] <source> <target>`\n\n" f"Click `📈` to see a graph for daily rate conversions."), inline=False)
    embed.add_field(name=f"✨ Daily Horoscope (Prefix: `{COMMAND_PREFIX}`)", value=(f"**Register:** `{COMMAND_PREFIX}reg`\n" f"**Modify Sign:** `{COMMAND_PREFIX}mod`\n" f"**Modify Timezone:** `{COMMAND_PREFIX}modtz`\n" f"**Remove your record:** `{COMMAND_PREFIX}remove`\n" f"**Show in channel:** `{COMMAND_PREFIX}list`\n\n" f"Receive a daily horoscope in your timezone!"), inline=False)
    embed.add_field(name=f"🐱 Fun Commands (Prefix: `{COMMAND_PREFIX}`)", value=(f"**Cat Picture:** `{COMMAND_PREFIX}c`\n" f"**Cat Fact:** `{COMMAND_PREFIX}cf`"), inline=False)
    embed.add_field(name=f"🎮 Game Deals (Prefix: `{COMMAND_PREFIX}`)", value=(f"**Top Steam Deals:** `{COMMAND_PREFIX}deals`\n" f"**Check Game Price:** `{COMMAND_PREFIX}price [game name]`"), inline=False)
    embed.add_field(name=f"📚 Utility Commands (Prefix: `{COMMAND_PREFIX}`)", value=(f"**Dictionary:** `{COMMAND_PREFIX}dict [word]`"), inline=False)
    
    if ctx.author.id == bot.owner_id:
        embed.add_field(name=f"👑 Owner Commands", value=f"**List all horoscope users:** `{COMMAND_PREFIX}olist`\n**Test your horoscope DM:** `{COMMAND_PREFIX}test`", inline=False)
    embed.set_footer(text="Made with ❤️ by Jenny")
    await ctx.send(embed=embed)

@bot.command(name='reg')
async def reg(ctx: commands.Context):
    if str(ctx.author.id) in load_user_data():
        await ctx.send(f"You are already registered, {ctx.author.mention}! Use `{COMMAND_PREFIX}mod` to change your sign or `{COMMAND_PREFIX}modtz` to change your timezone.")
        return
    view = ZodiacSelectionView(author=ctx.author)
    await ctx.send(f"Welcome, {ctx.author.mention}! Please select your zodiac sign to get started:", view=view)

@bot.command(name='mod')
async def mod(ctx: commands.Context):
    if str(ctx.author.id) not in load_user_data():
        await ctx.send(f"You haven't registered yet, {ctx.author.mention}. Please use `{COMMAND_PREFIX}reg` to get started.")
        return
    view = ZodiacSelectionView(author=ctx.author)
    await ctx.send(f"{ctx.author.mention}, please select your new zodiac sign:", view=view)

@bot.command(name='modtz')
async def modtz(ctx: commands.Context):
    if str(ctx.author.id) not in load_user_data():
        await ctx.send(f"You need to register with `{COMMAND_PREFIX}reg` first before changing your timezone.")
        return
    view = TimezoneSelectionView(author=ctx.author)
    await ctx.send("Please select your new timezone offset from the dropdowns:", view=view)

@bot.command(name='remove')
async def remove_record(ctx: commands.Context):
    user_id = str(ctx.author.id)
    users = load_user_data()
    if user_id in users:
        del users[user_id]
        save_user_data(users)
        await ctx.send(f"✅ Your record has been deleted, {ctx.author.mention}. Use `{COMMAND_PREFIX}reg` to register again.")
    else:
        await ctx.send(f"You do not have a registered sign to delete, {ctx.author.mention}.")

@bot.command(name='list')
async def list_horoscope(ctx: commands.Context):
    user_id = str(ctx.author.id)
    users = load_user_data()
    user_data = users.get(user_id)
    sign = None
    if isinstance(user_data, str):
        sign = user_data
    elif isinstance(user_data, dict):
        sign = user_data.get("sign")
    if sign:
        await fetch_and_send_horoscope(ctx, sign, user=ctx.author)
    else:
        await ctx.send(f"You haven't registered your sign yet, {ctx.author.mention}. Use `{COMMAND_PREFIX}reg` to get started.")

@bot.command(name='c')
async def c(ctx: commands.Context):
    API_URL = "https://api.thecatapi.com/v1/images/search"
    try:
        async with ctx.typing():
            response = requests.get(API_URL)
            response.raise_for_status()
            data = response.json()
            if not data: await ctx.send("The cat API returned no cats. 😿"); return
            embed = discord.Embed(title="Meow! Here's a cat for you 🐱", color=discord.Color.blue())
            embed.set_image(url=data[0]['url'])
            await ctx.send(embed=embed)
    except Exception as e: print(f"Error in !c command: {e}"); await ctx.send("Sorry, an unexpected error stopped me from getting a cat. 😿")

@bot.command(name='cf')
async def cf(ctx: commands.Context):
    API_URL = "https://meowfacts.herokuapp.com/"
    try:
        async with ctx.typing():
            response = requests.get(API_URL)
            response.raise_for_status()
            data = response.json()
            if 'data' not in data or not data['data']: await ctx.send("The cat fact API is empty. 😿"); return
            embed = discord.Embed(title="🐱 Did You Know?", description=data['data'][0], color=discord.Color.green())
            await ctx.send(embed=embed)
    except Exception as e: print(f"Error in !cf command: {e}"); await ctx.send("Sorry, an unexpected error stopped me from getting a cat fact. 😿")

@bot.command(name='deals')
async def deals(ctx: commands.Context):
    API_URL = "https://www.cheapshark.com/api/1.0/deals?storeID=1&sortBy=Savings&pageSize=5"
    try:
        async with ctx.typing():
            response = requests.get(API_URL)
            response.raise_for_status()
            deals_data = response.json()
            if not deals_data: await ctx.send("I couldn't find any hot deals on Steam right now."); return
            embed = discord.Embed(title="🔥 Top 5 Steam Deals Right Now", description="Here are the hottest deals, sorted by discount!", color=discord.Color.from_rgb(10, 29, 45))
            for deal in deals_data:
                deal_link = f"https://www.cheapshark.com/redirect?dealID={deal.get('dealID')}"
                value_text = (f"**Price:** ~~${deal.get('normalPrice', 'N/A')}~~ → **${deal.get('salePrice', 'N/A')}**\n" f"**Discount:** `{round(float(deal.get('savings', 0)))}%`\n" f"[Link to Deal]({deal_link})")
                embed.add_field(name=f"**{deal.get('title', 'Unknown Game')}**", value=value_text, inline=False)
            embed.set_thumbnail(url="https://store.cloudflare.steamstatic.com/public/shared/images/header/logo_steam.svg?t=962016")
            await ctx.send(embed=embed)
    except Exception as e: print(f"Error in !deals command: {e}"); await ctx.send("Sorry, an unexpected error stopped me from getting game deals. 😿")

@bot.command(name='price')
async def price(ctx: commands.Context, *, game_name: str = None):
    if not game_name: await ctx.send("Please tell me which game you want to check! Usage: `!price [game name]`"); return
    formatted_game_name = urllib.parse.quote(game_name)
    DEAL_API_URL = f"https://www.cheapshark.com/api/1.0/deals?storeID=1&onSale=1&exact=1&title={formatted_game_name}"
    try:
        async with ctx.typing():
            response = requests.get(DEAL_API_URL)
            response.raise_for_status()
            deals_data = response.json()
            if deals_data:
                deal = deals_data[0]
                steam_store_link = f"https://store.steampowered.com/app/{deal.get('steamAppID')}"
                embed = discord.Embed(title=f"🔥 Deal Found for: {deal.get('title', 'Unknown Game')}", url=steam_store_link, color=discord.Color.green())
                if deal.get('thumb'): embed.set_thumbnail(url=deal.get('thumb'))
                embed.add_field(name="Price", value=f"~~${deal.get('normalPrice', 'N/A')}~~ → **${deal.get('salePrice', 'N/A')}**", inline=True)
                embed.add_field(name="Discount", value=f"**{round(float(deal.get('savings', 0)))}% OFF**", inline=True)
                embed.add_field(name="Metacritic Score", value=f"`{deal.get('metacriticScore', 'N/A')}`", inline=True)
                await ctx.send(embed=embed)
            else:
                lookup_url = f"https://www.cheapshark.com/api/1.0/games?title={formatted_game_name}&exact=1"
                lookup_response = requests.get(lookup_url)
                lookup_response.raise_for_status()
                game_data = lookup_response.json()
                if not game_data: await ctx.send(f"Sorry, I couldn't find a game with the exact name **'{game_name}'**."); return
                game_info = game_data[0]
                steam_store_link = f"https://store.steampowered.com/app/{game_info.get('steamAppID')}"
                embed = discord.Embed(title=f"Price Check for: {game_info.get('external', 'Unknown Game')}", url=steam_store_link, color=discord.Color.light_grey())
                if game_info.get('thumb'): embed.set_thumbnail(url=game_info.get('thumb'))
                embed.add_field(name="Status", value="This game is **not currently on sale** on Steam.", inline=False)
                embed.add_field(name="Current Price", value=f"**${game_info.get('cheapest', 'N/A')}**", inline=False)
                await ctx.send(embed=embed)
    except Exception as e: print(f"Error in !price command: {e}"); await ctx.send("Sorry, an unexpected error stopped me from checking the price. 😿")

@bot.command(name='dict')
async def dict_command(ctx: commands.Context, *, word: str = None):
    """Provides definitions for a given word and attaches the pronunciation audio file."""
    if not word:
        await ctx.send("Please provide a word to look up. Usage: `!dict [word]`")
        return

    API_URL = f"https://api.dictionaryapi.dev/api/v2/entries/en/{word}"
    
    async with ctx.typing():
        try:
            response = requests.get(API_URL)
            response.raise_for_status() 
            data = response.json()

            if isinstance(data, dict) and data.get("title") == "No Definitions Found":
                await ctx.send(f"Sorry, I couldn't find a definition for **'{word}'**. Please check the spelling.")
                return

            word_data = data[0]
            word_text = word_data.get('word', 'N/A')
            
            # --- [CHANGED] Create embed with new title format and no URL ---
            embed = discord.Embed(
                title=f"**{word_text.title()}**",
                color=discord.Color.light_grey()
            )

            # --- Find Phonetics and Audio URL ---
            phonetic_text = None
            audio_url = None
            if 'phonetics' in word_data and word_data['phonetics']:
                for p in word_data['phonetics']:
                    if p.get('text'):
                        phonetic_text = p.get('text')
                        break
                for p in word_data['phonetics']:
                    if p.get('audio'):
                        audio_url = p.get('audio')
                        break
            
            if phonetic_text:
                embed.description = f"**Phonetic:** `{phonetic_text}`"

            # --- Add Meanings ---
            if 'meanings' in word_data:
                for meaning in word_data['meanings']:
                    part_of_speech = meaning.get('partOfSpeech', 'N/A').title()
                    definitions = []
                    for i, definition_info in enumerate(meaning.get('definitions', [])):
                        if i < 3:
                            definition_text = definition_info.get('definition', 'No definition available.')
                            definitions.append(f"**{i+1}.** {definition_text}")
                    
                    if definitions:
                        embed.add_field(name=f"As a {part_of_speech}", value="\n".join(definitions), inline=False)

            # --- [REMOVED] No footer is needed ---
            
            # --- Download Audio and Prepare File ---
            audio_file = None
            if audio_url:
                try:
                    audio_response = requests.get(audio_url)
                    audio_response.raise_for_status()
                    
                    if 'audio' in audio_response.headers.get('Content-Type', ''):
                        audio_data = io.BytesIO(audio_response.content)
                        audio_file = discord.File(fp=audio_data, filename=f"{word_text}_pronunciation.mp3")
                except Exception as e:
                    print(f"Failed to download audio file: {e}")

            # --- [FINAL] Send the embed and file together in one message ---
            await ctx.send(embed=embed, file=audio_file)

        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                await ctx.send(f"Sorry, I couldn't find a definition for **'{word}'**. Please check the spelling.")
            else:
                await ctx.send(f"An HTTP error occurred: {e}")
        except Exception as e:
            print(f"Error in !dict command: {e}")
            await ctx.send("An unexpected error occurred while looking up the word. 😿")

@bot.command(name='liverate')
async def liverate(ctx: commands.Context, *args):
    """Converts a currency amount using live rates from the Wise Sandbox API."""
    if not WISE_SANDBOX_TOKEN:
        await ctx.send("Sorry, the live rate feature is not configured by the bot owner.")
        return

    amount, source, target = 1.0, None, None

    # New, more robust argument parsing
    if not args:
        await ctx.send("Usage: `!liverate [amount] <source> <target>`\n(e.g., `!liverate 100 EUR USD` or `!liverate EUR USD`)")
        return
    
    try:
        if len(args) == 2:
            match = re.match(r'^(\d*\.?\d+)([a-zA-Z]{3,4})$', args[0], re.IGNORECASE)
            if match:
                amount = float(match.group(1))
                source = match.group(2)
                target = args[1]
            else:
                amount = 1.0
                source = args[0]
                target = args[1]
        elif len(args) == 3:
            amount = float(args[0])
            source = args[1]
            target = args[2]
        else:
            await ctx.send("Invalid format. Please use `!liverate [amount] <source> <target>`.")
            return
    except (ValueError, IndexError):
        await ctx.send("I couldn't understand your input. Please use a valid format like `!liverate 100 EUR USD`.")
        return

    source_curr, target_curr = source.upper(), target.upper()
    api_url = f"https://api.sandbox.transferwise.tech/v1/rates?source={source_curr}&target={target_curr}"
    headers = {"Authorization": f"Bearer {WISE_SANDBOX_TOKEN}"}
    
    async with ctx.typing():
        try:
            response = requests.get(api_url, headers=headers)
            response.raise_for_status()
            data = response.json()
            
            if not data or not isinstance(data, list):
                await ctx.send(f"The Wise API returned an unexpected response for {source_curr} to {target_curr}.")
                return

            rate_info = data[0]
            live_rate = rate_info.get('rate')
            time_str = rate_info.get('time')

            if not live_rate or not time_str:
                await ctx.send("The API response was missing the rate or time.")
                return

            converted_amount = amount * live_rate
            
            if time_str.endswith("+0000"):
                time_str = time_str[:-2] + ":" + time_str[-2:]
            dt_object = datetime.datetime.fromisoformat(time_str)
            unix_timestamp = int(dt_object.timestamp())

            embed = discord.Embed(title="Live Rate", description=f"**{amount:,.2f} {source_curr}** is equal to\n# **`{converted_amount:,.2f} {target_curr}`**", color=discord.Color.blue())
            embed.add_field(name="Live Rate", value=f"1 {source_curr} = {live_rate} {target_curr}", inline=False)
            embed.add_field(name="Rate As Of", value=f"<t:{unix_timestamp}:f>", inline=False)
            embed.set_footer(text="Rates from Wise")
            await ctx.send(embed=embed)

        except requests.exceptions.HTTPError:
            await ctx.send(f"Sorry, I couldn't get a rate for **{source_curr}** to **{target_curr}**. Please check if the currency codes are valid.")
        except Exception as e:
            print(f"An error occurred in the liverate command: {e}")
            await ctx.send("An unexpected error occurred.")


@bot.command(name='olist')
@commands.is_owner()
async def olist(ctx: commands.Context):
    """Lists all users registered for daily horoscopes."""
    users = load_user_data()
    if not users:
        await ctx.send("No users have registered for horoscopes yet.")
        return
    embed = discord.Embed(title="Horoscope Registered User List", color=discord.Color.gold())
    output_lines = []
    count = 1
    for user_id, data in users.items():
        try:
            user = await bot.fetch_user(int(user_id))
            user_display = f"{user.name}#{user.discriminator}"
        except discord.NotFound:
            user_display = "Unknown User (ID not found)"
        except Exception:
            user_display = "Error Fetching User"
        sign, timezone_str = "N/A", "N/A"
        if isinstance(data, str):
            sign, timezone_str = data, "Not Set (Old Format)"
        elif isinstance(data, dict):
            sign = data.get('sign', 'N/A')
            offset = data.get('timezone_offset', 'N/A')
            timezone_str = f"UTC{offset}"
        output_lines.append(f"**{count}. {user_display}** `(ID: {user_id})`\n   - **Sign:** {sign}\n   - **Timezone:** {timezone_str}")
        count += 1
    description_text = "\n\n".join(output_lines)
    if len(description_text) > 4000:
        description_text = description_text[:4000] + "\n\n... (list truncated)"
    embed.description = description_text
    embed.set_footer(text=f"Total Registered Users: {len(users)}")
    await ctx.send(embed=embed)

@bot.command(name='test')
@commands.is_owner()
async def test_daily_horoscopes(ctx):
    await ctx.message.add_reaction('🧪')
    owner_id = str(ctx.author.id)
    users = load_user_data()
    owner_data = users.get(owner_id)
    sign = None
    if isinstance(owner_data, str):
        sign = owner_data
    elif isinstance(owner_data, dict):
        sign = owner_data.get("sign")
    if sign:
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