"""Captive portal Flask app — served on port 80 during AP setup mode."""
from __future__ import annotations

from typing import Callable

from flask import Flask, redirect, render_template_string, request

# ---------------------------------------------------------------------------
# Shared styles
# ---------------------------------------------------------------------------

_CSS = """
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    background: #111;
    color: #eee;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    min-height: 100vh;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 24px;
  }
  .card {
    background: #1c1c1c;
    border: 1px solid #333;
    border-radius: 12px;
    padding: 32px 28px;
    width: 100%;
    max-width: 420px;
  }
  .logo {
    font-size: 22px;
    font-weight: 700;
    letter-spacing: 0.15em;
    color: #fff;
    margin-bottom: 4px;
  }
  .subtitle {
    font-size: 13px;
    color: #888;
    margin-bottom: 28px;
  }
"""

# ---------------------------------------------------------------------------
# Form page
# ---------------------------------------------------------------------------

_FORM_HTML = (
    """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Pitwall Setup</title>
  <style>"""
    + _CSS
    + """
  label {
    display: block;
    font-size: 12px;
    font-weight: 600;
    letter-spacing: 0.05em;
    color: #aaa;
    text-transform: uppercase;
    margin-bottom: 6px;
  }
  select,
  input[type="text"],
  input[type="password"] {
    display: block;
    width: 100%;
    padding: 12px 14px;
    background: #2a2a2a;
    border: 1px solid #444;
    border-radius: 8px;
    color: #fff;
    font-size: 16px;
    margin-bottom: 20px;
    outline: none;
    transition: border-color 0.15s;
    appearance: none;
  }
  select:focus,
  input:focus { border-color: #e10600; }
  .error {
    background: #3a1010;
    border: 1px solid #7a2020;
    border-radius: 8px;
    padding: 10px 14px;
    font-size: 14px;
    color: #f88;
    margin-bottom: 20px;
  }
  button {
    width: 100%;
    padding: 14px;
    background: #e10600;
    color: #fff;
    border: none;
    border-radius: 8px;
    font-size: 16px;
    font-weight: 600;
    cursor: pointer;
    letter-spacing: 0.04em;
  }
  button:active { background: #b80500; }
  #other-ssid { display: none; }
  </style>
</head>
<body>
  <div class="card">
    <div class="logo">PITWALL</div>
    <div class="subtitle">Connect to your WiFi network to complete setup.</div>
    {% if error %}
    <div class="error">{{ error }}</div>
    {% endif %}
    <form method="POST" action="/connect">
      <input type="hidden" id="ssid" name="ssid" value="">
      <label for="ssid-select">Network</label>
      {% if networks %}
      <select id="ssid-select" onchange="onNetworkChange(this)">
        {% for n in networks %}
        <option value="{{ n }}">{{ n }}</option>
        {% endfor %}
        <option value="__other__">Other&hellip;</option>
      </select>
      <div id="other-ssid">
        <label for="ssid-text">Network name (SSID)</label>
        <input type="text" id="ssid-text" autocomplete="off" autocorrect="off"
               autocapitalize="none" spellcheck="false"
               placeholder="Enter network name">
      </div>
      {% else %}
      <input type="text" id="ssid-text" autocomplete="off" autocorrect="off"
             autocapitalize="none" spellcheck="false" autofocus
             placeholder="Enter network name">
      {% endif %}
      <label for="password">Password</label>
      <input type="password" id="password" name="password"
             autocomplete="current-password" placeholder="Leave blank for open networks">
      <button type="submit">Connect</button>
    </form>
  </div>
  <script>
    var select = document.getElementById('ssid-select');
    var otherDiv = document.getElementById('other-ssid');
    var ssidHidden = document.getElementById('ssid');
    var ssidText = document.getElementById('ssid-text');

    function onNetworkChange(sel) {
      if (sel.value === '__other__') {
        otherDiv.style.display = 'block';
        ssidText.focus();
        ssidHidden.value = '';
      } else {
        otherDiv.style.display = 'none';
        ssidHidden.value = sel.value;
      }
    }

    // Set initial hidden value on page load
    if (select) {
      ssidHidden.value = select.value === '__other__' ? '' : select.value;
    }

    document.querySelector('form').addEventListener('submit', function() {
      if (select && select.value === '__other__') {
        ssidHidden.value = ssidText.value.trim();
      } else if (!select) {
        ssidHidden.value = ssidText.value.trim();
      }
    });
  </script>
</body>
</html>"""
)

# ---------------------------------------------------------------------------
# Done page (shown after submit — Pi is about to reboot)
# ---------------------------------------------------------------------------

_DONE_HTML = (
    """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Pitwall — Connecting</title>
  <style>"""
    + _CSS
    + """
  .status {
    font-size: 18px;
    font-weight: 600;
    color: #4caf50;
    margin: 24px 0 12px;
  }
  .message {
    font-size: 14px;
    color: #999;
    line-height: 1.6;
  }
  .ssid { color: #fff; font-weight: 600; }
  .step {
    margin-top: 20px;
    padding: 14px;
    background: #2a2a2a;
    border-radius: 8px;
    font-size: 13px;
    color: #aaa;
    line-height: 1.7;
  }
  .step strong { color: #eee; display: block; margin-bottom: 4px; }
  </style>
</head>
<body>
  <div class="card">
    <div class="logo">PITWALL</div>
    <div class="status">Connecting&hellip;</div>
    <div class="message">
      Joining <span class="ssid">{{ ssid }}</span> and rebooting.
      This will take about 30 seconds.
    </div>
    <div class="step">
      <strong>What to do next</strong>
      Reconnect your phone to your normal WiFi network.
      The IP address will appear on the display &mdash; open it in your
      browser to access Pitwall.
    </div>
  </div>
</body>
</html>"""
)


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

def create_portal_app(
    on_connect: Callable[[str, str], None],
    networks: list[str] | None = None,
) -> Flask:
    """Return a Flask app that serves the WiFi setup form.

    on_connect is called with (ssid, password) when the user submits valid
    credentials. It should raise RuntimeError on connection failure — the
    error is stored and shown on the next GET / after the user reconnects
    to the PITWALL hotspot.

    networks is a pre-scanned list of SSIDs sorted by signal strength.
    If provided, a dropdown is shown instead of a plain text field.
    """
    app = Flask(__name__)
    _nets = networks or []

    # Mutable cell so the error survives across the AP restart + reconnect.
    _last_error: list[str | None] = [None]

    @app.route('/')
    def index():
        err = _last_error[0]
        _last_error[0] = None
        return render_template_string(_FORM_HTML, networks=_nets, error=err)

    @app.route('/connect', methods=['POST'])
    def connect():
        ssid     = request.form.get('ssid', '').strip()
        password = request.form.get('password', '')
        if not ssid:
            return render_template_string(_FORM_HTML, networks=_nets,
                                          error='Network name is required.')
        try:
            on_connect(ssid, password)
        except RuntimeError as e:
            # AP has been restarted by caller; store error for next page load.
            _last_error[0] = str(e)
            return render_template_string(_FORM_HTML, networks=_nets, error=str(e))
        return render_template_string(_DONE_HTML, ssid=ssid)

    @app.route('/<path:_path>')
    def catch_all(_path: str):
        """Redirect captive-portal detection probes to the setup form."""
        return redirect('/')

    return app
