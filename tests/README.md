# tests

No dependencies beyond python3 (and chromium for the browser tests).

    python3 tests/test_signaling.py    # local server: http serving + websocket relay
    python3 tests/test_browser.py      # real browser: display <-> client over the local server
    python3 tests/test_browser.py --trackers
                                       # also check the public-tracker fallback (needs
                                       # internet; tracker peering can take ~60s)

`test_browser.py` drives headless chromium over the DevTools protocol and loads
`page.html`, which runs both roles (display and screen-sharing client) in one
page against a fake camera.
