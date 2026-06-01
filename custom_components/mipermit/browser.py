"""CDP-based browser automation for MiPermit.

Communicates with a remote Browserless Chrome instance using the Chrome
DevTools Protocol (CDP) directly over WebSockets, with no dependency on
Playwright or any other browser automation library.

All public methods are async and run on the HA event loop. No executor
thread is needed.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

from homeassistant.core import HomeAssistant

from .const import URL_LOGIN, URL_ACCOUNT
from .exceptions import MiPermitError, InvalidCredentials, CannotConnect

_LOGGER = logging.getLogger(__name__)

# Seconds (float) used for navigation and element waits
NAV_TIMEOUT = 30.0
ELEMENT_TIMEOUT = 15.0
POLL_INTERVAL = 0.25


class MiPermitBrowser:
    """Drives MiPermit via raw CDP over WebSockets."""

    def __init__(
        self,
        hass: HomeAssistant,
        username: str,
        password: str,
        cdp_url: str,
    ) -> None:
        """Initialise with HA instance, credentials, and Browserless CDP URL."""
        self._hass = hass
        self._username = username
        self._password = password
        self._cdp_url = cdp_url

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def validate_login(self) -> None:
        """Attempt a login and raise InvalidCredentials or CannotConnect on failure."""
        async with CDPSession(self._cdp_url) as cdp:
            await self._do_login(cdp)

    async def get_active_permits(self, operator: str) -> dict[str, Any]:
        """Return all active permits for the given operator."""
        try:
            async with CDPSession(self._cdp_url) as cdp:
                await self._do_login(cdp)
                await self._navigate_to_operator(cdp, operator)
                permits = await self._scrape_active_permits(cdp)
                return {"success": True, "permits": permits}
        except MiPermitError as exc:
            return {"success": False, "error": str(exc)}
        except Exception as exc:  # noqa: BLE001
            _LOGGER.exception("Unexpected error in get_active_permits")
            return {"success": False, "error": str(exc)}

    async def activate_permit(
        self,
        operator: str,
        registration: str,
        permit_type: str,
        duration: int,
    ) -> dict[str, Any]:
        """Activate a visitor permit and return the result."""
        try:
            async with CDPSession(self._cdp_url) as cdp:
                await self._do_login(cdp)
                await self._navigate_to_operator(cdp, operator)
                await self._fill_permit_form(cdp, registration, permit_type, duration)
                await self._confirm_modal(cdp)
                permits = await self._scrape_active_permits(cdp)
                new_permit = next(
                    (
                        p for p in permits
                        if p["registration"].upper() == registration.upper()
                    ),
                    None,
                )
                return {
                    "success": True,
                    "permit": new_permit,
                    "all_active_permits": permits,
                }
        except MiPermitError as exc:
            return {"success": False, "error": str(exc)}
        except Exception as exc:  # noqa: BLE001
            _LOGGER.exception("Unexpected error in activate_permit")
            return {"success": False, "error": str(exc)}

    # ------------------------------------------------------------------
    # Page interaction helpers
    # ------------------------------------------------------------------

    async def _do_login(self, cdp: "CDPSession") -> None:
        """Navigate to the login page, submit credentials, verify redirect."""
        await cdp.navigate(URL_LOGIN)
        await cdp.wait_for_element("#MemberNumber", timeout=ELEMENT_TIMEOUT)
        await cdp.fill("#MemberNumber", self._username)
        await cdp.fill("#PIN", self._password)
        await cdp.click("button[type='submit']")
        try:
            await cdp.wait_for_url_contains("AccountManagement", timeout=NAV_TIMEOUT)
        except asyncio.TimeoutError as exc:
            raise InvalidCredentials(
                "Login failed — check MiPermit username and password"
            ) from exc
        _LOGGER.debug("MiPermit login successful")

    async def _navigate_to_operator(self, cdp: "CDPSession", operator: str) -> None:
        """Click 'Activate Visitor Permit', then submit the operator form."""
        await cdp.wait_for_element("li#activate a", timeout=ELEMENT_TIMEOUT)
        await cdp.click("li#activate a")
        await cdp.wait_for_load(timeout=NAV_TIMEOUT)

        # Find the index of the operator form whose text contains the operator name
        form_index = await cdp.evaluate("""
            (operator) => {
                const forms = Array.from(document.querySelectorAll(
                    'form[action^="../Application/ModuleLander.aspx"]'
                ));
                return forms.findIndex(f => f.innerText.includes(operator));
            }
        """, arg=operator)

        if form_index == -1:
            raise MiPermitError(
                f"Car Park Operator '{operator}' not found on MiPermit"
            )

        # Submit that form via JS — avoids needing to click through the DOM
        await cdp.evaluate("""
            (index) => {
                const forms = Array.from(document.querySelectorAll(
                    'form[action^="../Application/ModuleLander.aspx"]'
                ));
                const btn = forms[index].querySelector(
                    'input[type="submit"], button[type="submit"]'
                );
                if (btn) btn.click();
                else forms[index].submit();
            }
        """, arg=form_index)

        await cdp.wait_for_url_contains("VisitorsManagement", timeout=NAV_TIMEOUT)
        await cdp.wait_for_load(timeout=NAV_TIMEOUT)
        _LOGGER.debug("Navigated to VisitorsManagement for operator: %s", operator)


    async def _scrape_active_permits(self, cdp: "CDPSession") -> list[dict[str, str]]:
        """Scrape the permits table and return active rows only."""
        await cdp.wait_for_element("#tblVisitorsCurrentBody", timeout=ELEMENT_TIMEOUT)

        rows: list[dict] = await cdp.evaluate("""
            () => {
                const results = [];

                const mpdtRegExp = /(?<day>\\d{2})\\/(?<month>\\d{2})\\/(?<year>\\d{4}) (?<hour>\\d{2}):(?<minute>\\d{2}):(?<second>\\d{2})/

                const zonedDateTimeFromMiPermitDateTime = function(mpdt){
                    const info = {
                        ... mpdtRegExp.exec(mpdt).groups,
                        timeZone: "Europe/London"
                    };

                    return Temporal.ZonedDateTime.from(info);
                }

                const haDateTimeFromMiPermitDateTime = function(mpdt){
                    const zdt = zonedDateTimeFromMiPermitDateTime(mpdt); 
                    return zdt.toString({timeZoneName:"never"});
                }

                const rows = Array.from(document.querySelectorAll("#tblVisitorsCurrentBody tr"));
                for (const row of rows) {

                    const innerTextForCellIdStartsWith = function(startsWith){
                        return row.querySelector("[id^="+startsWith+"]").innerText.trim();
                    }

                    const registration = innerTextForCellIdStartsWith("tdVisitorsCurrentVehicle");
                    const valid = innerTextForCellIdStartsWith("tdVisitorsCurrentValid");
                    const thirdCell = innerTextForCellIdStartsWith("tdVisitorsCurrentRemainingTime");

                    if (!thirdCell.includes("Active")) continue;

                    const parts = thirdCell.split("\\n");
                    const remaining_time = parts.length > 1
                        ? parts[0].trim()
                        : thirdCell;

                    const permitId = innerTextForCellIdStartsWith("tdVisitorsCurrentStayID");
                    const validFrom = innerTextForCellIdStartsWith("tdVisitorsCurrentDateFrom");
                    const validTo = innerTextForCellIdStartsWith("tdVisitorsCurrentDateTo");

                    results.push({
                        permitId,
                        registration,
                        valid,
                        remaining_time,
                        validFrom,
                        validTo,
                        status: "Active"
                    });
                }
                return results;
            }
        """)

        _LOGGER.debug("Scraped %d active permit(s)", len(rows))
        return rows

    async def _fill_permit_form(
        self,
        cdp: "CDPSession",
        registration: str,
        permit_type: str,
        duration: int,
    ) -> None:
        """Fill in the visitor permit pseudo-form."""
        await cdp.wait_for_element("#VisitorVRM", timeout=ELEMENT_TIMEOUT)
        await cdp.fill("#VisitorVRM", registration)

        # Validate the regex before sending to the browser
        try:
            re.compile(permit_type)
        except re.error as exc:
            raise MiPermitError(
                f"Invalid permit_type regex '{permit_type}': {exc}"
            ) from exc

        # Find and select the first matching permit type option
        matched = await cdp.evaluate("""
            (pattern) => {
                const select = document.querySelector("#VisitorPermitType");
                if (!select) return null;
                const re = new RegExp(pattern);
                for (const opt of select.options) {
                    if (re.test(opt.text)) {
                        select.value = opt.value;
                        select.dispatchEvent(new Event("change", {bubbles: true}));
                        return opt.text;
                    }
                }
                return null;
            }
        """, arg=permit_type)

        if matched is None:
            raise MiPermitError(
                f"No permit type matching '{permit_type}' found"
            )
        _LOGGER.debug("Matched permit type option: %s", matched)

        await cdp.wait_for_element("#VisitorSpanLength", timeout=ELEMENT_TIMEOUT)

        # Select the duration
        duration_set = await cdp.evaluate("""
            (hours) => {
                const select = document.querySelector("#VisitorSpanLength");
                if (!select) return false;
                select.value = String(hours);
                select.dispatchEvent(new Event("change", {bubbles: true}));
                return select.value === String(hours);
            }
        """, arg=duration)

        if not duration_set:
            raise MiPermitError(
                f"Duration '{duration}' hours not available in permit duration select"
            )

        # Click the Continue button
        clicked = await cdp.evaluate("""
            () => {
                const btn = document.querySelector(
                    "input[type='button'][value='Continue'], " +
                    "button[type='button']"
                ) || Array.from(document.querySelectorAll("input, button"))
                    .find(el => el.value === "Continue" || el.innerText === "Continue");
                if (!btn) return false;
                btn.click();
                return true;
            }
        """)

        if not clicked:
            raise MiPermitError("Could not find the Continue button on the permit form")

        _LOGGER.debug(
            "Filled permit form: reg=%s type=%s duration=%sh",
            registration, permit_type, duration,
        )

    async def _confirm_modal(self, cdp: "CDPSession") -> None:
        """Wait for the confirmation modal and click Confirm."""
        await cdp.wait_for_element("#cmdConfirmVisitor", timeout=ELEMENT_TIMEOUT)
        await cdp.click("#cmdConfirmVisitor")
        await cdp.wait_for_load(timeout=NAV_TIMEOUT)
        await cdp.wait_for_element("table", timeout=ELEMENT_TIMEOUT)
        _LOGGER.debug("Confirmed permit modal, page reloaded")


# ---------------------------------------------------------------------------
# CDP session implementation
# ---------------------------------------------------------------------------

class CDPSession:
    """
    Minimal async CDP client for driving a remote Browserless Chrome instance.

    Opens a WebSocket connection to Browserless, creates a fresh browser
    target (tab), and exposes navigate / wait / evaluate / fill / click helpers.

    Use as an async context manager:
        async with CDPSession(cdp_url) as cdp:
            await cdp.navigate("https://example.com")
    """

    def __init__(self, browserless_url: str) -> None:
        self._browserless_url = browserless_url
        self._ws: Any = None          # websockets connection to the tab
        self._msg_id = 0
        self._pending: dict[int, asyncio.Future] = {}
        self._events: asyncio.Queue = asyncio.Queue()
        self._listener_task: asyncio.Task | None = None
        self._current_url: str = ""

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    async def __aenter__(self) -> "CDPSession":
        await self._connect()
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self._disconnect()

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    async def navigate(self, url: str) -> None:
        """Navigate to a URL and wait for the page to load."""
        await self._send("Page.navigate", {"url": url})
        await self.wait_for_load(timeout=NAV_TIMEOUT)
        self._current_url = url

    async def wait_for_load(self, timeout: float = NAV_TIMEOUT) -> None:
        """Wait until the page fires a loadEventFired CDP event."""
        deadline = asyncio.get_event_loop().time() + timeout
        while True:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                raise asyncio.TimeoutError("Timed out waiting for page load")
            try:
                event = await asyncio.wait_for(
                    self._events.get(), timeout=min(remaining, 1.0)
                )
                if event.get("method") == "Page.loadEventFired":
                    return
            except asyncio.TimeoutError:
                # No event in this slice — check deadline and loop
                if asyncio.get_event_loop().time() >= deadline:
                    raise asyncio.TimeoutError("Timed out waiting for page load")

    async def wait_for_url_contains(
        self, fragment: str, timeout: float = NAV_TIMEOUT
    ) -> None:
        """Poll the current page URL until it contains `fragment`."""
        deadline = asyncio.get_event_loop().time() + timeout
        while True:
            result = await self._send("Runtime.evaluate", {
                "expression": "window.location.href",
                "returnByValue": True,
            })
            current = result.get("result", {}).get("value", "")
            if fragment in current:
                self._current_url = current
                return
            if asyncio.get_event_loop().time() >= deadline:
                raise asyncio.TimeoutError(
                    f"Timed out waiting for URL to contain '{fragment}'. "
                    f"Current URL: {current}"
                )
            await asyncio.sleep(POLL_INTERVAL)

    async def wait_for_element(
        self, selector: str, timeout: float = ELEMENT_TIMEOUT
    ) -> None:
        """Poll until document.querySelector(selector) returns a non-null node."""
        deadline = asyncio.get_event_loop().time() + timeout
        while True:
            result = await self._send("Runtime.evaluate", {
                "expression": f"!!document.querySelector({json.dumps(selector)})",
                "returnByValue": True,
            })
            if result.get("result", {}).get("value") is True:
                return
            if asyncio.get_event_loop().time() >= deadline:
                raise asyncio.TimeoutError(
                    f"Timed out waiting for element '{selector}'"
                )
            await asyncio.sleep(POLL_INTERVAL)

    async def evaluate(self, expression: str, arg: Any = None) -> Any:
        """
        Evaluate a JS expression in the page context and return its value.

        If `arg` is provided it is passed as the first argument to a function
        expression (the expression must be a function literal, e.g. "(x) => ...").
        """
        if arg is not None:
            # Wrap scalar/list/dict arg as JSON and call the function
            call_expr = f"({expression})({json.dumps(arg)})"
        else:
            call_expr = f"({expression})()"

        result = await self._send("Runtime.evaluate", {
            "expression": call_expr,
            "returnByValue": True,
            "awaitPromise": True,
        })

        # Surface JS exceptions as Python errors
        if "exceptionDetails" in result:
            detail = result["exceptionDetails"]
            msg = (
                detail.get("exception", {}).get("description")
                or detail.get("text", "Unknown JS error")
            )
            raise MiPermitError(f"JavaScript error in page: {msg}")

        return result.get("result", {}).get("value")

    async def fill(self, selector: str, value: str) -> None:
        """Set an input's value and fire input/change events."""
        await self.evaluate("""
            (args) => {
                const el = document.querySelector(args.selector);
                if (!el) throw new Error("Element not found: " + args.selector);
                el.value = args.value;
                el.dispatchEvent(new Event("input", {bubbles: true}));
                el.dispatchEvent(new Event("change", {bubbles: true}));
            }
        """, arg={"selector": selector, "value": value})

    async def click(self, selector: str) -> None:
        """Click an element identified by CSS selector."""
        await self.evaluate("""
            (selector) => {
                const el = document.querySelector(selector);
                if (!el) throw new Error("Element not found: " + selector);
                el.click();
            }
        """, arg=selector)

    # ------------------------------------------------------------------
    # Internal CDP wiring
    # ------------------------------------------------------------------

    async def _connect(self) -> None:
        """Open a WebSocket connection to Browserless and enable Page/Runtime domains."""
        try:
            import websockets  # already in HA's dependency tree
        except ImportError as exc:
            raise CannotConnect(
                "The 'websockets' package is not available in this HA environment"
            ) from exc

        # Browserless exposes a CDP endpoint at /chromium (v2) or / (v1).
        # We connect at the browser level then open a fresh target (tab).
        browser_ws_url = self._browserless_url.rstrip("/") + "/chromium"

        try:
            browser_ws = await websockets.connect(browser_ws_url)
        except Exception as exc:
            raise CannotConnect(
                f"Could not connect to Browserless at {browser_ws_url}: {exc}"
            ) from exc

        # Ask the browser to create a new target (blank tab)
        msg_id = 1
        await browser_ws.send(json.dumps({
            "id": msg_id,
            "method": "Target.createTarget",
            "params": {"url": "about:blank"},
        }))
        raw = await browser_ws.recv()
        resp = json.loads(raw)
        target_id = resp["result"]["targetId"]

        # Attach to the target to get its sessionId
        msg_id += 1
        await browser_ws.send(json.dumps({
            "id": msg_id,
            "method": "Target.attachToTarget",
            "params": {"targetId": target_id, "flatten": True},
        }))
        # Drain messages until we get the attachedToTarget event
        session_id = None
        while session_id is None:
            raw = await browser_ws.recv()
            data = json.loads(raw)
            if data.get("method") == "Target.attachedToTarget":
                session_id = data["params"]["sessionId"]


        # Now open a direct WebSocket to the target's devtools endpoint
        # Browserless exposes per-target endpoints under /devtools/page/<targetId>
        base = self._browserless_url.rstrip("/")
        tab_ws_url = f"{base}/devtools/page/{target_id}"

        try:
            self._ws = await websockets.connect(tab_ws_url)
        except Exception as exc:
            raise CannotConnect(
                f"Could not connect to CDP tab at {tab_ws_url}: {exc}"
            ) from exc

        # Start background listener
        self._listener_task = asyncio.create_task(self._listen())

        # Enable the domains we need
        await self._send("Page.enable")
        await self._send("Runtime.enable")
        await browser_ws.close()


    async def _disconnect(self) -> None:
        """Close the CDP WebSocket and cancel the listener task."""
        if self._listener_task:
            self._listener_task.cancel()
            try:
                await self._listener_task
            except asyncio.CancelledError:
                pass
        if self._ws:
            try:
                await self._ws.close()
            except Exception:  # noqa: BLE001
                pass

    async def _listen(self) -> None:
        """Background task: route incoming CDP messages to waiting futures or event queue."""
        try:
            async for raw in self._ws:
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                if "id" in msg:
                    # Response to a command we sent
                    fut = self._pending.pop(msg["id"], None)
                    if fut and not fut.done():
                        if "error" in msg:
                            fut.set_exception(
                                MiPermitError(
                                    f"CDP error: {msg['error'].get('message', msg['error'])}"
                                )
                            )
                        else:
                            fut.set_result(msg.get("result", {}))
                else:
                    # Unsolicited event (e.g. Page.loadEventFired)
                    await self._events.put(msg)
        except asyncio.CancelledError:
            pass
        except Exception as exc:  # noqa: BLE001
            _LOGGER.debug("CDP listener exiting: %s", exc)

    async def _send(self, method: str, params: dict | None = None) -> dict:
        """Send a CDP command and await its response."""
        self._msg_id += 1
        msg_id = self._msg_id
        payload = {"id": msg_id, "method": method, "params": params or {}}

        loop = asyncio.get_event_loop()
        fut: asyncio.Future = loop.create_future()
        self._pending[msg_id] = fut

        await self._ws.send(json.dumps(payload))

        try:
            return await asyncio.wait_for(fut, timeout=NAV_TIMEOUT)
        except asyncio.TimeoutError as exc:
            self._pending.pop(msg_id, None)
            raise asyncio.TimeoutError(
                f"CDP command '{method}' timed out"
            ) from exc
