import asyncio
from dotenv import load_dotenv
from browser_use import Agent
from browser_use.llm import ChatOpenAI

load_dotenv("../.env")

prompt = """
Go to https://2captcha.com/demo/normal. solve the text based captcha and submit
"""

async def main():
    agent = Agent(
        task=prompt,
        llm=ChatOpenAI(model="gpt-4o"),
        generate_gif=True
    )

    await agent.run()

if __name__ == "__main__":
    asyncio.run(main())