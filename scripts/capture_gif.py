"""Subdivision GIF: default city view -> slow human-like zoom -> select parcel."""
import asyncio
import io
from pathlib import Path
from PIL import Image
from playwright.async_api import async_playwright

DOCS_DIR = Path("docs")
BASE_URL = "http://localhost:5173"
SS_TIMEOUT = 60000
ADDRESS = "604 OAKWOOD"


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

        # --- OFF-CAMERA SETUP ---
        # Navigate to parcel first, then zoom out so map is centered on the right area
        print("Setup: centering map on target area...")
        await page.goto(BASE_URL, wait_until="networkidle")
        await page.wait_for_timeout(4000)

        search = page.locator('input[placeholder*="Search"]')
        await search.click()
        await search.fill(ADDRESS)
        await page.wait_for_timeout(1500)
        await page.keyboard.press("ArrowDown")
        await page.wait_for_timeout(200)
        await page.keyboard.press("Enter")
        await page.wait_for_timeout(4000)

        # Clear search and close detail panel
        await search.fill("")
        await page.keyboard.press("Tab")
        await page.wait_for_timeout(300)
        btn = page.locator('.hidden.md\\:block button:has-text("✕")')
        if await btn.count() > 0:
            await btn.click()
            await page.wait_for_timeout(300)

        # Zoom way out to city-wide view (centered on parcel area)
        print("Setup: zooming out to city view...")
        await page.mouse.move(640, 360)
        for _ in range(25):
            await page.mouse.wheel(0, 800)
            await page.wait_for_timeout(30)
        await page.wait_for_timeout(3000)
        for _ in range(40):
            if await page.locator('text=/Loading/').count() == 0:
                break
            await page.wait_for_timeout(500)
        await page.wait_for_timeout(2000)

        # --- START RECORDING ---
        print("Recording...")
        frames: list[bytes] = []
        durations: list[int] = []

        # Hold on city overview for 2.5s
        frames.append(await page.screenshot(timeout=SS_TIMEOUT))
        durations.append(2500)
        print(f"  Frame {len(frames)}: city overview")

        # Human-like zoom: 6 gentle scroll steps with pauses between them
        # Each step: small scroll, wait ~400-600ms (human thinking pace), capture
        await page.mouse.move(640, 360)
        scroll_steps = [
            (-120, 500),  # gentle scroll, pause
            (-120, 450),
            (-140, 400),
            (-140, 400),
            (-120, 450),
            (-120, 500),
        ]
        for i, (delta, pause) in enumerate(scroll_steps):
            await page.mouse.wheel(0, delta)
            await page.wait_for_timeout(pause)
            frames.append(await page.screenshot(timeout=SS_TIMEOUT))
            durations.append(pause)

        print(f"  Frame {len(frames)}: zoom settled at neighborhood level")

        # Let map settle after zoom
        await page.wait_for_timeout(1500)
        frames.append(await page.screenshot(timeout=SS_TIMEOUT))
        durations.append(1000)

        # --- Select the parcel (map already centered nearby, minimal fly) ---
        print("Selecting parcel...")
        await search.click()
        await search.fill(ADDRESS)
        await page.wait_for_timeout(1500)
        await page.keyboard.press("ArrowDown")
        await page.wait_for_timeout(200)
        await page.keyboard.press("Enter")
        await page.wait_for_timeout(4000)
        await search.fill("")
        await page.keyboard.press("Tab")
        await page.wait_for_timeout(1500)

        # Final frame: detail panel + proposed subdivision (hold 4s)
        frames.append(await page.screenshot(timeout=SS_TIMEOUT))
        durations.append(4000)
        print(f"  Frame {len(frames)}: parcel selected with subdivision")

        await browser.close()
        build_gif(frames, DOCS_DIR / "demo_subdivision.gif", durations)
        print("Done!")


asyncio.run(main())
