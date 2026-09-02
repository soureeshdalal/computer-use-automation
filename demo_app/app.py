"""Legacy-style credit union member servicing console (fictional data only)."""

from __future__ import annotations

import os
from dataclasses import dataclass

from flask import Flask, redirect, render_template_string, request, session, url_for

HOST = os.getenv("DEMO_APP_HOST", "127.0.0.1")
PORT = int(os.getenv("DEMO_APP_PORT", "8765"))

MEMBERS: dict[str, dict[str, str]] = {
    "12345": {
        "name": "Alex Rivera",
        "savings_balance": "$1,204.33",
        "checking_balance": "$842.10",
        "status": "active",
    },
    "54321": {
        "name": "Jordan Lee",
        "savings_balance": "$2,481.55",
        "checking_balance": "$120.00",
        "status": "active",
    },
    "77777": {
        "name": "Sam Patel",
        "savings_balance": "$0.00",
        "checking_balance": "$0.00",
        "status": "restricted",
    },
    "42424": {
        "name": "Casey Morgan",
        "savings_balance": "$900.00",
        "checking_balance": "$300.00",
        "status": "review_hold",
    },
}

BASE_STYLE = """
<style>
  body { font-family: Tahoma, Arial, sans-serif; background: #ece9d8; margin: 0; }
  .banner { background: #003366; color: white; padding: 8px 16px; font-size: 14px; }
  .frame { margin: 12px; border: 2px inset #ccc; background: white; padding: 12px; }
  table.legacy { border-collapse: collapse; width: 100%; font-size: 13px; }
  table.legacy td, table.legacy th { border: 1px solid #999; padding: 6px 8px; }
  table.legacy th { background: #d4d0c8; text-align: left; }
  input, select, button { font-family: Tahoma, Arial, sans-serif; font-size: 13px; }
  .error { color: #8b0000; font-weight: bold; }
  .notice { background: #ffffcc; border: 1px solid #cccc66; padding: 8px; margin-top: 8px; }
  .modal-backdrop { position: fixed; inset: 0; background: rgba(0,0,0,0.35); }
  .modal { position: fixed; top: 30%; left: 30%; width: 40%; background: #ffffe1; border: 2px outset #666; padding: 16px; }
</style>
"""

LOGIN_PAGE = BASE_STYLE + """
<div class="banner">NorthStar CU | Member Servicing Console v4.2</div>
<form class="frame" method="post">
  <table class="legacy"><tr><th colspan="2">Operator Sign-In</th></tr>
  <tr><td>Operator ID</td><td><input name="operator_id" aria-label="Operator ID" value="ops001"></td></tr>
  <tr><td>Password</td><td><input name="password" type="password" aria-label="Password"></td></tr>
  <tr><td colspan="2"><button type="submit">Sign In</button></td></tr></table>
  {% if error %}<p class="error">{{ error }}</p>{% endif %}
</form>
"""

HOME_PAGE = BASE_STYLE + """
<div class="banner">NorthStar CU | Member Servicing Console v4.2 | Operator: {{ operator }}</div>
<form class="frame" method="post">
  <table class="legacy">
    <tr><th colspan="2">Member Lookup</th></tr>
    <tr>
      <td>Member Number</td>
      <td><input name="member_id" aria-label="Member Number" value="{{ member_id or '' }}"></td>
    </tr>
    <tr><td colspan="2"><button type="submit">Search Member Records</button></td></tr>
  </table>
  {% if error %}<p class="error">{{ error }}</p>{% endif %}
</form>
"""

