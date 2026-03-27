"""Explore GIF: search for one address, see the subdivision detail."""
import asyncio
import io
from pathlib import Path
from PIL import Image
from playwright.async_api import async_playwright

DOCS_DIR = Path("docs")
BASE_URL = "http://localhost:5173"
SS_TIMEOUT = 60000
ADDRESS = "3104 MOSSDALE"


def build_gif(frames: list[bytes], output: Path, durations: list[int], scale: float = 0.75):
    images = []
    for raw in frames:
        img = Image.open(io.BytesIO(raw)).convert("RGB")
        w, h = img.size
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
        images.append(img)
    images[0].save(
        output, save_all=True, append_images=images[1:],
        duration=durations, loop=0, optimize=True,
    )
    size_kb = output.stat().st_size // 1024
    print(f"  {output.name}: {size_kb} KB, {len(images)} frames")


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1280, "height": 720})

        print("Loading page...")
        await page.goto(BASE_URL, wait_until="networkidle")
        await page.wait_for_timeout(4000)
        for _ in range(30):
            if await page.locator('text=/Loading/').count() == 0:
                break
            await page.wait_for_timeout(500)
        await page.wait_for_timeout(2000)

        frames: list[bytes] = []
        durations: list[int] = []

        # Frame 1: Default map view (hold 1.5s)
        frames.append(await page.screenshot(timeout=SS_TIMEOUT))
        durations.append(1500)
        print(f"  Frame {len(frames)}: default view")

        # Click the search bar
        search = page.locator('input[placeholder*="Search"]')
        await search.click()
        await page.wait_for_timeout(300)
        frames.append(await page.screenshot(timeout=SS_TIMEOUT))
        durations.append(400)

        # Type the address character by character (human pace)
        for i, char in enumerate(ADDRESS):
            await search.press_sequentially(char, delay=0)
            if i % 4 == 3 or i == len(ADDRESS) - 1:
                await page.wait_for_timeout(120)
                frames.append(await page.screenshot(timeout=SS_TIMEOUT))
                durations.append(150)

        # Wait for autocomplete dropdown
        await page.wait_for_timeout(1200)
        frames.append(await page.screenshot(timeout=SS_TIMEOUT))
        durations.append(800)
        print(f"  Frame {len(frames)}: autocomplete showing")

        # Select the first result
        await page.keyboard.press("ArrowDown")
        await page.wait_for_timeout(200)
        frames.append(await page.screenshot(timeout=SS_TIMEOUT))
        durations.append(300)

        await page.keyboard.press("Enter")
        await page.wait_for_timeout(4000)
        frames.append(await page.screenshot(timeout=SS_TIMEOUT))
        durations.append(500)

        # Clear search to show clean view
        await search.fill("")
        await page.keyboard.press("Tab")
        await page.wait_for_timeout(1500)

        # Final frame: parcel selected with detail panel (hold 4s)
        frames.append(await page.screenshot(timeout=SS_TIMEOUT))
        durations.append(4000)
        print(f"  Frame {len(frames)}: parcel selected with detail")

        await browser.close()
        build_gif(frames, DOCS_DIR / "demo_explore.gif", durations)
        print("Done!")


asyncio.run(main())
