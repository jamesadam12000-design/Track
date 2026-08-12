import discord
import json
import os
import asyncio
import aiohttp
from discord.ext import commands
from datetime import datetime

# Get configuration from environment variables
TOKEN = os.environ.get('DISCORD_BOT_TOKEN')
GUILD_ID = int(os.environ.get('GUILD_ID', '1271223880975126689'))
API_ENDPOINT = os.environ.get('API_ENDPOINT', 'https://bsyw-profile.vercel.app/api/presence')
API_SECRET = os.environ.get('API_SECRET', 'Bisaya-Presence-2024-SecretKey!')

# Enable necessary intents
intents = discord.Intents.default()
intents.presences = True
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"✅ {bot.user} is online!")
    print(f"📊 Bot ID: {bot.user.id}")
    print(f"📡 API Endpoint: {API_ENDPOINT}")
    
    # Get guild
    guild = bot.get_guild(GUILD_ID)
    if guild:
        print(f"📋 Connected to server: {guild.name}")
        print(f"👥 Members: {len(guild.members)}")
        
        # Initial sync of all members
        for member in guild.members:
            if not member.bot:  # Skip other bots
                await update_member_presence(member)
        print("✅ Initial member sync complete!")
    else:
        print(f"❌ Could not find server with ID {GUILD_ID}")
        print("🔍 Make sure the bot is in the server and GUILD_ID is correct")

@bot.event
async def on_presence_update(before, after):
    """Triggered when a member's presence changes"""
    if not after.bot:  # Skip bots
        print(f"🔄 Presence update for {after.name}")
        await update_member_presence(after)

