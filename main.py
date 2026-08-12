import discord
import json
import os
import asyncio
import aiohttp
from discord.ext import commands
from datetime import datetime, timedelta

# Get configuration from environment variables
TOKEN = os.environ.get('DISCORD_BOT_TOKEN')
GUILD_ID = int(os.environ.get('GUILD_ID', '1271223880975126689'))
API_ENDPOINT = os.environ.get('API_ENDPOINT', 'https://bsyw-profile.vercel.app/api/presence')
API_SECRET = os.environ.get('API_SECRET', 'Bisaya-Presence-2024-SecretKey!')
AFK_CHANNEL_ID = int(os.environ.get('AFK_CHANNEL_ID', '0'))  # Add your AFK voice channel ID
AFK_TIMEOUT_MINUTES = int(os.environ.get('AFK_TIMEOUT_MINUTES', '5'))  # Default 5 minutes

# Enable necessary intents
intents = discord.Intents.default()
intents.presences = True
intents.members = True
intents.message_content = True
intents.voice_states = True  # Required for voice tracking

bot = commands.Bot(command_prefix="!", intents=intents)

# Store voice activity tracking
voice_activity = {}  # {user_id: {"channel_id": channel_id, "last_active": timestamp, "afk_warning_sent": False}}
afk_tasks = {}  # {user_id: asyncio.Task}

@bot.event
async def on_ready():
    print(f"✅ {bot.user} is online!")
    print(f"📊 Bot ID: {bot.user.id}")
    print(f"📡 API Endpoint: {API_ENDPOINT}")
    print(f"🎙️ AFK Channel ID: {AFK_CHANNEL_ID}")
    print(f"⏰ AFK Timeout: {AFK_TIMEOUT_MINUTES} minutes")
    
    # Get guild
    guild = bot.get_guild(GUILD_ID)
    if guild:
        print(f"📋 Connected to server: {guild.name}")
        print(f"👥 Members: {len(guild.members)}")
        
        # Check if AFK channel exists
        if AFK_CHANNEL_ID:
            afk_channel = guild.get_channel(AFK_CHANNEL_ID)
            if afk_channel:
                print(f"✅ AFK Channel found: {afk_channel.name}")
                # Move users who are already in AFK channel to be properly set
                for member in afk_channel.members:
                    if not member.bot:
                        await move_to_afk(member, afk_channel)
            else:
                print(f"❌ AFK Channel with ID {AFK_CHANNEL_ID} not found!")
        else:
            print("⚠️ No AFK Channel ID set. Set AFK_CHANNEL_ID environment variable.")
        
        # Initial sync of all members for presence tracking
        for member in guild.members:
            if not member.bot:  # Skip other bots
                await update_member_presence(member)
                # Initialize voice tracking for members in voice channels
                if member.voice and member.voice.channel:
                    voice_activity[member.id] = {
                        "channel_id": member.voice.channel.id,
                        "last_active": datetime.now(),
                        "afk_warning_sent": False
                    }
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

@bot.event
async def on_voice_state_update(member, before, after):
    """Track voice state changes for AFK management"""
    if member.bot:
        return
    
    # User joined a voice channel
    if after.channel and not before.channel:
        print(f"🎙️ {member.name} joined voice channel: {after.channel.name}")
        # Reset tracking
        voice_activity[member.id] = {
            "channel_id": after.channel.id,
            "last_active": datetime.now(),
            "afk_warning_sent": False
        }
        # Cancel any existing AFK task
        if member.id in afk_tasks:
            afk_tasks[member.id].cancel()
            del afk_tasks[member.id]
    
    # User moved to a different voice channel
    elif after.channel and before.channel and after.channel.id != before.channel.id:
        print(f"🎙️ {member.name} moved from {before.channel.name} to {after.channel.name}")
        # Check if moved to AFK channel manually
        if AFK_CHANNEL_ID and after.channel.id == AFK_CHANNEL_ID:
            await move_to_afk(member, after.channel)
            return
        
        # Reset tracking for new channel
        voice_activity[member.id] = {
            "channel_id": after.channel.id,
            "last_active": datetime.now(),
            "afk_warning_sent": False
        }
        # Cancel any existing AFK task
        if member.id in afk_tasks:
            afk_tasks[member.id].cancel()
            del afk_tasks[member.id]
        
        # Start AFK timer for the new channel
        if AFK_CHANNEL_ID and after.channel.id != AFK_CHANNEL_ID:
            await start_afk_timer(member)
    
    # User left voice channel
    elif not after.channel and before.channel:
        print(f"🎙️ {member.name} left voice channel: {before.channel.name}")
        # Remove from tracking
        if member.id in voice_activity:
            del voice_activity[member.id]
        # Cancel AFK task
        if member.id in afk_tasks:
            afk_tasks[member.id].cancel()
            del afk_tasks[member.id]
    
    # User muted/unmuted or deafened/undeafened - update last active time
    elif after.channel and before.channel and after.channel.id == before.channel.id:
        # Check if user spoke (unmuted or undeafened)
        if (before.self_mute and not after.self_mute) or (before.self_deaf and not after.self_deaf):
            print(f"🎙️ {member.name} became active in voice")
            if member.id in voice_activity:
                voice_activity[member.id]["last_active"] = datetime.now()
                voice_activity[member.id]["afk_warning_sent"] = False
                # Reset AFK timer
                if member.id in afk_tasks:
                    afk_tasks[member.id].cancel()
                    del afk_tasks[member.id]
                await start_afk_timer(member)

