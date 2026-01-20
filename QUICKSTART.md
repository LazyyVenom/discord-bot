# Quick Start Guide

## Getting Your Bot Running in 5 Minutes

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Set Up Environment

```bash
cp .env.example .env
```

Edit `.env` and add your Discord bot token:

```
DISCORD_TOKEN=your_actual_bot_token_here
```

### 3. Initialize Database

```bash
python admin.py init
```

### 4. Add Sample Data (Optional)

```bash
python seed.py
```

### 5. Run the Bot

```bash
python main.py
```

## Creating Your Discord Bot

1. Go to https://discord.com/developers/applications
2. Click "New Application"
3. Give it a name (e.g., "Champak Chacha")
4. Go to "Bot" section → "Add Bot"
5. Enable these intents under "Privileged Gateway Intents":
   - ✅ Message Content Intent
   - ✅ Server Members Intent
6. Copy the bot token (click "Reset Token" if needed)
7. Paste token into `.env` file

## Inviting Bot to Your Server

1. Go to "OAuth2" → "URL Generator"
2. Select scopes:
   - ✅ `bot`
3. Select permissions:
   - ✅ Send Messages
   - ✅ Read Message History
   - ✅ Embed Links
   - ✅ Read Messages/View Channels
4. Copy the generated URL
5. Open URL in browser
6. Select your server and authorize

## Testing the Bot

Once the bot is running and in your server:

1. Type `!help` to see all commands
2. Type `!ask` to get a random question
3. Tag the bot: `@YourBotName hello` to get a response
4. Type `!profile` to see your profile

## Useful Admin Commands

```bash
# Show database statistics
python admin.py stats

# List all questions
python admin.py questions

# List all resources
python admin.py resources

# Reset database (CAUTION)
python admin.py reset
```

## Common Issues

### "DISCORD_TOKEN not found"

- Make sure you created `.env` file
- Check that the token is correct and has no extra spaces

### Bot doesn't respond

- Check that Message Content Intent is enabled
- Make sure bot has permissions in the channel
- Check that bot is online (green status)

### Database errors

- Run `python admin.py init` to initialize tables
- Check that DB_URL in `.env` is correct

## Next Steps

1. Add your own questions with `!addquestion`
2. Share resources with `!addresource`
3. Customize responses in `bot.py`
4. Modify the special user logic in [bot.py](bot.py#L119)
5. Invite friends and start building aura! 🔥

Enjoy your bot! 🚀
