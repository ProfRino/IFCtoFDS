# Bằng chứng phân tích ngày 04 tháng 11 năm 2026

probes.json ghi kết quả hàm, hash mã nguồn được kiểm tra và bốn biến thể solver. open/closed giữ nguyên phần điều khiển do emitter phát. Hai thư mục with_xyz chỉ thêm tọa độ timer để cô lập hành vi trạng thái. Mã sản phẩm không bị thay đổi trong các phép thử này.

Các ca gốc không có SMV vì FDS dừng ở ERROR(885). Exit code 0 không có nghĩa thành công. Hai biến thể chẩn đoán có file .out, .smv, ctrl.csv và devc_ctrl_log.csv. Các sự kiện HIDE_OBST/SHOW_OBST trong SMV phải được đọc cùng log điều khiển và thời gian solver.

related-tests.txt lưu kết quả 26 test liên quan, không phải full suite. Python 3.10.21 trên Windows. FDS được kiểm qua revision trong file .out và SHA256 khớp binary ghim 6.11.1.

Chạy lại probe từ gốc repository bằng lệnh sau. Đối số cuối phải là thư mục mới để không trộn bằng chứng cũ. Lệnh sẽ chạy bốn ca FDS rất nhỏ nếu binary ghim tồn tại.

```powershell
.venv/Scripts/python.exe -B -X utf8 docs/audit/remediation-2026-11-04/evidence/review_reanalysis_probe.py . scripts/out/review-reanalysis-rerun
```

Script tái hiện hành vi hiện tại, không phải regression assertions cho bản đã sửa. Sau khi triển khai phải viết test expected behavior theo A04–A08 trong kế hoạch.
