# Chạy Flex-split và PlaceRAN

Tài liệu này mô tả đúng các entry point hiện tại của repo: cần sửa file nào,
đứng ở thư mục nào để chạy, dữ liệu được sinh ở đâu và dùng file nào để so
sánh Flex-split với PlaceRAN.


## So sánh theo kích thước mạng T2

Đây là workflow nên dùng khi cần chạy các mạng `8, 16, 32, 64, 128, 256` và
tạo `comparison.csv` tự động.

Hai phương pháp phải dùng cùng:

- kích thước mạng;
- phân bố RU, thông thường là `F1` đối với các mạng sinh theo kích thước;
- resource profile, thông thường là `LC`;
- số candidate paths `k_paths`;
- node/link JSON tương ứng.

### Bước 1: sinh PHY và candidate paths cho Flex-split

Sửa file:

```text
FlexRanSplitProblem/settings/path_gen.txt
```

Ví dụ để sinh mạng 8, 16 và 32 với 10 path/RU:

```ini
[generation]
networks = 8, 16, 32
profile = LC
core = 0
k_paths = 10
overwrite = true

[input]
source_directory = FlexRanSplitProblem/model_files/T2_files

[output]
directory = FlexRanSplitProblem/data
```

`directory = FlexRanSplitProblem/data` rất quan trọng: đây là cây dữ liệu mà
`run_ilp.py` đọc mặc định. Không để `directory = data` nếu muốn lệnh solve bên
dưới dùng ngay dữ liệu vừa sinh.

Đặt `overwrite = true` khi thay `k_paths`, `profile` hoặc muốn tạo lại pickle.
Sau khi sinh xong có thể đổi lại thành `false` để tránh ghi đè ngoài ý muốn.

Đứng tại thư mục gốc và chạy:

```powershell
cd D:\Code\flexransplit
py -m FlexRanSplitProblem.generate_all_networks
```

Mỗi mạng tạo hai file:

```text
FlexRanSplitProblem/data/network_<N>/phy.pkl
FlexRanSplitProblem/data/network_<N>/paths.pkl
```

Nguồn JSON nằm tại:

```text
FlexRanSplitProblem/model_files/T2_files/F1_<N>_CRs_nodes_<PROFILE>.json
FlexRanSplitProblem/model_files/T2_files/<N>_CRs_links_<PROFILE>.json
```

Các mạng nhỏ `8/16/32/64/256` hiện chủ yếu có bộ `F1-LC`. Bộ T2-128 có thêm
R1 và các resource profile RC/HC. Không chọn một tổ hợp nếu hai JSON tương ứng
không tồn tại.

### Bước 2: chạy Flex-split

Sửa file:

```text
FlexRanSplitProblem/settings/ilp.txt
```

Ví dụ chạy mạng 16:

```ini
[input]
network = 16
profile = LC
phy = FlexRanSplitProblem/data/network_{network}/phy.pkl
paths = FlexRanSplitProblem/data/network_{network}/paths.pkl
nodes = FlexRanSplitProblem/model_files/T2_files/F1_{network}_CRs_nodes_{profile}.json

[model]
core = 0
beta = 0.5

[solver]
name = auto
log = false

[output]
directory = FlexRanSplitProblem/results/network_{network}
csv = FlexRanSplitProblem/results/network_{network}/solution.csv
append = false
save_json = true
save_sol = false
save_snapshot = false
```

Đứng tại thư mục gốc và chạy:

```powershell
cd D:\Code\flexransplit
py -m FlexRanSplitProblem.run_ilp
```

File dùng để so sánh là:

```text
FlexRanSplitProblem/results/network_<N>/solution.csv
```

Các file timestamp `.json`, `.sol` và `.pkl.gz` chỉ là artifact chi tiết/debug;
script so sánh không đọc chúng.

Lưu ý: `profile` trong `ilp.txt` chỉ đổi tên file `nodes`. CPU và bandwidth khi
solve được đọc từ `phy.pkl`. Vì vậy phải sinh lại `phy.pkl` đúng profile trước
khi đổi LC/RC/HC.

### Bước 3: chạy cùng mạng bằng PlaceRAN

Sửa file:

```text
PlaceRAN/settings/network.txt
```

Ví dụ chạy cùng mạng 16, F1-LC và 10 path/RU:

```ini
[network]
name = t2-16
ru_distribution = F1
resource_level = LC
k_paths = 10
solver = auto
solver_log = false
time_limit =
results_root = results_pulp
```

Đứng trong thư mục `PlaceRAN` và chạy:

```powershell
cd D:\Code\flexransplit\PlaceRAN
py .\run_model_pulp.py
```

`run_model_pulp.py` tự chạy `model_files/path_gen.py`, ghi candidate paths tạm
vào `PlaceRAN/paths.json`, sau đó giải mô hình PlaceRAN. Không cần chạy path
generator riêng.

File dùng để so sánh là:

```text
PlaceRAN/results_pulp/T2-F1-LC-<N>/k_paths_<K>/solution.csv
```

Ví dụ cụ thể:

```text
PlaceRAN/results_pulp/T2-F1-LC-16/k_paths_10/solution.csv
```

Các JSON gốc PlaceRAN đọc nằm trong:

```text
PlaceRAN/model_files/T2_files/
```

Các bộ JSON chuẩn trong `PlaceRAN/model_files` và
`FlexRanSplitProblem/model_files` hiện là bản sao tương ứng. Khi thêm hoặc sửa
topology, phải bảo đảm cả hai phương pháp đọc cùng nội dung node/link.

### Bước 4: tạo bảng so sánh

Sau khi cả hai phía đã có `solution.csv`, quay lại thư mục gốc:

```powershell
cd D:\Code\flexransplit
py -m FlexRanSplitProblem.compare_results `
  --flexible .\FlexRanSplitProblem\results `
  --placeran .\PlaceRAN\results_pulp `
  --k-paths 10 `
  --output .\FlexRanSplitProblem\results\comparison.csv
```

Input thực tế của phép so sánh là:

```text
Flex:     FlexRanSplitProblem/results/network_<N>/solution.csv
PlaceRAN: PlaceRAN/results_pulp/T2-F1-LC-<N>/k_paths_<K>/solution.csv
```

Output:

```text
FlexRanSplitProblem/results/comparison.csv
```

Các cột được so sánh:

```text
network
placeran_runtime_s
flexible_runtime_s
placeran_drc_count
flexible_drc_count
```

`drc_count` là số DRC khác nhau xuất hiện trong `solution.csv`; `runtime` là
giá trị runtime lặp lại trên các dòng NSC của lần chạy cuối cùng.

Luôn truyền `--k-paths <K>` nếu `results_pulp` chứa nhiều lần chạy với các K
khác nhau. Nếu cùng một network có nhiều `solution.csv` phù hợp, script sẽ dừng
và yêu cầu chỉ rõ hoặc dọn lại cây kết quả.


## Checklist trước khi so sánh

- Hai bên dùng cùng topology/node/link JSON.
- Cùng network size và RU distribution.
- Cùng LC/RC/HC.
- Cùng `k_paths`.
- Không lấy nhầm dữ liệu giữa `data/` ở repo root và
  `FlexRanSplitProblem/data/`.
- Flex có `results/network_<N>/solution.csv`.
- PlaceRAN có thư mục kết thúc bằng network size và chứa
  `k_paths_<K>/solution.csv`.
- Dùng cùng solver nếu muốn so sánh runtime công bằng.
- Không so sánh `run_summary.csv` với `solution.csv`: `run_summary.csv` chỉ là
  tổng kết trạng thái batch, còn `compare_results.py` đọc `solution.csv`.
