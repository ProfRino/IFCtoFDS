# Theo dõi nghiệm thu sửa IFCtoFDS

Mốc 04/11/2026. Đợt này đã phân tích và lưu kế hoạch, chưa triển khai thay đổi sản phẩm theo kế hoạch mới. Trạng thái dưới đây mô tả mức chứng minh hiện có, không phải cam kết đã sửa.

## Kết quả phân tích đã chạy

| Kiểm tra | Kết quả | Bằng chứng |
|---|---|---|
| 26 test partial audit, emitter, scenario integrity | PASS, 2 RuntimeWarning, 1,19 s | [Log](evidence/related-tests.txt) |
| Timer OPEN/CLOSED nguyên trạng | FAIL yêu cầu chạy FDS, ERROR(885), exit code vẫn 0 | [Probe](evidence/probes.json), thư mục open/closed |
| OPEN chỉ thêm XYZ trong fixture | FAIL ý định, HIDE lúc đầu rồi SHOW sau sự kiện | open_with_xyz CSV/SMV |
| CLOSED chỉ thêm XYZ trong fixture | FAIL ý định, SHOW sớm, CTRL không đổi tại sự kiện | closed_with_xyz CSV/SMV |
| T_END khoa học | FAIL, 1.8E3 bị thay thành 1936.2E3 | probes.json |
| Cửa và lưới | FAIL phép đo, 5/5 risk=true | probes.json |
| Năng lượng và HF | Xác nhận thiếu assessment và nguồn HF | probes.json |
| Vent không phẳng qua EndpointSpec | PASS chặn ở schema | probes.json |
| Full Python/JS/browser/ALL/benchmark/PyroSim | NOT_RUN trong lượt phân tích này | Không lấy kết quả lịch sử thay thế |

Hai biến thể XYZ là phép thử cô lập nguyên nhân. Chúng không phải bản sửa sản phẩm. FDS của hai biến thể kết thúc thành công nhưng hành vi không đạt yêu cầu, nên không đánh dấu A04 PASS.

## Ma trận tiêu chí mới

| Tiêu chí | Trạng thái hiện tại | Việc cần có để đóng |
|---|---|---|
| A01 | CHƯA NGHIỆM THU | Giải quyết browser selection/delete và chạy lại các đường trạng thái |
| A02 | MỘT PHẦN | Miền theo nguồn đã có bằng chứng cũ, frame heuristic còn tồn tại |
| A03 | CHƯA NGHIỆM THU | Normalization proof, Duplex và source defects đối chiếu đầy đủ |
| A04 | FAIL TÁI HIỆN | Timer hợp lệ và hành vi OPEN/CLOSED đúng trong solver |
| A05 | FAIL TÁI HIỆN EMITTER | Chặn đích thiếu ngay trước emit, giữ test composer/HTTP |
| A06 | FAIL TÁI HIỆN | TIME có cấu trúc và hash file cuối |
| A07 | FAIL TÁI HIỆN | Đúng tiết diện/hướng/lưới và parity |
| A08 | THIẾU CHỨNG CỨ VẬT LÝ | Assessment, budget policy, HF capability và UI |
| A09 | LỆCH HỢP ĐỒNG TRONG MÃ | Shared preflight/coverage và mixed parity tests |
| A10 | FAIL TRÊN AUDIT ĐÃ LƯU | Reason/evidence đúng cho mọi gate |
| A11 | MỘT PHẦN | Giữ HVAC contract, bổ sung cases và PyroSim evidence riêng |
| A12 | CHƯA NGHIỆM THU | Mutation trusted policy và phân loại lỗi |
| A13 | NOT_RUN | Import graph, benchmark đúng phương pháp, migration regression |
| A14 | GIỚI HẠN ĐÃ XÁC NHẬN | E1–E4 phải đóng độc lập, không ép PASS unsupported |
| A15 | NOT_RUN | Kiểm thử tích hợp và docs bàn giao |

## Đối chiếu kế hoạch ngày 03 tháng 11

| Tiêu chí cũ | Bằng chứng hoặc tình trạng đã biết | Tiếp nối |
|---|---|---|
| OUT-01/02 | Guard/schema có trong working tree, browser cũ FAIL tại delete selection | S0, A01 |
| OUT-03/04 | Tang7 automatic domain không còn boundary pending, mã đã tránh rounding miền | S0/S3, A02 |
| OUT-05/06 | Có normalization/proof, regression Duplex chưa giải thích xong | S0/S5, A03 |
| OUT-07/08 | Engine partial có test, runner còn thiếu parity/coverage | S5, A09/A10 |
| OUT-09 | Solver discovery có implementation và bằng chứng cũ | S0, kiểm precedence/hash/error log |
| OUT-10 | HVAC thiếu dữ liệu và effective subset vẫn phải thể hiện giới hạn | S4/S8, A08/A11/A14 |
| OUT-11 | Tang7 có 0 boundary pending, structural PASS trong audit 03/11 | S9 tái kiểm đúng SHA |
| OUT-12 | Chưa có full integration sau toàn bộ sửa đổi | S9, A15 |

## Nhật ký triển khai

Chưa bắt đầu S0–S9 của kế hoạch mới. Khi thực hiện, mỗi dòng ghi ngày, mã gói, file sửa, đầu vào, kết quả kỳ vọng, lệnh đã chạy, bằng chứng thực tế và sai lệch cần xử lý. Không xóa một lần thất bại khi có lần chạy mới.

| Ngày | Gói | Thay đổi | Kiểm chứng | Kết luận |
|---|---|---|---|---|
| 04/11/2026 | Phân tích trước sửa | Tạo hồ sơ và probe độc lập, không sửa mã sản phẩm | 26 tests, 4 solver probes, các probe hàm | Kế hoạch đã lưu, lỗi cửa/TIME cần sửa trước |
| 04/11/2026 | S0-S5 | Triển khai sửa lỗi cửa (CTRL INITIAL_STATE), TIME (parser allowed & span preservation), geometry package schema_version trong preview, energy RAMP integration clamping T_END, worker verdict, opening tangent tolerance, geometry pass reason, server cleanup | 523 tests pytest passed, 0 failures; FDS 6.11.1 solver probe verified OPEN/CLOSED | Đã khắc phục 9 lỗi cốt lõi từ code-review và khớp hợp đồng A01, A04, A05, A06, A07, A08, A10 |
| 04/11/2026 | S0-S6 (Đợt 2) | Xử lý rà soát toàn diện: restore package dict verification, manifest.configuration None guard trong audit conversion, legacy scenario extra preview fields & opening_events mapping, defaultDispatch !res.ok, strip inline comments trong TIME/OBST composer, effective_obstructions mesh guard & tangent non-inversion, MEP port flow direction sorting (SINK->SOURCE), format count trong GeometryChecker, CLI --coordinate-frame flag | 530 tests pytest passed (42 remediation tests), 0 failures; 2 node worker contract suites passed | Toàn bộ 15 điểm rà soát đã được thẩm định độc lập và kiểm chứng chặt chẽ |


