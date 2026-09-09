from __future__ import annotations

import asyncio
from html import escape

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

app = FastAPI(title="Legacy Credit Union Demo")

MEMBERS = {
    "12345": {"name": "Jamie Carter", "status": "Active", "savings": "$4,218.37"},
    "67890": {"name": "Morgan Lee", "status": "Active", "savings": "$925.04"},
    "00000": {"name": "Recovery Test Member", "status": "Active", "savings": "$1,234.56"},
}


def layout(title: str, body: str) -> HTMLResponse:
    return HTMLResponse(
        f"""<!doctype html>
<html>
<head>
<title>{escape(title)} - CU Servicing Console</title>
<style>
body {{ font-family: Arial, sans-serif; background:#ececec; margin:0; color:#111; }}
#header {{ background:#17365d; color:white; padding:12px 18px; font-weight:bold; }}
#shell {{ width:920px; margin:16px auto; background:white; border:1px solid #888; padding:14px; }}
table.legacy {{ border-collapse:collapse; width:100%; }}
table.legacy td, table.legacy th {{ border:1px solid #aaa; padding:8px; }}
.nav a {{ margin-right:14px; }}
.notice {{ border:1px solid #aa7000; background:#fff2cc; padding:10px; margin:10px 0; }}
.error {{ border-color:#a00; background:#f8d7da; }}
.small {{ font-size:12px; color:#555; }}
</style>
</head>
<body>
<div id="header">Regional Credit Union - Internal Servicing Console</div>
<div id="shell">
<div class="nav"><a href="/">Home</a><a href="/members">Member Servicing</a><a href="/reports">Reports</a></div>
<hr>
{body}
</div>
</body></html>"""
    )


@app.get("/", response_class=HTMLResponse)
async def home():
    return layout(
        "Home",
        """
        <h2>Operations Menu</h2>
        <table class="legacy">
          <tr><td><a href="/members">Member Servicing</a></td><td>Search and review member accounts.</td></tr>
          <tr><td><a href="/reports">Reports</a></td><td>Daily operational reports.</td></tr>
        </table>
        """,
    )


@app.get("/members", response_class=HTMLResponse)
async def member_search():
    return layout(
        "Member Search",
        """
        <h2>Member Search</h2>
        <form method="post" action="/members/search">
          <table class="legacy">
            <tr><td><label for="memberNumber">Member ID</label></td><td><input id="memberNumber" name="member_id" type="text" autocomplete="off"></td></tr>
            <tr><td colspan="2"><input type="submit" value="Search Member"></td></tr>
          </table>
        </form>
        <p class="small">Use the member number assigned by core servicing.</p>
        """,
    )


@app.post("/members/search", response_class=HTMLResponse)
async def search_member(request: Request, member_id: str = Form(...)):
    member_id = member_id.strip()

    if not member_id:
        return layout(
            "Member Search",
            '<div class="notice error">Validation error: Member ID is required.</div>',
        )

    if member_id == "40300":
        return layout(
            "Member Search",
            '<div class="notice error">Permission denied for this member record.</div>',
        )

    if member_id == "00000" and request.cookies.get("demo_reauthenticated") != "1":
        return layout(
            "Session Expired",
            """
            <div class="notice error">
                Session expired. Please sign in again.
            </div>

            <form method="post" action="/session/reauthenticate">
                <input type="hidden" name="member_id" value="00000">
                <button type="submit">Re-authenticate Session</button>
            </form>

            <p class="small">
                Human operator intervention is required to restore the existing session.
            </p>
            """,
        )

    if member_id not in MEMBERS:
        return layout(
            "Member Search",
            f'<div class="notice error">No member found for ID {escape(member_id)}.</div>',
        )

    return RedirectResponse(
        url=f"/members/{member_id}",
        status_code=303,
    )

@app.post("/session/reauthenticate")
async def reauthenticate_session(member_id: str = Form(...)):
    member_id = member_id.strip()

    if member_id not in MEMBERS:
        return layout(
            "Re-authentication Failed",
            '<div class="notice error">Unable to restore session for this member.</div>',
        )

    response = RedirectResponse(
        url=f"/members/{member_id}",
        status_code=303,
    )

    response.set_cookie(
        key="demo_reauthenticated",
        value="1",
        httponly=True,
        samesite="lax",
    )

    return response

@app.get("/members/{member_id}", response_class=HTMLResponse)
async def member_detail(member_id: str):
    member = MEMBERS.get(member_id)
    if not member:
        return layout("Member Detail", '<div class="notice error">No member found.</div>')
    return layout(
        "Member Detail",
        f"""
        <h2>Member Detail</h2>
        <table class="legacy">
          <tr><th>Member ID</th><td>{escape(member_id)}</td></tr>
          <tr><th>Name</th><td>{escape(member['name'])}</td></tr>
          <tr><th>Status</th><td>{escape(member['status'])}</td></tr>
        </table>
        <p><a href="/members/{escape(member_id)}/savings">Open Savings Account</a></p>
        """,
    )


@app.get("/members/{member_id}/savings", response_class=HTMLResponse)
async def savings(member_id: str, delay_ms: int = 0):
    if delay_ms:
        await asyncio.sleep(min(delay_ms, 3000) / 1000)
    member = MEMBERS.get(member_id)
    if not member:
        return layout("Savings", '<div class="notice error">No member found.</div>')
    return layout(
        "Savings",
        f"""
        <h2>Savings Account</h2>
        <table class="legacy">
          <tr><th>Member</th><td>{escape(member['name'])}</td></tr>
          <tr><th>Account Type</th><td>Primary Savings</td></tr>
          <tr><th>Savings Balance</th><td><span aria-label="Savings Balance Value">{escape(member['savings'])}</span></td></tr>
        </table>
        <form method="post" action="/members/{escape(member_id)}/suspend">
          <button type="submit">Suspend Account</button>
        </form>
        <p class="small">Suspension is irreversible without supervisor intervention.</p>
        """,
    )


@app.post("/members/{member_id}/suspend", response_class=HTMLResponse)
async def suspend(member_id: str):
    return layout("Suspended", '<div class="notice error">Demo only: suspension endpoint should never be reached by automation.</div>')


@app.get("/reports", response_class=HTMLResponse)
async def reports():
    return layout("Reports", "<h2>Reports</h2><p>No reports are configured in this demo.</p>")
