import os
import discord
import requests
from discord.ext import commands
from dotenv import load_dotenv

# --- Configuration ---
# IMPORTANT: Replace 'YOUR_BOT_TOKEN_HERE' with your actual Discord bot token.
# It's highly recommended to use environment variables for sensitive information.
# Example: BOT_TOKEN = os.getenv('DISCORD_BOT_TOKEN')
# For local testing, you can directly paste it, but remove before sharing publicly.
load_dotenv()
BOT_TOKEN = os.getenv('DISCORD_TOKEN') # Replace with your bot token

# Define the Discord bot's command prefix
PREFIX = '!'

# --- API Endpoints ---
BASE_API_URL = "https://api.frankfurter.dev"
LATEST_RATES_ENDPOINT = f"{BASE_API_URL}/v1/latest"
# The /v1/currencies endpoint is not used as per user's feedback.
# The bot will now assume the input currency is valid for the /latest endpoint.

# --- Bot Setup ---
# Set up Discord intents. These specify which events your bot wants to receive.
# For commands and messages, you typically need Message Content and Guilds.
intents = discord.Intents.default()
intents.message_content = True # Required to read message content for commands
intents.guilds = True # Required to interact with guilds (servers)

# Initialize the bot with a command prefix and intents
bot = commands.Bot(command_prefix=PREFIX, intents=intents)

# --- Helper Functions ---

async def fetch_exchange_rates(base_currency: str, target_currency: str = None):
    """
    Fetches exchange rates from the Frankfurter API.
    Args:
        base_currency (str): The base currency code (e.g., "USD").
        target_currency (str, optional): The target currency code (e.g., "EUR").
                                         If None, all rates for base_currency are returned.
    Returns:
        dict: A dictionary containing exchange rate data, or None if an error occurs.
    """
    params = {'base': base_currency.upper()}
    if target_currency:
        params['to'] = target_currency.upper()

    try:
        response = requests.get(LATEST_RATES_ENDPOINT, params=params)
        response.raise_for_status()  # Raise an exception for HTTP errors (4xx or 5xx)
        data = response.json()
        return data
    except requests.exceptions.RequestException as e:
        print(f"Error fetching exchange rates: {e}")
        return None

# --- Discord Bot Events ---

@bot.event
async def on_ready():
    """Event that fires when the bot successfully connects to Discord."""
    print(f'Logged in as {bot.user.name} ({bot.user.id})')
    print(f'Bot is ready! Use {PREFIX}help to see commands.')

@bot.event
async def on_message(message):
    """
    Handles messages to implement dynamic currency commands (e.g., !usd, !eur jpy).
    """
    # Ignore messages from the bot itself
    if message.author == bot.user:
        return

    # Process commands defined with @bot.command() first (e.g., !help)
    await bot.process_commands(message)

    # Check if the message starts with the prefix and is not a recognized command
    if message.content.startswith(PREFIX):
        # Split the message into parts: command and arguments
        parts = message.content[len(PREFIX):].split()
        if not parts:
            return # Empty command after prefix

        base_currency = parts[0].upper() # The first part is treated as the base currency
        target_currency = None

        if len(parts) > 1:
            target_currency = parts[1].upper()

        # Send the initial "please wait" message and store the message object
        status_message = await message.channel.send(f"Fetching exchange rates for {base_currency}, please wait...")

        rates_data = await fetch_exchange_rates(base_currency, target_currency)

        if rates_data:
            base = rates_data.get('base')
            date = rates_data.get('date')
            rates = rates_data.get('rates')

            if not rates:
                # This could happen if the base currency itself is not supported
                await status_message.edit(content=f"No rates found for {base}. Please ensure '{base}' is a valid currency code supported by the Frankfurter API.")
                return

            response_message = f"**Exchange Rates for 1 {base} (as of {date}):**\n"

            if target_currency:
                # Specific rate requested
                rate = rates.get(target_currency)
                if rate is not None:
                    response_message += f"**1 {base} = {rate:.4f} {target_currency}**"
                else:
                    response_message += f"Could not find rate for {target_currency}. Please ensure '{target_currency}' is a valid currency code."
            else:
                # All rates for the base currency
                rate_lines = []
                for currency, rate in rates.items():
                    rate_lines.append(f"  - {currency}: {rate:.4f}")
                
                # Discord message length limit is 2000 characters.
                # If the list is too long, split it into multiple messages.
                if len("\n".join(rate_lines)) + len(response_message) > 1900:
                    # If the message is too long, we still need to send subsequent parts
                    # as new messages, but the initial status_message will be updated
                    # with the first part.
                    await status_message.edit(content=response_message) # Update initial message with header
                    current_message_part = ""
                    for line in rate_lines:
                        if len(current_message_part) + len(line) + 1 > 1900:
                            await message.channel.send(f"```\n{current_message_part}\n```")
                            current_message_part = line
                        else:
                            current_message_part += "\n" + line
                    if current_message_part:
                        await message.channel.send(f"```\n{current_message_part}\n```")
                    return # Exit after sending multiple messages
                else:
                    response_message += "```\n" + "\n".join(rate_lines) + "\n```"
            
            # Edit the original status message with the final response
            await status_message.edit(content=response_message)
        else:
            # If fetching rates failed, edit the status message to reflect the error
            await status_message.edit(content="Sorry, I couldn't fetch the exchange rates at this moment. Please try again later.")
        # No need for explicit 'command not found' for currency codes, as they are now
        # directly passed to the API. The API's response (or lack thereof) will dictate
        # the error message.

# --- Run the Bot ---
if __name__ == '__main__':
    # Check if the BOT_TOKEN is still the placeholder
    if BOT_TOKEN == 'YOUR_BOT_TOKEN_HERE':
        print("ERROR: Please replace 'YOUR_BOT_TOKEN_HERE' with your actual Discord bot token.")
        print("The bot will not run without a valid token.")
    else:
        try:
            bot.run(BOT_TOKEN)
        except discord.LoginFailure:
            print("ERROR: Invalid Discord bot token. Please check your token.")
        except Exception as e:
            print(f"An unexpected error occurred: {e}")