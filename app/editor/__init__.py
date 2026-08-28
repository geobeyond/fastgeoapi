"""Configuration editor: the authoring surface (ADR-0008).

Kept apart from the serving surface on purpose: writing a configuration
and activating it are different powers, and a dry run empties the
process caches — beside a live server it would degrade what it serves.
"""
