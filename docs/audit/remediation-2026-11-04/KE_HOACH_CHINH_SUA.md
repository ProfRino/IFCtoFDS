# Kế hoạch chỉnh sửa IFCtoFDS theo review và bằng chứng mới

Ngày lập 04/11/2026. Trạng thái PLANNED. Kế hoạch được lưu trước khi thay đổi mã thực thi của đợt này. Mốc là working tree trên `codex/conversion-contracts-repair`, HEAD `c982eed7009000149680894dbf147d143b9db9be`, không phải HEAD sạch. [Phân tích và bằng chứng](PHAN_TICH_LOI.md)

## 1 Mục tiêu và thứ tự ưu tiên

Hoàn tất sửa đổi chuyển đổi ngày 03/11, loại lỗi điều khiển cửa và thời gian mô phỏng, thống nhất các đường kiểm toán, xác định rõ khả năng vật lý và giữ bằng chứng độc lập. Sau khi khóa đúng đắn mới tối ưu hiệu năng và tách module.

Mục tiêu không phải khiến mọi IFC được ACCEPTED. Đầu ra đạt yêu cầu có thể là REJECTED hoặc INCONCLUSIVE nếu chỉ đúng đối tượng, nguyên nhân, phạm vi chưa kiểm tra và việc cần bổ sung.

Ưu tiên triển khai theo thứ tự S0 → S1 → S2 → S3 → S4 → S5 → S6 → S7 → S8 → S9. S5 phụ thuộc các hợp đồng xác định từ S0 và có thể được đưa lên ngay sau S2 nếu việc parity đang chặn S3. Mọi đổi thứ tự phải được ghi vào sổ theo dõi trước sửa phần liên quan.

S8 là mở rộng capability theo từng mốc, không dùng việc hoàn tất S1–S7 để tuyên bố GEOM hoặc multi-mesh đã được chứng nhận.

## 2 Hợp đồng đầu vào

| Mã | Đầu vào | Điều kiện bắt buộc |
|---|---|---|
| I01 | Nguồn IFC và mô hình preview | Giữ source SHA, filename, entity_key, STEP/GlobalId. Preview chỉ có metadata không được đi vào exporter cần mesh. Không thay IFC gốc |
| I02 | Mesh và normalization | Vertices hữu hạn, faces/index hợp lệ. Giữ raw/result hash, phép biến đổi và dung sai. Tuân IN-03 cũ về 8 ULP có trần 1e-12 m, không vá mặt hở hoặc đổi cavity để lấy PASS |
| I03 | Scope và miền | Sáu số hữu hạn, min < max, mét, source identity và coordinate_frame. Nếu có rebase và tọa độ tường minh nhưng thiếu frame thì từ chối thay vì đoán theo 1000. Miền tự động nội bộ có frame do pipeline xác định |
| I04 | Lưới | Lấy các MESH từ FDS cuối hoặc MeshPlan tương đương đã kiểm parity. Có origin, IJK, dx/dy/dz, mesh_id. Không dùng fallback 0,2 m thay lưới thực |
| I05 | Kịch bản | ScenarioSpec có schema_version, base_bundle_sha256, selections, devices, events, time policy và physics policy. Một biểu diễn canonical sau biên. Giá trị trùng khác nhau giữa legacy/nested phải lỗi |
| I06 | Sự kiện cửa | entity_key trỏ đúng một fill OBST đã xác minh, OPEN/CLOSED, thời gian hữu hạn không âm. Timer có vị trí hợp lệ trong mesh. Nhiều sự kiện/GEOM chưa hỗ trợ phải từ chối rõ |
| I07 | Vật lý EV | HRR có đơn vị rõ, dimensions/position/time hữu hạn, preset và digest có nguồn. Ngân sách năng lượng phân biệt phần pin và vật liệu xe, nêu phạm vi cháy. Thiếu dữ liệu không được tự suy ra bằng tỷ lệ kWh |
| I08 | Mạng HVAC | Vai trò được duyệt, duct section/length/loss có schema và nguồn, đúng liên kết IFC port, boundary hợp lệ. Không tự nối ống hoặc biến hệ nước thành hệ khí |
| I09 | Audit policy | Cấu hình tạo artifact dùng để tái lập, tách khỏi giới hạn nghiệm thu do auditor chọn. Manifest không được tự cấp tolerance tin cậy hoặc executable để chứng nhận chính nó |
| I10 | Solver | Binary FDS ghim và hash có evidence. Explicit config sai không fallback. Log lỗi dù exit code 0 vẫn FAIL. Phiên bản thiếu/chưa chạy phải ghi rõ |

