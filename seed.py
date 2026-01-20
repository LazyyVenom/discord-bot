"""
Seed the database with sample questions and resources
"""
from db import get_session, add_question, add_resource, init_db

def seed_database():
    init_db()
    session = get_session()
    
    try:
        print("🌱 Seeding database with sample data...")
        
        # Add sample questions
        questions = [
            {
                "title": "Two Sum Problem - Time Complexity",
                "description": "What is the optimal time complexity for the Two Sum problem using a hash map?",
                "category": "DSA",
                "option_a": "O(n²)",
                "option_b": "O(n)",
                "option_c": "O(log n)",
                "option_d": "O(1)",
                "correct_option": "B",
                "difficulty": "easy",
                "points": 10
            },
            {
                "title": "JavaScript Closure",
                "description": "Which statement best describes a closure in JavaScript?",
                "category": "coding",
                "option_a": "A function that returns another function",
                "option_b": "A function that has access to variables from its outer scope",
                "option_c": "A function that closes the browser window",
                "option_d": "A function that cannot be called more than once",
                "correct_option": "B",
                "difficulty": "medium",
                "points": 15
            },
            {
                "title": "REST vs GraphQL",
                "description": "What is the main advantage of GraphQL over REST?",
                "category": "backend",
                "option_a": "GraphQL is faster than REST",
                "option_b": "GraphQL allows clients to request exactly the data they need",
                "option_c": "GraphQL is easier to implement",
                "option_d": "GraphQL doesn't use HTTP",
                "correct_option": "B",
                "difficulty": "medium",
                "points": 15
            },
            {
                "title": "Binary Tree Traversal",
                "description": "In which traversal order do we visit the left subtree, root, then right subtree?",
                "category": "DSA",
                "option_a": "Preorder",
                "option_b": "Postorder",
                "option_c": "Inorder",
                "option_d": "Level-order",
                "correct_option": "C",
                "difficulty": "easy",
                "points": 10
            },
            {
                "title": "Database Indexing",
                "description": "What is the primary purpose of database indexing?",
                "category": "backend",
                "option_a": "To reduce storage space",
                "option_b": "To speed up data retrieval operations",
                "option_c": "To encrypt data",
                "option_d": "To backup data automatically",
                "correct_option": "B",
                "difficulty": "easy",
                "points": 10
            },
            {
                "title": "Hash Table Time Complexity",
                "description": "What is the average time complexity for lookup in a hash table?",
                "category": "DSA",
                "option_a": "O(n)",
                "option_b": "O(log n)",
                "option_c": "O(1)",
                "option_d": "O(n log n)",
                "correct_option": "C",
                "difficulty": "easy",
                "points": 10
            }
        ]
        
        for q in questions:
            add_question(session, **q)
            print(f"  ✅ Added question: {q['title']}")
        
        # Add sample resources
        resources = [
            {
                "title": "LeetCode - Practice DSA",
                "url": "https://leetcode.com",
                "category": "DSA",
                "description": "Best platform to practice data structures and algorithms"
            },
            {
                "title": "MDN Web Docs",
                "url": "https://developer.mozilla.org",
                "category": "frontend",
                "description": "Comprehensive web development documentation"
            },
            {
                "title": "System Design Primer",
                "url": "https://github.com/donnemartin/system-design-primer",
                "category": "backend",
                "description": "Learn how to design large-scale systems"
            },
            {
                "title": "Roadmap.sh",
                "url": "https://roadmap.sh",
                "category": "coding",
                "description": "Developer roadmaps and learning paths"
            },
            {
                "title": "NeetCode",
                "url": "https://neetcode.io",
                "category": "DSA",
                "description": "Curated list of LeetCode problems with video explanations"
            }
        ]
        
        for r in resources:
            add_resource(session, **r)
            print(f"  ✅ Added resource: {r['title']}")
        
        print("\n✨ Database seeded successfully!")
        
    except Exception as e:
        print(f"❌ Error seeding database: {e}")
        session.rollback()
    finally:
        session.close()

if __name__ == "__main__":
    seed_database()
