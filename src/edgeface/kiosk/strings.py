# -*- coding: utf-8 -*-
"""Every piece of text the kiosk shows, in Vietnamese, in one place.

Patients read the guidance lines, so they are short and say what to DO. Nurses read the
candidate card and the admin screens, which can be denser.
"""

APP_TITLE = "Định danh bệnh nhân"

# Screen titles
IDLE_TITLE = "Xin chào"
IDLE_HINT = "Vui lòng đứng vào khung hình"
GUIDING_TITLE = "Đang nhận dạng"
COLLECTING_HINT = "Giữ yên trong giây lát"
CANDIDATE_TITLE = "Xác nhận bệnh nhân"
ALERT_TITLE = "Cần nhân viên hỗ trợ"
SEARCH_TITLE = "Tìm bệnh nhân"
PIN_TITLE = "Nhập mã PIN"
ADMIN_TITLE = "Quản trị"
ENROLL_TITLE = "Đăng ký khuôn mặt"
PATIENTS_TITLE = "Bệnh nhân hôm nay"
STATUS_TITLE = "Trạng thái hệ thống"
CHANGE_PIN_TITLE = "Đổi mã PIN"
ERROR_TITLE = "Hệ thống tạm dừng"

# One line per guidance code from the pipeline. Phrased as an instruction.
GUIDANCE = {
    "NO_FACE": "Vui lòng đứng vào khung hình",
    "STEP_CLOSER": "Vui lòng đứng gần hơn",
    "MOVE_TO_CENTER": "Vui lòng đứng vào giữa khung",
    "LOOK_STRAIGHT": "Vui lòng nhìn thẳng vào camera",
    "HOLD_STILL": "Vui lòng giữ yên",
    "TOO_DARK": "Chỗ đứng quá tối, vui lòng nhích lên phía trước",
    "TOO_BRIGHT": "Ánh sáng quá chói, vui lòng nhích sang một bên",
    "SPOOF_SUSPECT": "Vui lòng chờ nhân viên",
    "INVALID_BBOX": "Vui lòng đứng vào khung hình",
    "EMBED_INVALID": "Vui lòng thử lại",
    "CAMERA_ERROR": "Camera gặp sự cố",
}
GUIDANCE_DEFAULT = "Vui lòng nhìn thẳng vào camera"

# What each decision means on screen.
DECISION_TITLE = {
    "review_required": "Vui lòng kiểm tra thông tin",
    "spoof_suspect": "Nghi ngờ giả mạo khuôn mặt",
    "low_quality": "Chưa lấy được ảnh đạt yêu cầu",
    "candidate_suggested": "Đã tìm thấy bệnh nhân",
    "no_match": "Không có trong danh sách hôm nay",
}
DECISION_HINT = {
    "review_required": "Hệ thống chưa đủ chắc chắn. Điều dưỡng vui lòng đối chiếu trước khi xác nhận.",
    "spoof_suspect": "Phát hiện dấu hiệu dùng ảnh in hoặc màn hình. Vui lòng kiểm tra trực tiếp.",
    "low_quality": "Ảnh chưa đạt chất lượng. Mời bệnh nhân thử lại.",
    "candidate_suggested": "Điều dưỡng vui lòng xác nhận để hoàn tất.",
    "no_match": "Không tìm thấy bệnh nhân phù hợp. Vui lòng tìm thủ công hoặc đăng ký mới.",
}

# Buttons
BTN_CONFIRM = "Xác nhận"
BTN_REJECT = "Không phải"
BTN_RETRY = "Thử lại"
BTN_SEARCH = "Tìm thủ công"
BTN_CANCEL = "Huỷ"
BTN_BACK = "Quay lại"
BTN_OK = "Đồng ý"
BTN_ADMIN = "Quản trị"
BTN_ENROLL_START = "Bắt đầu chụp"
BTN_ENROLL_SAVE = "Lưu bệnh nhân"
BTN_REVOKE = "Thu hồi"
BTN_LOGOUT = "Thoát quản trị"
BTN_CHANGE_PIN = "Đổi PIN"

# The admin menu. These four are the whole reason the admin screen exists, so they are
# plain buttons on the landing screen rather than anything the nurse has to discover.
BTN_MENU_ENROLL = "Đăng ký bệnh nhân mới"
BTN_MENU_PATIENTS = "Bệnh nhân hôm nay"
BTN_MENU_STATUS = "Trạng thái hệ thống"

