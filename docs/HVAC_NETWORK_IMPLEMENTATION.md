# Luồng HVAC và bản sửa logic 02/11/2026

Bản sửa này thay nhánh suy luận ống từ hộp bao bằng mạng dùng port IFC và thông số được khai báo rõ. Hai đoạn ống nối trong IFC hiện tạo **một mạng gồm 3 NODE và 2 DUCT**, được audit độc lập và được FDS 6.11.1 chấp nhận khi khởi tạo.

## Cách sử dụng

Giữ profile `mapping` và cấp quyết định `action: "HVAC"` cho các đoạn ống thông gió cần đưa vào mạng. Dùng trường `decisions` trong cấu hình CLI/API hoặc tải file quyết định ở giao diện Verified Mapping.

Ví dụ một quyết định cho ống tròn:

```json
{
  "SOURCE_HASH:DUCT_STEP_ID": {
    "action": "HVAC",
    "policy_version": "hvac-v1",
    "reviewer": "Nguoi tham dinh",
    "rationale": "Xac nhan ong thong gio va dieu kien dau noi",
    "evidence": "Ho so thiet ke thong gio",
    "hvac": {
      "diameter_m": 0.2,
      "roughness_m": 0.0001,
      "endpoints": {
        "SOURCE_HASH:EXTERIOR_PORT_STEP_ID": {
          "kind": "AMBIENT",
          "loss": [1.0, 1.0]
        }
      }
    }
  }
}
```

Các khóa trong ví dụ là chỗ cần thay bằng `entity_key` và `port_key` thực tế từ inventory. Chúng không phải GlobalId hay tên tự đặt. Chỉ khai báo boundary tại đầu mạng; hai port nối giữa hai đoạn ống dùng quan hệ `IfcRelConnectsPorts` và được gom thành NODE chung.

- Tiết diện tròn: `diameter_m`.
- Tiết diện khác: `area_m2` và `perimeter_m`, không khai báo cùng `diameter_m`.
- Chiều dài mặc định là khoảng cách giữa hai port trong hệ tọa độ mét. Có thể khai báo `length_m`, nhưng không được nhỏ hơn khoảng cách hai đầu.
- `roughness_m` không âm. `volume_flow_m3_s` là tùy chọn; dấu theo thứ tự hai port của đoạn ống trong inventory, nên chỉ khai báo khi đã xác nhận hướng nối.
- Các thông số cấu hình dùng đơn vị SI. Chưa tự đổi lưu lượng hoặc áp suất từ property set không rõ đơn vị.

Để nối với miền CFD, dùng boundary:

```json
{
  "kind": "VENT",
  "vent_xb": [1, 1, 1, 1.4, 2, 2.3],
  "loss": [1, 1]
}
```

VENT phải là hình chữ nhật có diện tích dương, trùng một mặt OBST được hỗ trợ hoặc mặt biên MESH, và chứa tọa độ port. Hệ thống sinh VENT có `SURF_ID='HVAC'` rồi liên kết NODE bằng `VENT_ID`. Không tự đặt đầu bị thiếu dữ liệu thành AMBIENT.

## Ví dụ chạy được

[Thư mục mẫu](evidence/hvac-network-v1/) có IFC tổng hợp, quyết định, cấu hình, FDS và kết quả audit. Đây là ví dụ mạng có hai đầu AMBIENT để kiểm tra topology, không phải một thiết kế hút khói công trình. Muốn trao đổi khí với không gian CFD cần cấu hình VENT phù hợp.

Chạy lại để tạo bộ ví dụ mới:

```powershell
.\.venv\Scripts\python.exe scripts\audit-project-logic.py
```

Script in đường dẫn `evidence.json`. Trong cùng thư mục, `hvac/model.fds` là file mạng đã qua mapping audit; `hvac/input-configuration.json` là cấu hình tương ứng. Hai profile còn lại được xuất riêng để đối chiếu hình học với mạng vận hành.

Trên giao diện, profile Geometry Fidelity đã được đổi nhãn để làm rõ rằng nó xuất **hình học thiết bị thụ động**. Chọn profile đó không đồng nghĩa thiết bị có chức năng hút khói. Mạng HVAC từ FDS có lớp hiển thị riêng và nút bật/tắt `HVAC Network`.

## Những lỗi đã sửa

