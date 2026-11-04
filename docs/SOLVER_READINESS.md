# Cấu hình và bằng chứng FDS solver

Từ đợt sửa ngày 03/11/2026, bộ kiểm tra tìm executable theo thứ tự:

1. `audit.solver_executable` do operator cấu hình. Với server, biến môi trường `IFCFDS_SOLVER` được đưa vào trường này; upload không được phép chỉ định executable.
2. Lệnh `fds` trong PATH của tiến trình.
3. Trên Windows với phiên bản yêu cầu 6.11.1, đường dẫn cố định trong repository: `.deps/fds-6.11.1/firemodels/FDS6/bin/fds_openmp.exe`. Bản này chỉ được dùng khi SHA-256 khớp binary đã ghim trong `scripts/install-fds.py`.

Đường dẫn tường minh sai không làm chương trình âm thầm chọn bản khác. Discovery không tải hay cài phần mềm và không thực thi executable; bước solver sau đó mới ghi input, kiểm tra phiên bản và chạy FDS với giới hạn thời gian như trước.

Muốn cài bản được ghim, operator chạy `python scripts/install-fds.py`. Muốn dùng bản riêng, đặt `IFCFDS_SOLVER` trước khi khởi động server hoặc truyền `--solver` cho CLI. Khi dùng PATH, tên lệnh cần là `fds`.

Operator có thể đặt `IFCFDS_SOLVER_AUTODISCOVERY=0` để tắt cả tìm trong PATH và `.deps`. Đường dẫn cấu hình tường minh vẫn có hiệu lực. Tùy chọn này hữu ích khi chỉ muốn kiểm tra tĩnh và được dùng trong bộ kiểm thử không đánh dấu `solver`, để kiểm thử không phụ thuộc executable trên máy. Các worker con kế thừa lựa chọn này.

Đầu ra `gates.solver.evidence.resolution` ghi `source`, đường dẫn đã giải quyết, lý do và checksum khi tìm bản ghim. Các source gồm `explicit`, `PATH`, `project-pinned`, `disabled`, `not-found`. Không tìm thấy bản phù hợp hoặc checksum sai trả `INCONCLUSIVE` với lý do; không ghi `PASS`.

Tìm thấy executable chưa chứng minh mô hình chạy đúng: vẫn cần probe đúng FDS 6.11.1, kết thúc bình thường, hash input và bằng chứng của job. Preflight topology hoặc syntax/mesh gate không đạt vẫn có thể chặn solver.

Bộ đọc effective geometry kiểm tra OBST tĩnh trên một hoặc nhiều MESH đều và không chồng nhau. Với vật cản qua biên, đầu ra giữ phần vật cản theo từng mesh và chỉ chấp nhận khi các phần ghép thành một khối liên tục. GEOM, HOLE, VENT và vật cản điều khiển theo thời gian vẫn `INCONCLUSIVE`. Đối chiếu PyroSim và xác nhận vật lý cần bằng chứng riêng.
