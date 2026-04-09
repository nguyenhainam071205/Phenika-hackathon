import os
from openai import OpenAI
import httpx
from dotenv import load_dotenv

load_dotenv('RAG1_DEV_HANDOFF/.env')
token = os.getenv('GITHUB_TOKEN')

client = OpenAI(
    base_url='https://models.github.ai/inference',
    api_key=token
)
try:
    response = client.chat.completions.with_raw_response.create(
        model='openai/gpt-4o-mini',
        messages=[{'role': 'user', 'content': 'hello'}],
        max_tokens=10
    )
    print('SUCCESS')
except Exception as e:
    if hasattr(e, 'response') and hasattr(e.response, 'headers'):
        print('Headers:', e.response.headers)
    else:
        print('Error:', e)
