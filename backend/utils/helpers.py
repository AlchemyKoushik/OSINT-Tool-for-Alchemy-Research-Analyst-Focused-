import re

def clean_text(text: str) -> str:
    """Helper method to remove HTML noise and extra spaces"""
    text = re.sub(r'\s+', ' ', text)
    return text.strip()
