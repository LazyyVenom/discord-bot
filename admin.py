#!/usr/bin/env python3
"""
Admin script to manage the Champak Chacha bot database
"""
import sys
from db import get_session, init_db
from models import User, Question, Resource, Answer

def show_stats():
    """Show database statistics"""
    session = get_session()
    try:
        users = session.query(User).count()
        questions = session.query(Question).count()
        resources = session.query(Resource).count()
        answers = session.query(Answer).count()
        
        print("\n📊 Database Statistics")
        print("=" * 40)
        print(f"👥 Total Users: {users}")
        print(f"📝 Total Questions: {questions}")
        print(f"📚 Total Resources: {resources}")
        print(f"✍️  Total Answers: {answers}")
        print("=" * 40)
        
        if users > 0:
            print("\n🏆 Top 5 Users by Aura:")
            top_users = session.query(User).order_by(User.aura_points.desc()).limit(5).all()
            for i, user in enumerate(top_users, 1):
                print(f"  {i}. {user.username}: {user.aura_points} aura")
    finally:
        session.close()

def list_questions():
    """List all questions"""
    session = get_session()
    try:
        questions = session.query(Question).all()
        print(f"\n📝 All Questions ({len(questions)} total)")
        print("=" * 80)
        for q in questions:
            print(f"\nID: {q.id}")
            print(f"Title: {q.title}")
            print(f"Category: {q.category} | Difficulty: {q.difficulty} | Points: {q.points}")
            print(f"Active: {'✅' if q.is_active else '❌'}")
    finally:
        session.close()

def list_resources():
    """List all resources"""
    session = get_session()
    try:
        resources = session.query(Resource).all()
        print(f"\n📚 All Resources ({len(resources)} total)")
        print("=" * 80)
        for r in resources:
            print(f"\nID: {r.id}")
            print(f"Title: {r.title}")
            print(f"URL: {r.url}")
            print(f"Category: {r.category} | Upvotes: {r.upvotes}")
    finally:
        session.close()

def reset_database():
    """Reset the database (CAUTION: Deletes all data)"""
    confirm = input("⚠️  Are you sure you want to reset the database? This will DELETE ALL DATA! (yes/no): ")
    if confirm.lower() == 'yes':
        from db import Base, engine
        Base.metadata.drop_all(engine)
        init_db()
        print("✅ Database reset successfully!")
    else:
        print("❌ Reset cancelled")

def main():
    if len(sys.argv) < 2:
        print("\n🤖 Champak Chacha Admin Tool")
        print("\nUsage: python admin.py <command>")
        print("\nAvailable commands:")
        print("  stats        - Show database statistics")
        print("  questions    - List all questions")
        print("  resources    - List all resources")
        print("  reset        - Reset database (CAUTION)")
        print("  init         - Initialize database tables")
        return
    
    command = sys.argv[1].lower()
    
    if command == "stats":
        show_stats()
    elif command == "questions":
        list_questions()
    elif command == "resources":
        list_resources()
    elif command == "reset":
        reset_database()
    elif command == "init":
        init_db()
        print("✅ Database initialized!")
    else:
        print(f"❌ Unknown command: {command}")

if __name__ == "__main__":
    main()
