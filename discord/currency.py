# command !myr, !myr100, !myr eur, !myr 100 eur

import os
import discord
import requests
from discord.ext import commands
from dotenv import load_dotenv
import re # Import the regular expression module

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
# IMPORTANT: Set help_command=None to disable the default help command
bot = commands.Bot(command_prefix=PREFIX, intents=intents, help_command=None)

# --- Helper Functions ---

# Amount parameter is no longer passed to the API call.
# The API will always return rates for 1 unit.
async def fetch_exchange_rates(base_currency: str, target_currency: str = None):
    """
    Fetches exchange rates for 1 unit of the base currency from the Frankfurter API.
    Args:
        base_currency (str): The base currency code (e.g., "USD").
        target_currency (str, optional): The target currency code (e.g., "EUR").
                                         If None, all rates for base_currency are returned.
    Returns:
        dict: A dictionary containing exchange rate data for 1 unit, or None if an error occurs.
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
    Handles messages to implement dynamic currency commands (e.g., !usd, !eur jpy, !usd100, !usd 100 jpy).
    """
    # Ignore messages from the bot itself
    if message.author == bot.user:
        return

    # Create a context for the message. This allows discord.py to parse the command.
    ctx = await bot.get_context(message)

    # If a valid command was found and processed by discord.ext.commands,
    # then we stop processing this message here. This ensures !help works.
    if ctx.valid:
        await bot.process_commands(message)
        return

    # If no valid command was found by discord.ext.commands,
    # then we proceed with our custom currency parsing logic.
    if message.content.startswith(PREFIX):
        full_command_parts = message.content[len(PREFIX):].strip().split()
        
        if not full_command_parts:
            return # Empty command after prefix

        base_currency = None
        amount = 1.0 # Default amount, will be updated by user input
        target_currency = None

        # --- REFINED PARSING LOGIC ---
        # This logic handles:
        # !CURRENCY
        # !CURRENCYAMOUNT
        # !CURRENCY TARGET_CURRENCY
        # !CURRENCYAMOUNT TARGET_CURRENCY
        # !CURRENCY AMOUNT
        # !CURRENCY AMOUNT TARGET_CURRENCY

        first_arg = full_command_parts[0]
        
        # Try to match currency code potentially followed by an amount (e.g., USD100)
        currency_amount_match = re.match(r'^([A-Z]{2,4})(\d*\.?\d*)?$', first_arg, re.IGNORECASE)

        if currency_amount_match:
            base_currency = currency_amount_match.group(1).upper()
            attached_amount_str = currency_amount_match.group(2)
            if attached_amount_str:
                try:
                    amount = float(attached_amount_str)
                except ValueError:
                    amount = 1.0 # Fallback if parsing fails

            # Check for subsequent arguments
            if len(full_command_parts) > 1:
                second_arg = full_command_parts[1]
                
                # If the second argument is a number, it's an explicit amount
                if re.match(r'^\d+(\.\d+)?$', second_arg):
                    try:
                        amount = float(second_arg) # Override attached amount if explicit amount is given
                        # If there's a third argument, it's the target currency
                        if len(full_command_parts) > 2:
                            target_currency = full_command_parts[2].upper()
                    except ValueError:
                        pass # Ignore if not a valid number
                else:
                    # If second argument is not a number, it's the target currency
                    target_currency = second_arg.upper()
        else:
            # If the first argument is just a currency code (e.g., !USD)
            base_currency = first_arg.upper()
            if len(full_command_parts) > 1:
                second_arg = full_command_parts[1]
                # Check if the second argument is a number (e.g., !USD 100)
                if re.match(r'^\d+(\.\d+)?$', second_arg):
                    try:
                        amount = float(second_arg)
                        if len(full_command_parts) > 2:
                            target_currency = full_command_parts[2].upper()
                    except ValueError:
                        pass
                else:
                    # If second argument is not a number, it's the target currency (e.g., !USD MYR)
                    target_currency = second_arg.upper()

        # --- END REFINED PARSING LOGIC ---
        
        # If a base currency was successfully parsed, handle the currency command
        if base_currency:
            # Send the initial "please wait" message and store the message object
            status_message = await message.channel.send(f"Fetching exchange rates for {base_currency} (amount: {amount:.2f}), please wait...")

            # Call fetch_exchange_rates without the 'amount' parameter, as we do the multiplication locally
            # Pass the target_currency to the API if it was provided, to potentially optimize the API response
            rates_data = await fetch_exchange_rates(base_currency, target_currency)

            if rates_data:
                base = rates_data.get('base')
                date = rates_data.get('date')
                rates = rates_data.get('rates')

                if not rates:
                    # This could happen if the base currency itself is not supported
                    await status_message.edit(content=f"No rates found for {base}. Please ensure '{base}' is a valid currency code supported by the Frankfurter API.")
                    return

                # Display the result using the user's input amount
                response_message = f"**Exchange Rates for {amount:.2f} {base} (as of {date}):**\n"

                if target_currency:
                    # Specific rate requested, so only show that one
                    rate_for_one = rates.get(target_currency)
                    if rate_for_one is not None:
                        calculated_rate = rate_for_one * amount # Perform multiplication here
                        response_message += f"**{amount:.2f} {base} = {calculated_rate:.4f} {target_currency}**"
                    else:
                        response_message += f"Could not find rate for {target_currency}. Please ensure '{target_currency}' is a valid currency code."
                else:
                    # No specific target currency, list all available rates multiplied by the amount
                    rate_lines = []
                    for currency, rate_for_one in rates.items():
                        calculated_rate = rate_for_one * amount # Perform multiplication here
                        rate_lines.append(f"  - {currency}: {calculated_rate:.4f}")
                    
                    # Discord message length limit is 2000 characters.
                    # If the list is too long, split it into multiple messages.
                    if len("\n".join(rate_lines)) + len(response_message) > 1900:
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
            return # Important: Return after handling a currency command
        
    # If the message did not start with the prefix, or if it started with the prefix
    # but was not a recognized currency command, then this block will not be reached.


# --- Discord Bot Commands ---

@bot.command(name='help', help='Shows how to use the currency exchange commands.')
async def help_command(ctx):
    """
    Displays information about how to use the currency exchange commands.
    """
    help_message = (
        "**Currency Exchange Bot Commands:**\n"
        "Use the following formats to get exchange rates:\n\n"
        f"**1. Get all rates for a base currency (for 1 unit):**\n"
        f"   `{PREFIX}CURRENCY` (e.g., `{PREFIX}usd`)\n\n"
        f"**2. Get all rates for a specific amount of base currency:**\n"
        f"   `{PREFIX}CURRENCY<AMOUNT>` (e.g., `{PREFIX}usd100`)\n"
        f"   `{PREFIX}CURRENCY <AMOUNT>` (e.g., `{PREFIX}usd 100`)\n\n"
        f"**3. Get a specific conversion (for 1 unit):**\n"
        f"   `{PREFIX}CURRENCY <TARGET_CURRENCY>` (e.g., `{PREFIX}usd myr`)\n\n"
        f"**4. Get a specific conversion for a specific amount:**\n"
        f"   `{PREFIX}CURRENCY<AMOUNT> <TARGET_CURRENCY>` (e.g., `{PREFIX}usd100 myr`)\n"
        f"   `{PREFIX}CURRENCY <AMOUNT> <TARGET_CURRENCY>` (e.g., `{PREFIX}usd 100 myr`)\n\n"
        "**Note:** Replace `CURRENCY` with a 3-letter currency code (e.g., USD, EUR, MYR).\n"
        "Replace `AMOUNT` with the number you want to convert."
    )
    await ctx.send(help_message)


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
