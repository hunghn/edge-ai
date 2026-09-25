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
DUPLICATE_TITLE = "Khuôn mặt này đã có trong hệ thống"
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

# The duplicate screen. Names are never shown: the nurse has to answer "is this the same
# person", and the face answers that - the other patient's name is not theirs to read.
DUPLICATE_HINT = "So sánh khuôn mặt bên dưới. Nếu là cùng một người, hãy huỷ và tra cứu mã cũ."
DUPLICATE_UNCALIBRATED = "Ngưỡng so khớp chưa hiệu chuẩn — đây là những người gần nhất, không phải kết luận."
DUPLICATE_NO_PHOTO = "chưa có ảnh"
DUPLICATE_MASKED_NAME = "Tên: ***"
BTN_SAVE_ANYWAY = "Vẫn lưu"
LABEL_LOOKALIKE = "Người gần nhì"
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
    "fps": "Tốc độ khung",
    "ram": "RAM đang dùng",
    "temp": "Nhiệt độ",
}
NEVER = "chưa có"


def guidance(code):
    return GUIDANCE.get(code, GUIDANCE_DEFAULT)


def decision_title(value):
    return DECISION_TITLE.get(value, DECISION_TITLE["review_required"])


def decision_hint(value):
    return DECISION_HINT.get(value, DECISION_HINT["review_required"])


# ---------------------------------------------------------------- the redesign
# The five gates, as a patient would describe them. The stepper turns four seconds of
# silence into something that is visibly happening.
STEP_LABELS = (
    "Thấy khuôn mặt",
    "Khoảng cách và vị trí",
    "Nhìn thẳng",
    "Chất lượng ảnh",
    "So khớp danh sách",
)
ENROLL_STEPS = ("Thông tin", "Chụp ảnh", "Xem lại và lưu")

CLINIC_DEFAULT = "Phòng khám"
IDLE_LEAD = "Mời bệnh nhân đứng vào giữa khung hình, cách màn hình khoảng một sải tay."
IDLE_CHIP_MASK = "Không đeo khẩu trang"
IDLE_CHIP_LOOK = "Nhìn thẳng vào camera"
IDLE_FOOT = "Nhân viên sẽ xác nhận trước khi bạn vào phòng khám."
IDLE_OFFLINE = "Hoạt động cả khi mất mạng"
COLLECTING_LABEL = "Đang lấy ảnh"
HOLD_A_MOMENT = "Giữ yên khoảng một giây rưỡi"

CAMERA_TAG = "CAM 01"
FPS_TAG = "{fps:.1f} fps"
QUALITY_TAG = "chất lượng {value:.2f}"
BEST_FRAME_TAG = "khung tốt nhất"
CHOSEN_FRAME = "Ảnh đã chọn"
SCORE_DETAIL = "Chi tiết so khớp"
LABEL_MARGIN_SHORT = "Cách BN thứ hai"
LABEL_LOOKALIKE_SHORT = "Người gần nhì"

# Why a frame was turned away, next to the threshold it missed.
REJECTED_BECAUSE = "Khung hình bị loại vì"
METRIC_BLUR = "Độ nét"
METRIC_LUM = "Độ sáng"
METRIC_POSE = "Góc nghiêng"
METRIC_PASSED = "{value} đạt"
METRIC_BELOW = "{value} < {limit}"
METRIC_ABOVE = "{value} > {limit}"
GOOD_FRAMES = "{good}/{total} khung đạt"

SPOOF_HEADLINE = "Nghi ngờ dùng ảnh in hoặc màn hình"
SPOOF_TODO = "Việc cần làm"
SPOOF_STEPS = (
    "1 · Nhìn trực tiếp: người thật hay ảnh, điện thoại, máy tính bảng?",
    "2 · Nếu là người thật, mời đứng lại và bấm Thử lại.",
    "3 · Nếu không, không xác nhận và báo quản lý ca.",
)
SPOOF_NO_DETAILS = "Không hiển thị thông tin bệnh nhân ở màn hình này."
SPOOF_EVIDENCE = "Ảnh bằng chứng đã lưu trên máy này"

NO_MATCH_HEADLINE = "Chưa tìm thấy bệnh nhân phù hợp"
NO_MATCH_LEAD = ("Khuôn mặt này không khớp với ai trong {count} bệnh nhân đã tải về máy "
                 "hôm nay. Có thể bệnh nhân chưa đăng ký khuôn mặt, hoặc lịch hẹn chưa "
                 "được đồng bộ.")
BTN_ENROLL_LOCKED = "Đăng ký mới · cần PIN"
GALLERY_TAG = "gallery v{version} · {count} BN"