| Phát hiện trong audit | Thay đổi |
|---|---|
| R01: nhầm hình học với vận hành | Giữ lựa chọn hình học riêng, thêm operational network plan và giải thích profile trên UI |
| R02/R03: node thiếu biên, từng ống thành mạng rời | Gom port theo quan hệ IFC thực; kiểm tra terminal/internal node; sinh NODE/DUCT/VENT từ plan |
| R04: chiều dài/diện tích từ AABB | Bỏ suy luận AABB; dùng port chord và diameter hoặc area/perimeter rõ đơn vị |
| R05: manifest và audit không nhận HVAC | Tách operational records; kiểm tra network/provenance/assignments; báo coverage vận hành riêng với vật cản |
| R06: grammar/ID/tham chiếu mạng | Thêm AMBIENT; namespace NODE/DUCT; kiểm tra tham chiếu hai chiều, điều kiện biên và tham số dương |
| R07: hai đường validation khác gate | Cả engine và runner dùng checker HVAC và mesh-resolution; runner giữ lại kết quả effective geometry |
| R08: scenario tạo phòng thay thế khi thiếu nền | Yêu cầu bundle đã được xác minh; kiểm tra FDS/report/geometry; dựng plan sự kiện từ manifest đã seal; đo mesh từ FDS thật |
| R09: mở cửa vẫn còn fill cố định | Gắn điều khiển vào OBST cửa gốc, giữ ID/hình học/SURF và bỏ closure trùng; ID điều khiển không còn trùng khi hai cửa chung source hash |

Scenario còn kiểm tra xe nằm trong miền đã xác minh, dùng công suất thực của nguồn được sinh và giữ thời gian chạy đủ các mốc RAMP. Trạng thái sinh file/kiểm tra lưới không được mô tả là kết quả mô phỏng đã chạy.

## Ranh giới hỗ trợ hiện tại

- Hỗ trợ operational adapter cho `IfcDuctSegment` và `IfcFlowSegment` có phân loại thông gió/hút khói, hai port nguồn và quan hệ nối tường minh. Không tự biến ống nước PCCC thành ống gió.
- Chưa tự chuyển co/fitting, fan, damper, aircoil hoặc filter thành mô hình vận hành. Nếu chọn HVAC cho các loại chưa hỗ trợ, hệ thống trả lỗi rõ ràng.
- Chưa tự trích và xác nhận đầy đủ thông số thủy lực từ IFC profile/property sets; người dùng cung cấp thông số có thẩm định. Không dùng kích thước hiển thị thay cho dữ liệu còn thiếu.
- VENT ghép vào GEOM chưa được hỗ trợ. Điều khiển cửa dạng GEOM hoặc lịch nhiều sự kiện trên cùng cửa hiện bị từ chối thay vì tạo file có hành vi không chắc chắn.
- FDS initialization đã được kiểm tra. Chưa thao tác nhập file trực tiếp vào ứng dụng PyroSim hay xác nhận lưu lượng/áp suất hút khói công trình thực tế.

## Kiến trúc đã bắt đầu tách

- **Domain:** `domain/mep/hvac.py` chứa DuctSpec, EndpointSpec và HvacNetworkPlan; không phụ thuộc IFC kernel, filesystem hay namelist.
- **Biên dịch mạng:** `mep/network.py` biến source port topology và quyết định thành intent được kiểm tra.
- **Adapter FDS:** `mep/fds_records.py` chuyển plan thành bản ghi; exporter hình học không còn tự tạo thông số ống.
- **Validation:** `validation/checkers/hvac.py` đối chiếu file đã xuất với intent dựng lại; `validation/hvac.py` kiểm tra ngữ nghĩa mạng.
- **Scenario:** `application/services/scenario_base.py` xác nhận nền; `fire/scenario_composer.py` ghép sự kiện với biểu diễn nền.

Chưa di chuyển toàn bộ repository theo cây `modules/…` hay hợp nhất hoàn toàn hai engine validation. Đây là bước tách trách nhiệm đầu tiên, giữ các facade và kiểm tra tương thích hiện có. Các bước tiếp theo là adapter thiết bị/fitting và dùng cùng một bộ điều phối checker cho toàn bộ pipeline, sau khi giữ đủ các bảo vệ source preflight/boundary đang có.

## Kiểm chứng

- **471 bài Python pass**, 9 bài có marker solver/browser bị loại khỏi lệnh mặc định. Bao gồm IFC thật, mutation mạng, ống tròn đặt chéo, scenario thiếu nền/sai hash và sự kiện cửa.
- **13 script JavaScript pass**, gồm ca parser → geometry adapter → Three.js line cho HVAC, vent centroid và coordinate rebase.
- **4 ca solver FDS 6.11.1 pass**, gồm hai ca HVAC mới: AMBIENT endpoints và VENT nối CFD. Các ca này kiểm tra khởi tạo, không tự cấp `SIMULATION_VERIFIED`.
- Baseline A–F giữ nguyên nguồn, hình học, hash package, manifest CSV và verdict; chỉ bổ sung kỳ vọng hai gate mới NOT_APPLICABLE cho các fixture không có HVAC vận hành/nguồn cháy.
