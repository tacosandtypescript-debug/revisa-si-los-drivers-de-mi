---
version: alpha
name: "iPhone Wi-Fi Transfer"
description: "Una pequeña estación de transferencia local: silenciosa en reposo y muy legible durante una subida."
colors:
  primary: "#67B8FF"
  primaryStrong: "#1769E0"
  background: "#0D121B"
  surface: "rgba(13, 18, 27, 0.70)"
  text: "#F3F8FF"
  muted: "#B1BDC9"
  border: "rgba(232, 240, 248, 0.42)"
  success: "#58DB91"
  danger: "#FF6E78"
  neutral: "#778494"
typography:
  sans:
    fontFamily: "Bahnschrift, Segoe UI, system-ui, sans-serif"
    fontSize: "12px"
    lineHeight: "1.2"
  mono:
    fontFamily: "Cascadia Mono, Consolas, ui-monospace, monospace"
    fontSize: "9px"
    lineHeight: "1.2"
rounded:
  DEFAULT: "16px"
  sm: "5px"
  md: "10px"
spacing:
  window-width: "500px"
  window-height: "580px"
  inset: "28px"
components:
  trayWindow:
    backgroundColor: "#0D121B"
    textColor: "#F3F8FF"
    rounded: "0px"
    width: "500px"
    height: "580px"
  progressRing:
    size: "132px"
    backgroundColor: "rgba(232, 240, 248, 0.13)"
    textColor: "#67B8FF"
  qrCode:
    size: "220px"
    backgroundColor: "#F3F8FF"
  uploadPage:
    width: "680px"
    backgroundColor: "#F4F6F8"
    textColor: "#17202A"
---

# iPhone Wi-Fi Transfer Design System

## Overview

### Creative North Star

The visual reference is a small Windows desktop instrument: a dark, solid readout with one prominent machine-readable handoff mark, one circular gauge, and a clear native title bar. It should feel like a quiet piece of workshop equipment rather than a miniature dashboard.

### Product context and register

- **Audience and primary job:** One Windows user who wants to start a local iPhone video transfer and understand its state at a glance.
- **Target market(s) and evidence:** Personal/local utility; no market-specific claims or regulated domain.
- **Locale(s) and language policy:** Spanish UI, with filenames and URLs preserved exactly as supplied by the system.
- **Usage scene:** A normal Windows desktop window beside other work, with the iPhone upload page open on the same private Wi-Fi network.
- **Register:** Product utility; the Electron overlay is platform-native in behavior and deliberately restrained in content.
- **Memorable signature:** The large QR is the handoff mark; the progress ring is the status light beside it: blue while moving, green when committed, red when recovery is needed.
- **Restraint:** Native Windows chrome carries minimize/maximize/close. Inside the window there is one purposeful action, `Copiar URL`, plus the QR and state readout.
- **Anti-references:** Not a generic rounded SaaS card, neon gaming HUD, or full-size media manager; those patterns would compete with the file transfer itself.
- **Token ownership/runtime mapping:** This file is the visual source of truth. Electron tokens are implemented in `electron/renderer/styles.css`; the upload page keeps the same semantic blue/green/red roles in its local CSS because it is served as a standalone mobile surface.

## Colors

The Electron window uses `background` as a solid charcoal surface so the QR stays crisp and the native Windows frame remains legible. `text` is reserved for the current filename and status; `muted` carries speed, count, and the URL. `neutral` is the empty ring, `primary` is the active transfer, `success` is a committed file, and `danger` is a failed transfer. Color is always paired with text state and percentage; no state relies on color alone.

## Typography

`Bahnschrift`/`Segoe UI` gives the Windows overlay a compact instrument-label voice without shipping a font. Filenames use the sans role with ellipsis; speed and the base URL use the mono role so changing digits do not visually wander. System fallbacks keep the Spanish UI and arbitrary iPhone filenames readable.

## Layout

The Electron content surface starts at 500×580px inside a native Windows frame. The QR occupies the left handoff panel and the ring occupies the right readout; the URL and one copy action anchor the bottom. The page reports its measured height through IPC within a bounded desktop range so state changes do not move the window. The phone upload page is a single-column, document-scrolling surface with a visible picker and stable progress bar.

## Elevation & Depth

Depth comes from the solid charcoal field, quiet raised panels, thin light borders, and one restrained blue focus accent. The desktop surface does not use cards inside cards or heavy gradients. The phone page uses ordinary light panels because it is a touch-oriented upload surface, not the Windows instrument.

## Shapes

The native window owns the outer frame shape. Inside, the desktop surface uses 14px panels, a 6px QR radius, and a circular gauge. Long filenames are clipped with an ellipsis rather than allowed to change the window footprint. The upload page uses 10px controls and 16px panels to preserve touch affordance.

## Components

### Foundational visual states

- **Reposo:** neutral empty ring, `Listo`, full URL, QR visible, and `Copiar URL` available.
- **Subiendo:** blue determinate ring, current filename, speed, and `índice de total`.
- **Terminado:** green full ring with the last file and measured speed.
- **Error:** red ring and text naming the failed server condition.
- Reduced motion removes ring transitions while preserving the state change.

### Buttons and actions

The native Windows title bar owns minimize, maximize, and close. The desktop surface exposes one semantic button, `Copiar URL`, while the tray keeps the three system actions: copy URL, show QR, and close. The mobile upload page uses one primary submit action and per-file `Quitar` actions with native button semantics.

### Navigation and data display

There is no navigation shell or table. The only data display is a bounded status readout and a per-file upload queue on the phone page.

### Forms and overlays

The phone page uses a native file picker because Photos ownership belongs to iOS. Client validation is immediate; server validation remains authoritative. The Electron window is non-modal, uses native Windows chrome, and keeps its one clipboard action explicit.

### Iconography

The tray icon is a minimal ring-and-core mark matching the progress gauge. The QR is generated locally with `qrcode`; no remote asset or network service is used.

### Motion

The ring fills linearly with measured bytes. Color transitions are short and state-driven. There are no decorative loops, and `prefers-reduced-motion` disables the transition.

### Content and data visualization

Copy is direct and Spanish: `Listo`, `Subiendo`, `MB/s`, and `2 de 5`. The percentage is a determinate progress value based on the current raw request's `Content-Length`; the server's `/api/estado` is the authoritative desktop readout.

## Do's and Don'ts

- **Do:** Keep the filename, speed, and batch position stable in their reserved readout slots.
- **Do:** Pair blue/green/red with explicit text and numeric progress.
- **Don't:** Add buttons or dashboard chrome inside the 160×130 overlay.
- **Don't:** Send QR generation, upload data, or status polling through an external service.