SEARCH_HINT_SHORT = "mã hoặc tên không dấu"
SEARCH_COUNT = "{count} bệnh nhân hôm nay"
BTN_CHOOSE = "Chọn"
SEARCH_ROW_SUB = "{code} · {year}"

ERROR_HEADLINE = "Chưa nhận diện được lúc này"
ERROR_LEAD = ("Không nhận được tín hiệu từ bộ nhận dạng. Mời bệnh nhân làm thủ tục tại "
              "quầy như bình thường.")
ERROR_NO_DATA = "Dữ liệu bệnh nhân không hiển thị khi hệ thống đang lỗi"
ERROR_RETRYING = "tự thử lại mỗi 5 giây"
SUPPORT_CALL = "Gọi kỹ thuật · đọc mã {code}"
LAST_SEEN = "lần cuối {at}"
SILENT_FOR = "mất tín hiệu {seconds}s"
PAGE_TITLE_GUIDING = "Đang nhận dạng"
SESSION_TAG = "Phiên {short}"


# The supporting line under each number on the status screen. A bare "0" does not say
# whether it is good news.
HEARTBEAT_AGO = "nhịp tim {s} giây trước"
FPS_TARGET = "mục tiêu 10–15 khung/giây"
GALLERY_FOOT = "danh sách khuôn mặt trên máy"
PATIENTS_FOOT = "bản sao 24 giờ của hôm nay"
OUTBOX_EMPTY = "không còn gì chờ gửi"
OUTBOX_WAITING = "cũ nhất đã chờ {s} giây"
MINUTES_AGO = "{n} phút trước"
DISK_FOOT = "còn trống {pct}%"
RAM_FOOT = "trên {total} MB"
TEMP_FOOT = "vùng nóng nhất"
BTN_SYNC_NOW = "Đồng bộ ngay"
SYNC_REQUESTED = "Đã yêu cầu đồng bộ."

# Patient rows
SOURCE_KIOSK = "đăng ký tại kiosk"
SOURCE_SERVER = "tải từ server"
TEMPLATE_COUNT = "{n} đặc trưng"
EXPIRES_AT = "hết hạn {at}"
PIN_CHANGED_AGO = "đổi lần cuối {n} ngày trước"
PIN_NEVER_CHANGED = "chưa đổi lần nào"
ADMIN_AUTOLOCK_CHIP = "Tự khoá sau {mmss}"
ENROLL_CARD_HINT = "Điền thông tin rồi chụp 5 ảnh"

# Revoking, as a question that has to be answered on its own.
REVOKE_TITLE = "Thu hồi bệnh nhân {code}?"
REVOKE_BODY = ("Đặc trưng khuôn mặt của {name} sẽ bị xoá khỏi máy này và ghi vào danh "
               "sách thu hồi. Không hoàn tác được tại kiosk.")
BTN_REVOKE_CONFIRM = "Xoá khỏi máy này"

# Enrolment
ENROLL_SHOTS = "Ảnh đã lấy"
ENROLL_TURN_LEFT = "Mời bệnh nhân xoay nhẹ sang trái rồi sang phải."
ENROLL_NOT_STORED = "Ảnh chỉ dùng để trích đặc trưng, không lưu vào máy"
ENROLL_SUMMARY = "Xem lại trước khi lưu"
ENROLL_CONSISTENCY = "Độ đồng nhất giữa các ảnh"
ENROLL_TEMPLATES = "Đặc trưng lưu lại"
ENROLL_EXPIRES = "Hết hạn trên máy"
ENROLL_OPERATOR = "Người đăng ký"
ENROLL_NO_DUPLICATE = "Không tìm thấy khuôn mặt nào gần giống trong danh sách hiện có."
BTN_ENROLL_RETAKE = "Chụp lại"
BTN_ENROLL_CANCEL = "Huỷ đăng ký"
BTN_BACK_TO_MENU = "Quay lại menu"

# The duplicate warning, side by side.
DUPLICATE_NEW = "Ảnh vừa chụp"
DUPLICATE_NEAREST = "Gần nhất trong hệ thống"
DUPLICATE_SECOND = "Gần thứ hai"
BTN_SAVE_ANYWAY_LONG = "Vẫn lưu hồ sơ mới"
BTN_CANCEL_AND_LOOKUP = "Huỷ và tra mã cũ"
PATIENTS_ACTIVE_SHORT = "{n} đang hoạt động"
FROM_KIOSK = "{n} đăng ký tại kiosk"
ENGINE_IS = "Engine {state}"
OUTBOX_PENDING = "{n} sự kiện chờ gửi"
BOARD_NAME = "Jetson Nano 4GB"
DUPLICATE_NEW_TAG = "hồ sơ mới"