DETAIL_PAGE = BASE_STYLE + """
<div class="banner">NorthStar CU | Member Servicing Console v4.2 | Operator: {{ operator }}</div>
<div class="frame">
  <h3 style="margin-top:0;">Member Details</h3>
  <table class="legacy">
    <tr><th>Field</th><th>Value</th></tr>
    <tr><td>Member Number</td><td>{{ member_id }}</td></tr>
    <tr><td>Member Name</td><td>{{ name }}</td></tr>
    <tr><td>Savings Balance</td><td id="savings-balance">{{ savings_balance }}</td></tr>
    <tr><td>Checking Balance</td><td>{{ checking_balance }}</td></tr>
    <tr><td>Status</td><td>{{ status }}</td></tr>
  </table>
  <p><a href="{{ url_for('home') }}">Back to lookup</a></p>
</div>
{% if show_dialog %}
<form method="post">
  <div class="modal-backdrop"></div>
  <div class="modal" role="dialog" aria-label="Session Notice">
    <p><strong>Session Notice</strong></p>
    <p>This member record requires operator acknowledgment before balances display.</p>
    <button type="submit" name="ack" value="1">Acknowledge and Continue</button>
  </div>
</form>
{% endif %}
"""

PERMISSION_PAGE = BASE_STYLE + """
<div class="banner">NorthStar CU | Member Servicing Console v4.2</div>
<div class="frame">
  <p class="error">Access restricted for this operator profile.</p>
  <p>Permission denied for member servicing on restricted accounts.</p>
</div>
"""


@dataclass
class AppState:
    slow_member: str | None = None


state = AppState()


def create_app() -> Flask:
    app = Flask(__name__)
    app.secret_key = "demo-only-not-for-production"

    @app.get("/")
    def root():
        if not session.get("operator"):
            return redirect(url_for("login"))
        return redirect(url_for("home"))

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            password = request.form.get("password", "")
            if password != "demo":
                return render_template_string(
                    LOGIN_PAGE, error="Invalid credentials. Use password demo."
                )
            session["operator"] = request.form.get("operator_id", "ops001")
            return redirect(url_for("home"))
        return render_template_string(LOGIN_PAGE, error=None)

    @app.route("/home", methods=["GET", "POST"])
    def home():
        if not session.get("operator"):
            return redirect(url_for("login"))
        member_id = request.form.get("member_id", "").strip()
        if request.method == "POST" and member_id:
            if member_id == "99999":
                return render_template_string(
                    HOME_PAGE,
                    operator=session["operator"],
                    member_id=member_id,
                    error="No record found for the member number entered.",
                )
            if member_id not in MEMBERS:
                return render_template_string(
                    HOME_PAGE,
                    operator=session["operator"],
                    member_id=member_id,
                    error="No record found for the member number entered.",
                )
            member = MEMBERS[member_id]
            if member["status"] == "restricted":
                return render_template_string(PERMISSION_PAGE), 403
            if member_id == state.slow_member:
                import time

                time.sleep(2)
            return redirect(url_for("member_detail", member_id=member_id))
        return render_template_string(
            HOME_PAGE, operator=session["operator"], member_id="", error=None
        )

    @app.route("/member/<member_id>", methods=["GET", "POST"])
    def member_detail(member_id: str):
        if not session.get("operator"):
            return redirect(url_for("login"))
        member = MEMBERS.get(member_id)
        if not member:
            return render_template_string(
                HOME_PAGE,
                operator=session.get("operator", ""),
                member_id=member_id,
                error="No record found for the member number entered.",
            )
        show_dialog = member["status"] == "review_hold" and not session.get(
            f"ack_{member_id}"
        )
        if request.method == "POST" and request.form.get("ack"):
            session[f"ack_{member_id}"] = True
            show_dialog = False
        return render_template_string(
            DETAIL_PAGE,
            operator=session["operator"],
            member_id=member_id,
            name=member["name"],
            savings_balance=member["savings_balance"],
            checking_balance=member["checking_balance"],
            status=member["status"],
            show_dialog=show_dialog,
        )

    return app


def main() -> None:
    app = create_app()
    app.run(host=HOST, port=PORT, debug=False, threaded=True)


if __name__ == "__main__":
    main()
