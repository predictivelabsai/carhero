# CarHero Skills & Test Plans

## Mobile/Desktop Regression Test Plan

### Test Matrix

| # | Test Case | Viewport | Steps | Expected Result |
|---|-----------|----------|-------|----------------|
| **Mobile (375x812)** |
| M1 | Initial load | 375x812 | Navigate to /app | Chat visible, no right pane, no left pane, hamburger visible, no Results FAB |
| M2 | Hamburger opens left pane | 375x812 | Tap hamburger | Left pane slides in from left, overlay visible behind it |
| M3 | Overlay closes left pane | 375x812 | Tap overlay (right side) | Left pane closes, overlay gone |
| M4 | Send query, chat visible | 375x812 | Type query, send, wait for response | Chat response fully visible, right pane stays closed |
| M5 | Results FAB appears | 375x812 | After query with artifacts | Black "Results" FAB visible bottom-right |
| M6 | Results FAB opens right pane | 375x812 | Tap Results FAB | Right pane slides in with overlay behind it, FAB hidden |
| M7 | Results scrollable | 375x812 | Scroll inside right pane | Can scroll through all listing cards |
| M8 | Close button closes right pane | 375x812 | Tap X in right pane header | Right pane closes, FAB reappears, chat visible |
| M9 | Overlay closes right pane | 375x812 | Tap overlay behind right pane | Right pane closes |
| M10 | Hamburger works after query | 375x812 | Close right pane, tap hamburger | Left pane opens with session history |
| M11 | Second query works | 375x812 | Send another query, wait | Chat response visible, right pane stays closed |
| M12 | Input visible | 375x812 | Check input area | Input field and send button within viewport |
| **Desktop (1280x800)** |
| D1 | Initial load | 1280x800 | Navigate to /app | 3-pane layout: left sidebar, center chat, right closed |
| D2 | Left pane always visible | 1280x800 | Check layout | Left pane visible, no hamburger, history + agents shown |
| D3 | Query auto-opens right pane | 1280x800 | Send query, wait | Right pane auto-opens with listing cards |
| D4 | Right pane scrollable | 1280x800 | Scroll inside right pane | Can scroll through all listing cards |
| D5 | Canvas button toggles pane | 1280x800 | Click canvas icon | Right pane closes/opens |
| D6 | Share button works | 1280x800 | Click share icon | Green checkmark flash |
| D7 | Copy button works | 1280x800 | Click copy icon | Green checkmark flash |
| D8 | New chat works | 1280x800 | Click "+ New chat" | Clean state, welcome hero visible |
| D9 | Session history clickable | 1280x800 | Click a session | Loads that session's messages |
| D10 | Session share hover button | 1280x800 | Hover over session item | Chain link icon appears |

### Architecture Notes

**Z-index hierarchy (mobile):**
- 40: left-overlay (backdrop behind left pane)
- 50: left-pane (sidebar)
- 55: right-overlay (backdrop behind right pane)
- 60: right-pane (artifact/results pane)
- 100: signin-overlay

**Critical CSS patterns:**
- `.artifact-body` needs `min-height: 0` for flex overflow scrolling
- `.artifact-header` needs `flex-shrink: 0` to prevent compression
- Right pane on mobile: `position: fixed; right: -100%` slides to `right: 0`
- Left pane on mobile: `position: fixed; left: -280px` slides to `left: 0`

**JS behavior:**
- `showArtifact()`: On desktop auto-opens right pane; on mobile shows Results FAB only
- `toggleArtifactPane()`: On mobile toggles right-overlay visibility
- Mobile init: Ensures right pane starts closed on load
