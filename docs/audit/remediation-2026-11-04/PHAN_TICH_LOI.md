# Phân tích lại lỗi IFCtoFDS ngày 04 tháng 11 năm 2026

## Phạm vi và độ chắc chắn

Nguồn review là [Review lần 2](../Review-Toan-Dien-IFCtoFDS-.docx), SHA256 `77baceec21f1bb15f510e515881ad660daed857b34e2d514fc4bbd3f73b92920`. Review đánh giá snapshot 02/11, chạy trên Linux ngày 03/11. Lần đối chiếu này đọc mã working tree ngày 04/11 trên Windows, đã bao gồm các sửa đổi chưa hoàn tất ngày 03/11. Do đó số lỗi, số test và mức tiến triển không thể lấy nguyên từ review.

Nhãn **tái hiện** chỉ dùng cho ca thực sự chạy trong lần này. **Xác nhận mã** là kết luận từ đường dữ liệu trong mã. **Bằng chứng cũ** là kết quả đã lưu trước đó. **Cần đo** là giả thuyết hoặc giới hạn chưa được tái kiểm nghiệm. Mỗi loại cần được giữ riêng trong sổ nghiệm thu.

26 test của `test_partial_audit_contract.py`, `test_fire_scenario_emitter.py` và `test_scenario_integrity.py` đạt, có 2 RuntimeWarning, trong 1,19 giây. Bộ này chưa chứng minh đúng vật lý hoặc đúng hành vi điều khiển trong FDS. Chưa chạy lại toàn bộ Python, browser, toàn bộ ALL, benchmark hai phiên bản hoặc PyroSim GUI ở lần này.

## 1 Lỗi điều khiển cửa cần nâng ưu tiên

### R01 Timer thiếu tọa độ làm FDS từ chối

**Tái hiện trên FDS 6.11.1 thật.** `fire/scenario_emitter.py` phát `DEVC QUANTITY='TIME'` không có XYZ. Hai ca OPEN và CLOSED đều dừng với `ERROR(885)` yêu cầu tọa độ. Parser nội bộ chấp nhận cú pháp nhưng không kiểm đủ điều kiện solver.

Bản FDS dùng trong thử nghiệm chỉ lấy nguyên cụm điều khiển cửa do emitter sinh, đặt trong một miền 1 m với 10 × 10 × 10 ô và T_END 2 s. Không có cháy để cô lập lỗi. Binary SHA256 là `dfaf04f1d46dbad77969b1cdd17baaa02a7aa6d63f46e96e93b9d9e635452b55`, khớp bản ghim trong dự án. Đây là thử module điều khiển, chưa phải chạy toàn bộ kịch bản ghép qua HTTP.

Tiến trình vẫn trả mã 0 dù log ghi ERROR. Bộ kiểm solver hiện tại đã kiểm log và completion nên không kết luận nó báo PASS sai. Tuy nhiên ca test mới phải giữ tình huống mã 0 có ERROR để bảo vệ hành vi này. [Bằng chứng](evidence/probes.json)

### R02 OPEN và CLOSED không thực hiện đúng trạng thái yêu cầu

**Tái hiện có biến thể chẩn đoán.** Chỉ thêm XYZ vào input của ca thử, giữ nguyên DEVC, CTRL và OBST còn lại, không chỉnh mã sản phẩm.

- OPEN có HIDE_OBST tại 0 s rồi SHOW_OBST khoảng 1,27732 s. Vật cản xuất hiện sau sự kiện, trái yêu cầu cửa đang đóng chuyển sang mở.
- CLOSED có SHOW_OBST khoảng 0,159665 s. CTRL giữ trạng thái true trong suốt lần chạy. Timer đổi ở khoảng 1,11765 s nhưng không gây chuyển trạng thái cửa theo yêu cầu.
- Chênh lệch thời điểm qua setpoint gắn với bước thời gian của solver, không lấy số thập phân trên làm mục tiêu kiểm thử cứng.

Nguyên nhân ở cả việc đặt INITIAL_STATE sai tầng và cách dùng ANY với trạng thái timer. Comment hiện tại nói vật cản bị loại khi CTRL true là sai. Test hiện tại chủ yếu kiểm sự có mặt của chuỗi namelist nên vẫn xanh.

