# Cortex Platform Styles Reference

This directory contains reference styles extracted from the Cortex XSIAM platform for alignment purposes.

## Files

- `login.css` - Main stylesheet from the Cortex login page, including:
  - CSS custom properties (CSS variables) for the dark theme
  - Color palette definitions
  - Component styles
  - Layout and typography styles

## Fonts

The platform uses the **Lato** font family from Google Fonts:
- Font weights: 100, 400, 700
- Fallback: "Assistant", sans-serif

To include the fonts in your project, add this to your HTML:
```html
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Lato:wght@100;400;700&display=swap" rel="stylesheet">
```

## Color Palette

The styles use CSS custom properties (variables) defined in the `.xdr-dark-theme` class. Key colors include:

- **Primary**: `#128df3` (blue)
- **Background**: `#1f1f1f` (dark gray)
- **On Background**: `#eaebeb` (light gray)
- **Surface**: `#151515` (darker gray)
- **Border**: `#484848` (medium gray)
- **Link**: `#128df3` (blue)

## Usage

To use these styles, apply the `.xdr-dark-theme` class to your root element (e.g., `<body>` or a container).

## Source

Extracted from: https://077a95d2a-b8c1.xdr.ca.paloaltonetworks.com/dashboard?id=3
Date: Extracted on request for project alignment