Schema mới phải có adapter cho dạng request cũ thực sự còn dùng. Adapter chạy trước extra=forbid của canonical model, có deprecation reason và test tương thích. Không bật forbid rồi vô tình làm hỏng panel EV hiện có.

## 3 Hợp đồng đầu ra và tiêu chí nghiệm thu

| Mã | Đầu ra đạt yêu cầu | Bằng chứng bắt buộc |
|---|---|---|
| A01 | Preview không xuất Quick sau tải/toggle/delete/Undo, lỗi mesh có entity/stage | Node + browser qua controller thật, worker thật và inline parity |
| A02 | Miền theo đúng nguồn, frame và bounds, không thu hẹp vì làm tròn | ALL → Tang7, stale response, world/rebased và giá trị biên nhỏ |
| A03 | Normalization không thay hình học vật lý và không che dữ liệu lỗi | Raw/result proof, openings 6671, 8 STEP ALL, cavity/shell fixtures, giải thích Duplex |
| A04 | OPEN có fill trước sự kiện và không còn fill sau, CLOSED ngược lại | FDS 6.11.1 chạy đủ thời gian, CTRL/DEVC log và SHOW/HIDE_OBST, đối chiếu bước thời gian |
| A05 | Thiếu fill/bounds, thời gian sai hoặc lịch chưa hỗ trợ bị từ chối trước tạo artifact hoàn chỉnh | Unit emitter + composer + worker + HTTP, không có CTRL vô tác dụng |
| A06 | FDS cuối có TIME đúng policy, không exponent sót, hash đúng bytes lưu | Các dạng số/namelist, parse lại sau sửa cuối, worker file đọc lại |
| A07 | Opening grid dùng tiết diện thông thủy và lưới thực, không kết luận effective PASS từ heuristic | Fixture X/Y/Z, cửa nghiêng/mơ hồ, translated grid, anisotropic/multi-mesh, hai entrypoint |
| A08 | Năng lượng và HF có trạng thái/nguồn rõ, dữ liệu thiếu không được xác minh vật lý | Tích phân RAMP đã serialize, budget cases, API/report/UI nhất quán |
| A09 | Engine và runner cùng preflight, dependencies, coverage và verdict | Mixed source errors, full/fail-fast/partial, mocked forbidden dependent calls |
| A10 | Mọi gate có reason_code, reason và evidence phù hợp trạng thái | Invariants cho PASS/FAIL/NOT_RUN/INCONCLUSIVE/NOT_APPLICABLE, không dùng placeholder |
| A11 | HVAC giữ ngữ nghĩa, đúng topology và không phát passive trùng | Fixtures mạng, thiếu dữ liệu, scope boundary, solver, PyroSim ghi riêng |
| A12 | Policy kiểm toán độc lập với artifact và lỗi được phân loại | Mutation manifest tolerance/source/hash; DATA_INVALID/DATA_AMBIGUOUS/UNSUPPORTED/INTERNAL_ERROR |
| A13 | Cải tiến kiến trúc/hiệu năng giữ kết luận audit và truy vết | Import graph, migration tests, profile cùng máy, deterministic outputs và scoped caches |
| A14 | Các giới hạn effective có capability matrix và bằng chứng đúng mốc | OBST single mesh, OBST multi-mesh, GEOM/HOLE/VENT mỗi loại một mục độc lập |
| A15 | Bàn giao khớp mã, docs, test và artifact hiện hành | Full suites phù hợp, SHA/config/version/log, cập nhật OUT-xx và A-xx |

Các mã trạng thái job, mapping, simulation, physics và mesh phải là trường riêng. Job COMPLETED hoặc mesh PASS không được hiển thị thành “mô phỏng đạt”. Nếu giữ trường verdict cũ, phải định nghĩa và kiểm bằng test chuyển đổi, không âm thầm đổi nghĩa.

## 4 Các gói triển khai

### S0 Khóa nền sửa đổi đang có

Phạm vi gồm controller, verified-workflow, fds-exporter, geometry normalization/cache, engine partial và solver discovery đang chưa commit.