Hướng dẫn FDS 6.11.1 quy định OBST bị loại khi điều khiển chuyển false và được tạo khi chuyển true. Ví dụ ANY mở cửa khai báo INITIAL_STATE trên CTRL. Như vậy nhận định “H-5 đã sửa” trong review cần rút lại. Chọn một biểu diễn điều khiển nhất quán, kiểm cả trạng thái ban đầu và sau sự kiện bằng solver thật. [Nguồn FDS chính thức](https://github.com/firemodels/fds/blob/FDS-6.11.1/Manuals/FDS_User_Guide/FDS_User_Guide.tex#L7651-L7778) [Bằng chứng thử nghiệm](evidence/probes.json)

### R03 Điều khiển cửa không có đối tượng đích

**Tái hiện emitter trực tiếp.** MappingPlan rỗng và sự kiện cho entity không tồn tại vẫn sinh DEVC/CTRL rồi ghi comment thiếu bounds. Đây là hợp đồng emitter chưa chặt.

Cần phân biệt phạm vi. `scenario_composer.py` hiện kiểm entity là IfcDoor/IfcWindow, có đúng một OBST trong nền, lịch hợp lệ và chưa có điều khiển cũ. Luồng worker vì vậy đã có lớp chặn đối tượng không hợp lệ. Không được suy ra mọi request HTTP đều tạo CTRL treo. Cần đẩy kiểm tra chung lên trước phát fragment và giữ kiểm tra lại khi ghép nền. [Bằng chứng](evidence/probes.json)

## 2 Cập nhật T_END sai có thể làm thời gian tăng hàng nghìn lần

### R04 Regex không đọc và thay toàn bộ số

**Tái hiện biểu thức hiện tại.** Input `&TIME T_END=1.8E3 /` bị đọc thành 1,8. Khi thay bằng giá trị mục tiêu 1936,2, đầu ra thành `T_END=1936.2E3`, tương đương 1.936.200 giây.

Mức tác động lớn hơn mô tả “đọc thành 0” trong review. Regex khớp phần đầu số rồi giữ lại hậu tố số mũ. Hỗ trợ chữ hoa/thường, E/D exponent, dấu, thiếu TIME, TIME không có T_END và cấu trúc namelist nhiều dòng cần được xử lý ở parser/serializer có hợp đồng. Hiện chỉnh TIME xảy ra sau parse của composer và chưa parse lại file cuối trước ghi. [Bằng chứng](evidence/probes.json)

Các N-8, N-9, N-10, N-11 cùng một nguyên nhân kiến trúc. Worker đang sửa ngữ nghĩa FDS bằng chuỗi và fallback không kiểu. Gộp chúng vào một thay đổi về cấu hình thời gian và chỉnh namelist. N-9 vẫn cần probe parser malformed. N-10 thiếu HEAD có thể đã bị sealed-base chặn, phải test đường công khai trước khi gọi là lỗi thực tế.

## 3 Cửa và ô lưới đang dùng sai dữ liệu

### R05 Kiểm tra lưới lấy bề dày thay cho tiết diện thông thủy

**Tái hiện.** Bốn cửa đi/cửa sổ bình thường và một lỗ nhỏ đều nhận risk_sealed_by_grid=true ở cell_size 0,2 m. Hàm `validation/effective.py::check_opening_grid_alignment` chỉ lấy X/Y, bỏ Z và dùng gốc 0.

**Phát hiện bổ sung từ mã.** OpeningsChecker lấy cell_size bằng getattr trên AuditConfig. Schema AuditConfig hiện không có trường đó và cấm extra, nên đường này thông thường luôn dùng fallback 0,2 m. Chỉ sửa công thức min vẫn chưa sửa được lỗi lấy lưới sai.

Hàm chỉ được gọi trong checker modular, không được gọi trực tiếp trong engine chính. Kết quả nằm trong metrics, không đủ căn cứ nói mọi đường xuất hiện đều có cảnh báo UI hoặc gate đã FAIL. Kế hoạch phải kiểm API, report và UI của cùng một ca.

Không dùng “trục ngắn nhất của AABB” như chân lý cho cửa nghiêng hoặc tường dày. Cần pháp tuyến/tiết diện lấy từ host hoặc dữ liệu hình học có bằng chứng. Không xác định được thì INCONCLUSIVE. Lưới lấy từ MESH đã serialize, có origin, dx/dy/dz và mesh identity. Kết quả tiên nghiệm vẫn khác bằng chứng effective geometry từ solver. [Probe](evidence/probes.json)

## 4 Vật lý cháy và trạng thái nghiệm thu

### R06 Năng lượng chỉ nằm trong comment

**Tái hiện.** Xe auto-nmc, pin 40 kWh và đỉnh 7 MW sinh đường cong ghi 9015,5 MJ so với 144 MJ danh định của pin. Bundle không có gate năng lượng hoặc trạng thái chứng cứ tương ứng.

Điểm đúng của review là chưa có ràng buộc và dữ liệu tải cháy. Tỷ số 62,6 tự nó không chứng minh đường cong toàn xe vi phạm vật lý. Năng lượng điện danh định không phải tổng năng lượng hóa học của pin và mọi vật liệu xe. Không đưa ngưỡng 3× được gợi ý trong review vào mã như một chuẩn đã được thẩm định.

Cần khai báo phạm vi cháy, ngân sách năng lượng có nguồn, tích phân chính đường RAMP đã serialize, phần năng lượng nằm trong T_END và giới hạn chấp nhận được phê duyệt. Thiếu dữ liệu thì physics_status=INCONCLUSIVE và không được cấp xác minh mô phỏng. [Probe](evidence/probes.json)

### R07 HF có tên nhưng chưa có mô hình nguồn định lượng

**Tái hiện phần phát file và xác nhận mã.** weighted_hf chỉ đi vào comment và SPEC. Không có adapter nguồn HF trong fragment do emitter tạo. Không diễn giải kết quả HF bằng 0 là bằng chứng an toàn.

Giai đoạn sửa gần chọn thể hiện UNSUPPORTED/NOT_MODELED, giữ dữ liệu yield trong metadata với đơn vị và nguồn, không phát SPEC trang trí. Nếu người dùng yêu cầu đánh giá HF thì phải chặn kết luận mô phỏng. Phát triển nguồn HF là phần riêng, cần đối chiếu khối lượng và chạy FDS. Không sửa bằng việc chèn một tham số YIELD chưa chứng minh. [Probe](evidence/probes.json)

### R08 Dữ liệu kịch bản có hai hình dạng và nhiều fallback

**Xác nhận mã.** Server cho extra=allow, scenario_data không kiểu đầy đủ. Worker tìm dữ liệu ở nhiều vị trí, âm thầm bỏ lỗi đọc JSON hoặc t_end_s và dùng object() làm model cho checker.

Rủi ro là giá trị mâu thuẫn giữa top-level và nested, cùng một request bị hiểu khác nhau giữa HTTP và worker. Cần schema version, adapter chuyển đổi định dạng cũ tường minh và một ScenarioSpec sau biên. Bản export phải băm theo file cuối sau ghép và sửa TIME, không chỉ fragment.

Cổng lưới phải dùng cùng giá trị HRR đã resolve cho từng xe và lưới thực. Không tự thay trung điểm thành cực đại dải rồi gọi đó là sửa đúng cho mọi trường hợp. Nếu cần chế độ bảo thủ, phải khai rõ policy và ghi evidence.

## 5 Hai luồng kiểm toán và sửa đổi cũ chưa hoàn tất

### R09 Engine và ValidationRunner lệch hợp đồng

**Xác nhận mã.** Engine có source preflight, collect_partial_geometry_evidence, các nhóm attempted/completed/failed/inconclusive/skipped. ValidationRunner vẫn gọi tuần tự mọi checker và chỉ truyền syntax/mesh status cho SolverChecker. CheckerOutcome chưa có coverage, evaluator không hợp nhất coverage.

Vì vậy không thể lấy các test engine đã đạt để tuyên bố đường modular đã đồng nhất. Kiểm tra lại dependency graph giữa gates và so sánh output của hai entrypoint trên fixture tốt, nguồn lỗi, so sánh lỗi và chế độ partial. Đầu ra partial không được cấp chứng nhận cho toàn mô hình.

### R10 Lý do PASS còn rỗng

**Bằng chứng audit đã lưu.** Tang7 ngày 03/11 có 8 gate PASS với reason rỗng, gồm syntax, traceability, scope, openings, mep, representation, boundary, domain. Review nêu 6 trên FZK, không phải số cố định của sản phẩm.

Cần reason_code và evidence gắn phép kiểm. Không dùng một câu chung “đã kiểm tra” để lấp chỗ trống. Phân biệt không có đối tượng áp dụng với đã kiểm đầy đủ các đối tượng.

### R11 Air path và normalization chưa có kết luận gốc

**Bằng chứng cũ.** Tang7 còn leak volume âm khoảng -0,000657015 m³ và air_path INCONCLUSIVE. Có 14 cửa/cửa sổ không so sánh được do tự giao, 218 thực thể đã ghi, 204 verified và 0 boundary pending. Đây là các con số khác phạm vi, không cộng hoặc đổi thành “còn thiếu 14 kết cấu”.

Lỗi âm cần truy vết từ từng operand, phép difference, shell orientation, cavity và cách đo signed volume. Việc Boolean trả Trimesh(process=False) chưa đủ chứng minh nguyên nhân. Không tự thêm fix_normals toàn cục hoặc lấy abs để tạo PASS. Đặc biệt phải bảo toàn hướng shell trong khối rỗng.

Kết quả chạy trước ghi nhận test Duplex sai kỳ vọng thể tích khoảng 1,0 so với 2,53972 m³ sau normalization. Chưa xác nhận nguyên nhân gốc và chưa tái chạy trong lượt này. Phải tái hiện, lưu tập entity/mesh thay đổi trước khi điều chỉnh golden.

### R12 Các sửa đổi ngày 03/11 chưa đủ nghiệm thu

Guard preview, miền gắn nguồn, normalization có proof, partial engine và solver discovery đã tồn tại trong working tree. Browser log ngày 03/11 còn FAIL ở nút xóa sau chọn entity, chưa chứng minh là lỗi UI hay cách điều khiển test. Sổ OUT-xx cũ chưa cập nhật. Không tiếp tục thêm refactor lớn lên nền chưa được khóa bằng kiểm thử.

## 6 HVAC và giới hạn effective geometry

### R13 Ánh xạ ống cần phân biệt hình học và vận hành

Mã hiện có chiến lược HVAC riêng, port topology, DuctSpec, NODE/DUCT và adapter FDS. Ống chỉ có hình học hoặc chưa được duyệt không đủ dữ liệu để thành mạng thông gió. Cần báo rõ từng entity đang ở REFERENCE_GEOMETRY, PASSIVE_OBSTACLE, HVAC hay UNRESOLVED và lý do.

Không tự nối port, suy ra lưu lượng hay fan curve từ AABB. Test mạng 2 đoạn nối tiếp, nhánh, đầu VENT/AMBIENT, biên scope, thiếu tham số và ống nước không được biến thành HVAC. Đối chiếu PyroSim phải có phiên bản, file nhập và bằng chứng riêng. Không đồng nhất “FDS hợp lệ” với “đã kiểm trực tiếp trên PyroSim”.

### R14 Effective geometry mới hỗ trợ tập con

**Xác nhận mã.** Adapter hiện chặn GEOM/HOLE/VENT và multi-mesh. Bật solver discovery không làm adapter này hỗ trợ thêm. Tang7 có 218 GEOM nên không thể được kiểm effective bằng adapter hiện tại.

Tách thành công việc mở rộng có mốc riêng. Ưu tiên nhiều mesh OBST và chuẩn hóa identity theo mesh trước. GEOM cut-cell, openings và coupling phải có dataset solver và phép đối chiếu riêng. Chưa hỗ trợ phải giữ INCONCLUSIVE.

## 7 Hiệu năng kiến trúc và độ tin cậy báo cáo

N-2/H-9 có số đo trong review trên cùng máy, nhưng chưa chạy lại hai revision trong lượt này. Chưa đủ bằng chứng đổ lỗi cho trích xuất port. Cần profile riêng reread, geometry, openings, Boolean và package audit, đo lặp trên cùng dependency và cấu hình.

Không chia sẻ mesh cache của converter làm bằng chứng độc lập cho auditor. Cho phép cache nội bộ mỗi lượt audit sau khi chính lượt đó mở lại nguồn, khóa theo source SHA, extraction settings và revision. Không bỏ đọc lại nguồn để giảm thời gian.

M-4 là rủi ro kiến trúc cần đo graph. Đếm import cục bộ không chứng minh vòng phụ thuộc. Phải lấy cạnh import thật, tìm thành phần liên thông mạnh và chỉ di chuyển trách nhiệm qua port/DTO cần thiết.

N-3 là đề xuất tối ưu mesh cần benchmark FDS, chưa phải lỗi nghiệm thu đã chứng minh. Không làm tròn IJK từng mesh độc lập gây đổi cell size hoặc lệch mặt tiếp giáp.

M-25 cần tách cấu hình tái lập mô hình từ manifest và chính sách nghiệm thu do auditor tin cậy cấp. AuditConversion hiện dùng manifest.configuration khi không truyền config. Cần ca sửa tolerance trong manifest để kiểm tác động, không kết luận khai thác thành công khi chưa chạy.

## 8 Những mục review cần sửa lại trạng thái

| Mã | Kết luận đối chiếu hiện tại | Xử lý trong kế hoạch |
|---|---|---|
| H-5 | Đã tái hiện lỗi solver và trạng thái điều khiển, không phải đã sửa xong | Ưu tiên đầu, R01/R02 |
| H-12 | Cả hai dispatcher gọi /api/scenario-jobs | Giữ test đường mặc định, hợp nhất mã lặp sau |
| H-13 | Thiếu fetch trả Promise.reject ở dispatch và poll | Giữ regression, không báo PASS giả ở nhánh này |
| M-10 | _get_connection đã đặt synchronous=NORMAL | Kiểm regression nhiều connection, không sửa lại vô cớ |
| N-7 | EndpointSpec chặn vent 3D trước next() | Rủi ro caller bỏ qua schema, củng cố biên nội bộ khi cần |
| H-4b | Lỗi emitter trực tiếp, composer có chặn entity/fill | Đồng nhất hợp đồng, không phóng đại reachability |
| N-1 | Sai phép đo, thêm lỗi fallback cell_size và lệch entrypoint | Sửa cả dữ liệu lưới, hướng cửa và đường gọi |
| N-11 | Khớp một phần số rồi giữ exponent | Ưu tiên cao hơn lỗi định dạng nhỏ |
| M-11 | Solver hiện đọc SMV để audit và lưu file/hash, chưa thấy nhúng toàn văn vào report ở nhánh này | Trace các đường còn lại trước khi đổi |
| M-4 | Số import trong hàm không đủ chứng minh cycle | Lập import graph trước refactor |
| C-1 | Đã chặn PASS sai, nguyên nhân thể tích âm chưa được chứng minh | Giữ fail-closed, điều tra hình học riêng |
| Thống kê review | Phần đầu ghi 21/28, bảng ghi 18/28 | Không dùng tỷ lệ tổng hợp làm tiêu chí đóng lỗi |

## 9 Bao phủ toàn bộ backlog còn lại

Các mục dưới đây đã đọc từ review nhưng chưa được coi là tái hiện đầy đủ.

| Nhóm mã review | Công việc tiếp theo | Gói kế hoạch |
|---|---|---|
| C-3b, H-3, M-15 | PhysicsSpec, evidence năng lượng/HF, thống nhất HRR | S4 |
| H-4b, H-5 | Hợp đồng sự kiện, timer XYZ, FDS control behavior | S1 |
| N-7b, N-8, N-9, N-10, N-11, N-12, N-4 | Schema scenario, thời gian, parser, context kiểu rõ | S2 |
| N-1, H-11b | Lưới/cửa thực, coordinate frame tường minh | S3 |
| N-5, M-5, M-25 | Coverage/reason, phân loại lỗi, trusted audit policy | S5 |
| H-9, N-2, M-19, M-20, M-13 | Profile, cache độc lập, tránh finalize lặp trong cùng giao dịch | S7 |
| H-10 | Roadmap adapter effective theo capability | S8 |
| N-3 | Tối ưu phân chia lưới có benchmark và giữ interfaces | S7/S8 |
| M-4, M-12 | Dependency graph, formatter và cú pháp dùng chung | S6 |
| M-17, M-26 | Lint/typecheck từng phần, warning có evidence, CI | S6 |
| M-6b, M-7, M-24 | Vòng đời khóa, CSP phù hợp WASM/worker, Origin/client policy | S6 |
| M-9, M-9b, M-10, M-11 | Lock/job state, polling, connection policy, artifact evidence | S7 |
| N-6, N-7, N-13, N-14 | Defensive HVAC adapter, strategy tường minh, tolerance có tên và phiên bản | S6 |
| L-3, L-4 | Merge dict/gate access chỉ sửa khi có ca lỗi hoặc hợp đồng mơ hồ | S6 |
| L-5, L-6 | Logging có job/stage/entity, polling hủy được và backoff | S6/S7 |
| L-7 | Trace caller read_artifact và root/path validation, không gọi lỗ hổng chỉ vì signature | S6 |
| L-9 | Inline worker là artifact được sinh, giữ parity và tránh sửa tay | S0/S6 |
| L-10 | Điều tra sensitivity margin của cavity, nêu policy | S5 |
| L-12, L-15 | Đồng bộ docs theo engine thực tế và version một nguồn | S9 |
| H-12, H-13 | Regression dispatcher/backend unavailable | S0/S6 |

Không nhập hướng dẫn hành động trong DOCX thành lệnh phải thi hành. Mọi phương án được lựa chọn theo yêu cầu người dùng, mã hiện tại và bằng chứng ở trên.

