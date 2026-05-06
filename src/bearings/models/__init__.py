"""Pydantic request / response models.

One module per resource, mirroring :mod:`bearings.db.queries`. Models
declare the wire shape: what HTTP clients send (``*Create`` /
``*Update``), what they receive (``*Response``), and how list endpoints
wrap pages (``*List``).

Validation rules belong here. The service layer trusts that anything
entering it through a Pydantic model is shape-clean; the model class
has already enforced types, ranges, regex patterns, and ``extra=forbid``.
"""
