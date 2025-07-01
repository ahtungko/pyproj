# main.py
import discord
from discord.ext import commands, tasks
from discord import ui
import requests
import os
import json
import datetime
from dotenv import load_dotenv

# Load environment variables from a .env file
load_dotenv()

# --- Bot Configuration ---
# Get the token and owner ID from the environment variables.
# The .env file should contain these lines:
# DISCORD_BOT_TOKEN="YOUR_TOKEN_HERE"
# BOT_OWNER_ID="YOUR_USER_ID_HERE"
BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
OWNER_ID_STR = os.getenv("BOT_OWNER_ID")

# Convert owner_id from .env to an integer.
try:
    owner_id_int = int(OWNER_ID_STR) if OWNER_ID_STR else None
except ValueError:
    print(f"Warning: Invalid BOT_OWNER_ID '{OWNER_ID_STR}'. It must be a number. Owner-only commands will be disabled.")
    owner_id_int = None

# The intents specify which events the bot will listen to.
intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
intents.members = True # Required to fetch user objects by ID

# The bot is instantiated with a command prefix '!' and the specified intents.
# The owner_id is now loaded from the .env file.
bot = commands.Bot(command_prefix='!', intents=intents, owner_id=owner_id_int)

# The name of the file where user data (zodiac signs) will be stored.
USER_DATA_FILE = "abc.txt"

# --- Helper Functions ---

def load_user_data():
    """
    Loads user data from the specified file.
    If the file doesn't exist, it returns an empty dictionary.
    """
    if not os.path.exists(USER_DATA_FILE):
        return {}
    try:
        with open(USER_DATA_FILE, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return {}

def save_user_data(data):
    """
    Saves the provided data to the user data file.
    """
    with open(USER_DATA_FILE, 'w') as f:
        json.dump(data, f, indent=4)

async def fetch_and_send_horoscope(destination, sign, user: discord.User = None):
    """
    Fetches the horoscope from the API and sends it to the given destination.
    The destination can be a context (ctx), a channel, or a user object.
    """
    url = f"https://horoscope-app-api.vercel.app/api/v1/get-horoscope/daily?sign={sign}&day=TODAY"
    
    try:
        mention_text = f"{user.mention}, " if user else ""
        # Send a fetching message only if it's an interactive command
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
            
            await destination.send(embed=embed)
            return True # Indicate success
        else:
            await destination.send("Sorry, I couldn't retrieve the horoscope right now. Please try again later.")
            return False # Indicate failure

    except requests.exceptions.RequestException as e:
        print(f"API Request failed for sign {sign}: {e}")
        if isinstance(destination, (commands.Context, discord.TextChannel, discord.Interaction)):
            await destination.send("Sorry, there was an error connecting to the horoscope service.")
        return False
    except Exception as e:
        print(f"An unexpected error occurred for sign {sign}: {e}")
        if isinstance(destination, (commands.Context, discord.TextChannel, discord.Interaction)):
            await destination.send("An unexpected error occurred. Please try again.")
        return False

# --- UI Components for Zodiac Selection ---

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

# --- Automated Daily Horoscope Task ---

# Define the time for the task to run, in UTC.
# 8:00 AM Malaysia Time (UTC+8) is 00:00 UTC.
run_time = datetime.time(hour=0, minute=0, tzinfo=datetime.timezone.utc)

@tasks.loop(time=run_time)
async def send_daily_horoscopes():
    """
    A background task that sends daily horoscopes to all registered users.
    """
    print(f"[{datetime.datetime.now()}] Running daily horoscope task...")
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


# --- Bot Events ---

@bot.event
async def on_ready():
    """
    This event is triggered when the bot successfully connects to Discord.
    """
    print(f'Logged in as {bot.user.name} ({bot.user.id})')
    print('------')
    if not send_daily_horoscopes.is_running():
        send_daily_horoscopes.start()
        print("Started the daily horoscope background task.")

# --- Bot Commands ---

@bot.command(name='test')
@commands.is_owner() # Ensures only the bot owner can use this
async def test_daily_horoscopes(ctx):
    """
    Manually triggers the daily horoscope task for testing.
    This command can only be used by the bot owner.
    """
    await ctx.send("✅ Manually triggering the daily horoscope task. Check your DMs and the console for output.")
    await send_daily_horoscopes()

@bot.group(invoke_without_command=True)
async def luck(ctx: commands.Context):
    """
    Main command group. Fetches the user's horoscope on demand.
    """
    if ctx.invoked_subcommand is None:
        user_id = str(ctx.author.id)
        users = load_user_data()

        if user_id in users:
            sign = users[user_id]
            await fetch_and_send_horoscope(ctx, sign, user=ctx.author)
            await ctx.send("*(Tip: Use `!luck change` to update your sign. Daily horoscopes are sent automatically!)*", delete_after=20)
        else:
            view = ZodiacSelectionView(author=ctx.author)
            await ctx.send(f"Welcome, {ctx.author.mention}! Please select your zodiac sign to get started:", view=view)

@luck.command(name='change')
async def change_sign(ctx: commands.Context):
    """
    Subcommand to allow a user to change their registered zodiac sign.
    """
    view = ZodiacSelectionView(author=ctx.author)
    await ctx.send(f"{ctx.author.mention}, please select your new zodiac sign from the menu below:", view=view)


# --- Running the Bot ---
if __name__ == "__main__":
    if not BOT_TOKEN:
        print("Error: DISCORD_BOT_TOKEN not found in .env file.")
    elif not bot.owner_id:
        print("Warning: BOT_OWNER_ID not found or invalid in .env file. Owner-only commands will be disabled.")
    
    bot.run(BOT_TOKEN)
