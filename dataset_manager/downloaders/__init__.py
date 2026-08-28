from typing import Optional
from .base import BaseDownloader
from .huggingface import HuggingFaceDownloader
from .http import HttpDownloader
from .firecrawl import FirecrawlDownloader
from .stream import StreamDownloader

def get_downloader(name: str) -> Optional[BaseDownloader]:
    name = name.lower()
    if name == 'huggingface':
        return HuggingFaceDownloader()
    elif name == 'http':
        return HttpDownloader()
    elif name == 'firecrawl':
        return FirecrawlDownloader()
    elif name == 'stream':
        return StreamDownloader()
    # Add more downloaders here in the future:
    # elif name == 'git':
    #     return GitDownloader()
    
    return None
