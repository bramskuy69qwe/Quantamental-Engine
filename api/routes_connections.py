"""
API routes for 3rd-party data connections management.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Form
from fastapi.responses import HTMLResponse

from core.connections import connections_manager, KNOWN_PROVIDERS

log = logging.getLogger("routes_connections")

router = APIRouter(tags=["connections"])


@router.get("/fragments/connections")
async def list_connections_fragment():
    """HTMX fragment: connection list for the config page."""
    configured = connections_manager.list_connections()
    configured_providers = {c["provider"] for c in configured}

    # Merge known providers (show unconfigured ones as empty slots)
    items = list(configured)
    for kp in KNOWN_PROVIDERS:
        if kp["provider"] not in configured_providers:
            items.append({
                "provider":     kp["provider"],
                "label":        kp["label"],
                "api_key_hint": "",
                "is_active":    0,
                "has_key":      False,
            })

    rows_html = []
    for item in items:
        provider = item["provider"]
        label = item["label"]
        has_key = item.get("has_key", False)
        hint = item.get("api_key_hint", "")

        if has_key:
            badge = '<span class="badge badge-green">Connected</span>'
            key_display = f'<span style="font-family:var(--font-mono);font-size:.7rem;">{hint}</span>'
            actions = (
                f'<button class="btn btn-ghost btn-sm" '
                f'hx-post="/connections/{provider}/test" '
                f'hx-target="#conn-msg-{provider}" hx-swap="innerHTML">Test</button>'
                f'<button class="btn btn-ghost btn-sm" '
                f'onclick="document.getElementById(\'conn-edit-{provider}\').style.display=\'flex\'"'
                f'>Edit</button>'
                f'<button class="btn btn-ghost btn-sm" style="color:var(--red);" '
                f'hx-delete="/connections/{provider}" '
                f'hx-target="#conn-row-{provider}" hx-swap="outerHTML" '
                f'hx-confirm="Remove {label} connection?">Remove</button>'
            )
        else:
            badge = '<span class="badge badge-muted">Not Set</span>'
            key_display = ""
            actions = ""

        rows_html.append(f'''
        <div id="conn-row-{provider}" class="card" style="padding:12px;margin-bottom:8px;">
          <div style="display:flex;justify-content:space-between;align-items:center;">
            <div>
              <strong style="font-size:.78rem;">{label}</strong>
              {badge}
              {key_display}
            </div>
            <div style="display:flex;gap:4px;align-items:center;">
              {actions}
            </div>
          </div>
          <div id="conn-msg-{provider}" style="font-size:.65rem;color:var(--sub);margin-top:4px;"></div>

          <!-- Edit/Add form (hidden by default) -->
          <div id="conn-edit-{provider}" style="display:{'none' if has_key else 'flex'};flex-direction:column;gap:6px;margin-top:8px;padding-top:8px;border-top:1px solid var(--border);">
            <input type="hidden" name="provider" value="{provider}" form="conn-form-{provider}">
            <input type="hidden" name="label" value="{label}" form="conn-form-{provider}">
            <form id="conn-form-{provider}" hx-post="/connections" hx-target="#connections-list" hx-swap="innerHTML"
                  style="display:flex;gap:6px;align-items:end;">
              <input type="hidden" name="provider" value="{provider}">
              <input type="hidden" name="label" value="{label}">
              <div style="flex:1;">
                <label style="font-size:.65rem;color:var(--sub);">API Key</label>
                <input type="password" name="api_key" placeholder="Enter API key" style="width:100%;height:28px;font-size:.7rem;">
              </div>
              <button type="submit" class="btn btn-sm" style="height:28px;">Save & Test</button>
            </form>
          </div>
        </div>
        ''')

    # Add custom provider form
    rows_html.append('''
    <div class="card" style="padding:12px;margin-top:12px;">
      <strong style="font-size:.75rem;color:var(--sub);">+ Add Provider</strong>
      <form hx-post="/connections" hx-target="#connections-list" hx-swap="innerHTML"
            style="display:flex;gap:6px;align-items:end;margin-top:8px;">
        <div>
          <label style="font-size:.65rem;color:var(--sub);">Provider ID</label>
          <input type="text" name="provider" placeholder="e.g. alphavantage" style="width:120px;height:28px;font-size:.7rem;" required>
        </div>
        <div>
          <label style="font-size:.65rem;color:var(--sub);">Label</label>
          <input type="text" name="label" placeholder="e.g. Alpha Vantage" style="width:140px;height:28px;font-size:.7rem;" required>
        </div>
        <div style="flex:1;">
          <label style="font-size:.65rem;color:var(--sub);">API Key</label>
          <input type="password" name="api_key" placeholder="Enter API key" style="width:100%;height:28px;font-size:.7rem;" required>
        </div>
        <button type="submit" class="btn btn-sm" style="height:28px;">Add</button>
      </form>
    </div>
    <div style="font-size:.62rem;color:var(--muted);margin-top:8px;padding:0 4px;">
      Keys are encrypted at rest with AES-256 (Fernet).
    </div>
    ''')

    return HTMLResponse("\n".join(rows_html))


@router.post("/connections")
async def upsert_connection(
    provider: str = Form(...),
    label: str = Form(...),
    api_key: str = Form(...),
):
    """Add or update a connection, then test it."""
    await connections_manager.upsert(provider, label, api_key)

    # Re-render the full list
    return await list_connections_fragment()


@router.delete("/connections/{provider}")
async def delete_connection(provider: str):
    """Remove a connection."""
    await connections_manager.delete(provider)
    return HTMLResponse("")  # HTMX removes the row via outerHTML swap


@router.post("/connections/{provider}/test")
async def test_connection(provider: str):
    """Test a connection and return status badge."""
    result = await connections_manager.test(provider)
    status = result.get("status", "error")
    msg = result.get("msg", "")

    if status == "ok":
        return HTMLResponse(
            f'<span style="color:var(--green);font-size:.65rem;">&#10003; {msg}</span>'
        )
    return HTMLResponse(
        f'<span style="color:var(--red);font-size:.65rem;">&#10007; {msg}</span>'
    )