1. Ghi git status/diff, phiên bản dependency, source SHA và cấu hình. Lưu bản diff để phân biệt thay đổi trước/sau đợt mới.
2. Chạy bộ liên quan đã có, sau đó giải quyết browser failure ở selection/delete bằng luồng chọn thực tế. Không chỉ sửa assertion cho xanh.
3. Tái chạy Duplex với normalization bật/tắt trong ca chẩn đoán. So sánh entities được đưa vào phép Boolean, oriented faces, volumes và cavity. Chỉ đổi expected nếu có bằng chứng đây là baseline sai.
4. Cập nhật OUT-01 đến OUT-12 cũ theo log có thật. Giữ NOT_RUN cho ca chưa chạy.
5. Khóa mẫu tốt và mẫu lỗi cho các bước sau. Chưa refactor rộng trước khi giải thích regression hiện có.

Điều kiện xong gồm A01–A03 và các phần bằng chứng cũ đã đối chiếu. Nếu nguồn IFC thật còn lỗi, ghi nguyên trạng và vẫn cho phép tiến sang các gói không phụ thuộc kết luận hình học đó.

### S1 Sửa điều khiển cửa

File chính gồm `fire/scenario_emitter.py`, `fire/scenario_composer.py`, model sự kiện và tests scenario/solver.

1. Thêm regression cho ERROR(885), giữ ca FDS trả code 0 nhưng log lỗi.
2. Đưa validation sự kiện vào hợp đồng chung, yêu cầu đối tượng đích và vị trí timer hợp lệ.
3. Chọn biểu diễn timer/control rõ ràng. Ưu tiên một quan hệ điều khiển đơn giản nếu không cần tổ hợp, hoặc khai INITIAL_STATE trên CTRL theo hướng dẫn chính thức. Không chỉ đổi comment.
4. Thêm oracle trạng thái vật cản trước/sau sự kiện, tránh chỉ assert chuỗi INITIAL_STATE.
5. Composer giữ identity, bounds và surface của fill gốc. Không thêm một fill mới đè lên fill gốc.
6. Chạy lại qua worker và ít nhất một request HTTP với nền đã xác minh.

Đầu ra A04/A05. Ca FDS hiện tại chưa sửa phải tái hiện sai, ca sau sửa phải có đúng chuyển trạng thái. Sai lệch thời điểm được giới hạn theo bước thời gian quan sát, không hardcode mốc 1,27732 s.

### S2 Chuẩn hóa scenario và chỉnh TIME có cấu trúc

File chính gồm `server.py`, `adapters/jobs/runner.py`, domain/fire schema, application scenario service, parser/formatter và dispatcher JS.

1. Định nghĩa ScenarioSpec và mapping legacy rõ ràng. Reject các giá trị NaN/Infinity, giờ âm, field lạ và xung đột giữa hai nguồn.
2. Resolve preset/dimensions/HRR một lần, dùng lại cùng DTO cho mesh gate, emitter, report.
3. Tách thao tác TIME khỏi worker. Đọc và chỉnh record đã parse, giữ các trường TIME khác, reject duplicate không được hỗ trợ.
4. Thay floor 1800 s ngầm bằng policy có tên. Mặc định giữ T_END nền dài hơn và bảo đảm toàn bộ ramp/events thuộc thời gian nếu người dùng chọn chạy đầy đủ. Nếu cho phép cắt ngắn để khảo sát, phải explicit và ghi incomplete-duration, không coi đó là toàn kịch bản.
5. Parse FDS lần cuối sau mọi chỉnh sửa và tính hash theo bytes thực ghi ra. Tách hash fragment, final FDS và bundle nếu giữ cả ba.
6. Thay context model=object() bằng contract đúng dữ liệu checker cần.

Đầu ra A05/A06/A08. Test tối thiểu gồm 1.8E3, 1.8e3, 1.8D3 nếu parser hỗ trợ, số có dấu, nhiều dòng, TIME thiếu T_END, không TIME, HEAD thiếu hoặc lặp, request t_end sai, ramp vượt thời gian và file có nhiều RAMP. Cú pháp không hỗ trợ phải từ chối rõ, không tự đoán.

### S3 Sửa miền tọa độ và kiểm tra cửa theo lưới thật

File chính gồm `application/services/model_preparer.py`, `validation/effective.py`, `validation/checkers/openings.py`, schema MeshPlan và các entrypoint kiểm toán.

