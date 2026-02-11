"""Shared utilities: logging, delays, and retry logic."""

import asyncio
import functools
import logging
import random
import sys
from pathlib import Path


def setup_logging(verbose: bool = False) -> logging.Logger:
    """Configure console + file logging. Returns the root project logger."""
    logger = logging.getLogger("hmha")
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)

    # Console handler with color-coded level
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.DEBUG if verbose else logging.INFO)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
    console.setFormatter(fmt)
    logger.addHandler(console)

    # File handler for full debug log
    log_dir = Path("data")
    log_dir.mkdir(exist_ok=True)
    file_handler = logging.FileHandler(log_dir / "session.log", mode="a")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    )
    logger.addHandler(file_handler)

    return logger


async def random_delay(min_seconds: float = 2.0, max_seconds: float = 5.0) -> None:
    """Sleep for a random duration to mimic human pacing."""
    delay = random.uniform(min_seconds, max_seconds)
    await asyncio.sleep(delay)


def retry_async(max_retries: int = 3, backoff_base: float = 2.0):
    """Decorator: retry an async function with exponential backoff.

    Usage:
        @retry_async(max_retries=3)
        async def flaky_call():
            ...
    """
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            last_error = None
            for attempt in range(max_retries):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    last_error = e
                    if attempt < max_retries - 1:
                        wait = backoff_base ** attempt
                        logging.getLogger("hmha").warning(
                            f"{func.__name__} attempt {attempt + 1} failed: {e}. "
                            f"Retrying in {wait:.1f}s..."
                        )
                        await asyncio.sleep(wait)
            raise last_error  # type: ignore[misc]
        return wrapper
    return decorator
