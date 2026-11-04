# Theo dõi thực hiện kế hoạch sửa lỗi IFC → FDS

Đối chiếu với [kế hoạch đã lưu trước sửa](CONVERSION_REPAIR_PLAN_2026-11-03.md). Ngày bắt đầu: 03/11/2026. Nhánh: `codex/conversion-contracts-repair`. Mốc trước sửa: `c982eed`.

## Nhật ký trước sửa

- Repository sạch trước khi lưu kế hoạch; không thay đổi IFC riêng.
- Python mặc định: **PASS — 471 passed, 9 deselected, 104 warnings, 107.44 s**. Log: `scripts/out/conversion-repair-2026-11-03/baseline-python.log`.
- Các script `test-golden-workflow.js` và `test-background-export-worker.js`: **PASS** trên mã cũ; chứng minh các ca hiện có chưa bắt đường lỗi người dùng.
- Reproducer trước sửa chạy worker thật và verified workflow: GEOM/hybrid nhận preview-only trả TypeError; đổi ALL → Tang7 vẫn gửi miền ALL. Lưu bằng chứng trong thư mục phiên, ngoài mã nguồn.

## Ma trận theo dõi

| Tiêu chí | Trạng thái | Bằng chứng / phần còn lại |
|---|---|---|
| OUT-01 | NOT_RUN | Đang sửa guard Quick theo capability |
| OUT-02 | NOT_RUN | Đang sửa schema mesh và worker diagnostic |
| OUT-03 | NOT_RUN | Đang sửa miền gắn tập nguồn |
| OUT-04 | NOT_RUN | Đang bỏ làm tròn thu hẹp miền |
| OUT-05 | NOT_RUN | Đang triển khai chuẩn hóa số học có proof |
| OUT-06 | NOT_RUN | Sẽ đọc lại 8 STEP và opening 6671 |
| OUT-07 | NOT_RUN | Đang bổ sung thống kê so sánh/report |
| OUT-08 | NOT_RUN | Đang bổ sung chế độ partial tường minh |
| OUT-09 | NOT_RUN | Đang bổ sung dò solver tin cậy |
| OUT-10 | NOT_RUN | Sẽ kiểm tra giữ đúng MEP/effective giới hạn |
| OUT-11 | NOT_RUN | Sẽ tái kiểm tra Tang7 đúng SHA |
| OUT-12 | NOT_RUN | Chưa chạy bộ sau sửa |

## Cập nhật phạm vi trước triển khai phần tương ứng

- IN-03 bổ sung trần dịch chuyển số học 1e-12 m để ngân sách ULP không tăng nguy hiểm ở tọa độ thế giới lớn.
- IN-04 bổ sung tùy chọn operator tắt autodiscovery và cách cô lập solver trong kiểm thử đơn vị. Kiểm thử real solver vẫn phải chạy riêng, không được tính là PASS khi thiếu executable.

Kết luận hiện tại: **đang thực hiện**. Các tiêu chí chỉ chuyển PASS khi có kết quả kiểm tra tương ứng.