async def update_member_presence(member):
    """Extract and send presence data to your website"""
    
    print(f"🔍 Checking {member.name} - Activities count: {len(member.activities)}")
    
    # Status mapping
    status_map = {
        discord.Status.online: "online",
        discord.Status.idle: "idle",
        discord.Status.dnd: "dnd",
        discord.Status.offline: "offline"
    }
    status = status_map.get(member.status, "offline")
    
    # Get avatar hash and decoration
    avatar_hash = member.avatar.key if member.avatar else None
    
    # Handle avatar decoration properly
    avatar_decoration = None
    avatar_decoration_data = None
    
    # Check for avatar decoration in different possible locations
    if hasattr(member, 'avatar_decoration'):
        decoration = member.avatar_decoration
        if decoration:
            # If it's an Asset object, convert to string URL
            if isinstance(decoration, discord.Asset):
                avatar_decoration = str(decoration.url)
            else:
                avatar_decoration = str(decoration)
            print(f"   ✨ Has avatar decoration: {avatar_decoration}")
    
    # Also check for avatar_decoration_data (sometimes used)
    if hasattr(member, 'avatar_decoration_data') and member.avatar_decoration_data:
        if isinstance(member.avatar_decoration_data, dict):
            avatar_decoration_data = member.avatar_decoration_data
        else:
            avatar_decoration_data = str(member.avatar_decoration_data)
    
    # Extract activities
    activities = []
    custom_status = None
    
    for activity in member.activities:
        print(f"  Activity: {activity.name} (Type: {activity.type})")
        
        if activity.type == discord.ActivityType.custom:
            # Custom status
            custom_status = {
                "state": activity.state,
                "emoji": str(activity.emoji) if activity.emoji else None
            }
            print(f"    💬 Custom: {activity.state}")
            
        elif activity.type == discord.ActivityType.playing:
            # Game
            game_data = {
                "type": "game",
                "name": activity.name,
                "details": getattr(activity, "details", None),
                "state": getattr(activity, "state", None)
            }
            activities.append(game_data)
            print(f"    🎮 Game: {activity.name}")
            if activity.details:
                print(f"      Details: {activity.details}")
            if activity.state:
                print(f"      State: {activity.state}")
                
        elif activity.type == discord.ActivityType.listening:
            # Music (Spotify, etc.)
            if activity.name == "Spotify":
                # Get album art if available
                album_art = None
                if hasattr(activity, "album_cover_url") and activity.album_cover_url:
                    album_art = activity.album_cover_url
                
                # Handle timestamps for progress bar
                start_time = None
                end_time = None
                duration_seconds = None
                elapsed_seconds = None
                
                # Get duration and elapsed time
                if hasattr(activity, "duration") and activity.duration:
                    duration_seconds = int(activity.duration.total_seconds())
                
                if hasattr(activity, "elapsed") and activity.elapsed:
                    elapsed_seconds = int(activity.elapsed.total_seconds())
                    
                    # Calculate end time based on elapsed + remaining
                    if hasattr(activity, "remaining") and activity.remaining:
                        remaining_seconds = int(activity.remaining.total_seconds())
                        end_time = (datetime.now().timestamp() + remaining_seconds) * 1000
                    else:
                        # Or use start + duration
                        start_time = (datetime.now().timestamp() - elapsed_seconds) * 1000
                        if duration_seconds:
                            end_time = start_time + (duration_seconds * 1000)
                
                # Also check for direct timestamp properties
                if hasattr(activity, "start") and activity.start:
                    start_time = activity.start.timestamp() * 1000
                
                if hasattr(activity, "end") and activity.end:
                    end_time = activity.end.timestamp() * 1000
                
                # Get track ID from assets if available
                track_id = None
                if hasattr(activity, "assets") and activity.assets:
                    if "large_image" in activity.assets:
                        large_image = activity.assets["large_image"]
                        if large_image and large_image.startswith("spotify:track:"):
                            track_id = large_image.replace("spotify:track:", "")
                
                spotify_data = {
                    "type": "spotify",
                    "name": "Spotify",
                    "song": getattr(activity, "title", "Unknown"),
                    "artist": getattr(activity, "artist", "Unknown"),
                    "album": getattr(activity, "album", "Unknown"),
                    "album_art": album_art,
                    "track_id": track_id,
                    "track_url": f"https://open.spotify.com/track/{track_id}" if track_id else None,
                    "duration": duration_seconds,
                    "elapsed": elapsed_seconds,
                    "start_time": start_time,
                    "end_time": end_time,
                    "remaining": int(activity.remaining.total_seconds()) if hasattr(activity, "remaining") and activity.remaining else None
                }
                activities.append(spotify_data)
                print(f"    🎵 Spotify: {getattr(activity, 'title', 'Unknown')} by {getattr(activity, 'artist', 'Unknown')}")
                if elapsed_seconds and duration_seconds:
                    print(f"      ⏱️ {elapsed_seconds//60}:{elapsed_seconds%60:02d} / {duration_seconds//60}:{duration_seconds%60:02d}")
            else:
                activities.append({
                    "type": "listening",
                    "name": activity.name
                })
                print(f"    🎧 Listening: {activity.name}")
                
        elif activity.type == discord.ActivityType.watching:
            activities.append({
                "type": "watching",
                "name": activity.name
            })
            print(f"    👀 Watching: {activity.name}")
            
        elif activity.type == discord.ActivityType.streaming:
            activities.append({
                "type": "streaming",
                "name": activity.name,
                "url": getattr(activity, "url", None),
                "platform": "Twitch" if getattr(activity, "twitch", False) else "Other"
            })
            print(f"    📺 Streaming: {activity.name}")
    
    # Prepare payload with full user info including decoration
    payload = {
        "discord_id": str(member.id),
        "username": member.name,
        "global_name": member.global_name,
        "avatar": avatar_hash,  # Send hash, frontend constructs URL
        "avatar_decoration": avatar_decoration,  # Now this is a string URL, not an Asset
        "avatar_decoration_data": avatar_decoration_data,
        "status": status,
        "custom_status": custom_status,
        "activities": activities,
        "last_updated": datetime.now().isoformat()
    }
    
    # Only send if there are activities or status changed
    if activities or custom_status or status != "offline":
        print(f"📤 Sending data for {member.name}: {status} with {len(activities)} activities")
        
        # Send to your API
        async with aiohttp.ClientSession() as session:
            try:
                headers = {"Authorization": API_SECRET} if API_SECRET else {}
                headers["Content-Type"] = "application/json"
                
                async with session.post(API_ENDPOINT, json=payload, headers=headers) as resp:
                    if resp.status == 200:
                        print(f"✅ Updated {member.name}: {status}")
                        # Print what we sent for debugging
                        if activities:
                            for act in activities:
                                if act.get("type") == "spotify":
                                    song = act.get('song', 'Unknown')
                                    artist = act.get('artist', 'Unknown')
                                    elapsed = act.get('elapsed')
                                    duration = act.get('duration')
                                    if elapsed and duration:
                                        print(f"    🎵 {song} - {artist} [{elapsed//60}:{elapsed%60:02d}/{duration//60}:{duration%60:02d}]")
                                    else:
                                        print(f"    🎵 {song} - {artist}")
                                elif act.get("type") == "game":
                                    print(f"    🎮 {act.get('name')}")
                    else:
                        response_text = await resp.text()
                        print(f"⚠️ API returned {resp.status} for {member.name}: {response_text}")
            except Exception as e:
                print(f"❌ Error updating {member.name}: {e}")
    else:
        print(f"⏭️ No activities for {member.name}, skipping")

