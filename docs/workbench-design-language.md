# HarnessCoder Workbench Design Language

## One-Line Definition

HarnessCoder Dark uses a gray-blue workspace as the base, semantic accents only
for real runtime state, and surface hierarchy plus density to communicate
structure.

It is not a terminal skin.

It is not pure-black command-line chrome.

It is not a cyberpunk dashboard.

It is a long-running local agent workbench.

## Product Mood

The default tone is:

- calm
- precise
- workable

The surface should feel stable during long sessions. It should read more like a
local engineering tool than a product showcase.

The visual model is a layered workbench:

- a quiet app shell on the left
- a broad central workspace
- a right inspector and bottom composer that float above the workspace as
  operating surfaces

The interface should rely on surface brightness, spacing, radius, and gentle
shadow before it relies on borders.

## Color Model

HarnessCoder should borrow the gray-blue atmosphere from One Dark Pro, but
organize it through semantic color roles similar to Material-style design
systems.

Principle:

- gray owns space
- blue-gray owns product mood
- accent colors own state

### Base Space Roles

- `app.background`: darkest gray-blue background
- `sidebar.surface`: slightly raised navigation background
- `workspace.surface`: primary conversation workspace
- `panel.surface`: inspector and supporting panels
- `block.surface`: messages, runtime summaries, tool timeline items
- `composer.surface`: highest-priority input surface

### Semantic Roles

- blue: active, focus, running, link
- green: success, connected, completed
- amber: attention, approval, pending, warning
- red: failed, error, danger
- purple: context, memory, notes
- cyan: trace, tool, stream

Accent colors should stay small. Prefer dots, rails, text accents, small chips,
and icons over large filled panels.

## Surface Hierarchy

The workbench should rely on surfaces, not border-heavy card stacks.

Use five levels:

- `L0 / App`: page background
- `L1 / Navigation`: sidebar and inspector
- `L2 / Workspace`: center workspace base
- `L3 / Content Block`: messages, runtime summaries, tool calls, notes
- `L4 / Composer / Focus`: composer, selected items, active items, focused
  surfaces

Rule:

If borders disappeared, users should still understand grouping and focus.

In particular:

- the sidebar should feel docked and quiet
- the workspace should feel broad and stable
- the inspector and composer should feel slightly elevated above the workspace
- full-black terminal contrast should be avoided because it collapses these
  layers

## Border Strategy

Borders are for reinforcement, not for building every component.

Default behavior:

- normal blocks: no strong border
- hover: surface brightens slightly
- selected: active rail or inset line
- focus: subtle blue focus indicator
- warning/error: explicit but compact state border

Border is a hint, not the skeleton.

## Type System

Text should be readable, restrained, and scannable.

Suggested roles:

- `title`: thread title, panel title, message author
- `body`: task text, runtime summary, final answer
- `meta`: timestamps, model, file counts, step counts, status text
- `code`: commands, paths, tool names, run ids, thread ids

Rules:

- titles should be clear but not loud
- body text should stay comfortable in dark mode
- metadata should be weaker but still legible
- monospace is for identifiers and commands, not for everything

## Layout Roles

The workbench uses a three-column app shell:

- left: thread navigation
- center: conversation workspace
- right: inspector
- bottom: composer

Visual priority:

1. center conversation
2. bottom composer
3. left quick switching
4. right deep inspection

## Left Sidebar

The sidebar should behave like an editor file list:

- lightweight rows, not repeated cards
- single-line truncation for titles
- tiny status dots
- selected row shown through surface shift plus a thin active rail
- metadata kept weak and compact

It should feel closer to a file tree than to a social feed.

## Center Workspace

The center column is the main execution narrative.

Desired reading order:

1. what the user asked
2. how the runtime interpreted it
3. what actions happened
4. where attention or approval is needed
5. what final result was produced

Representation rules:

- task is a user message bubble
- runtime summary is an agent response block
- tool calls are timeline events
- raw trace belongs behind secondary disclosure
- final result is visually clear but not celebratory

The center column should never collapse into a dashboard.

## Runtime And Tool Timeline

Tool activity should look like a timeline, not like KPI cards.

Preferred structure:

- left: state marker or status symbol
- middle: action label and short summary
- right: compact metadata such as elapsed time or event index

State color usage:

- running: blue dot or active accent
- success: green dot or check
- warning: amber indicator
- error: red indicator plus compact state emphasis
- tool/trace: cyan tag when needed

Default view should show readable summaries first. Parameters, stdout, stderr,
diffs, and artifacts should stay secondary.

## Composer

The composer is the most important component in the product.

It should feel like a command composer:

- light
- compact
- flat
- input-first

Structure:

- first row: input
- second row: lightweight controls
- left side: mode, model, permission as inline pills
- right side: secondary actions plus send

Rules:

- `Send` is the only strong button
- `More` and auxiliary controls are lower-contrast
- composer surface can be one level brighter than surrounding workspace
- radius can be the largest in the interface
- focus should use a subtle blue line or glow, not a thick border

The composer should make it obvious where to type and how to send without
turning into a settings panel.

## Right Inspector

The inspector should feel like a property panel:

- narrow
- dense
- quiet
- clear

Good candidates:

- run details
- context
- memory
- files
- permissions
- model settings
- artifacts

Labels stay weak. Values stay readable. Empty states still need rhythm.

## Radius System

Radius should communicate component identity.

Suggested scale:

- composer: `18px–24px`
- message bubble: `14px–18px`
- runtime block: `10px–14px`
- chip/badge: `6px–10px`

Do not give every component the same radius.

## Interaction Feedback

Feedback should be light and fast.

- hover: raise surface slightly
- selected: add active rail or subtle inset line
- focus: thin blue emphasis
- running: compact animated or highlighted state
- error: clear but restrained red state

The interface should behave like a serious tool, not a motion showcase.

## Implementation Formula

HarnessCoder Dark can be summarized as:

One Dark Pro atmosphere

+ semantic color roles

+ layered dark surfaces

+ editor-style density

+ Codex-like bottom composer

= local agent workbench

In implementation terms:

- use surfaces to define space
- use color roles to define state
- use density to preserve tool-like efficiency
- use the composer as the main entry point
- use a timeline to explain agent behavior
- use the inspector to hold complexity
