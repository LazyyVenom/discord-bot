from bot import run_bot

if __name__ == "__main__":
    print("🚀 Starting Champak Chacha Discord Bot...")
    try:
        run_bot()
    except KeyboardInterrupt:
        print("\n👋 Bot stopped by user")
    except Exception as e:
        print(f"❌ Error: {e}")