# Labels
LABEL_CODE = "Mã bệnh nhân"
LABEL_NAME = "Họ và tên"
LABEL_BIRTH_YEAR = "Năm sinh"
LABEL_APPOINTMENT = "Mã lịch hôm nay"
LABEL_CONFIDENCE = "Mức khớp"
LABEL_SEARCH = "Nhập mã hoặc tên bệnh nhân"
LABEL_PROGRESS = "Đã chụp {done}/{total} ảnh"

# The word stays: it is what a nurse reads at a glance. The numbers sit above it for
# whoever wants to look closer, and can be switched off with kiosk.show_score for a
# clinic deployment. They are cosine similarities, not probabilities - never write them
# as a percentage, which would promise an accuracy the uncalibrated system cannot claim.
CONFIDENCE_HIGH = "Khớp cao"
CONFIDENCE_LOW = "Cần kiểm tra"
LABEL_SCORE = "Điểm khớp"
LABEL_MARGIN = "Cách BN thứ hai"

# PIN / admin
PIN_HINT = "Nhập mã PIN {digits} chữ số"
PIN_WRONG = "Mã PIN không đúng. Còn {left} lần thử."
PIN_LOCKED = "Đã khoá. Vui lòng thử lại sau {seconds} giây."
ADMIN_LOCKED_HINT = "Màn hình quản trị tự khoá sau {seconds} giây không thao tác."

# Changing the PIN. Three steps, because a typo in step two would lock the nurse out of
# the kiosk with no way back in from the kiosk itself.
CHANGE_PIN_OLD = "Nhập mã PIN hiện tại"
CHANGE_PIN_NEW = "Nhập mã PIN mới"
CHANGE_PIN_REPEAT = "Nhập lại mã PIN mới"
CHANGE_PIN_MISMATCH = "Hai lần nhập không giống nhau. Vui lòng nhập lại."
CHANGE_PIN_WRONG_OLD = "Mã PIN hiện tại không đúng."
CHANGE_PIN_BAD_FORMAT = "Mã PIN phải gồm {digits} chữ số."
CHANGE_PIN_SAVED = "Đã đổi mã PIN."

# Revoking a patient
REVOKE_PICK = "Chọn một bệnh nhân trong danh sách để thu hồi."
REVOKE_CONFIRM = "Thu hồi bệnh nhân {code}? Dữ liệu khuôn mặt sẽ bị xoá khỏi máy này."
REVOKE_DONE = "Đã thu hồi bệnh nhân {code}."
PATIENTS_EMPTY = "Chưa có bệnh nhân nào được đăng ký hôm nay."

# Enrollment
ENROLL_DUPLICATE = "Khuôn mặt này giống bệnh nhân {code}. Vui lòng kiểm tra kỹ trước khi lưu."
ENROLL_DUPLICATE_UNKNOWN = "Bệnh nhân giống nhất hiện có: {code}. Ngưỡng so khớp chưa hiệu chuẩn."
ENROLL_INCONSISTENT = "Các ảnh chụp không đồng nhất. Nên chụp lại."
ENROLL_ERRORS = {
    "timeout": "Hết thời gian chụp. Vui lòng thử lại.",
    "missing_form": "Thiếu thông tin bệnh nhân.",
    "missing_patient_code": "Vui lòng nhập mã bệnh nhân.",
    "missing_full_name": "Vui lòng nhập họ tên.",
    "bad_birth_year": "Năm sinh không hợp lệ.",
}
ENROLL_SAVED = "Đã lưu bệnh nhân {code}."

# System status
STATUS_ENGINE_DOWN = "Không nhận được tín hiệu từ engine. Vui lòng gọi kỹ thuật."
STATUS_CAMERA = "Camera gặp sự cố. Vui lòng gọi kỹ thuật."
STATUS_ROWS = {
    "gallery": "Phiên bản gallery",
    "patients": "Bệnh nhân đang hoạt động",
    "outbox": "Sự kiện chờ gửi",
    "last_sync": "Lần đồng bộ gần nhất",
    "disk_free": "Dung lượng trống",
    "engine_state": "Trạng thái engine",
}
NEVER = "chưa có"


def guidance(code):
    return GUIDANCE.get(code, GUIDANCE_DEFAULT)


def decision_title(value):
    return DECISION_TITLE.get(value, DECISION_TITLE["review_required"])


def decision_hint(value):
    return DECISION_HINT.get(value, DECISION_HINT["review_required"])
