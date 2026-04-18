#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import base64
import time
from typing import Any

import requests
from mcp.server.fastmcp import FastMCP, Image

BRIDGE_URL = os.environ.get("OMORI_BRIDGE_URL", "http://127.0.0.1:43111")
VM_BRIDGE_CMD = os.environ.get("OMORI_VM_BRIDGE_CMD", "muvm -i curl -s")

INSTRUCTIONS = (
    "Always read game://state/current before choosing an action. "
    "Always call list_actions before perform_action. "
    "Never invent actions not returned by list_actions. "
    "After each perform_action, call wait_until_idle before reading state again."
)

mcp = FastMCP("omori-e2e", instructions=INSTRUCTIONS)


def _vm_get(path: str) -> Any:
    """Try to reach bridge via VM wrapper."""
    # Pass through common env vars needed by muvm
    env = os.environ.copy()
    # Ensure these are set for muvm
    env.setdefault("XDG_RUNTIME_DIR", "/run/user/1000")
    env.setdefault("HOME", "/home/w")
    env.setdefault("USER", "w")

    cmd = f"{VM_BRIDGE_CMD} http://127.0.0.1:43111{path}"
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=15, env=env
        )
        if result.returncode == 0:
            return json.loads(result.stdout)
        raise ConnectionError(f"VM curl failed: {result.stderr}")
    except Exception as e:
        raise ConnectionError(f"VM bridge failed: {e}")


def _try_url(url: str, timeout: float = 5.0) -> requests.Response | None:
    """Try a single URL, return response or None."""
    try:
        return requests.get(url, timeout=timeout)
    except Exception:
        return None


def _get_with_fallback(path: str, timeout: float = 10.0) -> Any:
    """Try normal URL first, then fall back to VM wrapper."""
    normal_url = f"{BRIDGE_URL}{path}"
    vm_path = path

    # Try normal URL first
    resp = _try_url(normal_url, timeout=5.0)
    if resp and resp.status_code == 200:
        return resp.json()

    # Fallback to VM wrapper
    try:
        return _vm_get(vm_path)
    except Exception as vm_err:
        # Last resort: try normal URL with longer timeout
        resp = _try_url(normal_url, timeout=timeout)
        if resp and resp.status_code == 200:
            return resp.json()
        raise ConnectionError(
            f"Both normal and VM bridge failed. Normal: {resp}, VM: {vm_err}"
        )


