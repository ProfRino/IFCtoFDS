# Kế hoạch viết lại README.md bằng tiếng Việt

Ngày lập: 02/11/2026. Phạm vi: README giới thiệu dự án và hướng dẫn sử dụng chi tiết, đối chiếu với mã nguồn v0.5.0 cùng các bản sửa HVAC/scenario trong working tree hiện tại.

## 1. Mục tiêu và đối tượng đọc

README cần giúp ba nhóm người đọc sử dụng cùng một dự án:

- Người mới: hiểu dự án làm gì, cài đặt được, chạy được một ví dụ và biết tìm kết quả.
- Người làm BIM/PCCC: chọn đúng phạm vi, hiểu khác biệt hình học/MEP/HVAC, cấu hình mạng và đọc được báo cáo kiểm định.
- Người phát triển/nghiên cứu: hiểu kiến trúc hiện có, cách gọi CLI/API, chạy kiểm thử và tái lập kết quả.

Toàn bộ phần giải thích viết bằng tiếng Việt. Giữ nguyên tên nút trên giao diện, tên lệnh, trường JSON, tên tệp và trạng thái máy; đặt giải thích tiếng Việt ngay cạnh khi xuất hiện lần đầu.

README chứa đủ các bước sử dụng thông thường ngay trong tài liệu. Các bài phân tích thuật toán, audit lịch sử và thiết kế kiến trúc dài được liên kết tại phần đọc thêm.

## 2. Các nội dung cần hiệu chỉnh từ README hiện tại

| Nội dung hiện có | Hướng viết lại |
|---|---|
| Các cụm “chính xác tuyệt đối”, “độc lập tuyệt đối”, “production-ready” | Mô tả cụ thể thuật toán, phạm vi độc lập, phép kiểm tra đã chạy và giới hạn của kết luận |
| Số gate xuất hiện cả 12 và 14 | Liệt kê gate theo mã nguồn hiện hành và điều kiện áp dụng; giải thích gate phát sinh theo profile, không ghim một tổng số dễ lỗi thời |
| IFC → vật thể và IFC → HVAC trình bày chưa rõ | Có bảng phân biệt tham chiếu, vật cản OBST/GEOM và mạng NODE/DUCT/VENT |
| “Chạy batch mô phỏng EV” dễ được hiểu là đã chạy CFD | Tách tạo ma trận, sinh scenario.fds, kiểm tra lưới, khởi tạo solver và chạy/phân tích mô phỏng |
| HF, năng lượng pack và kiểm tra lưới được mô tả mạnh hơn mức hiện thực | Nêu rõ phần đã khai báo/tính toán, phần chưa tạo nguồn định lượng hoặc chưa được kiểm chứng vật lý |
| model.fds được mô tả gồm cả namelist cháy | Tách file nền model.fds và file kịch bản scenario.fds, giải thích quan hệ qua bundle hash |
| Manifest được mô tả ánh xạ 1–1 | Giải thích khả năng một-nhiều/nhiều-một, gồm NODE chung của nhiều đoạn ống |
| Hướng dẫn FDS chưa nói rõ nền tảng của script cài | Ghi rõ script hiện lấy bộ Windows; hướng dẫn cấu hình solver theo hệ điều hành và đường dẫn thực tế |
| Mẫu công trình và mẫu HVAC chưa được phân vai | Chỉ rõ mẫu nào dùng xem hình học, mẫu nào dùng kiểm tra mạng; ghi kết quả mẫu với cấu hình tương ứng |
| Lệnh cài đặt người dùng trộn với công cụ kiểm thử | Tách cài để sử dụng và cài thêm phần phục vụ phát triển/kiểm thử |

## 3. Bố cục README dự kiến