@bot.event
async def on_voice_channel_update(channel):
    """Triggered when a voice channel is updated"""
    # This can be used to detect if AFK channel settings change
    pass

async def start_afk_timer(member):
    """Start an AFK timer for a member"""
    if member.id in afk_tasks:
        afk_tasks[member.id].cancel()
    
    task = asyncio.create_task(afk_timeout_task(member))
    afk_tasks[member.id] = task

async def afk_timeout_task(member):
    """Task that waits for AFK timeout and moves user to AFK channel"""
    try:
        # Wait for the AFK timeout period
        await asyncio.sleep(AFK_TIMEOUT_MINUTES * 60)
        
        # Check if member is still in voice and not already in AFK channel
        if not member.voice or not member.voice.channel:
            return
        
        # Check if the channel is the AFK channel (shouldn't happen but just in case)
        if AFK_CHANNEL_ID and member.voice.channel.id == AFK_CHANNEL_ID:
            return
        
        # Get the AFK channel
        afk_channel = member.guild.get_channel(AFK_CHANNEL_ID)
        if not afk_channel:
            print(f"❌ AFK Channel not found for {member.name}")
            return
        
        # Check if user has been inactive (no unmute/undeafen events)
        if member.id in voice_activity:
            last_active = voice_activity[member.id]["last_active"]
            time_since_active = (datetime.now() - last_active).total_seconds()
            
            # Only move if truly inactive
            if time_since_active >= AFK_TIMEOUT_MINUTES * 60:
                await move_to_afk(member, afk_channel)
            else:
                # User became active, restart timer
                await start_afk_timer(member)
        else:
            # User not in tracking, move to AFK
            await move_to_afk(member, afk_channel)
            
    except asyncio.CancelledError:
        # Task was cancelled, clean up
        pass
    except Exception as e:
        print(f"❌ Error in AFK timeout task for {member.name}: {e}")

