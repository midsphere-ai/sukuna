name: design-system-jatayu-ai
description: Creates implementation‑ready design‑system guidance for Jatayu AI. This file captures colour, typography, spacing and component rules so AI tools can generate UIs consistent with our brand.
Jatayu AI Design System
Mission

Jatayu AI is an execution engine for agents rather than a chat bot. Our visual language should feel like infrastructure software – calm, precise, and under control. Interfaces must read like a log or document rather than a dashboard. The goal of this system is to provide a set of tokens and rules that make it easy for any tool to reproduce our dark, monochrome, system‑first aesthetic while preserving usability and accessibility.

Brand
Product / brand – Jatayu AI and its agent execution platform
Audience – technical users, developers and knowledge workers who run AI agents to automate tasks
Product surface – web app, developer CLI, agent dashboards and knowledge/file management
Style Foundations
Visual style

Our style is system‑like: calm, precise and monochrome. Colour is used sparingly and only to communicate state. Interfaces should rely on typography and spacing rather than decoration to create hierarchy. The look should evoke a terminal or code editor, with clean lines, generous whitespace and minimal chrome. Two themes are provided – a dark mode and a light mode – that share the same principles but invert the contrast.

Colour palettes

Use semantic colour tokens rather than raw hex values; these tokens map to exact values so that AI tools can apply them consistently. The design system defines both dark‑mode and light‑mode palettes that mirror each other in tone and contrast.

Dark mode

Base colours

bg: #0B0B0C – Application background
surface: #111113 – Primary surface (panels, inputs)
surface‑2: #151517 – Secondary surface (sidebar, secondary panels)

Text colours

text‑primary: #F5F5F7 – Primary text
text‑secondary: #CDCDD3 – Secondary/metadata (high contrast against bg, passes WCAG AA)
text‑tertiary: #96969E – Tertiary/disabled text (passes WCAG AA for normal text)

Accent & status colours

accent: #EDEDED – Off‑white accent used for focus rings, active states and highlights
success: #6EE7B7 – Success state (agent completed)
error: #FF6B6B – Error state (agent failure)
warning: #FACC15 – Warning state (caution)
Light mode

Base colours

bg‑light: #FFFFFF – Application background
surface‑light: #F5F6F8 – Primary surface (panels, inputs)
surface‑2‑light: #ECEEF1 – Secondary surface (sidebar, secondary panels)

Text colours

text‑primary‑light: #202124 – Primary text
text‑secondary‑light: #3A3D43 – Secondary/metadata
text‑tertiary‑light: #64666C – Tertiary/disabled text

Accent & status colours

accent‑light: #1A1A1C – Dark accent used for focus rings, active states and highlights
success‑light: #0F9D58 – Success state
error‑light: #B31424 – Error state
warning‑light: #C66C00 – Warning state

For both themes, accent colours should only be used to communicate state in logs or to draw focus; never for decoration. Avoid multiple accent colours on a single screen.

Typography scale

Define font families and sizes explicitly so tools can apply them without guessing.

Primary UI font: Geist, sans‑serif (fallback: Inter Tight, sans‑serif). Use for all headings, labels and body text.
Mono font: JetBrains Mono, monospace (fallback: IBM Plex Mono). Use for agent logs, command palette input and any code or CLI output.
Type sizes

The type scale follows an 8 pt step. **Only two weights are used: 500 (medium) for anything that needs emphasis — headings, labels, buttons, active states — and 400 (regular) for body, metadata and log output.** Bold (600+) is an anti‑pattern. The visual rhythm of the system comes from size, spacing and colour, not weight contrast.

Token	Size	Weight	Usage
h1	40 px	500	Page or section titles
h2	32 px	500	Major headings
h3	24 px	500	Subheadings
body	15 px	400	Primary paragraph text
small	13 px	400	Captions, metadata, small labels
code/log	13 px	400	Mono type for logs and code blocks

Line heights should be 1.4 × the font size for readability. Increase letter spacing by 2 – 4 % on headings to create breathing room.

Spacing scale

Adopt an 8 pt grid to ensure consistent spacing. All margins, padding and gaps should be multiples of the base unit.

Base unit: 8 px
Values: 4, 8, 16, 24, 32, 48 px
Gaps between UI elements should follow the scale: e.g. 16 px between sections, 8 px between labels and inputs. Avoid one‑off spacing values.
Radius and motion
Radius tokens: radius‑small = 4 px (chips, tags); radius‑medium = 6 px (inputs, buttons); radius‑large = 8 px (cards, modals). Do not mix radii within the same component.
Shadow: None. Instead of drop shadows, separate surfaces with subtle borders using the border token.
Motion: Animations should be fast (120–220 ms), subtle and easing in/out. Use them to communicate state changes (e.g., a pulse on the logo when an agent runs). Never use bouncing or elastic effects.
Accessibility

The system must meet at least WCAG 2.2 AA contrast requirements. Colour contrast for text against backgrounds must be sufficient in both dark and light themes; dark mode uses light text and subtle borders, while light mode uses dark text and subtle shadows to maintain separation. All interactive elements must be navigable via keyboard, with visible focus indicators (e.g., a 2 px outline using the appropriate accent colour). Avoid low‑contrast text or hidden focus states. Provide descriptive labels and ensure pointer targets are at least 44 × 44 px.