@bot.command(name="ping")
async def ping(ctx):
    """Check if bot is alive"""
    latency = round(bot.latency * 1000)
    await ctx.send(f"🏓 Pong! Latency: {latency}ms")

@bot.command(name="stats")
async def stats(ctx):
    """Show bot statistics"""
    guild = bot.get_guild(GUILD_ID)
    if not guild:
        await ctx.send("❌ Not connected to server")
        return
    
    # Count activities
    games = 0
    spotify = 0
    custom = 0
    online_count = 0
    decorations = 0
    
    for member in guild.members:
        if member.bot:
            continue
        if member.status != discord.Status.offline:
            online_count += 1
        # Check for decoration
        if hasattr(member, 'avatar_decoration') and member.avatar_decoration:
            decorations += 1
        for activity in member.activities:
            if activity.type == discord.ActivityType.playing:
                games += 1
            elif activity.type == discord.ActivityType.listening and activity.name == "Spotify":
                spotify += 1
            elif activity.type == discord.ActivityType.custom:
                custom += 1
    
    tracked = len([m for m in guild.members if not m.bot])
    
    embed = discord.Embed(title="📊 Bot Statistics", color=0x00ff00)
    embed.add_field(name="Tracked Members", value=str(tracked), inline=True)
    embed.add_field(name="Online Now", value=str(online_count), inline=True)
    embed.add_field(name="Playing Games", value=str(games), inline=True)
    embed.add_field(name="Listening to Spotify", value=str(spotify), inline=True)
    embed.add_field(name="Custom Status", value=str(custom), inline=True)
    embed.add_field(name="Avatar Decorations", value=str(decorations), inline=True)
    embed.set_footer(text="Bisaya Presence Tracker")
    
    await ctx.send(embed=embed)

@bot.command(name="checkme")
async def check_my_activity(ctx):
    """Force check your current activities"""
    member = ctx.author
    
    response = f"**🔍 Checking {member.name}**\n"
    response += f"Status: {member.status}\n"
    response += f"Activities count: {len(member.activities)}\n"
    
    # Check for decoration
    if hasattr(member, 'avatar_decoration') and member.avatar_decoration:
        decoration = member.avatar_decoration
        if isinstance(decoration, discord.Asset):
            response += f"Avatar Decoration: ✨ {decoration.url}\n"
        else:
            response += f"Avatar Decoration: ✨ {decoration}\n"
    else:
        response += "Avatar Decoration: None\n"
    
    if len(member.activities) == 0:
        response += "\n❌ **NO ACTIVITIES DETECTED**\n"
        response += "This means Discord is not sending activity data to the bot.\n\n"
        response += "**Check your Discord settings:**\n"
        response += "1️⃣ Privacy & Safety → Activity Privacy → ALL ON\n"
        response += "2️⃣ Right-click server → Privacy Settings → Allow members to see activity\n"
        response += "3️⃣ Try restarting Discord completely"
    else:
        for i, activity in enumerate(member.activities):
            response += f"\n**Activity {i+1}:** {activity.name}\n"
            if activity.type == discord.ActivityType.playing:
                response += f"  Type: Game\n"
                if hasattr(activity, 'details') and activity.details:
                    response += f"  Details: {activity.details}\n"
                if hasattr(activity, 'state') and activity.state:
                    response += f"  State: {activity.state}\n"
            elif activity.type == discord.ActivityType.listening:
                if activity.name == "Spotify":
                    song = getattr(activity, 'title', 'Unknown')
                    artist = getattr(activity, 'artist', 'Unknown')
                    elapsed = getattr(activity, 'elapsed', None)
                    duration = getattr(activity, 'duration', None)
                    
                    response += f"  Song: {song}\n"
                    response += f"  Artist: {artist}\n"
                    response += f"  Album: {getattr(activity, 'album', 'Unknown')}\n"
                    
                    if elapsed and duration:
                        elapsed_min = elapsed.total_seconds() // 60
                        elapsed_sec = elapsed.total_seconds() % 60
                        duration_min = duration.total_seconds() // 60
                        duration_sec = duration.total_seconds() % 60
                        response += f"  Time: {int(elapsed_min)}:{int(elapsed_sec):02d} / {int(duration_min)}:{int(duration_sec):02d}\n"
            elif activity.type == discord.ActivityType.custom:
                response += f"  Custom: {activity.state}\n"
    
    await ctx.send(response)

