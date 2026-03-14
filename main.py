import asyncio
import logging
from app.bot import main as bot_main
from app.db import initialize_db

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    initialize_db()
    asyncio.run(bot_main())