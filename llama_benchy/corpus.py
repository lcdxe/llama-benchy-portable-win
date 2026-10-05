import os
import hashlib
import requests
from pathlib import Path
from typing import Any, Optional

# Bundled offline assets so the tool works with no network access at all.
_ASSETS_DIR = Path(__file__).resolve().parent / "assets"
_BUNDLED_TOKENIZER = _ASSETS_DIR / "gpt2_tokenizer.json"
# Portable ("green") cache: stored next to the program, never on the system drive.
_CACHE_DIR = Path("data") / "cache"


def _book_local_path(book_url: str) -> Optional[str]:
    """Return a local filesystem path if book_url points to an existing file.

    Accepts plain paths (C:\\... or /home/...) and file:// URLs.
    Returns None when the source is not a local file.
    """
    raw = book_url[len("file://"):] if book_url.startswith("file://") else book_url
    # Windows file URL: file:///D:/path -> D:/path
    if (
        raw.startswith("/")
        and len(raw) > 2
        and raw[1].isalpha()
        and raw[2] == ":"
    ):
        raw = raw[1:]
    return raw if os.path.isfile(raw) else None


class LightweightTokenizer:
    def __init__(self, tokenizer: Any):
        self._tokenizer = tokenizer

    @classmethod
    def from_pretrained(cls, name: str) -> "LightweightTokenizer":
        from tokenizers import Tokenizer

        if os.path.isfile(name):
            tokenizer = Tokenizer.from_file(name)
        else:
            tokenizer_json = os.path.join(name, "tokenizer.json")
            if os.path.isdir(name) and os.path.exists(tokenizer_json):
                tokenizer = Tokenizer.from_file(tokenizer_json)
            else:
                tokenizer = Tokenizer.from_pretrained(name)
        return cls(tokenizer)

    def encode(self, text: str, add_special_tokens: bool = False):
        return self._tokenizer.encode(
            text, add_special_tokens=add_special_tokens
        ).ids

    def decode(self, token_ids):
        return self._tokenizer.decode(list(token_ids), skip_special_tokens=False)


class TokenizedCorpus:
    def __init__(self, book_url: str, tokenizer_name: Optional[str], model_name: str):
        self.book_url = book_url
        self.tokenizer = self._get_tokenizer(model_name, tokenizer_name)
        self.tokens = self._load_data()

    def _get_transformers_tokenizer(self, name: str):
        from transformers import AutoTokenizer

        return AutoTokenizer.from_pretrained(
            name,
            use_fast=True,
            trust_remote_code=False,
        )

    def _get_tokenizer(self, model_name: str, tokenizer_name: Optional[str] = None):
        name = tokenizer_name if tokenizer_name else model_name
        lightweight_error = None

        try:
            return LightweightTokenizer.from_pretrained(name)
        except Exception as e:
            lightweight_error = e

        try:
            return self._get_transformers_tokenizer(name)
        except Exception as e:
            print(
                f"Error loading tokenizer '{name}': {e} "
                f"(lightweight tokenizer error: {lightweight_error})"
            )
            if _BUNDLED_TOKENIZER.exists():
                print(f"Falling back to bundled offline gpt2 tokenizer: {_BUNDLED_TOKENIZER}")
                return LightweightTokenizer.from_pretrained(str(_BUNDLED_TOKENIZER))
            print("Falling back to 'gpt2' tokenizer as approximation.")
            try:
                return LightweightTokenizer.from_pretrained("gpt2")
            except Exception:
                return self._get_transformers_tokenizer("gpt2")

    def _load_data(self):
        try:
            # Local file (or file:// URL) - no network needed
            local_path = _book_local_path(self.book_url)
            if local_path is not None:
                print(f"Loading text from local file: {local_path}")
                with open(local_path, "r", encoding="utf-8") as f:
                    return self.tokenizer.encode(f.read(), add_special_tokens=False)

            # Portable ("green") cache next to the program - never on the system drive
            _CACHE_DIR.mkdir(parents=True, exist_ok=True)

            # Generate hash of the URL for the filename
            url_hash = hashlib.md5(self.book_url.encode()).hexdigest()
            cache_file = str(_CACHE_DIR / f"{url_hash}.txt")
            
            if os.path.exists(cache_file):
                print(f"Loading text from cache: {cache_file}")
                with open(cache_file, "r", encoding="utf-8") as f:
                    text = f.read()
            else:
                try:
                    print(f"Downloading book from {self.book_url}...")
                    response = requests.get(self.book_url)
                    response.raise_for_status()
                    text = response.text
                    # Basic cleanup
                    start_idx = text.find("*** START OF THE PROJECT GUTENBERG EBOOK")
                    if start_idx != -1:
                        text = text[start_idx:]
                    
                    # Save to cache
                    with open(cache_file, "w", encoding="utf-8") as f:
                        f.write(text)
                    print(f"Saved text to cache: {cache_file}")
                except Exception as e:
                    data_book = Path("data") / "book.txt"
                    if data_book.exists():
                        print(f"Book download failed ({e}); using local data/book.txt.")
                        with open(data_book, "r", encoding="utf-8") as f:
                            text = f.read()
                    else:
                        raise
                    
            return self.tokenizer.encode(text, add_special_tokens=False)
        except Exception as e:
            print(f"Error downloading or processing book: {e}")
            exit(1)

    def get_tokenizer(self):
        return self.tokenizer

    def get_tokens(self):
        return self.tokens

    def __len__(self):
        return len(self.tokens)
