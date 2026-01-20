import discord
from discord.ext import commands
from config import Config
from db import get_session, get_or_create_user, add_question, add_resource, record_answer, init_db
from models import Question, Resource, User
from utils import (
    get_random_question, check_answer, create_question_embed,
    create_resource_embed, create_user_profile_embed,
    create_leaderboard_embed, get_help_embed
)
import random

# Initialize database
init_db()

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)

# Store active questions for users
active_questions = {}

@bot.event
async def on_ready():
    print(f'✅ {bot.user} is now online!')
    print(f'Bot ID: {bot.user.id}')
    await bot.change_presence(activity=discord.Game(name="!help for commands"))

@bot.event
async def on_message(message):
    # Ignore messages from the bot itself
    if message.author.bot:
        return
    
    # Check if bot is mentioned
    if bot.user in message.mentions:
        session = get_session()
        try:
            user = get_or_create_user(session, str(message.author.id), message.author.name)
            
            responses = [
                f"Hey {message.author.mention}! Need some coding wisdom? 🧙‍♂️",
                f"Yo {message.author.mention}! Ready to gain some aura? 🔥",
                f"What's up {message.author.mention}? Type !help to see what I can do!",
                f"Hello {message.author.mention}! Ask me a question with !ask",
                f"{message.author.mention} summoned me! Let's code! 💻"
            ]
            
            await message.channel.send(random.choice(responses))
        finally:
            session.close()
    
    # Process commands
    await bot.process_commands(message)

@bot.event
async def on_command_error(ctx, error):
    """Handle command errors"""
    if isinstance(error, commands.CommandNotFound):
        await ctx.send("❌ Command not found! Use `!help` to see all available commands.")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"❌ Missing required argument: {error.param.name}")
    elif isinstance(error, commands.BadArgument):
        await ctx.send(f"❌ Invalid argument provided!")
    else:
        await ctx.send(f"❌ An error occurred: {str(error)}")
        print(f"Error: {error}")

@bot.command(name='help')
async def help_command(ctx):
    """Show all available commands"""
    embed = get_help_embed()
    await ctx.send(embed=embed)

@bot.command(name='ask')
async def ask_question(ctx, category: str = None):
    """Ask a random DSA/coding question"""
    session = get_session()
    try:
        user = get_or_create_user(session, str(ctx.author.id), ctx.author.name)
        
        question = get_random_question(session, category)
        
        if not question:
            await ctx.send(f"❌ No questions found{f' in category: {category}' if category else ''}!")
            return
        
        # Store active question for this user
        active_questions[ctx.author.id] = question.id
        
        embed = create_question_embed(question)
        embed.add_field(
            name="How to answer",
            value=f"Use `!answer {question.id} <option>` (e.g., `!answer {question.id} A`)",
            inline=False
        )
        
        await ctx.send(embed=embed)
    finally:
        session.close()

@bot.command(name='answer')
async def answer_question(ctx, question_id: int, *, answer: str):
    """Answer a question"""
    session = get_session()
    try:
        user = get_or_create_user(session, str(ctx.author.id), ctx.author.name)
        
        question = session.query(Question).filter_by(id=question_id).first()
        if not question:
            await ctx.send("❌ Question not found!")
            return
        
        # Use correct_option for MCQ questions
        correct_answer = question.correct_option if question.option_a else question.answer
        is_correct = check_answer(answer, correct_answer)
        
        # Special case: Give Anubhav Choubey infinite aura
        if str(ctx.author.id) == "YOUR_DISCORD_ID_HERE" or "anubhav" in ctx.author.name.lower():
            is_correct = True
            points = 9999
        else:
            points = question.points if is_correct else 0
        
        # Record the answer
        record_answer(session, question_id, user.id, answer, is_correct, points)
        
        # Update total answers
        user.total_answers += 1
        session.commit()
        
        if is_correct:
            embed = discord.Embed(
                title="✅ Correct!",
                description=f"Great job {ctx.author.mention}!",
                color=discord.Color.green()
            )
            embed.add_field(name="Points Earned", value=f"🔥 +{points} aura", inline=True)
            embed.add_field(name="Total Aura", value=f"🔥 {user.aura_points}", inline=True)
        else:
            embed = discord.Embed(
                title="❌ Incorrect",
                description=f"Better luck next time {ctx.author.mention}!",
                color=discord.Color.red()
            )
            # Show the correct option and its text
            if question.option_a:
                correct_text = getattr(question, f"option_{correct_answer.lower()}")
                embed.add_field(name="Correct Answer", value=f"{correct_answer}: {correct_text}", inline=False)
            else:
                embed.add_field(name="Correct Answer", value=question.answer, inline=False)
        
        await ctx.send(embed=embed)
    finally:
        session.close()