Writing Tone

UI copy should be concise, confident and implementation‑focused. Use technical language that resonates with developers and power users. Avoid hype or marketing language. When summarising execution, prefix log entries with J> to reinforce the agent’s identity (e.g., J> initializing tools…).

Component Guidelines

This section defines anatomy, variants and states for common components. Each rule uses semantic tokens and covers default, hover, focus, active and disabled states.

Buttons

Primary button

Default – Text colour bg on accent background; padding: 12 px vertical, 16 px horizontal; radius‑medium corners.
Hover – Lightly darken the background (e.g., apply 8 % black overlay).
Active – Pressed state uses a slightly smaller scale (96 %) and darker background.
Disabled – Lower opacity to 40 % and switch text colour to text‑tertiary.

Secondary button

Transparent background (surface), 1 px border using border token (rgba(255,255,255,0.06)).
On hover, surface darkens slightly; on focus, apply a 2 px outline in accent.

Ghost button

Text‑only button for low‑emphasis actions. Use text‑secondary colour with no border. On hover, change text to text‑primary.
Inputs
Container – Use surface background with radius‑medium and 1 px border using border token.
Text – Use text‑primary for user input; placeholder text uses text‑tertiary.
Focus – Apply a 2 px outline in accent and drop the border colour; maintain high contrast.
Disabled – Decrease opacity and switch text to text‑tertiary.
Cards and Panels

Cards are used sparingly; our UI favours flat surfaces. When required (e.g., for knowledge documents or logs):

Background – Use surface for the card body; do not add shadows.
Border – 1 px border using border token. This creates separation without elevation.
Radius – Use radius‑large (8 px) to soften edges subtly.
Padding – 16 px internal padding on all sides.
Execution Timeline & Logs

The timeline is the hero element. It should read like a narrative. Use the mono font and prefix each line with J> to reflect the agent. Distinguish log types via colour: successes in success, errors in error, warnings in warning. Logs flow in a single column with 4 px vertical spacing and no bounding box. When a task runs, highlight the current step by increasing its brightness or adding a subtle animation.

Navigation (Sidebar)
Use surface‑2 for the background. Text labels use text‑secondary with increased tracking. Selected items should have a 2 px accent‑coloured bar on the left and a surface background.
Icons are outline style (1.5 px stroke) from the Lucide set to match the system aesthetic. Avoid filled icons. Size: 18 px.
Command Palette

The command palette is a floating panel used to launch agents or commands. It uses the surface colour with a border token. Input text uses the mono font. List items highlight on hover with an accent background at 4 % opacity. Keyboard shortcut hints appear in text‑tertiary aligned right.

Agent Cards

Agents are first‑class objects. Represent each agent with a minimal card containing its name, tools, last run timestamp and status. Use surface background, radius‑large, 1 px border token and 16 px padding. Actions (Run, Configure) appear as secondary buttons inside the card.

Forms and Task Definitions

Our new UX emphasises structured task definitions rather than free‑form chat. Use labelled input groups aligned on a vertical grid. Provide fields for goal, context, tools and mode. Keep labels top‑aligned and set to text‑secondary. Use 8 px vertical gaps between fields and 24 px below the group. The Run button should float at the bottom right of the form.

Accessibility Acceptance Criteria

For every component, the following must hold:

Colour contrast for text and interactive elements meets or exceeds WCAG 2.2 AA (contrast ratio ≥ 4.5:1 for normal text and 3:1 for large text). Avoid low‑contrast combinations.
Every interactive element has a visible focus indicator using the accent token.
Components are operable via keyboard and pointer, with focus order matching the visual order.
Label form controls explicitly and provide aria‑attributes where necessary.
Responsive behaviour should preserve readability and touch targets across breakpoints. The design uses fluid layouts; avoid fixed widths.
Anti‑Patterns
Do not introduce custom colours or random accents. Always refer to the semantic tokens defined above.
Do not use drop shadows, glassmorphism or gradients. Our aesthetic relies on flat surfaces and subtle borders.
Avoid low‑contrast text or hidden focus indicators.
Do not add one‑off spacing or typography exceptions. Stick to the spacing and type scales.
Do not use ambiguous labels or non‑descriptive actions.
QA Checklist

Use this checklist to verify new screens adhere to the design system:

All colours are derived from semantic tokens. No raw hex values are used except in token definitions. Tokens exist for both dark and light themes; ensure you use the correct set for the current theme.
Typography uses only the defined fonts, weights and sizes. Mono font is used for logs and code.
Spacing follows the 8 pt grid; no arbitrary values.
Buttons, inputs and cards adhere to the radius tokens and state definitions (default, hover, focus, active, disabled).
Accessibility criteria are met: sufficient contrast, visible focus, keyboard operable controls.
Logs and execution steps use the mono font and J> prefix; statuses apply the correct semantic colour.
Micro‑interactions (hover, focus, animations) are subtle and respect the timing guidelines.
The design remains responsive and maintains readability on smaller viewports.