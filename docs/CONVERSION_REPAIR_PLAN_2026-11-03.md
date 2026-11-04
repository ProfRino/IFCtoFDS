# Kế hoạch sửa lỗi và hợp đồng đầu vào/đầu ra IFC → FDS

Ngày lập: 03/11/2026. Mốc mã nguồn trước sửa: `c982eed` (main, PR #20). Kế hoạch này được lưu trước khi chỉnh sửa mã thực thi. Kết quả thực hiện được cập nhật tại `docs/CONVERSION_REPAIR_VERIFICATION_2026-11-03.md` theo các mã yêu cầu dưới đây.

## 1. Mục tiêu và nguyên tắc nghiệm thu

Sửa các nguyên nhân đã tái hiện từ `conversion-diagnostic.json` và hai báo cáo ALL_FDS_2027/Tang7: lỗi xuất mô hình preview, miền cũ/làm tròn miền, thiếu chuẩn hóa lưới ở mức sai số số học, cách báo cáo khi preflight chặn kiểm tra và cách tìm FDS đã cài.

Không sửa IFC gốc; giữ tên/SHA/STEP/GlobalId. Không biến bbox thành hình học thay thế, không tự vá mặt hở, không sinh port/airflow/thiết bị giả, không bỏ đối tượng khó mà thiếu trạng thái. Ghi FDS thành công, mapping được kiểm chứng và simulation được kiểm chứng là ba trạng thái khác nhau.

Không cam kết tất cả mô hình được ACCEPTED: hình học thực sự chưa hỗ trợ, opening không dựng được, thiếu quyết định MEP và thiếu bộ đọc effective geometry phải tiếp tục hiện rõ FAIL/INCONCLUSIVE/NOT_RUN. Đầu ra đúng bao gồm cả kết quả từ chối có nguyên nhân và định danh cụ thể.

## 2. Dữ liệu tái hiện và nguồn bằng chứng

- JSON người dùng: `D:/Users/Downloads/conversion-diagnostic.json`: TypeError tại serialization, STEP 6967, requestId 7, jobId null.
- ALL: `../ifc-to-fds/input/ALL_FDS_2027.ifc`, SHA `a54ba512754efe1f82b87d7fb1853361889ad00d59be5a7a14ecac075e2cc7af`, 5.641 phần tử.
- Tầng 7: `../Resources/Tang7/Tang7.ifc`, SHA `df856013a2b3d91d4d53549f8dc496439f910e6e5f4503fbf9e47af2277377f3`, 279 phần tử, 195 kết cấu.
- Báo cáo chẩn đoán và JSON tái hiện ngày 03/11 đã lưu ngoài repository trong thư mục phiên làm việc. Không đưa IFC riêng vào Git.
- Môi trường ban đầu: Python 3.10.21, IfcOpenShell 0.9.0.post1, NumPy 2.2.6, trimesh 5.1.1, Pydantic 2.14.1, Node 24.13.1.

## 3. Hợp đồng đầu vào

### IN-01 — Hai loại mô hình giao diện

`backendPreview:true` là inventory/bounds/tham chiếu payload phục vụ viewer; không phải mô hình đầy đủ cho Quick Conversion. Quick chỉ nhận mô hình đầy đủ, có dữ liệu đáp ứng chiến lược xuất. Tải được mesh vào viewer không tự cấp quyền cho bộ xuất đọc metadata như mesh.

GEOM yêu cầu mesh có mảng vertices hữu hạn [x,y,z], faces tam giác có chỉ số nguyên hợp lệ và dữ liệu opening đã xử lý đầy đủ. Dữ liệu thiếu/sai phải tạo lỗi có loại rõ ràng và định danh phần tử, không TypeError vô danh và không bỏ qua im lặng.

### IN-02 — Miền tính toán và scope

Miền cố định gồm sáu số hữu hạn, không được để trống, min < max trên mỗi trục, đơn vị mét. Miền khai báo phải gắn với tập nguồn thực tế đang chọn. Đổi tập nguồn làm mất hiệu lực miền cũ; người dùng phải khai báo lại trước khi dùng. Chỉnh miền cho cùng một nguồn phải được giữ.

Không gửi `simulation_domain` còn sót trong object cấu hình khi checkbox miền đã tắt. Gợi ý miền giữ độ chính xác binary64 hoặc nới ra ngoài; không làm tròn vào trong. Chỉ cập nhật gợi ý từ viewer/inventory nếu đúng nguồn đang chọn; đáp ứng cũ không được ghi đè nguồn mới. Viewer clipping vẫn độc lập với export scope.

### IN-03 — Hình học nguồn và chuẩn hóa số học

Nguồn trích xuất luôn giữ chẩn đoán raw. Cho phép chuẩn hóa có bằng chứng ở mức sai số floating-point: gộp đỉnh trong ngân sách tối đa `min(8 ULP của độ lớn tọa độ ở thang ít nhất 1 m, 1e-12 m)`, ghi rõ tolerance và dịch chuyển Euclidean đo được. Trần 1e-12 m ngăn tọa độ thế giới rất lớn làm ngân sách ULP tăng thành khe hở vật lý. Đây không phải dung sai sai số hình học của dự án và không được dùng để lấp khe hở vật lý.

Không thêm/bớt tam giác, không nhận candidate làm sụp mặt hoặc tạo mặt trùng/non-manifold, không tự vá lỗ. Đảo hướng mặt chỉ trên shell kín, định hướng được và không có nhiều shell/cavity mơ hồ. Gộp seam cho nhiều shell chỉ được xét nếu không đổi hướng mặt và giữ đối ứng mặt/đỉnh. Candidate phải đạt valid_solid và bằng chứng đối ứng; không đạt thì trả raw nguyên vẹn cùng lý do từ chối.

Độc lập audit phải mở lại IFC và trích xuất/chuẩn hóa lại; không lấy mesh/proof từ converter cache làm bằng chứng. Cache phải đổi revision khi chính sách chuẩn hóa đổi. Chuẩn hóa thành công không tự chứng minh openings/air-path/fidelity đã PASS.

### IN-04 — MEP/HVAC và solver

Tên riêng gợi ý van/ống không đủ để tự tạo HVAC. Mạng vận hành cần quyết định phân loại, thông số và liên kết IFC đã duyệt theo schema hiện tại. Phần tử thiếu ngữ nghĩa vẫn UNRESOLVED/REVIEW_REQUIRED; không tự cấp thông số hoặc nối port.

Executable solver do môi trường tin cậy của operator cung cấp: cấu hình tường minh ưu tiên, tiếp theo PATH, cuối cùng bản FDS ghim trong `.deps` của dự án nếu đúng nền tảng và tồn tại. Không tìm/tải/chạy executable do upload chỉ định. Đường dẫn tường minh sai phải hiện lỗi, không âm thầm thay thế.

Operator có thể đặt `IFCFDS_SOLVER_AUTODISCOVERY=0` để tắt việc dò PATH/bản ghim (cấu hình executable tường minh vẫn được kiểm tra). Kiểm thử đơn vị mặc định phải tắt dò tự động để không vô tình chạy solver thật do máy phát triển đã cài `.deps`; các ca kiểm tra dò solver bật lại riêng và kiểm thử solver thật dùng executable xác định. Bản ghim tự tìm phải khớp checksum đã khai báo bởi bộ cài dự án.

## 4. Hợp đồng đầu ra

| Mã | Kết quả bắt buộc | Cách chứng minh |
|---|---|---|
| OUT-01 | Preview-only luôn khóa Quick sau tải/toggle/xóa/Undo; gọi trực tiếp bị từ chối có thông báo hướng dẫn | Kiểm thử trạng thái controller + browser |
| OUT-02 | Thiếu/sai mesh trả lỗi có code/name, stage serialization, entity/request identity; valid full model vẫn xuất được | Worker thật và inline worker; re-parse FDS hợp lệ |
| OUT-03 | Đổi ALL → Tang7 không tái dùng miền ALL; miền cùng nguồn không bị xóa tùy tiện | Kiểm thử DOM/source transition, stale response, cấu hình request |
| OUT-04 | Gợi ý miền bao hết bounds nguồn; các số không bị `toFixed(2)` thu hẹp | Ca Ymin -0.1523929042/-0.1504 và giá trị nhỏ/nhiều chữ số |
| OUT-05 | Chuẩn hóa được ghi raw/result hash, chất lượng, tolerance, dịch chuyển, map/hướng mặt; input không bị mutate; lặp lại ổn định | Unit/integration + 8 STEP lỗi của ALL |
| OUT-06 | 9923/39948 khắc phục lỗi hướng mặt; 11969/6490 xử lý được seam số học nếu đủ chứng minh; 6671 và các lỗi thật vẫn chưa được xác nhận | Đọc lại IFC trực tiếp; đối chiếu opening và topology |
| OUT-07 | Báo cáo phân biệt số ghi FDS, đã so sánh, đạt, lỗi và chưa so sánh; không diễn giải 0 verified thành toàn bộ FDS sai | Mixed valid/invalid fixture; trường metrics/status và renderer |
| OUT-08 | Preflight lỗi vẫn chặn kiểm tra toàn cục phụ thuộc; cho phép thu thập so sánh cục bộ độc lập theo cấu hình tường minh, không phát mapping verified sai | Kiểm thử chính sách fail-fast/partial và gate aggregation |
| OUT-09 | Tìm được FDS ghim đã cài khi thiếu PATH; lưu đường dẫn/cách tìm; thiếu hoặc sai executable trả trạng thái đúng | Unit precedence + real pinned FDS fixture |
| OUT-10 | MEP thiếu dữ liệu và GEOM effective-adapter chưa hỗ trợ hiện đúng giới hạn; không chuyển sang PASS giả | Regression HVAC/review/boundary/effective |
| OUT-11 | Tầng 7 miền tự động: 0 pending biên/0 kết cấu withheld ở bước mapping; miền ALL tái tạo 104/81 làm ca phản chứng | Chạy lại đúng IFC/SHA; lưu JSON số liệu |
| OUT-12 | Bộ mặc định, JS, browser liên quan và solver được chạy phù hợp; ghi riêng PASS/FAIL/NOT_RUN, không gộp thiếu bằng chứng | Nhật ký lệnh/exit code/test counts + báo cáo đối chiếu |

## 5. Các bước triển khai và quyền sở hữu module

1. **P0 — Khóa mốc và baseline:** lưu kế hoạch này, tạo nhánh `codex/conversion-contracts-repair`, ghi status/HEAD/phiên bản, chạy baseline trước sửa. Tạo reproducer cho từng nhóm thay vì chỉ kiểm tra dòng mã.
2. **P1 — Giao diện và dữ liệu xuất:** một người phụ trách controller/verified workflow/exporter và JS/browser tests; tập trung guard khả năng Quick, schema mesh, worker diagnostics. Sinh lại inline worker sau thay đổi.
3. **P2 — Tính đúng miền:** cùng người P1 phụ trách để tránh sửa chồng controller; ràng buộc nguồn, reset khi đổi nguồn, giữ chỉnh sửa cùng nguồn, kiểm tra số/minmax, loại cấu hình cũ, bỏ làm tròn vào trong.
4. **P3 — Chuẩn hóa số học có bằng chứng:** người phụ trách geometry engine/helper/cache/tests. Converter và reference cùng tuân hợp đồng, chạy độc lập. Không thay logic nhận diện ngữ nghĩa MEP hay chế tạo hình học thiếu.
5. **P4 — Chẩn đoán audit:** người điều phối phụ trách engine/reporting/config/tests. Giữ fail-fast để bảo vệ thời gian chạy mặc định; bổ sung chế độ thu thập so sánh cục bộ tường minh và thống kê không gây hiểu nhầm. Không chạy solver khi preflight toàn cục chưa đạt.
6. **P5 — Sẵn sàng solver và giới hạn:** người điều phối phụ trách resolver/evidence/tests/docs. Dò bản ghim trong môi trường tin cậy, giữ ràng buộc upload; ghi rõ giới hạn effective adapter và dữ liệu MEP phải bổ sung.
7. **P6 — Tích hợp và kiểm chứng:** chạy các bộ liên quan, kiểm tra worker parity, CLI/API, đọc lại hai IFC gốc, lưu đầu ra theo OUT-xx. Nếu thêm/đổi phạm vi, cập nhật kế hoạch với lý do trước khi triển khai phần đổi.
8. **P7 — Bàn giao:** báo cáo từng OUT-xx, những việc sửa được, những đối tượng/giới hạn còn FAIL/INCONCLUSIVE và cách tiếp tục. Không tự push/merge thay đổi này khi chưa có yêu cầu mới.

## 6. Chiến lược kiểm tra và đối chiếu liên tục

- Trước mỗi phần: ghi ca lỗi đầu vào, kỳ vọng đầu ra và test sẽ phát hiện sai lệch. Sau mỗi phần: chạy test sở hữu, cập nhật trạng thái P/OUT và bằng chứng.
- Baseline bộ Python mặc định và JS hiện có; không coi baseline PASS là đã phủ lỗi người dùng. Kiểm tra mới phải thất bại với logic cũ và đạt sau sửa khi có thể tách tái hiện an toàn.
- Dùng fixture nhỏ cho các trường hợp: preview-only, malformed mesh, source switching, inward rounding, wound seam, true open surface, invalid opening, mixed valid/invalid audit, explicit/PATH/pinned/missing solver.
- Sau tích hợp: bộ Python mặc định, 13 JS scripts hiện có và script mới, browser liên quan, solver thật ghim 6.11.1. Chỉ chạy rộng lại khi có thay đổi/failure cần chứng minh.
- IFC thật: kiểm tra hash không đổi; đối chiếu các STEP ALL, chuẩn hóa độc lập và opening 6671; Tang7 mapping/acceptance khi khả thi. Chạy toàn bộ ALL audit có thể tốn nhiều thời gian; phải ghi rõ bước nào đã chạy, không suy diễn từ test nhỏ.
- Luôn phân biệt PASS (đã có bằng chứng), FAIL (sai yêu cầu), NOT_RUN (chưa chạy), INCONCLUSIVE (chưa đủ bằng chứng). Bất kỳ mục chưa đạt phải có lý do và tác động, không sửa kỳ vọng chỉ để làm test xanh.

## 7. Phạm vi cần dữ liệu hoặc phát triển tiếp

- Không tự sửa opening 6671, mặt hở/non-manifold còn lại trong IFC gốc. Đây là các đầu vào cần xem lại hoặc cơ chế sửa có phê duyệt và bằng chứng riêng.
- Không tự quyết định 508 MEP unresolved, 188 đối tượng review hoặc tạo mạng HVAC. Cung cấp hướng dẫn/schema và giữ danh tính để operator bổ sung quyết định.
- Chưa triển khai adapter effective geometry tổng quát cho GEOM/HOLE/VENT/multi-mesh trong đợt sửa này. Thông báo đầu ra phải nêu đúng khả năng hiện có; chỉ cấu hình solver không được làm mất cảnh báo.
- Không coi hết exception hay hết withheld do miền sai là chứng minh simulation đã đúng vật lý hoặc tương thích PyroSim đã được kiểm tra trực tiếp.
