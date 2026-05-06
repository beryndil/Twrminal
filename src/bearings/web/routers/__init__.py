"""Per-resource routers.

One module per HTTP-exposed resource. The app factory imports each
router and includes it on the FastAPI app. Plugins added by §15 will
hook in here via a registry — same shape, additional source — without
reshuffling existing routes.
"""