1. Với scope/domain tường minh và có rebase, yêu cầu coordinate_frame. Giao diện phải gửi frame cùng source identity.
2. Tạo descriptor lưới từ FDS cuối. Không thêm một fallback cell_size khác vào AuditConfig để che lỗi.
3. Lấy pháp tuyến và tiết diện thông thủy từ quan hệ opening/host có evidence. Trường hợp axis-aligned rõ mới dùng hai trục tiếp tuyến. Trường hợp AABB mơ hồ hoặc cửa nghiêng chưa hỗ trợ trả INCONCLUSIVE.
4. Đánh giá theo origin và bước lưới từng trục, phát hiện giao nhiều mesh. Không mặc định mọi mesh có ô lập phương.
5. Tách kết quả rủi ro tiên nghiệm khỏi gate effective_geometry. Hiển thị phạm vi và căn cứ trong report/UI.
6. Dùng cùng phép đo cho engine và runner.

Đầu ra A02/A07. Bốn cửa bình thường trong probe không bị đánh dấu chỉ do tường mỏng. Lỗ nhỏ chỉ được kết luận khi hướng đã xác định, nếu mơ hồ phải nói rõ. Translation đồng thời cửa và origin không được làm đổi kết luận.

### S4 Chuẩn đầu ra vật lý cháy

File chính gồm domain/fire, EV library, emitter, scenario service, mesh checker và UI/report.

1. Thêm PhysicsAssessment với energy_budget, provenance, assumptions, energy_curve_mj, energy_within_tend_mj, status và reason.
2. Tích phân tuyến tính từng đoạn RAMP đúng thời gian/giá trị sau serialize. Đối chiếu với ngân sách nhiệt hóa học có nguồn, tách khỏi điện năng danh định.
3. Ca 40 kWh/7 MW khi thiếu budget trả INCONCLUSIVE có lý do, không phải lỗi vì một tỷ số tùy ý. Ca có budget bị vượt trả FAIL theo policy đã khai. Giữ đủ metadata cho kỹ sư đánh giá.
4. Chế độ nghiên cứu có thể xuất artifact chưa được xác minh kèm assessment. Yêu cầu xác minh vật lý phải bị chặn nếu thiếu dữ liệu.
5. Đặt HF NOT_MODELED trong capability/assessment và không sinh SPEC không có nguồn trong fragment do công cụ quản lý. Request yêu cầu HF định lượng phải nhận unsupported rõ.
6. Thống nhất HRR đã chọn giữa UI, emitter và mesh checker. Ghi rõ lựa chọn trung điểm/giá trị người dùng/chế độ bảo thủ.

Đầu ra A08. Chưa phát triển complex chemistry/HF hoặc thermal runaway trong gói này. Nếu bổ sung mô hình nguồn, phải lập extension với cân bằng khối lượng, dữ liệu nguồn và solver evidence trước sửa.

### S5 Thống nhất kiểm toán và điều tra hình học

File chính gồm `validation/engine.py`, `validation/runner.py`, domain validation, checker outcomes/evaluator, Boolean/metrics và audit use case.

1. Tách SourcePreflight và GeometryComparisonSummary dùng chung. Coverage đi qua CheckerOutcome, evaluator hợp nhất có kiểm tra xung đột.
2. Khai dependency của gate tường minh. Nguồn không đủ điều kiện phải chặn các phép kiểm toàn cục phụ thuộc. Chế độ partial chỉ thu chứng cứ cục bộ có thể làm độc lập.
3. Cả hai entrypoint có cùng status/count/reason trên fixture tương đương. Không yêu cầu findings giữ thứ tự ngẫu nhiên hoặc wording byte-identical.
4. Ghi reason_code và evidence thực cho mọi gate, giữ lỗi nguồn/không hỗ trợ tách khỏi exception lập trình. INTERNAL_ERROR không được trôi thành PASS hoặc một câu thiếu dữ liệu vô danh.
5. Tách trusted acceptance policy khỏi cấu hình manifest. Mutation tolerance không được tự nới chuẩn. Giữ provenance của MEP decisions khi dùng để tái lập.
6. Điều tra leak âm bằng capture operands/result hash, component orientations, cavity, volume signed/unsigned và Boolean. Thêm fixture shell rỗng lồng nhau và winding sai.
7. Chỉ chuẩn hóa kết quả Boolean khi chứng minh bảo toàn tập thể tích và hướng cavity. Nếu chưa đủ chứng minh, giữ INCONCLUSIVE cùng chẩn đoán.
8. Đối chiếu lại package verification, độc lập reread và finalization sau thay đổi summary.