def _post_with_fallback(
    path: str, payload: dict[str, Any] | None = None, timeout: float = 10.0
) -> Any:
    """POST with fallback to VM."""
    normal_url = f"{BRIDGE_URL}{path}"

    # Try normal URL first
    try:
        resp = requests.post(normal_url, json=payload or {}, timeout=5.0)
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass

    # Fallback to VM wrapper using curl -X POST with JSON body
    try:
        env = os.environ.copy()
        env.setdefault("XDG_RUNTIME_DIR", "/run/user/1000")
        env.setdefault("HOME", "/home/w")
        env.setdefault("USER", "w")
        # Use json.dumps for proper JSON body, not urlencoded
        json_body = json.dumps(payload or {})
        # Escape single quotes in JSON for shell
        json_body_escaped = json_body.replace("'", "'\\''")
        cmd = f"{VM_BRIDGE_CMD} -X POST -H 'Content-Type: application/json' -d '{json_body_escaped}' http://127.0.0.1:43111{path}"
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=15, env=env
        )
        if result.returncode == 0:
            return json.loads(result.stdout)
    except Exception:
        pass

    # Last resort: try normal
    resp = requests.post(normal_url, json=payload or {}, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


@mcp.resource("game://state/current")
def current_state() -> str:
    return json.dumps(_get_with_fallback("/state"), ensure_ascii=False)


@mcp.resource("game://actions/current")
def current_actions() -> str:
    return json.dumps(_get_with_fallback("/actions"), ensure_ascii=False)


@mcp.resource("game://events/recent")
def recent_events() -> str:
    return json.dumps(_get_with_fallback("/last_events"), ensure_ascii=False)


@mcp.resource("game://menu/state")
def menu_state_resource() -> str:
    return json.dumps(_get_with_fallback("/menu_state"), ensure_ascii=False)


@mcp.resource("game://name-input/state")
def name_input_state_resource() -> str:
    return json.dumps(_get_with_fallback("/name_input_state"), ensure_ascii=False)


@mcp.tool()
def health_check() -> dict[str, Any]:
    """Check whether the in-game bridge is reachable (tries normal then VM)."""
    return _get_with_fallback("/health")


@mcp.tool()
def list_actions() -> dict[str, Any]:
    """Return legal immediate actions and all actionable map tiles."""
    return _get_with_fallback("/actions")


@mcp.tool()
def perform_action(action_id: str) -> dict[str, Any]:
    """Enqueue exactly one action id returned by list_actions."""
    return _post_with_fallback("/action", {"id": action_id})


@mcp.tool()
def wait_until_idle(timeout_ms: int = 5000) -> dict[str, Any]:
    """Wait until game reaches a stable post-action state."""
    return _post_with_fallback("/wait_until_idle", {"timeoutMs": int(timeout_ms)})


@mcp.tool()
def step(action_id: str, timeout_ms: int = 5000) -> dict[str, Any]:
    """Perform one action, wait until idle, then return updated state."""
    perform_action(action_id)
    wait_until_idle(timeout_ms)
    return _get_with_fallback("/state")


@mcp.tool()
def eval(code: str) -> dict[str, Any]:
    """Execute arbitrary JavaScript code in the game context."""
    return _post_with_fallback("/eval", {"code": code})


def _find_target_tile(
    actions_payload: dict[str, Any], event_id: int | None, action_id: str | None
) -> dict[str, Any] | None:
    tiles = actions_payload.get("actionableTiles", []) or []
    for tile in tiles:
        if event_id is not None and tile.get("eventId") == int(event_id):
            return tile
        if action_id and tile.get("actionId") == action_id:
            return tile
    return None


def _immediate_action_ids(actions_payload: dict[str, Any]) -> set[str]:
    out: set[str] = set()
    for action in actions_payload.get("actions", []) or []:
        if not isinstance(action, dict):
            continue
        action_id = action.get("id")
        if isinstance(action_id, str):
            out.add(action_id)
    return out


def _preferred_move_order(dx: int, dy: int) -> list[str]:
    horiz = "move_right" if dx > 0 else "move_left"
    vert = "move_down" if dy > 0 else "move_up"
    if abs(dx) >= abs(dy):
        primary = [horiz, vert]
    else:
        primary = [vert, horiz]
    all_moves = ["move_up", "move_down", "move_left", "move_right"]
    for move in all_moves:
        if move not in primary:
            primary.append(move)
    return primary


def _client_side_goto_and_interact(
    event_id: int | None, action_id: str | None, timeout_ms: int
) -> dict[str, Any]:
    deadline = time.time() + max(timeout_ms, 1000) / 1000.0
    last_positions: list[tuple[int, int]] = []

    while time.time() < deadline:
        actions_payload = list_actions()
        state = _get_with_fallback("/state")
        target = _find_target_tile(actions_payload, event_id, action_id)
        if not target:
            return {
                "ok": False,
                "reason": "interactable_not_found",
                "mode": "client_fallback",
                "mapId": actions_payload.get("mapId"),
            }

        immediate_ids = _immediate_action_ids(actions_payload)
        target_action_id = target.get("actionId")

        if target.get("reachableNow") and isinstance(target_action_id, str):
            if target_action_id in immediate_ids:
                start = perform_action(target_action_id)
                remaining_ms = int(max(500, (deadline - time.time()) * 1000))
                idle = wait_until_idle(min(remaining_ms, 5000))
                new_state = _get_with_fallback("/state")
                return {
                    "ok": bool(start.get("ok")) and bool(idle.get("ok")),
                    "mode": "client_fallback",
                    "start": start,
                    "idle": idle,
                    "state": new_state,
                    "target": target,
                }

            # Reachable but no direct interact action surfaced yet.
            if "confirm" in immediate_ids or "advance_dialogue" in immediate_ids:
                press_id = (
                    "advance_dialogue"
                    if "advance_dialogue" in immediate_ids
                    else "confirm"
                )
                perform_action(press_id)
                wait_until_idle(1000)
                continue

        player = state.get("player") or {}
        px = player.get("x")
        py = player.get("y")
        tx = target.get("x")
        ty = target.get("y")
        if (
            not isinstance(px, int)
            or not isinstance(py, int)
            or not isinstance(tx, int)
            or not isinstance(ty, int)
        ):
            return {
                "ok": False,
                "reason": "player_or_target_position_missing",
                "mode": "client_fallback",
            }

        # If dialogue is open while routing, advance it and continue.
        if "advance_dialogue" in immediate_ids:
            perform_action("advance_dialogue")
            wait_until_idle(1000)
            continue

        dx = tx - px
        dy = ty - py
        ordered_moves = _preferred_move_order(dx, dy)
        chosen_move = next((m for m in ordered_moves if m in immediate_ids), None)
        if not chosen_move:
            return {
                "ok": False,
                "reason": "no_movement_actions_available",
                "mode": "client_fallback",
                "state": state,
            }

        before = (px, py)
        perform_action(chosen_move)
        wait_until_idle(1200)

        new_state = _get_with_fallback("/state")
        new_player = new_state.get("player") or {}
        after = (new_player.get("x"), new_player.get("y"))
        last_positions.append(before)
        if len(last_positions) > 8:
            last_positions.pop(0)

        # If we are oscillating/stuck, inject confirm once.
        if (
            after == before
            and last_positions.count(before) >= 3
            and "confirm" in immediate_ids
        ):
            perform_action("confirm")
            wait_until_idle(700)

    return {
        "ok": False,
        "reason": "goto_timeout",
        "mode": "client_fallback",
    }


@mcp.tool()
def goto_and_interact(
    event_id: int | None = None,
    action_id: str | None = None,
    timeout_ms: int = 15000,
) -> dict[str, Any]:
    """Autoroute to an interactable tile and interact with it.

    Provide either event_id (from actionableTiles[].eventId) or
    action_id (from actionableTiles[].actionId).
    """
    if event_id is None and not action_id:
        return {"ok": False, "reason": "event_id_or_action_id_required"}

    # Preflight: verify the target exists on current map so agent doesn't spam impossible IDs.
    pre_actions = list_actions()
    pre_target = _find_target_tile(pre_actions, event_id, action_id)
    if not pre_target:
        return {
            "ok": False,
            "reason": "interactable_not_on_current_map",
            "mapId": pre_actions.get("mapId"),
            "requested": {"event_id": event_id, "action_id": action_id},
            "availableEventIds": [
                t.get("eventId") for t in (pre_actions.get("actionableTiles", []) or [])
            ],
            "availableActionIds": [
                t.get("actionId")
                for t in (pre_actions.get("actionableTiles", []) or [])
            ],
        }

    payload: dict[str, Any] = {}
    if event_id is not None:
        payload["eventId"] = int(event_id)
    if action_id:
        payload["actionId"] = action_id

    start: dict[str, Any] | None = None
    for endpoint in ("/goto_and_interact", "/goto-and-interact", "/gotoAndInteract"):
        candidate = _post_with_fallback(endpoint, payload)
        # Older bridge may return endpoint-level not_found; try aliases before failing.
        if candidate.get("reason") == "not_found":
            start = candidate
            continue
        start = candidate
        break

    if start is None:
        return {"ok": False, "reason": "bridge_unreachable"}

    if not start.get("ok"):
        return start

    idle = wait_until_idle(timeout_ms)
    state = _get_with_fallback("/state")
    return {
        "ok": bool(idle.get("ok")),
        "start": start,
        "idle": idle,
        "state": state,
    }


@mcp.tool()
def menu_open(timeout_ms: int = 5000, force: bool = True) -> dict[str, Any]:
    """Open game menu. With force=True, bypasses Scene_Map.isMenuEnabled gate."""
    opened = _post_with_fallback("/menu_open", {"force": bool(force)})
    if not opened.get("ok"):
        return opened
    idle = wait_until_idle(timeout_ms)
    state = _get_with_fallback("/menu_state")
    return {
        "ok": bool(idle.get("ok")) and bool(state.get("open")),
        "open": opened,
        "idle": idle,
        "menu": state,
    }


@mcp.tool()
def menu_state() -> dict[str, Any]:
    """Get detailed current menu scene/window state and selectable entries."""
    return _get_with_fallback("/menu_state")


@mcp.tool()
def menu_move(direction: str, steps: int = 1, wrap: bool = True) -> dict[str, Any]:
    """Move cursor in active menu window: direction in {up,down,left,right}."""
    direction = str(direction).lower().strip()
    if direction not in {"up", "down", "left", "right"}:
        return {"ok": False, "reason": "invalid_direction"}
    result: dict[str, Any] = {"ok": True}
    for _ in range(max(1, int(steps))):
        result = _post_with_fallback(
            "/menu_move", {"direction": direction, "wrap": bool(wrap)}
        )
        if not result.get("ok"):
            return result
    return {"ok": True, "result": result, "menu": _get_with_fallback("/menu_state")}


@mcp.tool()
def menu_select(index: int | None = None, symbol: str | None = None) -> dict[str, Any]:
    """Select a menu entry by index or command symbol (e.g. item, save, options)."""
    payload: dict[str, Any] = {}
    if index is not None:
        payload["index"] = int(index)
    if symbol:
        payload["symbol"] = str(symbol)
    if not payload:
        return {"ok": False, "reason": "missing_index_or_symbol"}
    result = _post_with_fallback("/menu_select", payload)
    if not result.get("ok"):
        return result
    return {"ok": True, "result": result, "menu": _get_with_fallback("/menu_state")}


@mcp.tool()
def menu_confirm(timeout_ms: int = 3000) -> dict[str, Any]:
    """Confirm/OK in current menu window."""
    result = _post_with_fallback("/menu_confirm", {})
    idle = wait_until_idle(timeout_ms)
    return {
        "ok": bool(result.get("ok")) and bool(idle.get("ok")),
        "result": result,
        "idle": idle,
        "menu": _get_with_fallback("/menu_state"),
    }


@mcp.tool()
def menu_cancel(timeout_ms: int = 3000) -> dict[str, Any]:
    """Cancel/back in current menu window."""
    result = _post_with_fallback("/menu_cancel", {})
    idle = wait_until_idle(timeout_ms)
    return {
        "ok": bool(result.get("ok")) and bool(idle.get("ok")),
        "result": result,
        "idle": idle,
        "menu": _get_with_fallback("/menu_state"),
    }


@mcp.tool()
def name_input_state() -> dict[str, Any]:
    """Get state of Scene_Name input window (if active)."""
    return _get_with_fallback("/name_input_state")


@mcp.tool()
def name_input_set(text: str, submit: bool = False) -> dict[str, Any]:
    """Set name input text directly; optional immediate submit."""
    result = _post_with_fallback(
        "/name_input_set", {"text": str(text), "submit": bool(submit)}
    )
    return {
        "ok": bool(result.get("ok")),
        "result": result,
        "name_input": _get_with_fallback("/name_input_state"),
    }


@mcp.tool()
def name_input_submit(timeout_ms: int = 3000) -> dict[str, Any]:
    """Jump to OK in name input and submit current name."""
    result = _post_with_fallback("/name_input_submit", {})
    idle = wait_until_idle(timeout_ms)
    return {
        "ok": bool(result.get("ok")) and bool(idle.get("ok")),
        "result": result,
        "idle": idle,
        "state": _get_with_fallback("/state"),
    }


@mcp.tool()
def see_screen() -> Image:
    """Capture the current game screen as a multimodal image."""
    shot = _get_with_fallback("/screen")
    if not shot.get("ok"):
        raise RuntimeError(
            f"screen_capture_failed: {shot.get('reason')} {shot.get('error', '')}"
        )
    raw = base64.b64decode(shot["data"])
    return Image(data=raw, format="png")


if __name__ == "__main__":
    mcp.run(transport="stdio")
