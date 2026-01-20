import asyncio
import sys
import re
from playwright.async_api import async_playwright

async def run(url):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()

        found_url = None
        event = asyncio.Event()

        # Listen for network requests
        async def handle_request(request):
            nonlocal found_url
            # Looking for m3u8 or mp4 files, usually with 'master' or 'playlist' in the name
            if (".m3u8" in request.url or ".mp4" in request.url) and not found_url:
                # Filter out obvious ads or tracking if necessary
                if "master.m3u8" in request.url or "playlist.m3u8" in request.url or ".mp4" in request.url:
                    found_url = request.url
                    event.set()

        page.on("request", handle_request)

        try:
            # We use a longer timeout because these sites can be slow/heavy
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)

            embed_link = page.locator('.getEmbed a')
            # Click the embed link if it exists
            if await embed_link.count() > 0:
                await embed_link.click()
                # Wait for navigation to complete
                await page.wait_for_load_state('domcontentloaded', timeout=60000)
            else:
                print("No embed link found on the page.")

            # Wait for the URL to be captured or timeout after 30 seconds
            try:
                await asyncio.wait_for(event.wait(), timeout=30)
            except asyncio.TimeoutError:
                print("Timeout: Could not capture m3u8/mp4 URL automatically.")

        except Exception as e:
            print(f"Error during extraction: {e}")
        finally:
            await browser.close()

        return found_url

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python extract_3esk.py <URL>")
        sys.exit(1)

    captured = asyncio.run(run(sys.argv[1]))
    if captured:
        print(f"Captured URL: {captured}")
    else:
        sys.exit(1)
