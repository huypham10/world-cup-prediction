"""
Browser-level timezone test.
Verifies that the localizeTimes() JS correctly converts UTC to local time.

2026-06-12T18:00:00Z + UTC+7 (Asia/Bangkok) = 2026-06-13 01:00 local.
"""
from playwright.sync_api import sync_playwright

# Minimal HTML page containing the localizeTimes function from base.html.
# The function is copied here so the test is self-contained and doesn't
# require a running server.
_FIXTURE = """<!DOCTYPE html>
<html><body>
<time id="kickoff" data-utc="2026-06-12T18:00:00+00:00">placeholder</time>
<script>
  const _tz = new Intl.DateTimeFormat([], { timeZoneName: 'short' });
  function tzAbbr(dt) {
    return _tz.formatToParts(dt).find(p => p.type === 'timeZoneName')?.value ?? '';
  }
  document.querySelectorAll('time[data-utc]').forEach(el => {
    const dt = new Date(el.getAttribute('data-utc'));
    const time = dt.toLocaleString([], { hour: '2-digit', minute: '2-digit' });
    const date = dt.toLocaleString([], { weekday: 'short', day: 'numeric', month: 'short' });
    el.textContent = date + ' · ' + time + ' ' + tzAbbr(dt);
  });
</script>
</body></html>"""


def test_utc_displays_as_gmt_plus_7():
    """2026-06-12T18:00 UTC must display as Jun 13 · 01:00 in Asia/Bangkok (UTC+7)."""
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(timezone_id="Asia/Bangkok")
        page = context.new_page()
        page.set_content(_FIXTURE)

        text = page.locator("#kickoff").inner_text()

        assert "13" in text, f"Expected date to show June 13, got: {text!r}"
        assert "01:00" in text, f"Expected time to show 01:00, got: {text!r}"

        context.close()
        browser.close()