| Mục | Nội dung cần viết | Điểm người đọc cần nắm được |
|---|---|---|
| 1. Giới thiệu | Mục tiêu IFC → FDS, bối cảnh BIM/PCCC, phạm vi nghiên cứu, nguồn kế thừa và giấy phép | Dự án giải quyết bước nào trong quy trình mô phỏng |
| 2. Khả năng và trạng thái | Bảng chức năng: hoạt động, có giới hạn, đang phát triển; snapshot kiểm thử có ngày ghi nhận | Chức năng nào có thể sử dụng và mức kiểm chứng đến đâu |
| 3. Quy trình tổng thể | Sơ đồ Mermaid từ IFC, inventory, geometry, MEP, kế hoạch ánh xạ đến FDS, artifact và audit; nhánh scenario riêng | Phân biệt các giai đoạn và đầu ra của từng giai đoạn |
| 4. Cài đặt | Python/dependency, Windows PowerShell là luồng chính, Linux/macOS riêng, khởi động backend, cấu hình FDS tùy chọn | Cài và mở được Workbench |
| 5. Chạy ví dụ đầu tiên | Một ví dụ nhỏ có sẵn, lệnh/giao diện tương ứng, kết quả mong đợi và vị trí báo cáo | Hoàn thành một lượt chạy từ đầu đến cuối |
| 6. Sử dụng Workbench | Nạp IFC, đọc inventory, điều hướng, chọn tầng/miền/lưới, chọn profile, reviewed decisions, chạy Verified, xem kết quả và tải tệp | Sử dụng các chức năng chính theo thứ tự thao tác |
| 7. Nhiều IFC và phạm vi | Chung hệ tọa độ, transform, rebase, tầng, bounding box, simulation domain và boundary policy | Phân biệt chọn phần tử với xác định miền tính toán |
| 8. MEP/HVAC và PyroSim | Vai trò hình học, port/source identity, NODE/DUCT/VENT, thông số SI, điều kiện đầu nối, mẫu hoạt động, giới hạn thiết bị | Xuất đúng mạng thông gió và hiểu điều kiện cần có |
| 9. Kịch bản cháy EV | Mô hình nền được xác minh, preset, vị trí xe, tham số ma trận, sự kiện cửa, mesh gate, hàng đợi và scenario.fds | Sinh kịch bản gắn đúng với mô hình nền |
| 10. Đầu ra và kiểm định | Bảng tệp, cách giữ gói nhị phân, trạng thái job/gate/acceptance, findings, source keys, kiểm tra checksum | Đọc được kết quả và biết vì sao một lượt chạy bị chặn |
| 11. CLI và cấu hình | Các lệnh thật, JSON đầy đủ, phạm vi/miền, HVAC, solver, audit lại, exit codes | Tự động hóa được thao tác đã làm trên giao diện |
| 12. API | Luồng nộp job → theo dõi → đọc kết quả → tải artifact, request mẫu, hủy job, API key khi cần | Tích hợp bằng mã mà không nhầm trạng thái tác vụ với nghiệm thu |
| 13. Kiến trúc và mã nguồn | Cây thư mục thực tế, trách nhiệm từng phần, các module HVAC mới và phần kiến trúc đang chuyển đổi | Tìm đúng mã cần đọc hoặc sửa |
| 14. Kiểm thử và tái lập | Python, JavaScript, solver, browser; marker và môi trường; nguồn các IFC mẫu | Chạy lại các kiểm tra và hiểu giới hạn kết quả |
| 15. Xử lý sự cố | Bảng triệu chứng → kiểm tra → cách xử lý → kết quả cần thấy | Tự giải quyết các lỗi thường gặp |
| 16. Lộ trình, đóng góp và trích dẫn | Ưu tiên phát triển, báo lỗi tái hiện được, nguồn mô hình, AGPL và CITATION.cff | Biết phần việc tiếp theo và cách đóng góp |

## 4. Thiết kế hướng dẫn sử dụng chi tiết

Mỗi quy trình sẽ có năm phần cố định: **đầu vào cần chuẩn bị → các bước thao tác → cấu hình minh họa → đầu ra dự kiến → cách kiểm tra và xử lý khi khác dự kiến**.

### Quy trình A — Cài và mở ứng dụng

1. Kiểm tra Python và vị trí thư mục dự án.
2. Tạo môi trường riêng, cài dependency để sử dụng.
3. Đưa thêm cách gọi Python trong môi trường riêng khi PowerShell không cho chạy Activate.ps1.
4. Chạy `python -m ifc_to_fds serve --port 8000`.
5. Mở địa chỉ loopback, kiểm tra kết nối backend và cách dừng server.
6. Phân biệt mở trực tiếp index.html với chạy Workbench có backend Verified.

Giải thích FDS/PyroSim là thành phần tùy mục tiêu sử dụng; chuyển đổi hình học và xem mô hình không đồng nghĩa đang chạy solver.

### Quy trình B — Verified Mapping cho một IFC

