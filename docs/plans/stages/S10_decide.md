# S10 — Quyết định (rule engine)

**Milestone:** M5 (task M5-T11) · **Module:** `src/edgeface/pipeline/decision.py`

## 1. Mục tiêu
Tổng hợp kết quả S4 (spoof cấp phiên), S5/S8 (chất lượng) và S9 (so khớp) thành **một quyết định enum** kèm lý do, để kiosk hiển thị. **Luôn có nút xác nhận thủ công của điều dưỡng**; hệ thống không bao giờ tự cho bệnh nhân vào.

## 2. Input / Output
- **Input:**
  - `SessionEvidence`: `spoof_frames`, `k_frames`, `min_p_real`, `collector_status (READY | LOW_QUALITY)`, `n_good`, `MatchResult | None`
  - config `decision.*`, `match.*`, `antispoof.*`
- **Output:** `DecisionResult(decision: Decision, rule_id: str, candidate: {code, score, margin, votes} | None, requires_nurse: True)`.

## 3. Thiết kế

### 3.1 Enum Decision
Spec (§6.3) chưa có danh sách đầy đủ; chỉ có `spoof_suspect`, `low_quality`, `review_required`. **Đề xuất (D-04, chưa áp dụng):**

| Giá trị | Ý nghĩa trên kiosk | Có trong spec? |
|---|---|---|
| `spoof_suspect` | Cảnh báo, gọi điều dưỡng, có ảnh bằng chứng | Có |
| `low_quality` | "Vui lòng thử lại", không hiện ứng viên | Có |
| `review_required` | Hiện ứng viên top1 (nếu có) với nhãn "độ tin cậy thấp", điều dưỡng kiểm tra kỹ | Có |
| `candidate_suggested` | Hiện ứng viên với nhãn "khớp cao", điều dưỡng vẫn phải bấm xác nhận | **Đề xuất** |
| `no_match` | Không có ai trong danh sách hôm nay khớp → tìm thủ công / đăng ký | **Đề xuất** |

Trước khi D-04 được chốt, code **chỉ** dùng 3 giá trị có trong spec.

### 3.2 Bảng luật (thứ tự ưu tiên từ trên xuống; luật đầu tiên khớp thì dừng)
| Mã luật | Điều kiện | Quyết định |
|---|---|---|
| R1 | Luật gộp spoof cấp phiên (D-30) cho kết quả giả mạo | `spoof_suspect` |
| R2 | `collector_status = LOW_QUALITY` | `low_quality` |
| R3 | Bất kỳ ngưỡng nào của `match.*` hoặc `decision.*` là `null` | `review_required` (kèm top1 nếu có) |
| R4 | Gallery rỗng, hoặc `top1_score < decision.no_match_below` | `no_match` *(sau khi D-04 chốt; trước đó là `review_required`)* |
| R5 | `MatchResult.passed_threshold = True` | `candidate_suggested` *(sau D-04; trước đó `review_required`)* |
| R6 | Còn lại | `review_required` |

- Luật được viết thành hàm thuần, thứ tự cố định trong code; **mọi con số** lấy từ config. Không dùng DSL/YAML luật để tránh phức tạp. Nếu người dùng muốn luật cấu hình được thì cập nhật plan.
- `rule_id` được ghi vào `sessions` (M4) và outbox để truy vết lý do quyết định ở M9.
- `requires_nurse` luôn `True` (khẳng định bằng test).

## 4. Config keys
`decision.no_match_below` (D-04), `decision.spoof_rule` (D-30), `decision.enabled_outcomes` (danh sách enum được bật, mặc định 3 giá trị của spec).

## 5. Giá trị cần xác nhận
- **D-04:** danh sách enum và bảng luật.
- **D-30:** luật gộp spoof cấp phiên.
- **D-01, D-02:** thông qua `match.*`.
- `no_match_below`: ngưỡng thấp hơn `match.threshold`, hiệu chuẩn ở M9.

## 6. File
- `src/edgeface/pipeline/decision.py`, mở rộng `src/edgeface/types.py` (`Decision`, `DecisionResult`)
- `tests/unit/test_decision.py`

## 7. Trường hợp biên
- Vừa spoof vừa low quality → R1 thắng (an toàn hơn).
- `MatchResult = None` (không gọi được S9) → R3/R6 → `review_required` không có ứng viên.
- `enabled_outcomes` thiếu giá trị mà một luật trả về → rơi xuống `review_required` (có test).

## 8. Test
Bảng test tham số hoá: mỗi luật R1–R6 ít nhất một ca khớp và một ca sát biên; mọi ca đều có `requires_nurse = True`; thứ tự ưu tiên R1 > R2 > R3.

## 9. Đo lường
Phân bố quyết định theo `rule_id` (tỉ lệ `review_required`, `low_quality`: chỉ số vận hành trong spec §5).

## 10. Tiêu chí hoàn thành
- [ ] Test pass với 3 enum của spec
- [ ] Sau khi D-04 và D-30 được chốt: bật enum mới, cập nhật test và plan này
