# Guide: Customizing the Risk Workspace Layout (CSS)

This guide explains how to adjust the visual layout of the `risk_workspace.py` using Textual's CSS system. Think of this as your "formatting menu" for the dashboard.

## 1. Core Layout Concepts
- **`height: 1fr;`**: "1 Fraction". Stretches the element to fill all remaining vertical space.
- **`width: 60%;`**: Sets a relative horizontal width.
- **`height: 4;`**: Sets a fixed height of exactly 4 character rows.
- **`padding: 1 2;`**: Space **inside** the border (1 row top/bottom, 2 columns left/right).
- **`margin: 1 0;`**: Space **outside** the border.

---

## 2. Element-by-Element Breakdown

### The Panes (The 60/40 Split)
- `#left-pane`: Targets the Portfolio Grid side.
- `#right-pane`: Targets the Modelling Sidebar side.
- *Adjustment:* Change `width` percentages to rebalance the screen.

### Modelling Sidebar (`#discovery-layout`)
- `.discovery-sub-pane`: Targets the individual FIXED and TRAILING boxes.
- *Adjustment:* Decrease `height: 10;` to `height: 8;` to see more of the help panel without scrolling.

### Headers & Context
- `.panel-header`: The bold titles at the top of every box.
- `#position-context`: The box showing the current Asset Name and Entry Date.
- *Constraint:* Needs at least `height: 3;` to show text inside a border.

### Input Area (`#input-container`)
This is the "Assign Risk Strategy" box.
- `border: tall $accent;`: A thick highlighted border. Change to `solid` for a thinner line or `none` to save space.
- `min-height: 7;`: Ensures the box doesn't collapse. Decrease to tighten.
- `margin-top: 1;`: Adds a gap between the table and the input box. Set to `0` to join them.
- `margin-bottom: 1;`: Adds a gap at the very bottom of the screen.

### Widgets (Input & Select)
- `height: 3;`: The standard height for widgets with borders.
- `border: none; height: 1;`: The secret to making widgets ultra-tight (no box, just text).

---

## 3. How to "Tighten" the Layout
If the input area feels too large, try these steps in the `CSS` block:
1. Change `#input-container` padding to `0`.
2. Change `#input-container` border to `solid` or `none`.
3. Set `#input-container Label { display: none; }` to hide the title.
4. Set `margin-top: 0;` to push the container flush against the table above.

## 4. Where to find in code
Find the `CSS = """ ... """` block at the very top of the `RiskWorkspace` class in `risk_workspace.py`.