1. Chọn IFC, kiểm tra inventory và đơn vị.
2. Xem mô hình, chọn phần tử và đọc thông tin nguồn.
3. Chọn tầng/phạm vi, xác định miền, đặt kích thước ô lưới theo mục tiêu.
4. Giải thích bốn profile bằng bảng: mục đích, dữ liệu bổ sung cần có và giới hạn nghiệm thu.
5. Tải reviewed decisions nếu cần.
6. Chạy `Run Verified Mapping`, theo dõi job và cách hủy.
7. Mở báo cáo, kiểm tra trạng thái tổng thể và các gate bắt buộc.
8. Tải model.fds cùng manifest, báo cáo, geometry index/payload hoặc archive phù hợp.

Quick Preview/Quick Export có một tiểu mục riêng giải thích năng lực và quan hệ với Verified Mapping.

### Quy trình C — Nhiều IFC

Trình bày ví dụ kết hợp kiến trúc và MEP: xác nhận tọa độ, xem nguồn bị trùng nội dung, khai báo transform, chọn phạm vi và kiểm tra lớp phủ sau rebase. Giải thích khác biệt `GlobalId`, `step_id`, `entity_key` và `port_key` bằng ví dụ ngắn.

### Quy trình D — Mạng HVAC

1. Dùng IFC/decisions/configuration đã có trong `docs/evidence/hvac-network-v1/` để chạy ví dụ kiểm chứng.
2. Chỉ cách lấy entity_key/port_key từ inventory để làm cho mô hình khác.
3. Cung cấp JSON hoàn chỉnh cho ống tròn và tiết diện khác; giải thích diameter, area, perimeter, length, roughness và đơn vị.
4. Giải thích đầu AMBIENT, đầu VENT và nút nối nội bộ.
5. Chạy Verified, kiểm tra số NODE/DUCT và gate HVAC.
6. Xem lớp `HVAC Network` trong ứng dụng; hướng dẫn đối chiếu file trong PyroSim với phiên bản được ghi nhận khi thực hiện kiểm tra.
7. Mô tả lỗi thiếu port, đầu nối chưa cấu hình, sai tiết diện, ống nước được gán HVAC, và loại thiết bị chưa hỗ trợ.

Nêu rõ ví dụ hai đầu AMBIENT kiểm tra topology; trao đổi khí với miền CFD cần đầu VENT phù hợp. Geometry Fidelity vẫn là hình học thiết bị thụ động.

### Quy trình E — Sinh kịch bản EV

1. Xác nhận bundle nền tồn tại và đạt MAPPING_VERIFIED.
2. Chọn preset đang có, đặt xe nằm trong miền tính toán và kiểm tra kích thước/vị trí.
3. Cấu hình ma trận, khoảng cách, trạng thái cửa và các tham số có trong giao diện; giải thích ý nghĩa vật lý và giới hạn của từng tham số theo mã nguồn.
4. Sinh batch, theo dõi hàng đợi và kết quả mesh gate.
5. Tải scenario.fds và giải thích khác biệt với model.fds.
6. Mô tả kiểm tra khởi tạo FDS và bước chạy/phân tích mô phỏng tiếp theo; phân biệt với trạng thái sinh file thành công.

Lệnh CLI cho scenario chỉ được đưa vào nếu thật sự có subcommand tương ứng. Hiện hướng dẫn phần này dựa trên Workbench/API.

### Quy trình F — Đọc báo cáo và audit lại

Giải thích riêng ba cấp trạng thái:

- **Job:** QUEUED/RUNNING/COMPLETED/FAILED và các trạng thái vòng đời được triển khai.
- **Gate:** PASS/FAIL/NOT_RUN/INCONCLUSIVE/NOT_APPLICABLE.
- **Acceptance:** MAPPING_VERIFIED/REJECTED/INCONCLUSIVE; vị trí và giới hạn của SIMULATION_VERIFIED.

Dùng ví dụ JSON ngắn để chỉ cách tra finding về phần tử IFC, tìm gate bắt buộc, kiểm tra output_complete và checksum. Nêu rõ việc thiếu solver hoặc effective geometry có ảnh hưởng ra sao theo profile/required flag thực tế.

## 5. Ví dụ và tài nguyên cần chuẩn bị

