"""Capture genuine screenshots from the running Streamlit app and FastAPI service.

The script does not mock the UI or the API. It drives the real browser UI, runs real
deterministic audits, captures full-page screenshots, and removes the temporary audits it
created where the API supports deletion. The bundled data is fictional synthetic demo data.

Prerequisites:
    python -m pip install -e ".[screenshots]"
    python -m playwright install chromium
    uvicorn backend.app:app --host 0.0.0.0 --port 8000
    streamlit run frontend/app.py --server.address 0.0.0.0 --server.port 8501
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FULL_PAGE_CSS = """
() => {
  const style = document.createElement('style');
  style.id = 'screenshot-full-page';
  style.textContent = `
    html, body, #root,
    [data-testid="stApp"],
    [data-testid="stAppViewContainer"],
    [data-testid="stMain"] {
      height: auto !important;
      min-height: 100vh !important;
      max-height: none !important;
      overflow: visible !important;
    }
    [data-testid="stMain"] > div { overflow: visible !important; }
  `;
  document.head.appendChild(style);
}
"""


def _api_headers() -> dict[str, str]:
    token = (os.getenv("API_ACCESS_TOKEN") or "").strip()
    return {"Authorization": f"Bearer {token}"} if token else {}


def _api_url(api_base: str, path: str) -> str:
    return f"{api_base.rstrip('/')}{path}"


def _delete_audits(api_base: str, audit_ids: list[int]) -> None:
    headers = _api_headers()
    for audit_id in sorted(set(audit_ids)):
        try:
            response = requests.delete(
                _api_url(api_base, f"/api/audits/{audit_id}"),
                headers=headers,
                timeout=15,
            )
            if response.ok:
                print(f"Cleaned up temporary audit #{audit_id}")
        except requests.RequestException:
            print(f"Warning: could not clean up temporary audit #{audit_id}")


def _audit_ids_from_text(text: str) -> list[int]:
    return sorted(
        {
            int(value)
            for value in re.findall(
                r"(?:audit\s*#|saved as\s*#|audit\s+#?)(\d+)", text, re.I
            )
        }
    )


def _trim_bottom(path: Path, padding: int = 44) -> None:
    """Remove the uniform background tail left by forced full-page viewport sizing."""
    try:
        import numpy as np
        from PIL import Image
    except ImportError:
        return
    image = Image.open(path).convert("RGB")
    pixels = np.asarray(image)
    height, width = pixels.shape[:2]
    if height < 300:
        return
    # Ignore the fixed sidebar: its vertical gradient differs slightly on every row.
    main_left = min(320, width - 1)
    reference = np.median(pixels[-16:, main_left:].astype(np.int16), axis=0)
    row_difference = np.abs(
        pixels[:, main_left:].astype(np.int16) - reference[None, :, :]
    ).max(axis=2)
    content_rows = np.flatnonzero((row_difference > 12).any(axis=1))
    if content_rows.size == 0:
        return
    bottom = min(height, int(content_rows[-1]) + padding)
    if bottom < height - 8:
        image.crop((0, 0, width, bottom)).save(path, optimize=True)


def _capture(page, output: Path, name: str) -> None:
    page.evaluate(FULL_PAGE_CSS)
    page.wait_for_timeout(900)
    height = page.evaluate(
        """() => {
          const main = document.querySelector('[data-testid="stMain"]');
          return Math.max(
            main ? main.scrollHeight : 0,
            document.body ? document.body.scrollHeight : 0,
            1200
          );
        }"""
    )
    height = min(int(height) + 120, 9000)
    page.set_viewport_size({"width": 1440, "height": height})
    page.evaluate("window.scrollTo(0, 0)")
    page.wait_for_timeout(450)
    path = output / name
    page.screenshot(path=str(path), full_page=True)
    _trim_bottom(path)
    if not path.is_file() or path.stat().st_size < 15_000:
        raise RuntimeError(f"Screenshot is missing or unexpectedly small: {path}")
    print(f"Captured {path} ({path.stat().st_size:,} bytes)")


def _navigate(page, name: str) -> None:
    # Streamlit 1.66 renders a hidden radio input with a visible react-aria label.
    # Click the visible sidebar label rather than the input element.
    sidebar = page.get_by_test_id("stSidebar")
    target = sidebar.get_by_text(name, exact=True)
    if target.count():
        target.first.click()
    else:
        page.get_by_text(name, exact=True).first.click()
    page.wait_for_timeout(1600)


def _fill_textarea(page, label: str, value: str, index: int | None = None) -> None:
    field = page.get_by_label(label, exact=False)
    if field.count():
        field.first.fill(value)
        return
    if index is None:
        raise RuntimeError(f"Could not find textarea labelled {label!r}")
    page.locator("textarea").nth(index).fill(value)


def _select_option(page, label: str, value: str) -> None:
    combobox = page.get_by_role("combobox", name=label)
    if not combobox.count():
        combobox = page.get_by_label(label, exact=False)
    combobox.first.click()
    page.wait_for_timeout(250)
    page.keyboard.type(value)
    page.wait_for_timeout(350)
    option = page.get_by_role("option", name=value, exact=True)
    if option.count():
        option.first.click()
    else:
        page.keyboard.press("Enter")
    # Multiselects keep the popover open after a selection; close it so the form
    # buttons are no longer covered by the overlay.
    page.keyboard.press("Escape")
    page.wait_for_timeout(600)


def _capture_single_audit(page, output: Path, api_base: str) -> None:
    _navigate(page, "Single Audit")
    page.get_by_role("heading", name="Single Response Audit").wait_for(timeout=30_000)
    _fill_textarea(page, "Case ID", "SCREENSHOT-ORDER-STATUS")
    _select_option(page, "Category", "order_status")
    _fill_textarea(
        page,
        "Customer message",
        "Hi, my order ORD-88231 was expected three days ago. Where is it now, "
        "and when should I expect delivery?",
        index=0,
    )
    _fill_textarea(
        page,
        "Candidate response to audit",
        "I'm sorry your order is late. I checked the shipment record for ORD-88231: it is "
        "in transit, and the carrier's latest estimate is October 21. You can track it with "
        "TRK-88231 on the carrier website. If the tracking has not updated by October 22, "
        "reply here and I will open a trace with the carrier for you.",
        index=1,
    )
    _fill_textarea(
        page,
        "Facts JSON",
        '{"order_id":"ORD-88231","order_status":"shipped",'
        '"tracking_number":"TRK-88231","expected_delivery":"2026-10-21"}',
        index=2,
    )
    _fill_textarea(
        page,
        "Expected actions",
        "acknowledge delay; share tracking number; provide delivery date",
        index=3,
    )
    _select_option(page, "Policy scope", "shipping_policy")
    page.get_by_role("button", name="Audit response").click()
    page.get_by_text("Audit complete", exact=False).wait_for(timeout=90_000)
    page.wait_for_timeout(900)
    completion = page.get_by_text("Audit complete", exact=False).first.inner_text()
    _capture(page, output, "single-audit.png")
    _delete_audits(api_base, _audit_ids_from_text(completion))


def _capture_batch(page, output: Path, api_base: str) -> None:
    _navigate(page, "Batch Auditor")
    page.get_by_role("heading", name="Batch Auditor").wait_for(timeout=30_000)
    _capture(page, output, "batch-auditor.png")

    batch_id = f"screenshot-benchmark-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}"
    field = page.get_by_label("Benchmark batch ID", exact=False)
    if field.count():
        field.first.fill(batch_id)
    page.get_by_role("button", name="Run full synthetic benchmark").click()
    page.get_by_text("Batch finished.", exact=False).wait_for(timeout=180_000)
    page.wait_for_timeout(1400)
    _capture(page, output, "batch-results.png")
    try:
        response = requests.get(
            _api_url(api_base, f"/api/batches/{batch_id}"),
            headers=_api_headers(),
            timeout=20,
        )
        if response.ok:
            ids = [
                row["audit_id"]
                for row in response.json().get("audits", [])
                if row.get("audit_id")
            ]
            _delete_audits(api_base, ids)
        else:
            print("Warning: could not look up temporary benchmark batch for cleanup")
    except requests.RequestException:
        print("Warning: could not look up temporary benchmark batch for cleanup")


def _capture_human_review(page, output: Path) -> None:
    _navigate(page, "Human Review")
    page.get_by_role("heading", name="Human Review Workspace").wait_for(timeout=30_000)
    _select_option(page, "Hard stop", "yes")
    page.wait_for_timeout(1400)
    page.get_by_text("This audit triggered a hard stop", exact=False).wait_for(timeout=30_000)
    _capture(page, output, "human-review.png")


def _capture_model_comparison(page, output: Path, api_base: str) -> None:
    _navigate(page, "Model Comparison")
    page.get_by_role("heading", name="Model Comparison").wait_for(timeout=30_000)
    page.get_by_role("button", name="Audit both responses").click()
    # The results section uses the shared styled section title, not an HTML heading.
    page.get_by_text("Results", exact=True).first.wait_for(timeout=90_000)
    page.get_by_text("Score difference", exact=False).first.wait_for(timeout=30_000)
    page.wait_for_timeout(1000)
    _capture(page, output, "model-comparison.png")
    _delete_audits(api_base, _audit_ids_from_text(page.locator("body").inner_text()))


def _capture_settings(page, output: Path) -> None:
    _navigate(page, "Settings")
    page.get_by_role("heading", name="Settings").wait_for(timeout=30_000)
    provider_tab = page.get_by_role("tab", name="Providers & models")
    if provider_tab.count():
        provider_tab.first.click()
        page.wait_for_timeout(800)
    ollama_tab = page.get_by_role("tab", name="Local Ollama")
    if ollama_tab.count():
        ollama_tab.first.click()
        page.wait_for_timeout(900)
    _capture(page, output, "settings-providers.png")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8501")
    parser.add_argument("--api-base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--output", type=Path, default=ROOT / "docs" / "images")
    parser.add_argument("--headed", action="store_true", help="show the browser while capturing")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise SystemExit(
            "Install the screenshot extra: python -m pip install -e '.[screenshots]'"
        ) from exc

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=not args.headed)
        page = browser.new_page(viewport={"width": 1440, "height": 1200}, device_scale_factor=1)
        page.goto(args.base_url, wait_until="domcontentloaded", timeout=60_000)
        page.get_by_text("Policy-grounded QA", exact=False).first.wait_for(timeout=60_000)
        page.wait_for_timeout(2200)

        _capture(page, args.output, "overview.png")

        _capture_single_audit(page, args.output, args.api_base_url)
        _capture_batch(page, args.output, args.api_base_url)

        _navigate(page, "Scenario Explorer")
        page.get_by_role("heading", name="Scenario Explorer").wait_for(timeout=30_000)
        page.wait_for_timeout(900)
        _capture(page, args.output, "scenario-explorer.png")

        _navigate(page, "Policy Manager")
        page.get_by_role("heading", name="Policy Manager").wait_for(timeout=30_000)
        page.wait_for_timeout(900)
        _capture(page, args.output, "policy-manager.png")

        _navigate(page, "Escalation Intelligence")
        page.get_by_role("heading", name="Escalation Intelligence").wait_for(timeout=30_000)
        page.wait_for_timeout(900)
        _capture(page, args.output, "escalation-intelligence.png")

        _capture_human_review(page, args.output)
        _capture_model_comparison(page, args.output, args.api_base_url)

        _navigate(page, "Analytics & Reports")
        page.get_by_role("heading", name="Analytics & Reports").wait_for(timeout=30_000)
        page.wait_for_timeout(1200)
        _capture(page, args.output, "analytics.png")

        _capture_settings(page, args.output)
        browser.close()

    print("All screenshots captured from the running app.")


if __name__ == "__main__":
    main()
