# Champak Chacha Discord Bot 🤖

A feature-rich Discord bot for learning and sharing coding knowledge with your community!

## Features

- **MCQ-Based DSA Questions** - Answer multiple choice questions to test your knowledge
- **Resource Sharing** - Share and discover dev resources across categories
- **User Database** - Track users, their stats, and aura points
- **Question Database** - Store and manage coding questions with 4 options
- **Resource Database** - Organize learning resources by category
- **Aura Points System** - Earn points for correct answers and climb the leaderboard
- **Leaderboard** - Compete with others and see who has the most aura
- **Message Commands** - Interact with the bot through mentions and commands
- **Profile System** - View your stats, accuracy, and progress
- **Multiple Categories** - Questions and resources for DSA, coding, backend, frontend, and more

## Setup

### 1. Clone the Repository

```bash
git clone <your-repo-url>
cd champak-chacha
```

### 2. Create Virtual Environment

```bash
python -m venv env
source env/bin/activate  # On Windows: env\Scripts\activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Create Discord Bot

1. Go to [Discord Developer Portal](https://discord.com/developers/applications)
2. Click "New Application" and give it a name
3. Go to the "Bot" section and click "Add Bot"
4. Under "Privileged Gateway Intents", enable:
   - Message Content Intent
   - Server Members Intent
5. Copy the bot token

### 5. Configure Environment

```bash
cp .env.example .env
```

Edit `.env` and add your Discord bot token:

```
DISCORD_TOKEN=your_bot_token_here
DB_URL=sqlite:///app.db
LOGGING_LEVEL=INFO
```

### 6. Seed Database (Optional)

Add sample questions and resources:

```bash
python seed.py
```

### 7. Run the Bot

```bash
python main.py
```

### 8. Invite Bot to Your Server

1. Go to Discord Developer Portal → OAuth2 → URL Generator
2. Select scopes: `bot`
3. Select bot permissions:
   - Send Messages
   - Read Message History
   - Use Slash Commands
   - Embed Links
4. Copy the generated URL and open it in your browser
5. Select your server and authorize

## Commands

### 📝 Questions (MCQ Format)

- `!ask [category]` - Get a random MCQ question (optional: specify category)
- `!answer <question_id> <option>` - Answer with A, B, C, or D (e.g., `!answer 1 B`)
- `!addquestion <title> | <description> | <category> | <optionA> | <optionB> | <optionC> | <optionD> | <correct_option>` - Add a new MCQ question

**Example:**

```
!addquestion What is 2+2? | Basic math question | coding | 3 | 4 | 5 | 6 | B
```

### 📚 Resources

- `!resource [category]` - Get a random resource (optional: specify category)
- `!addresource <title> | <url> | <category> | [description]` - Add a new resource

### 👤 Profile & Stats

- `!profile [@user]` - View your or another user's profile
- `!aura [@user]` - Check aura points for you or another user
- `!leaderboard` - View the top 10 users by aura points

### ℹ️ Other

- `!help` - Show all available commands
- `!categories` - View all available categories
- **@Champak Chacha** - Tag the bot to get a response

## Database Schema

### Users

- Discord ID, Username
- Aura Points (earned by correct answers)
- Correct/Total Answers
- Accuracy tracking

### Questions

- Title, Description, Category
- Difficulty (easy, medium, hard)
- **4 MCQ Options** (A, B, C, D)
- **Correct Option** (A/B/C/D)
- Points, Who asked the question

### Resources

- Title, URL, Category
- Description, Tags
- Upvotes, Who added it

### Answers

- Links users to questions
- Tracks correctness and points awarded

## Project Structure

```
champak-chacha/
├── bot.py           # Main bot logic and commands
├── config.py        # Configuration and environment variables
├── db.py            # Database setup and helper functions
├── models.py        # SQLAlchemy models (User, Question, Resource, Answer)
├── utils.py         # Utility functions (embeds, answer checking, etc.)
├── main.py          # Entry point to run the bot
├── seed.py          # Seed database with sample data
├── requirements.txt # Python dependencies
├── .env.example     # Environment variables template
└── README.md        # This file
```

## Special Features

- **Infinite Aura for Anubhav Choubey** 😉 - Automatically awards maximum points
- **Smart Answer Checking** - Case-insensitive answer validation
- **Beautiful Embeds** - Rich Discord embeds for better UX
- **Category System** - Organize questions and resources by topic
- **Stat Tracking** - Track accuracy, correct answers, and progress

## Contributing

Feel free to add more questions, resources, and features! Open a PR or issue.

## License

MIT License - Feel free to use and modify!

---

Made with ❤️ for the coding community
