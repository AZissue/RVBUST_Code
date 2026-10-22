"""Presentation action contract. Names describe intent, never widget structure.

A redesigned view implements the same signals and result methods; these bindings
and the business controller remain unchanged. Validation precedes connection.
"""
MULTI_ACTIONS = (
    ("capture_requested", "_on_multi_capture"),
    ("detect_requested", "_on_multi_detect"),
    ("calibrate_requested", "_on_multi_calibrate"),
    ("calibration_visualization_requested", "_on_multi_visualize_calibration"),
    ("save_extrinsics_requested", "_on_multi_save_extrinsics"),
    ("load_extrinsics_requested", "_on_multi_load_extrinsics"),
    ("capture_scan_requested", "_on_multi_capture_scan"),
    ("stitch_save_requested", "_on_multi_stitch_save"),
    ("batch_scan_requested", "_on_multi_batch_scan"),
    ("reference_changed", "_on_multi_reference_changed"),
    ("step_back_requested", "_on_multi_step_back"),
    ("card_preview_toggled", "_on_card_preview_toggled"),
    ("card_capture_requested", "_on_card_capture"),
    ("card_detect_requested", "_on_card_detect"),
)
MOBILE_ACTIONS = (
    ("capture_station_requested", "_on_mobile_capture_station"),
    ("preview_toggled", "_on_mobile_preview_toggled"),
    ("undo_requested", "_on_mobile_undo"),
    ("recapture_requested", "_on_mobile_recapture"),
    ("delete_station_requested", "_on_mobile_delete_station"),
    ("optimize_requested", "_on_mobile_optimize"),
    ("save_requested", "_on_mobile_save"),
    ("offline_load_requested", "_on_mobile_offline_load"),
    ("station_selected", "_on_mobile_station_selected"),
)
SHELL_ACTIONS = (
    ("save_session_requested", "_on_save_session"),
    ("open_session_requested", "_on_open_session"),
    ("param_debug_requested", "_on_param_debug"),
)


def validate_actions(view, controller, actions):
    for signal_name, slot_name in actions:
        if not callable(getattr(getattr(view, signal_name, None), "connect", None)):
            raise TypeError(f"{type(view).__name__} lacks signal {signal_name}")
        if not callable(getattr(controller, slot_name, None)):
            raise TypeError(f"{type(controller).__name__} lacks handler {slot_name}")


def connect_actions(view, controller, actions):
    validate_actions(view, controller, actions)
    for signal_name, slot_name in actions:
        getattr(view, signal_name).connect(getattr(controller, slot_name))