@bot.command(name="diagnose")
async def diagnose(ctx, member: discord.Member = None):
    """Diagnose why activities aren't showing"""
    if not member:
        member = ctx.author
    
    embed = discord.Embed(
        title=f"🔍 Discord Presence Diagnostic for {member.name}",
        color=0x00ff00
    )
    
    # Check 1: Bot's intents
    embed.add_field(
        name="🤖 Bot Intents",
        value=f"Presences Intent: {bot.intents.presences}\nMembers Intent: {bot.intents.members}",
        inline=False
    )
    
    # Check 2: Member's status
    status_map = {
        discord.Status.online: "🟢 Online",
        discord.Status.idle: "🟡 Idle",
        discord.Status.dnd: "🔴 DND",
        discord.Status.offline: "⚫ Offline"
    }
    status_text = status_map.get(member.status, "Unknown")
    embed.add_field(name="📊 Current Status", value=status_text, inline=True)
    
    # Check for decoration
    decoration_text = "None"
    if hasattr(member, 'avatar_decoration') and member.avatar_decoration:
        decoration = member.avatar_decoration
        if isinstance(decoration, discord.Asset):
            decoration_text = f"✨ {decoration.url}"
        else:
            decoration_text = f"✨ {decoration}"
    embed.add_field(name="🎨 Avatar Decoration", value=decoration_text, inline=True)
    
    # Check 3: Activities count
    embed.add_field(name="🎮 Activities Count", value=str(len(member.activities)), inline=True)
    
    # Check 4: Detailed activities
    if len(member.activities) == 0:
        embed.add_field(
            name="⚠️ NO ACTIVITIES DETECTED",
            value=(
                "This means Discord is NOT sending activity data to the bot.\n\n"
                "**Please check:**\n"
                "1️⃣ **Discord Settings → Privacy & Safety**\n"
                "   • 'Share your activity status' must be ON\n"
                "   • 'Display current activity as a status message' must be ON\n\n"
                "2️⃣ **Right-click this server → Privacy Settings**\n"
                "   • 'Allow server members to see your activity' must be ON\n\n"
                "3️⃣ **Discord Developer Portal → Bot**\n"
                "   • 'PRESENCE INTENT' must be ENABLED\n"
                "   • 'SERVER MEMBERS INTENT' must be ENABLED\n\n"
                "4️⃣ **Try this:**\n"
                "   • Restart Discord completely\n"
                "   • Toggle settings OFF and ON again\n"
                "   • Wait 5 minutes for changes to take effect"
            ),
            inline=False
        )
    else:
        for i, activity in enumerate(member.activities):
            details = f"**Type:** {activity.type}\n**Name:** {activity.name}"
            
            if activity.type == discord.ActivityType.playing:
                if activity.details:
                    details += f"\n**Details:** {activity.details}"
                if activity.state:
                    details += f"\n**State:** {activity.state}"
            elif activity.type == discord.ActivityType.listening:
                if activity.name == "Spotify":
                    details += f"\n**Song:** {getattr(activity, 'title', 'Unknown')}"
                    details += f"\n**Artist:** {getattr(activity, 'artist', 'Unknown')}"
                    details += f"\n**Album:** {getattr(activity, 'album', 'Unknown')}"
                    
                    elapsed = getattr(activity, 'elapsed', None)
                    duration = getattr(activity, 'duration', None)
                    if elapsed and duration:
                        elapsed_min = elapsed.total_seconds() // 60
                        elapsed_sec = elapsed.total_seconds() % 60
                        duration_min = duration.total_seconds() // 60
                        duration_sec = duration.total_seconds() % 60
                        details += f"\n**Time:** {int(elapsed_min)}:{int(elapsed_sec):02d} / {int(duration_min)}:{int(duration_sec):02d}"
            elif activity.type == discord.ActivityType.custom:
                details += f"\n**Status:** {activity.state}"
            
            embed.add_field(name=f"Activity {i+1}", value=details, inline=False)
    
    # Check 5: Bot's permissions
    permissions = ctx.guild.me.guild_permissions
    embed.add_field(
        name="👮 Bot Permissions",
        value=f"View Members: {permissions.view_members}\nRead Messages: {permissions.read_messages}",
        inline=False
    )
    
    await ctx.send(embed=embed)

@bot.command(name="forcecheck")
async def forcecheck(ctx, member: discord.Member = None):
    """Force check a member's presence"""
    if not member:
        member = ctx.author
    
    await ctx.send(f"🔄 Force checking {member.name}...")
    await update_member_presence(member)
    await ctx.send("✅ Check complete! Check the bot logs for details.")

# Run the bot
if __name__ == "__main__":
    if not TOKEN:
        print("❌ ERROR: DISCORD_BOT_TOKEN not set!")
        exit(1)
    if GUILD_ID == 0:
        print("⚠️ WARNING: GUILD_ID not set!")
    
    print("🚀 Starting bot...")
    bot.run(TOKEN)
