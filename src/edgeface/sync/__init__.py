"""Sync process: push the outbox, pull the gallery, verify model bundles.

Offline-first: everything here may fail, and when it does the kiosk keeps identifying
patients with the gallery it already has. Nothing in the pipeline waits on the network.
"""
