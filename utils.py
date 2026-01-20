import random
from models import Question, Resource, User
import discord

def get_random_question(session, category=None):
    """Get a random active question from the database"""
    query = session.query(Question).filter_by(is_active=True)
    if category:
        query = query.filter_by(category=category)
    
    questions = query.all()
    if not questions:
        return None
    
    return random.choice(questions)

def check_answer(user_answer, correct_answer):
    """Check if the user's answer is correct (case-insensitive)"""
    # For MCQ questions, just check the option letter (A, B, C, D)
    user_ans = user_answer.strip().upper()
    correct_ans = correct_answer.strip().upper()
    return user_ans == correct_ans

def create_question_embed(question):
    """Create a Discord embed for a question"""
    embed = discord.Embed(
        title=f"📝 {question.title}",
        description=question.description,
        color=discord.Color.blue()
    )
    
    # Add MCQ options if they exist
    if question.option_a:
        options_text = f"**A)** {question.option_a}\n"
        options_text += f"**B)** {question.option_b}\n"
        options_text += f"**C)** {question.option_c}\n"
        options_text += f"**D)** {question.option_d}"
        embed.add_field(name="Options", value=options_text, inline=False)
    
    embed.add_field(name="Category", value=question.category, inline=True)
    embed.add_field(name="Difficulty", value=question.difficulty, inline=True)
    embed.add_field(name="Points", value=f"🔥 {question.points}", inline=True)
    embed.set_footer(text=f"Question ID: {question.id}")
    return embed

def create_resource_embed(resource):
    """Create a Discord embed for a resource"""
    embed = discord.Embed(
        title=f"📚 {resource.title}",
        description=resource.description or "No description provided",
        color=discord.Color.green(),
        url=resource.url
    )
    embed.add_field(name="Category", value=resource.category, inline=True)
    embed.add_field(name="Upvotes", value=f"👍 {resource.upvotes}", inline=True)
    if resource.tags:
        embed.add_field(name="Tags", value=resource.tags, inline=False)
    if resource.added_by:
        embed.add_field(name="Added by", value=resource.added_by, inline=True)
    return embed

def create_user_profile_embed(user):
    """Create a Discord embed for user profile"""
    embed = discord.Embed(
        title=f"👤 {user.username}'s Profile",
        color=discord.Color.gold()
    )
    embed.add_field(name="🔥 Aura Points", value=user.aura_points, inline=True)
    embed.add_field(name="✅ Correct Answers", value=user.correct_answers, inline=True)
    
    accuracy = (user.correct_answers / user.total_answers * 100) if user.total_answers > 0 else 0
    embed.add_field(name="🎯 Accuracy", value=f"{accuracy:.1f}%", inline=True)
    
    return embed

def create_leaderboard_embed(session, limit=10):
    """Create a Discord embed for leaderboard"""
    top_users = session.query(User).order_by(User.aura_points.desc()).limit(limit).all()
    
    embed = discord.Embed(
        title="🏆 Aura Leaderboard",
        description="Top users by aura points",
        color=discord.Color.purple()
    )
    
    medals = ["🥇", "🥈", "🥉"]
    for idx, user in enumerate(top_users, 1):
        medal = medals[idx-1] if idx <= 3 else f"{idx}."
        embed.add_field(
            name=f"{medal} {user.username}",
            value=f"🔥 {user.aura_points} aura | ✅ {user.correct_answers} correct",
            inline=False
        )
    
    return embed

def get_help_embed():
    """Create a help embed with all commands"""
    embed = discord.Embed(
        title="🤖 Champak Chacha - Help",
        description="Here are all the commands you can use:",
        color=discord.Color.blue()
    )
    
    embed.add_field(
        name="📝 Questions (MCQ Format)",
        value="• `!ask [category]` - Get a random MCQ question\n"
              "• `!answer <question_id> <option>` - Answer with A, B, C, or D\n"
              "• `!addquestion <title> | <desc> | <category> | <optA> | <optB> | <optC> | <optD> | <correct>` - Add MCQ question",
        inline=False
    )
    
    embed.add_field(
        name="📚 Resources",
        value="• `!resource [category]` - Get a random resource\n"
              "• `!addresource <title> | <url> | <category> | [description]` - Add a new resource",
        inline=False
    )
    
    embed.add_field(
        name="👤 Profile & Stats",
        value="• `!profile [@user]` - View profile\n"
              "• `!leaderboard` - View top users\n"
              "• `!aura [@user]` - Check aura points",
        inline=False
    )
    
    embed.add_field(
        name="ℹ️ Other",
        value="• `!help` - Show this message\n"
              "• Tag the bot with a message to get a response",
        inline=False
    )
    
    return embed