Đầu ra A03/A09/A10/A12. Số entity đã ghi FDS, attempted, compared, verified, deviated, failed, inconclusive và skipped phải có định nghĩa và tập ID đối chiếu. Không cộng các nhóm chồng lấn thành tổng.

### S6 Tách trách nhiệm module và khóa hồi quy

Thực hiện từng lát chức năng nhỏ có test, không đổi toàn bộ thư mục trong một lần.

| Module | Domain | Application | Adapter |
|---|---|---|---|
| IFC và hình học | Entity identity, mesh contracts, normalization evidence | Prepare source, convert, reread | IfcOpenShell, Boolean kernel, geometry package |
| Mapping | Scope, strategy, representation decision | Resolve policy và tạo MappingPlan | FDS writer và manifest storage |
| HVAC | DuctSpec, port/network contracts | Compile và validate network | FDS HVAC/VENT renderer |
| Scenario | ScenarioSpec, OpeningEvent, PhysicsAssessment | Validate base, resolve physics, compose scenario | FDS syntax và solver execution |
| Validation | GateResult, outcomes, dependency policy | Điều phối gates và kết luận | Geometry measurements, FDS output readers |
| Jobs và giao diện | Job/request/result DTO | Queue lifecycle và artifact access | HTTP, SQLite, filesystem, JS clients |

1. Đo import graph trước, ghi cycle thực và cạnh dependency được phép. Không cấm toàn bộ local import.
2. Tách format số/ID/namelist dùng chung có policy precision. Parser dùng chung ngữ pháp được, nhưng audit vẫn phải đọc lại bytes và xác minh hình học độc lập.
3. Giữ facade cũ trong lúc chuyển từng use case. Thêm contract tests dependency direction và behavior parity.
4. Dùng Ruff/typecheck/ESLint theo phạm vi kiểm soát, pin cấu hình và baseline legacy. Không autoformat toàn repo lẫn sửa logic.
5. Thu RuntimeWarning trong thao tác có entity context thành diagnostics. Sau khi khoanh vùng, nâng warning-as-error cho vùng đã kiểm soát, không suppress toàn bộ NumPy/trimesh.
6. HVAC dùng nhánh strategy tường minh, kiểm tra assignments khi gọi adapter trực tiếp, tolerance có tên/version/evidence. Chưa cho người dùng tùy ý tăng tolerance nối port.
7. Hợp nhất transport scenario, giữ lỗi fetch/backend/network rõ. Di chuyển API key sang memory/session theo vòng đời đã ghi, kiểm tra logout/reload.
8. CSP phải tương thích web-ifc WASM, worker, tài nguyên viewer. Origin policy phân biệt browser và CLI có xác thực, không chặn mọi request không có Origin.
9. Trace read_artifact và consumer đến root/path guard trước khi đổi API storage.

Đầu ra A11/A12/A13. Không coi sessionStorage là giải pháp thay cho CSP hoặc kiểm soát XSS.

### S7 Tối ưu theo số đo

1. Chạy hai baseline cùng máy, dependency, nguồn SHA và config. Ít nhất một warm-up và 5 lần đo, tách cold/warm cache, lưu median và độ phân tán cùng peak RSS.
2. Profile reread/openings/Boolean/package riêng. Chỉ tối ưu phần có chi phí đo được.
3. Cache trong từng audit bằng source hash, extraction options và policy revision. Không dùng mesh/proof của converter thay độc lập đọc nguồn.
4. Giảm phép union/free_volume lặp và dùng spatial index sau khi kiểm giữ nguyên semantics.
5. Thu nhỏ lock bằng state transitions có version/compare-and-set phù hợp. Test cancel, retry, cleanup, crash/restart và polling đồng thời trước tăng concurrency.
6. Xác nhận PRAGMA trên từng connection bằng regression, tránh sửa lại M-10 đã có.
7. Báo cáo chỉ giữ hash/path/summary cho artifact solver lớn. Kiểm retention không làm đứt evidence.
8. Đánh giá FFT-friendly mesh bằng FDS thật nếu triển khai. Giữ cell size, mesh interfaces, total cell budget và miền theo policy.

Ngưỡng benchmark là chính sách CI dự án, không là chuẩn vật lý. Chốt ngưỡng từ độ nhiễu baseline trước khi bật chặn merge. Nếu chưa có hai revision chạy cùng môi trường, báo chưa xác nhận mức cải thiện. Đầu ra A13.

