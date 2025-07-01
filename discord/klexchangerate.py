
import discord
import requests
import os
from dotenv import load_dotenv

# --- Configuration ---
# It's highly recommended to use environment variables for your bot token.
# 1. Create a file named .env in the same directory as your bot script.
# 2. In the .env file, add the following line:
#    DISCORD_TOKEN=YOUR_BOT_TOKEN_HERE
# 3. Replace YOUR_BOT_TOKEN_HERE with your actual bot token.
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

# BNM API Configuration
API_URL = "https://api.bnm.gov.my/public/kl-usd-reference-rate"
API_HEADERS = {
    "Accept": "application/vnd.BNM.API.v1+json"
}

# --- Bot Setup ---
# Define the necessary intents. The message_content intent is required to read messages.
intents = discord.Intents.default()
intents.messages = True
intents.message_content = True

client = discord.Client(intents=intents)

def get_exchange_rate():
    """
    Fetches the latest USD/MYR exchange rate from the BNM API.
    Returns a dictionary with rate data or an error message.
    """
    try:
        response = requests.get(API_URL, headers=API_HEADERS, timeout=10)
        # Raise an exception for bad status codes (4xx or 5xx)
        response.raise_for_status()
        
        json_data = response.json()
        
        # Extract data from the JSON response
        rate_data = json_data.get('data', {})
        meta_data = json_data.get('meta', {})
        
        return {
            "success": True,
            "date": rate_data.get('date', 'N/A'),
            "rate": rate_data.get('rate', 'N/A'),
            "last_updated": meta_data.get('last_updated', 'N/A')
        }

    except requests.exceptions.RequestException as e:
        print(f"Error fetching from API: {e}")
        return {
            "success": False,
            "error": "Could not connect to the BNM API. Please try again later."
        }
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        return {
            "success": False,
            "error": "An unexpected error occurred while fetching the data."
        }


@client.event
async def on_ready():
    """
    This function is called when the bot successfully connects to Discord.
    """
    print(f'Bot is logged in as {client.user}')
    print('Ready to receive commands!')


@client.event
async def on_message(message):
    """
    This function is called whenever a message is sent in a channel the bot can see.
    """
    # Ignore messages sent by the bot itself to prevent loops
    if message.author == client.user:
        return

    # Check if the message is the command '!rm'
    if message.content.lower() == '!rm':
        # Let the user know the bot is working on the request
        await message.channel.send("Fetching the latest USD/MYR rate...")

        # Get the exchange rate data
        data = get_exchange_rate()

        if data["success"]:
            # Create a Discord Embed for a nicely formatted response
            embed = discord.Embed(
                title="🇺🇸 USD/ 🇲🇾 MYR Reference Rate",
                description="The latest Kuala Lumpur USD/MYR reference rate.",
                color=discord.Color.blue()
            )
            embed.add_field(name="Rate", value=f"**1 USD = {data['rate']} MYR**", inline=False)
            embed.add_field(name="Date", value=data['date'], inline=True)
            embed.add_field(name="Last Updated", value=data['last_updated'], inline=True)
            embed.set_footer(text="Source: Bank Negara Malaysia (BNM)")
            
            # Send the embed to the channel
            await message.channel.send(embed=embed)
        else:
            # Send an error message if the data could not be fetched
            embed = discord.Embed(
                title="Error",
                description=data["error"],
                color=discord.Color.red()
            )
            await message.channel.send(embed=embed)

# --- Run the Bot ---
if __name__ == "__main__":
    if TOKEN is None:
        print("Error: DISCORD_TOKEN environment variable not found.")
        print("Please create a .env file and add your bot token.")
    else:
        client.run(TOKEN)