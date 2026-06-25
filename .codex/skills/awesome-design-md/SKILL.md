---
name: awesome-design-md
description: Use when the user wants to apply, choose, fetch, or reason about DESIGN.md design-system documents from VoltAgent/awesome-design-md or getdesign.md; useful for making UI match a named product/site design language while preserving existing app behavior.
---

# Awesome DESIGN.md

This project-local skill wraps the usage model from `VoltAgent/awesome-design-md`.

The upstream repository is not itself a Codex skill: it is a curated collection of `DESIGN.md` files. The intended workflow is to choose a design language, copy or fetch its `DESIGN.md`, and have Codex use that markdown design system when implementing UI.

## Core Workflow

1. Identify the desired design language:
   - If the user names a product/site, use that specific design.
   - If the user describes a style, choose the closest matching DESIGN.md from the collection.
   - If the choice materially affects the result, ask the user to choose between 2-3 concrete candidates.
2. Fetch or read the relevant `DESIGN.md`.
   - Collection landing page: `https://github.com/VoltAgent/awesome-design-md`
   - Individual design docs are usually available at `https://getdesign.md/<slug>/design-md`.
3. Treat `DESIGN.md` as visual guidance, not as permission to break the app.
   - Preserve existing product functionality, routes, IDs, forms, APIs, and state flows unless the user explicitly asks to change them.
   - Apply layout, typography, spacing, color, component styling, motion, and interaction principles from the design document.
4. For existing projects, map the chosen design language onto the current app:
   - Keep domain-specific content and workflows.
   - Replace generic styling with design-system-aligned surfaces, buttons, inputs, cards, tables, and empty/loading/error states.
   - Verify responsive behavior and text fit after implementation.

## Candidate Selection Hints

Use these examples when the user gives a broad style request:

- Minimal white, precise, deployment/product UI: `vercel`
- Clean developer documentation: `mintlify`, `replicate`
- Enterprise data/dashboard feel: `cohere`, `ibm`
- Technical blueprint/system feel: `together.ai`
- Premium Apple-like white space: `apple`
- Dark terminal/developer aesthetic: `warp`, `opencode.ai`, `vercel`
- Futuristic black-and-white: `x.ai`, `spacex`
- Friendly SaaS/productivity: `linear.app`, `notion`, `cal`

## Implementation Rules

- Do not blindly copy marketing-page structure into operational tools. For dashboards, upload flows, and internal systems, keep the first screen usable and task-focused.
- Use the chosen DESIGN.md to inform visual language, but keep accessibility, readability, and workflow clarity ahead of spectacle.
- If generating assets, save project-bound assets into the workspace and update references; do not leave them only in a temporary or global generated-images directory.
- When a UI already has JavaScript behavior, preserve element IDs, names, and event hooks unless the plan explicitly includes updating the behavior.

## Validation

After applying a DESIGN.md-driven redesign:

- Render or run the affected pages.
- Verify key workflows still work.
- Check desktop and mobile breakpoints.
- Confirm no major text overlap, clipped controls, or hidden primary actions.
- Summarize which DESIGN.md or style source was applied.
