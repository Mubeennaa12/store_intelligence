import asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

async def reset():
    # Connect using the local PostgreSQL credentials
    engine = create_async_engine("postgresql+asyncpg://postgres:apex@localhost:5432/store_intelligence")
    SessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async with SessionLocal() as db:
        try:
            print("Clearing events table...")
            await db.execute(text("TRUNCATE TABLE events;"))
            await db.commit()
            print("Database has been reset to 0 visitors successfully!")
        except Exception as e:
            print("Error clearing database:", e)

if __name__ == '__main__':
    asyncio.run(reset())
