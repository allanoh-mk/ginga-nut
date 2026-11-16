# ADR 0001: Shared radius scale

Status: accepted

## Context

The interface has scattered 4px and 6px radii and some square controls. New flow
surfaces need a consistent geometry while table cells and hairline dividers remain square.

## Decision

Use CSS custom properties `--radius-xs: .25rem`, `--radius-sm: .375rem`,
`--radius-md: .5rem`, `--radius-lg: .75rem`, and `--radius-xl: 1rem` for interactive
and container surfaces. Listing tiles use `--radius-md`. Full-bleed sections and table
cells stay square; circular avatars use `50%`. Rounded image containers clip their contents.

## Consequences

Existing component radii will be migrated to the scale as pages are reconciled. Admin
surfaces use the same tokens. No feature surface may use a zero radius.
