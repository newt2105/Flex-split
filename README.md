# Chạy Flex-split và PlaceRAN

Tài liệu này mô tả đúng các entry point hiện tại của repo: cần sửa file nào,
đứng ở thư mục nào để chạy, dữ liệu được sinh ở đâu và dùng file nào để so
sánh Flex-split với PlaceRAN.

## 1. Cài dependencies

Mở PowerShell tại thư mục gốc của repo:

```powershell
cd D:\Code\flexransplit
py -m pip install -r .\FlexRanSplitProblem\requirements.txt
py -m pip install -r .\PlaceRAN\requirements-pulp.txt
```

`cbc` chạy được qua PuLP. Nếu muốn dùng Gurobi thì máy phải có Gurobi và
license hợp lệ; nếu không, đặt solver thành `auto` hoặc `cbc`.

## 2. So sánh theo kích thước mạng T2

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

## 3. Chạy benchmark 12 scenario chuẩn

Các case chuẩn có dạng:

```text
T1/T2 - R1/F1 - LC/RC/HC
```

Ví dụ `T2-F1-LC` hoặc `T1-R1-HC`.

### Flex-split batch

Sửa:

```text
FlexRanSplitProblem/settings/experiments.ini
```

Chọn các dòng trong `cases`, đồng thời đặt cùng `k_paths` với PlaceRAN. Nếu
không có Gurobi, đổi `solver = auto` hoặc `solver = cbc`.

Chạy từ thư mục gốc:

```powershell
cd D:\Code\flexransplit
py -m FlexRanSplitProblem.run_experiments
```

Kết quả từng case:

```text
FlexRanSplitProblem/results_experiments/<CASE>/k_paths_<K>/solution.csv
```

Tổng kết batch:

```text
FlexRanSplitProblem/results_experiments/run_summary.csv
```

### PlaceRAN batch

Sửa:

```text
PlaceRAN/settings/experiments.ini
```

Phải chọn cùng danh sách `cases` và cùng `k_paths` như Flex-split. Trong file
INI này có thể dùng `;` hoặc `#` để comment case không chạy.

Chạy trong thư mục PlaceRAN:

```powershell
cd D:\Code\flexransplit\PlaceRAN
py .\run_experiments_pulp.py
```

Kết quả từng case:

```text
PlaceRAN/results_pulp/<CASE>/k_paths_<K>/solution.csv
```

Tổng kết batch:

```text
PlaceRAN/results_pulp/run_summary.csv
```

Với benchmark 12 scenario, cặp file cần đối chiếu là:

```text
FlexRanSplitProblem/results_experiments/<CASE>/k_paths_<K>/solution.csv
PlaceRAN/results_pulp/<CASE>/k_paths_<K>/solution.csv
```

`compare_results.py` hiện nhận diện Flex theo thư mục `network_<N>`, nên chưa
tự động ghép cây `results_experiments/<CASE>`. Muốn so sánh batch theo case,
cần đọc trực tiếp hai `solution.csv` cùng `<CASE>` và `<K>`, hoặc mở rộng script
so sánh để dùng tên case làm khóa.

## 4. Mạng heterogeneous

Sửa:

```text
FlexRanSplitProblem/settings/heterogeneous_phy.txt
```

Nếu PHY chuẩn được sinh theo mục 2, đặt input/output nhất quán như sau:

```ini
[input]
data_directory = FlexRanSplitProblem/data
nodes_directory = FlexRanSplitProblem/model_files/T2_files

[output]
directory = FlexRanSplitProblem/data_heterogeneous
copy_paths = true
write_placeran_json = true
```

Chạy từ thư mục gốc:

```powershell
cd D:\Code\flexransplit
py -m FlexRanSplitProblem.generate_heterogeneous_phy
```

Flex-split dùng:

```text
FlexRanSplitProblem/data_heterogeneous/network_<N>/phy.pkl
FlexRanSplitProblem/data_heterogeneous/network_<N>/paths.pkl
FlexRanSplitProblem/data_heterogeneous/network_<N>/nodes.json
```

Để giải bằng Flex-split, đổi phần `[input]` và `[output]` trong
`FlexRanSplitProblem/settings/ilp.txt`:

```ini
[input]
network = 16
profile = LC
phy = FlexRanSplitProblem/data_heterogeneous/network_{network}/phy.pkl
paths = FlexRanSplitProblem/data_heterogeneous/network_{network}/paths.pkl
nodes = FlexRanSplitProblem/data_heterogeneous/network_{network}/nodes.json

[output]
directory = FlexRanSplitProblem/results_heterogeneous/network_{network}
csv = FlexRanSplitProblem/results_heterogeneous/network_{network}/solution.csv
append = false
save_json = true
save_sol = false
save_snapshot = false
```

Sau đó chạy từ repo root:

```powershell
cd D:\Code\flexransplit
py -m FlexRanSplitProblem.run_ilp
```

PlaceRAN dùng JSON được generator tạo tại:

```text
FlexRanSplitProblem/data_heterogeneous/network_<N>/placeran/
```

Ví dụ chạy PlaceRAN trên topology heterogeneous:

```powershell
cd D:\Code\flexransplit\PlaceRAN
py .\run_model_pulp.py `
  --case T2-F1-LC `
  --network t2-16 `
  --k-paths 10 `
  --topology-dir ..\FlexRanSplitProblem\data_heterogeneous\network_16\placeran `
  --results .\results_pulp_heterogeneous\T2-F1-LC-16\k_paths_10
```

Khi so sánh heterogeneous, truyền đúng hai result root:

```powershell
cd D:\Code\flexransplit
py -m FlexRanSplitProblem.compare_results `
  --flexible .\FlexRanSplitProblem\results_heterogeneous `
  --placeran .\PlaceRAN\results_pulp_heterogeneous `
  --k-paths 10 `
  --output .\FlexRanSplitProblem\results_heterogeneous\comparison.csv
```

## 5. Checklist trước khi so sánh

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