async def move_to_afk(member, afk_channel):
    """Move a member to the AFK channel and mute/deafen them"""
    try:
        # Move to AFK channel
        await member.move_to(afk_channel)
        print(f"🔇 Moved {member.name} to AFK channel: {afk_channel.name}")
        
        # Wait a moment for the move to complete
        await asyncio.sleep(0.5)
        
        # Mute and deafen the member
        await member.edit(mute=True, deafen=True)
        print(f"🔇 Muted and deafened {member.name}")
        
        # Send a DM notification (optional)
        try:
            await member.send(f"🔇 You were moved to {afk_channel.name} and muted/deafened due to {AFK_TIMEOUT_MINUTES} minutes of inactivity.")
        except discord.Forbidden:
            pass  # User has DMs disabled
        
        # Clean up tracking
        if member.id in voice_activity:
            del voice_activity[member.id]
        if member.id in afk_tasks:
            del afk_tasks[member.id]
            
    except discord.Forbidden:
        print(f"❌ Missing permissions to move {member.name}")
    except discord.HTTPException as e:
        print(f"❌ Error moving {member.name}: {e}")

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
    voice_members = 0
    
    for member in guild.members:
        if member.bot:
            continue
        if member.status != discord.Status.offline:
            online_count += 1
        # Check for decoration
        if hasattr(member, 'avatar_decoration') and member.avatar_decoration:
            decorations += 1
        # Check voice
        if member.voice and member.voice.channel:
            voice_members += 1
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
    embed.add_field(name="In Voice Channels", value=str(voice_members), inline=True)
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
    
    # Check voice status
    if member.voice and member.voice.channel:
        response += f"Voice Channel: {member.voice.channel.name}\n"
        response += f"Muted: {member.voice.self_mute or member.voice.mute}\n"
        response += f"Deafened: {member.voice.self_deaf or member.voice.deaf}\n"
    else:
        response += "Voice: Not in a voice channel\n"
    
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
        value=f"Presences Intent: {bot.intents.presences}\nMembers Intent: {bot.intents.members}\nVoice States: {bot.intents.voice_states}",
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
    
    # Check 4: Voice status
    voice_info = "Not in voice"
    if member.voice and member.voice.channel:
        voice_info = f"Channel: {member.voice.channel.name}\n"
        voice_info += f"Muted: {member.voice.self_mute or member.voice.mute}\n"
        voice_info += f"Deafened: {member.voice.self_deaf or member.voice.deaf}"
    embed.add_field(name="🎙️ Voice Status", value=voice_info, inline=True)
    
    # Check 5: Detailed activities
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
    
    # Check 6: Bot's permissions
    permissions = ctx.guild.me.guild_permissions
    embed.add_field(
        name="👮 Bot Permissions",
        value=f"View Members: {permissions.view_members}\nRead Messages: {permissions.read_messages}\nMove Members: {permissions.move_members}\nMute Members: {permissions.mute_members}\nDeafen Members: {permissions.deafen_members}",
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

@bot.command(name="setafk")
@commands.has_permissions(administrator=True)
async def set_afk_channel(ctx, channel: discord.VoiceChannel = None):
    """Set the AFK voice channel (Admin only)"""
    global AFK_CHANNEL_ID
    
    if not channel:
        await ctx.send("❌ Please specify a voice channel. Usage: `!setafk #channel`")
        return
    
    AFK_CHANNEL_ID = channel.id
    await ctx.send(f"✅ AFK channel set to: {channel.name}")

@bot.command(name="afktime")
@commands.has_permissions(administrator=True)
async def set_afk_timeout(ctx, minutes: int):
    """Set the AFK timeout in minutes (Admin only)"""
    global AFK_TIMEOUT_MINUTES
    
    if minutes < 1:
        await ctx.send("❌ Timeout must be at least 1 minute")
        return
    
    AFK_TIMEOUT_MINUTES = minutes
    await ctx.send(f"✅ AFK timeout set to {minutes} minutes")

@bot.command(name="afkstatus")
async def afk_status(ctx):
    """Check AFK system status"""
    guild = ctx.guild
    
    embed = discord.Embed(title="🎙️ AFK System Status", color=0x00ff00)
    
    # AFK Channel info
    if AFK_CHANNEL_ID:
        afk_channel = guild.get_channel(AFK_CHANNEL_ID)
        if afk_channel:
            embed.add_field(name="AFK Channel", value=f"{afk_channel.name} ({len(afk_channel.members)} users)", inline=True)
        else:
            embed.add_field(name="AFK Channel", value="❌ Not found", inline=True)
    else:
        embed.add_field(name="AFK Channel", value="❌ Not set", inline=True)
    
    embed.add_field(name="Timeout", value=f"{AFK_TIMEOUT_MINUTES} minutes", inline=True)
    
    # Users in AFK
    if AFK_CHANNEL_ID:
        afk_channel = guild.get_channel(AFK_CHANNEL_ID)
        if afk_channel and afk_channel.members:
            afk_users = ", ".join([m.name for m in afk_channel.members if not m.bot])
            embed.add_field(name="Users in AFK", value=afk_users[:1024], inline=False)
        else:
            embed.add_field(name="Users in AFK", value="None", inline=True)
    
    # Active voice users
    active_users = []
    for member in guild.members:
        if not member.bot and member.voice and member.voice.channel and member.voice.channel.id != AFK_CHANNEL_ID:
            active_users.append(member.name)
    
    if active_users:
        embed.add_field(name="Active Voice Users", value=f"{len(active_users)} users", inline=True)
    else:
        embed.add_field(name="Active Voice Users", value="None", inline=True)
    
    await ctx.send(embed=embed)

@bot.command(name="afkclear")
@commands.has_permissions(administrator=True)
async def afk_clear(ctx):
    """Clear all users from AFK channel (Admin only)"""
    if not AFK_CHANNEL_ID:
        await ctx.send("❌ AFK channel not set")
        return
    
    afk_channel = ctx.guild.get_channel(AFK_CHANNEL_ID)
    if not afk_channel:
        await ctx.send("❌ AFK channel not found")
        return
    
    count = 0
    for member in afk_channel.members:
        if not member.bot:
            try:
                # Unmute and undeafen before moving
                await member.edit(mute=False, deafen=False)
                # Move to a general voice channel or disconnect
                await member.move_to(None)  # Disconnect
                count += 1
                await asyncio.sleep(0.5)  # Rate limit prevention
            except Exception as e:
                print(f"❌ Error clearing {member.name}: {e}")
    
    await ctx.send(f"✅ Cleared {count} users from AFK channel")

# Run the bot
if __name__ == "__main__":
    if not TOKEN:
        print("❌ ERROR: DISCORD_BOT_TOKEN not set!")
        exit(1)
    if GUILD_ID == 0:
        print("⚠️ WARNING: GUILD_ID not set!")
    if AFK_CHANNEL_ID == 0:
        print("⚠️ WARNING: AFK_CHANNEL_ID not set! Set it in environment variables.")
    
    print("🚀 Starting bot...")
    bot.run(TOKEN)
