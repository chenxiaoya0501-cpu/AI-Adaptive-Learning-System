"""List paper filenames"""
import asyncio
from app.database import async_session
from sqlalchemy import select
from app.models.question import ExamPaper

async def main():
    async with async_session() as db:
        result = await db.execute(select(ExamPaper))
        for p in result.scalars():
            print(f"{p.id}: {p.title} -> {p.stored_filename}")

asyncio.run(main())
