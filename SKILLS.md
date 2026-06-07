# SKILLS.md

Instructions for the testing agent. Every UI change MUST be verified with Playwright MCP before reporting the task as complete.

## When to test

After any change to:
- `chat/components.py` (left pane, center pane, right pane, welcome hero, sign-in overlay)
- `chat/layout.py` (page wrapper, head, overlays, toggle buttons)
- `chat/routes.py` (chat API, session endpoints, share routes)
- `chat/market_map.py` (market map page, tabs, charts)
- `static/app.css` (layout, responsive breakpoints, component styles)
- `static/chat.js` (chat interaction, SSE, share/copy, artifact pane, toggles)
- `auth/routes.py` (login, register, forgot password, profile)
- `main.py` `/app` or `/` route changes

## Pre-flight

1. Start the server if not already running:
   ```
   python main.py &
   ```
2. Wait for it to respond:
   ```
   curl -s -o /dev/null -w '%{http_code}' http://localhost:5010/app
   ```
   Expect `200`. If not, check `/tmp/carhero.log`.

3. Load Playwright MCP tools via ToolSearch:
   ```
   select:mcp__plugin_playwright_playwright__browser_navigate,mcp__plugin_playwright_playwright__browser_snapshot,mcp__plugin_playwright_playwright__browser_take_screenshot,mcp__plugin_playwright_playwright__browser_resize,mcp__plugin_playwright_playwright__browser_click,mcp__plugin_playwright_playwright__browser_evaluate,mcp__plugin_playwright_playwright__browser_hover,mcp__plugin_playwright_playwright__browser_type,mcp__plugin_playwright_playwright__browser_close
   ```

## Test matrix

Every test pass covers **both viewports**:

| Viewport | Width | Height | Represents         |
|----------|-------|--------|---------------------|
| Desktop  | 1280  |  800   | Laptop / monitor    |
| Mobile   |  375  |  812   | iPhone 14 / similar |

Use `browser_resize` to switch between them.

## Test checklist

### 1. Chat app (`/app`)

**Desktop (1280x800):**
- [ ] 3-pane layout renders: left pane (280px), center pane, right pane (closed)
- [ ] Left pane sections: CarHero logo, "+ New chat", History, Agents (3 categories), Workspace (5 links), auth section
- [ ] Workspace links: Market Map, Favorites, Saved Searches, My Garage, Profile & Preferences
- [ ] Center pane: header with "Car Advisor", language dropdown, Share/Copy/Canvas icons
- [ ] Welcome hero with 5 sample prompt cards
- [ ] Chat input + send button visible at bottom
- [ ] Hamburger menu NOT visible (desktop only)
- [ ] No Results FAB visible (desktop only)

**Mobile (375x812):**
- [ ] Left pane hidden by default (off-screen at x=-280)
- [ ] Right pane hidden by default (off-screen)
- [ ] Hamburger menu (three lines SVG) visible in header, 40x40 tap target
- [ ] Click hamburger -> left pane slides in, overlay visible behind it
- [ ] Tap overlay -> left pane closes
- [ ] Welcome hero and sample cards render
- [ ] Chat input + send button visible within viewport
- [ ] No Results FAB until a query is sent

### 2. Chat interaction (both viewports)

**Desktop:**
- [ ] Send a search query -> right pane auto-opens with listing cards
- [ ] Right pane scrollable (artifact-body has overflow-y: auto + min-height: 0)
- [ ] Canvas button toggles right pane open/closed
- [ ] Share button fires /api/share, shows green checkmark flash
- [ ] Copy button copies chat text, shows green checkmark flash
- [ ] "+ New chat" resets to clean state with welcome hero
- [ ] Session history: clicking a session loads its messages
- [ ] Session share: hover shows chain-link icon, click copies share URL

**Mobile:**
- [ ] Send a search query -> chat response visible, right pane stays CLOSED
- [ ] "Results" FAB appears (black pill, bottom-right) after artifacts arrive
- [ ] Tap Results FAB -> right pane slides in, overlay behind it
- [ ] Results pane scrollable (can scroll through all listing cards)
- [ ] X close button (top-right of pane) closes right pane, FAB reappears
- [ ] Tap overlay behind right pane -> closes it
- [ ] Hamburger still works after query (left pane opens with history)
- [ ] Second query works correctly, chat visible

### 3. Sign-in overlay (both viewports)

- [ ] Click "Sign In" button -> overlay appears
- [ ] Two tabs: Sign In / Register, tab switching works
- [ ] Login form: email + password fields, "Forgot password?" link
- [ ] Register form: name, email, password fields
- [ ] Forgot password form accessible from login
- [ ] Google SSO button present
- [ ] Cancel or backdrop click closes overlay

### 4. Market Map (`/app/market-map`)

- [ ] Page loads with tab navigation
- [ ] Charts render (Plotly)
- [ ] Responsive on both viewports

### 5. Shared chat (`/shared/{token}`)

- [ ] Read-only view of shared chat renders
- [ ] Messages display with markdown rendering
- [ ] No input field or send button

## Architecture reference

**Z-index hierarchy (mobile):**
- 40: `.left-overlay` (backdrop behind left pane)
- 50: `.left-pane` (sidebar)
- 55: `.right-overlay` (backdrop behind right pane)
- 60: `.right-pane` (artifact/results pane)
- 100: `.signin-overlay` (auth modal)

**Critical CSS patterns:**
- `.artifact-body` needs `min-height: 0` for flex overflow scrolling
- `.artifact-header` needs `flex-shrink: 0` to prevent compression
- Right pane mobile: `position: fixed; right: -100%` slides to `right: 0`
- Left pane mobile: `position: fixed; left: -280px` slides to `left: 0`
- Hamburger: `display: none` on desktop, `display: flex` on mobile (40x40)

**JS behavior:**
- `showArtifact()`: Desktop auto-opens right pane; mobile shows Results FAB only
- `toggleArtifactPane()`: On mobile also toggles `#right-overlay` visibility
- `toggleLeftPane()`: Toggles `.left-pane.open` and `.left-overlay.visible`
- Mobile init: Ensures right pane starts closed on load

## How to verify

Use `browser_snapshot` (accessibility tree) as the primary verification tool -- it's faster and more reliable than screenshots for checking element presence, text content, and structure.

Use `browser_evaluate` for DOM state checks (classList, getBoundingClientRect, computed styles).

Use `browser_take_screenshot` when:
- Checking visual layout (overflow, alignment, spacing)
- Verifying responsive behavior
- The snapshot doesn't capture what you need (e.g., CSS-hidden elements)

Use `browser_click` / `browser_hover` to test interactive elements.

## Snapshot tips

- `depth: 2-3` for page-level structure checks
- `depth: 4-5` for section-level detail
- `boxes: true` to get bounding boxes for position verification
- Target a specific element (`target: .chat-header`) to drill into a section without noise
- After `browser_click` or `browser_resize`, take a new snapshot before using refs

## Reporting results

After testing, report:
1. Which viewport(s) were tested
2. Pass/fail for each checklist item
3. Any console errors
4. Screenshots if any visual issue is found

## Cleanup

Always close the browser when done:
```
browser_close
```

Kill the dev server if you started it:
```
kill $(lsof -ti:5010) 2>/dev/null
```