### S8 Mở rộng effective geometry và đối chiếu PyroSim

- Mốc E1 giữ bộ OBST một mesh đã hỗ trợ, thêm mutation làm sai snapped geometry phải bị phát hiện.
- Mốc E2 OBST nhiều mesh, đọc TRNX/Y/Z theo mesh identity, đối tượng băng qua biên, kiểm không mất hoặc đếm đôi.
- Mốc E3 HOLE/VENT và sự kiện động, so sánh đúng thời điểm, không gộp ảnh khởi tạo với hình học vận hành.
- Mốc E4 GEOM cut-cell, phải xác định output solver đủ dữ liệu và xây reader có validation fixtures trước khi nhận hỗ trợ.
- Đối chiếu PyroSim qua cùng file FDS, cùng phiên bản FDS và ghi thao tác import/run, warnings và object/network nhận được. Chưa có cài đặt hoặc dữ liệu thì PYROSIM_NOT_RUN, không suy từ parser nội bộ.

Mỗi mốc có capability matrix đầu vào, supported/unsupported, artifacts và test riêng. Thất bại mốc sau không được gỡ bảo vệ mốc trước. Đầu ra A14 và phần PyroSim của A11.

### S9 Tích hợp và bàn giao

1. Chạy Python mặc định, các script JS trong verified.yml, worker parity, browser liên quan và FDS solver suite.
2. Chạy các fixtures tốt, FZK, Duplex. Với dữ liệu riêng chạy đúng ALL và Tang7/SHA đã ghi. Không đưa IFC riêng vào Git.
3. Tang7 phải tiếp tục không bị 81 kết cấu withheld do miền ALL. Các self-intersection, invalid opening và MEP thiếu thông tin vẫn có trạng thái đúng.
4. Đọc lại file FDS cuối, manifest, report và artifact hashes, đối chiếu từng A-xx và OUT-xx.
5. Cập nhật README tiếng Việt, capability matrix, changelog, version một nguồn, thay các mô tả không đúng giữa Quick/Python.
6. Ghi rõ phần đã sửa, phần dữ liệu nguồn cần xử lý và phần adapter chưa hỗ trợ. Không gộp suite chưa chạy vào PASS.
7. Chỉ chuẩn bị thay đổi để review. Commit/push/merge đợt sửa mới là thao tác riêng theo yêu cầu tiếp theo.

## 5 Quy trình đối chiếu trong lúc sửa

Trước mỗi gói ghi fixture đầu vào, lỗi hiện tại, kỳ vọng đầu ra, file dự kiến sửa và mã A/OUT liên quan. Khi có kết quả trái kế hoạch, cập nhật giả thuyết và tiêu chí trước thay đổi implementation hoặc golden.

Sau mỗi gói lưu lệnh, exit code, test counts, log, source/config SHA và kết quả của từng tiêu chí. Chỉ đổi tiêu chí sang PASS khi chứng cứ đúng phạm vi. Giữ các lần thử thất bại để giải thích vì sao đổi phương án.

Nếu sửa một contract chung, tìm mọi producer/consumer và chạy parity. Các thay đổi schema, formatter, time, coordinates, grid và summary phải có migration test. Không dùng mock thay solver/browser ở tiêu chí bắt buộc thực thi thật.

Không sửa ngưỡng nghiệm thu để biến mô hình nguồn lỗi thành đạt. Không bật solver cho đầu vào bị gate phụ thuộc chặn chỉ để có artifact.

## 6 Ranh giới hoàn thành

Hoàn tất đợt sửa nền khi S0–S6 và kiểm chứng tương ứng S9 đạt, cùng các A-xx thuộc phạm vi đó. Hiệu năng S7 và adapter S8 có tiêu chí riêng, không bị đánh dấu xong chỉ vì refactor đã merge.

Bài toán dữ liệu cần người có dữ liệu/chuyên môn gồm budget cháy toàn xe, yield HF và mô hình nguồn, thông số vận hành HVAC, IFC lỗi topology và đối chứng PyroSim thật. Phần mềm phải có luồng yêu cầu bổ sung và giữ trạng thái đúng khi chưa có. Việc thiếu các dữ liệu này không ngăn sửa lỗi timer, TIME, schema, preflight và báo cáo đã xác nhận.