- Một cấu hình tối thiểu để chuyển đổi một IFC bằng CLI.
- Một bộ cấu hình HVAC hoạt động, dùng nguyên các tệp mẫu hiện có để giữ đúng source hash và port key.
- Một request API nộp job, lấy trạng thái, đọc kết quả và tải artifact; một request scenario dùng bundle nền thực tế.
- Bảng file đầu ra lấy từ adapter storage và registry artifact; ghi rõ tên phụ thuộc tên file xuất CLI.
- Một cây thư mục theo mã hiện tại, thay vì dùng bản mô tả as-is cũ như nguồn duy nhất.
- Ảnh Workbench, vị trí cấu hình Verified, lớp HVAC, Audit Drawer và bảng scenario. Dùng ảnh hiện có khi khớp giao diện; đánh dấu những ảnh cần chụp cập nhật trong bước viết.
- Chú thích thuật ngữ: IFC, FDS, PyroSim, OBST, GEOM, HVAC, MEP, inventory, manifest, scope, mesh và port.

## 6. Tổ chức thực hiện

| Bước | Công việc | Sản phẩm kiểm tra được |
|---|---|---|
| 1 | Lập bảng đối chiếu tính năng và tuyên bố | Từng khả năng gắn với mã nguồn, bài kiểm tra hoặc giới hạn đã ghi nhận |
| 2 | Chốt dàn ý và thứ tự đọc | Người mới tìm được cài đặt/ví dụ trước phần thuật toán và kiến trúc |
| 3 | Viết mô tả dự án và quy trình tổng thể | Phần giới thiệu, bảng trạng thái, sơ đồ và bảng profile |
| 4 | Viết hướng dẫn A–F | Mỗi quy trình đủ đầu vào, thao tác, cấu hình, đầu ra và cách tự kiểm tra |
| 5 | Viết CLI/API, cấu hình và vận hành | Các ví dụ bám đúng help, schema và endpoint thật |
| 6 | Viết kiến trúc, kiểm thử, sự cố và lộ trình | Phân biệt rõ hiện trạng với kiến trúc mục tiêu |
| 7 | Kiểm tra toàn tài liệu | Chạy ví dụ, kiểm tra JSON/đường dẫn, đối chiếu trạng thái và đọc thử theo vai người mới |

## 7. Tiêu chí hoàn thành

- README có mục lục và liên kết nội bộ hoạt động, giải thích thống nhất bằng tiếng Việt.
- Người mới hoàn thành được một ví dụ có sẵn và tìm được file/báo cáo kết quả bằng các bước trong README.
- Mọi lệnh chính được kiểm tra với CLI hiện tại; ví dụ API dùng đúng tên trường, định dạng request và thứ tự gọi.
- Có hướng dẫn HVAC hoàn chỉnh, thể hiện rõ mạng vận hành khác với hình học vật cản.
- Có hướng dẫn scenario hoàn chỉnh, phân biệt sinh file, kiểm tra lưới, khởi tạo solver và xác minh mô phỏng.
- Các trạng thái job/gate/acceptance không bị dùng thay thế nhau.
- Các ví dụ nêu kết quả dự kiến, gồm cả trường hợp có thể REJECTED/INCONCLUSIVE do nguồn hoặc cấu hình.
- Số liệu kiểm thử có ngày, môi trường và phạm vi; không coi số lượng bài pass là bằng chứng xác thực mô phỏng công trình.
- Ảnh, tệp mẫu, nguồn mô hình, giấy phép và trích dẫn đều có liên kết phù hợp.
- Nội dung kiến trúc nêu đúng phần đã tách và phần đang chuyển đổi.

## 8. Phạm vi sản phẩm tài liệu

Sản phẩm chính của bước viết tiếp theo là **README.md tiếng Việt được viết lại đầy đủ**, cùng các tệp ví dụ/ảnh cần thiết nếu có. Liên kết README.en.md được giữ và ghi rõ khi bản tiếng Anh chưa đồng bộ với nội dung mới. Việc dịch đồng bộ bản tiếng Anh, sửa code hay bổ sung chức năng ứng dụng là các phần việc riêng.

Các nguồn đối chiếu đã đọc khi lập kế hoạch: README hiện tại, pyproject.toml, CLI help và cli.py, server.py, registry artifact, giao diện index.html, CI verified.yml, tài liệu HVAC mới, fixture HVAC và CITATION.cff.