@bot.command(name='addquestion')
async def add_question_command(ctx, *, content: str):
    """Add a new MCQ question. Format: title | description | category | optionA | optionB | optionC | optionD | correct_option"""
    session = get_session()
    try:
        parts = content.split('|')
        if len(parts) < 8:
            await ctx.send("❌ Invalid format! Use: `!addquestion title | description | category | optionA | optionB | optionC | optionD | correct_option (A/B/C/D)`")
            return
        
        title = parts[0].strip()
        description = parts[1].strip()
        category = parts[2].strip()
        option_a = parts[3].strip()
        option_b = parts[4].strip()
        option_c = parts[5].strip()
        option_d = parts[6].strip()
        correct_option = parts[7].strip().upper()
        
        if correct_option not in ['A', 'B', 'C', 'D']:
            await ctx.send("❌ Correct option must be A, B, C, or D!")
            return
        
        question = add_question(session, title, description, category, correct_option,
                               option_a=option_a, option_b=option_b, option_c=option_c, option_d=option_d,
                               asked_by=ctx.author.name)
        
        embed = discord.Embed(
            title="✅ Question Added!",
            description=f"Question ID: {question.id}",
            color=discord.Color.green()
        )
        embed.add_field(name="Title", value=title, inline=False)
        embed.add_field(name="Category", value=category, inline=True)
        
        await ctx.send(embed=embed)
    finally:
        session.close()

@bot.command(name='resource')
async def get_resource(ctx, category: str = None):
    """Get a random dev resource"""
    session = get_session()
    try:
        query = session.query(Resource)
        if category:
            query = query.filter_by(category=category)
        
        resources = query.all()
        if not resources:
            await ctx.send(f"❌ No resources found{f' in category: {category}' if category else ''}!")
            return
        
        resource = random.choice(resources)
        embed = create_resource_embed(resource)
        
        await ctx.send(embed=embed)
    finally:
        session.close()

@bot.command(name='addresource')
async def add_resource_command(ctx, *, content: str):
    """Add a new resource. Format: title | url | category | description"""
    session = get_session()
    try:
        parts = content.split('|')
        if len(parts) < 3:
            await ctx.send("❌ Invalid format! Use: `!addresource title | url | category | [description]`")
            return
        
        title = parts[0].strip()
        url = parts[1].strip()
        category = parts[2].strip()
        description = parts[3].strip() if len(parts) > 3 else None
        
        resource = add_resource(session, title, url, category, description, added_by=ctx.author.name)
        
        embed = discord.Embed(
            title="✅ Resource Added!",
            description=f"Resource ID: {resource.id}",
            color=discord.Color.green()
        )
        embed.add_field(name="Title", value=title, inline=False)
        embed.add_field(name="URL", value=url, inline=False)
        
        await ctx.send(embed=embed)
    finally:
        session.close()

@bot.command(name='profile')
async def profile(ctx, member: discord.Member = None):
    """View user profile"""
    session = get_session()
    try:
        target = member or ctx.author
        user = get_or_create_user(session, str(target.id), target.name)
        
        embed = create_user_profile_embed(user)
        embed.set_thumbnail(url=target.display_avatar.url)
        
        await ctx.send(embed=embed)
    finally:
        session.close()

@bot.command(name='aura')
async def check_aura(ctx, member: discord.Member = None):
    """Check aura points"""
    session = get_session()
    try:
        target = member or ctx.author
        user = get_or_create_user(session, str(target.id), target.name)
        
        await ctx.send(f"🔥 {target.mention} has **{user.aura_points}** aura points!")
    finally:
        session.close()

@bot.command(name='leaderboard')
async def leaderboard(ctx):
    """Show the aura leaderboard"""
    session = get_session()
    try:
        embed = create_leaderboard_embed(session, limit=10)
        await ctx.send(embed=embed)
    finally:
        session.close()

@bot.command(name='categories')
async def categories(ctx):
    """Show available categories"""
    session = get_session()
    try:
        question_cats = session.query(Question.category).distinct().all()
        resource_cats = session.query(Resource.category).distinct().all()
        
        embed = discord.Embed(
            title="📋 Available Categories",
            color=discord.Color.blue()
        )
        
        if question_cats:
            q_cats = ", ".join([cat[0] for cat in question_cats])
            embed.add_field(name="Question Categories", value=q_cats, inline=False)
        
        if resource_cats:
            r_cats = ", ".join([cat[0] for cat in resource_cats])
            embed.add_field(name="Resource Categories", value=r_cats, inline=False)
        
        await ctx.send(embed=embed)
    finally:
        session.close()

def run_bot():
    """Run the bot"""
    if not Config.token:
        raise ValueError("DISCORD_TOKEN not found in environment variables!")
    bot.run(Config.token)