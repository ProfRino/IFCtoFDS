# Hồ sơ phân tích lại và kế hoạch sửa IFCtoFDS

Ngày lập 04/11/2026. Hồ sơ này đối chiếu bản Review lần 2 với mã đang có trên nhánh `codex/conversion-contracts-repair`, HEAD `c982eed7009000149680894dbf147d143b9db9be` và các thay đổi chưa commit. Đây là kế hoạch trước triển khai, không phải báo cáo đã sửa xong.

## Tài liệu

- [Phân tích lỗi và điều chỉnh kết luận review](PHAN_TICH_LOI.md).
- [Kế hoạch sửa và hợp đồng đầu vào đầu ra](KE_HOACH_CHINH_SUA.md).
- [Bảng đối chiếu nghiệm thu](THEO_DOI_NGHIEM_THU.md).
- [Bằng chứng probe ngày 04/11](evidence/probes.json).
- [Chương trình tái hiện](evidence/review_reanalysis_probe.py).
- [Kết quả kiểm thử liên quan](evidence/related-tests.txt).

## Kết luận chính

Ưu tiên sửa điều khiển cửa, cập nhật thời gian mô phỏng và tính nhất quán của kiểm toán trước khi tối ưu hoặc mở rộng module. Ca FDS 6.11.1 thật phát hiện timer thiếu tọa độ. Sau khi chỉ bổ sung tọa độ trong ca thử, OPEN tạo vật cản thay vì mở cửa và CLOSED không chuyển đúng thời điểm. 26 kiểm thử hiện có vẫn đạt nên cần bổ sung kiểm tra hành vi solver.

Review cũng có kết luận chưa đúng với mã hiện tại. H-12 và H-13 không tái xác nhận được ở nhánh được nêu. M-10 đã đặt PRAGMA trên mỗi connection. N-7 bị schema chặn trước đường lỗi được mô tả. Không sao chép nguyên trạng các mục này thành lỗi phải sửa.

Phạm vi lần này là phân tích, tái hiện và lưu kế hoạch. Không thay mã thực thi, không thay IFC gốc, không commit hoặc push. Các sửa đổi ngày 03/11 vẫn còn trong working tree và chưa được nghiệm thu toàn bộ.

## Liên hệ kế hoạch trước

Kế hoạch này bổ sung và sắp thứ tự thực hiện tiếp cho [kế hoạch ngày 03/11](../../CONVERSION_REPAIR_PLAN_2026-11-03.md). Các OUT-01 đến OUT-12 cũ vẫn phải được đối chiếu. [Sổ theo dõi cũ](../../CONVERSION_REPAIR_VERIFICATION_2026-11-03.md) còn nhiều dòng NOT_RUN và chưa phản ánh đầy đủ bằng chứng đã có. Không sửa lịch sử thành PASS khi chưa kiểm tra lại.

