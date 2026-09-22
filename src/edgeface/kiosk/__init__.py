"""Kiosk process: the touchscreen shared by the patient and the nurse.

Logic lives in controller.py, view_model.py and auth.py, none of which import Qt, so the
whole flow is testable without a display. window.py and screens/ only draw.
"""
