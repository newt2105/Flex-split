# Báo cáo phân tích và tuning tài nguyên vật lý cho Flex-split

## 1. Mục tiêu và phạm vi

Mục tiêu của công việc này là điều chỉnh hợp lý tài nguyên của mạng vật lý để
Flex-split tự nhiên sử dụng nhiều hơn một DRC trong cùng một network instance.
Việc tuning phải tuân thủ các nguyên tắc sau:

- Không thay đổi yêu cầu CPU, RAM, bandwidth hoặc latency của bất kỳ DRC/VNF nào.
- Không hard-code DRC được chọn cho từng NSC.
- Không thêm constraint bắt buộc solver sử dụng nhiều DRC.
- Không thay đổi objective chỉ để tạo ra kết quả mong muốn.
- Giữ nguyên topology, vị trí RU và link delay của PlaceRAN.
- Chỉ thay đổi CPU capacity của một số CR/RU và bandwidth capacity của một số
  physical link.

Các JSON PlaceRAN gốc trong `model_files/T1_files/` và
`model_files/T2_files/` được giữ nguyên. Các profile đã tuning được sinh thành
bản sao riêng trong `model_files/T2_tuned_files/` với tên profile `HET`.

## 2. Mô hình trong paper Flex-split

### 2.1. Mạng vật lý

Paper biểu diễn mạng vật lý bằng đồ thị có trọng số:

\[
\mathcal{G}=(\mathcal{N},\mathcal{E}),
\]

trong đó:

- `i0` là core node;
- `C` là tập các computing resource node/CR;
- `B` là tập RU;
- `T` là tập transport node;
- mỗi node `i` có capacity `A_i`;
- mỗi link `ij` có bandwidth capacity `A_ij` và latency `L_ij`.

Mỗi RU có một tập candidate path từ core đến RU. Latency của path bằng tổng
latency của tất cả physical link trên path.

### 2.2. Functional split và DRC

Mỗi NSC gồm bốn VNF theo thứ tự:

\[
v_{upf} \rightarrow v_{cu} \rightarrow v_{du} \rightarrow v_{ru}.
\]

UPF được cố định tại core, RU VNF được cố định tại CR chứa RU. Solver quyết
định DRC, path, vị trí CU và vị trí DU.

Paper mô tả 12 tổ hợp functional split chuẩn hóa. Tuy nhiên, implementation
hiện tại chỉ chứa đúng 9 DRC có ID:

`1, 2, 4, 5, 6, 7, 8, 9, 10`.

Do solver lấy trực tiếp tập DRC từ `DRC_structure_T2()`, mọi phân tích và tuning
trong báo cáo này sử dụng đúng 9 profile thực sự có trong code.

## 3. Yêu cầu tài nguyên DRC chính xác từ implementation

Các giá trị dưới đây được đọc trực tiếp từ `phy/ran_model.py`. CPU và latency
giống nhau giữa T1 và T2; bandwidth của hai topology family khác nhau.

| DRC | CU CPU | DU CPU | RU CPU | Delay BH/MH/FH | BW T1 BH/MH/FH | BW T2 BH/MH/FH |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 0.49 | 2.058 | 2.352 | 10 / 10 / 0.25 | 3 / 5.4 / 17.4 | 9.9 / 13.2 / 42.6 |
| 2 | 0.98 | 1.568 | 2.352 | 10 / 10 / 0.25 | 3 / 5.4 / 17.4 | 9.9 / 13.2 / 42.6 |
| 4 | 0.49 | 1.225 | 3.185 | 10 / 10 / 0.25 | 3 / 5.4 / 5.6 | 9.9 / 13.2 / 13.6 |
| 5 | 0.98 | 0.735 | 3.185 | 10 / 10 / 0.25 | 3 / 5.4 / 5.6 | 9.9 / 13.2 / 13.6 |
| 6 | 0 | 0.49 | 4.41 | 0 / 10 / 10 | 0 / 3 / 5.4 | 0 / 9.9 / 13.2 |
| 7 | 0 | 3 | 3.92 | 0 / 10 / 10 | 0 / 3 / 5.4 | 0 / 9.9 / 13.2 |
| 8 | 0 | 0 | 4.9 | 0 / 0 / 10 | 0 / 0 / 3 | 0 / 0 / 9.9 |
| 9 | 0 | 2.54 | 2.354 | 0 / 10 / 0.25 | 0 / 3 / 17.4 | 0 / 9.9 / 42.6 |
| 10 | 0 | 1.71 | 3.185 | 0 / 10 / 0.25 | 0 / 3 / 5.6 | 0 / 3 / 13.6 |

Như vậy, giả thuyết trong yêu cầu ban đầu được xác nhận cho T2:

- DRC5 và DRC10 cần RU CPU `3.185` và FH bandwidth `13.6`.
- DRC8 cần RU CPU `4.9` và FH bandwidth `9.9`.

Các DRC khác cũng đã được xét đầy đủ. Đặc biệt:

- DRC1, DRC2 và DRC9 có FH bandwidth rất lớn: `42.6`.
- DRC6 và DRC7 có FH bandwidth `13.2`.
- DRC8 là DRC duy nhất có FH bandwidth không vượt quá `10.5`.

## 4. Ánh xạ formulation sang implementation

| Thành phần trong paper | Thành phần trong code |
|---|---|
| Mạng vật lý `G=(N,E)` | `FlexRanSplitProblem.PHY`, `N`, `E` |
| Một NSC cho mỗi RU | `problem.S` |
| Tập DRC `K` | `problem.K` từ `DRC_structure_T2()` |
| Candidate paths `P_s` | `problem.paths_for_slice(s)` |
| Chọn DRC `pi[s,k]` | biến nhị phân `pi` |
| DRC được sử dụng `pi_tilde[k]` | biến nhị phân `pi_tilde` |
| Chọn cặp DRC/path | biến nhị phân `y[s,k,p]` |
| VNF placement | biến nhị phân `x_node[s,k,p,i,v]` |
| Virtual-link mapping | biến nhị phân `x_link[s,k,p,i,j,v,w]` |
| C1 | mỗi NSC chọn đúng một DRC |
| C2 | mỗi NSC chọn đúng một cặp DRC/path |
| C2b | liên kết `y` với `pi`, được code bổ sung vì draft bị thiếu |
| C3 | UPF cố định tại core, RU VNF cố định tại RU-bearing CR |
| C4 | mỗi VNF được đặt tại đúng một node trên path |
| C5 | hai VNF của cùng NSC không được cùng một physical node |
| C6 | tổng CPU và bandwidth không vượt physical capacity |
| C7 | flow conservation cho từng virtual link |
| C8 | loại link-mapping variable của path không được chọn |
| C9 | `pi_tilde[k]` là phép OR của các `pi[s,k]` |

Objective trong implementation là:

\[
\min \; \beta\sum_k \widetilde{\pi}_k
+(1-\beta)\frac{\sum_{s,k,p}y_{s,k}^{p}L_p}{L_{max}}.
\]

Trong các kết quả hiện tại, `beta = 0.5`.

### 4.1. Các điểm cần chú ý

1. Code thêm C2b, `sum_p y[s,k,p] = pi[s,k]`. Constraint này cần thiết để
   DRC trong biến chọn path nhất quán với biến chọn DRC.
2. C5 áp dụng cả khi CU CPU hoặc DU CPU bằng 0. Vì vậy UPF, CU, DU và RU của
   cùng NSC vẫn phải nằm trên bốn physical node khác nhau. Candidate path cần
   ít nhất bốn node để khả thi.
3. Một số shortest path chỉ có ba node được lưu trong `paths.pkl` nhưng không
   thể được chọn vì C5. Solver phải chọn candidate path dài hơn.
4. Các giới hạn delay BH/MH/FH của DRC được lưu trong data model nhưng không
   được enforce trong `lp_formulation.py`. Link delay chỉ tham gia objective
   thông qua tổng path latency.
5. Mẫu số chuẩn hóa latency là maximum latency của một candidate path, không
   phải tổng maximum latency của tất cả NSC. Do đó normalized latency term có
   thể lớn hơn 1, mặc dù draft nói nó nằm trong `[0,1]`.
6. T2 JSON mô tả link vô hướng, nhưng `load_phy_T2()` thêm hai directed edge.
   Capacity được enforce riêng cho từng hướng.

## 5. Pipeline tạo `phy.pkl` và `paths.pkl`

### 5.1. `phy.pkl`

`generate_all_networks.py` gọi `load_phy_T2()` trong `phy/genphy.py`.

`load_phy_T2()` đọc:

- trường `cpu` của node JSON;
- trường `capacity` và `delay` của link JSON;
- mỗi physical link được thêm vào NetworkX graph theo cả hai hướng.

Vì vậy, khi thay đổi CPU hoặc link bandwidth trong JSON, bắt buộc phải sinh lại
`phy.pkl`. Nếu giữ một `phy.pkl` cũ thì solver vẫn sử dụng capacity LC cũ.

### 5.2. `paths.pkl`

`generate_paths()` trong `phy/path_gen.py` sinh tối đa `k_paths` latency-shortest
simple paths cho mỗi RU.

Path generator chỉ sử dụng:

- topology endpoint của physical link;
- link delay.

Path generator không sử dụng node CPU hoặc link bandwidth. Vì profile HET giữ
nguyên topology và delay, candidate node sequences của HET về nguyên tắc giống
LC. Tuy nhiên, settings HET vẫn để `overwrite = true` nhằm đảm bảo `phy.pkl`
được cập nhật và toàn bộ artifact đồng bộ với profile mới.

## 6. Mạng vật lý T1 và T2

Trước khi sinh profile HET, toàn bộ JSON T1/T2 của Flex-split đã được kiểm tra
hash và khớp byte-for-byte với các file tương ứng trong PlaceRAN.

### 6.1. T1

T1 có 51 CR và 63 undirected physical link trong JSON.

- F1 có 49 RU.
- R1 có 39 RU.
- LC có 4 CR với CPU 16 và 47 CR với CPU 8.
- LC link capacity thuộc các mức 10, 25 và 100.
- LC link delay nằm trong khoảng 0.4 đến 0.9073.
- HC và RC giữ cùng topology nhưng sử dụng các profile CPU, RAM, bandwidth,
  delay và RU placement khác.

### 6.2. T2 LC

| Network | Số RU/NSC | Số node theo hop tier từ core | CPU của RU-bearing CR | Phân bố link capacity |
|---:|---:|---|---|---|
| 8 | 6 | 1 / 2 / 3 / 3 | 3x16, 3x8 | 2x100, 6x50, 6x25 |
| 16 | 14 | 1 / 2 / 5 / 9 | 5x16, 9x8 | 2x100, 10x50, 18x25 |
| 32 | 30 | 1 / 2 / 6 / 24 | 6x16, 24x8 | 2x800, 12x100, 49x50 |
| 64 | 62 | 1 / 2 / 8 / 54 | 8x16, 54x8 | 2x800, 16x100, 109x50 |
| 128 | 126 | 1 / 2 / 20 / 76 / 15 / 15 | 20x16, 106x8 | 2x800, 40x100, 152x50, 30x40 |
| 256 | 254 | 1 / 2 / 20 / 200 / 21 / 13 | 20x16, 234x8 | 2x2000, 248x100, 226x50 |

Số đầu tiên trong cột hop tier là core node ở hop 0.

## 7. Phân tích kết quả hiện tại

Kết quả Flex-split hiện tại:

| Network | DRC được ghi nhận | Số NSC | Tổng path latency |
|---:|---:|---:|---:|
| 8 | 5 | 6 | 6.717 |
| 16 | 10 | 14 | 15.119 |
| 32 | 8 | 30 | 30.744 |
| 64 | 8 | 62 | 61.956 |
| 128 | 8 | 126 | 136.139 |
| 256 | 8 | 254 | 277.057 |

PlaceRAN sử dụng số distinct DRC tương ứng là `2, 1, 1, 2, 5, 3`, trong khi
Flex-split sử dụng `1, 1, 1, 1, 1, 1`. Đây không phải bug. Objective hiện tại
trực tiếp thưởng nghiệm có ít distinct DRC.

### 7.1. Vì sao network 8 ghi nhận DRC5?

Khi giữ nguyên path và placement của kết quả hiện tại, các DRC sau đều khả thi:

`DRC4, DRC5, DRC6, DRC7, DRC8, DRC10`.

Một kiểm tra placement đầy đủ cũng xác nhận cả sáu DRC trên đều có thể trở
thành universal DRC cho network 8 và đạt cùng tổng shortest feasible latency
`6.717`.

DRC1, DRC2 và DRC9 không thể cover các RU tier ngoài vì FH bandwidth `42.6`
lớn hơn access-link capacity `25`.

Vì objective không có thành phần phân biệt DRC4, 5, 6, 7, 8 và 10 khi chúng
cùng sử dụng một distinct DRC và cùng đạt latency, việc CBC/Gurobi trả về DRC5
là kết quả tie-breaking giữa nhiều nghiệm tối ưu, không phải do objective có
preference riêng cho DRC5.

### 7.2. Vì sao network 16 ghi nhận DRC10?

Trên đúng path và placement hiện tại, `DRC6, DRC7, DRC8, DRC10` đều khả thi và
có cùng objective. DRC1, 2, 4 và 5 tạo tải BH `138.6` trên link `0->1`, vượt
capacity `100`. DRC9 gặp bottleneck FH trên các link aggregation.

Do đó DRC10 cũng là một nghiệm được solver chọn trong một tập nghiệm tối ưu
hòa, thay vì là DRC duy nhất khả thi.

### 7.3. Vì sao network từ 32 trở lên thường ghi nhận DRC8?

DRC8 có ba lợi thế đặc biệt dưới formulation hiện tại:

- CU CPU bằng 0;
- DU CPU bằng 0;
- BH và MH bandwidth bằng 0.

Toàn bộ CPU được dồn về RU với mức `4.9`, và chỉ FH segment sử dụng bandwidth
`9.9`. Vì vậy DRC8 tránh được shared bottleneck tại core, aggregation CR và
aggregation link khi số NSC tăng.

Tuy nhiên, DRC8 vẫn không phải nghiệm duy nhất trong mọi network:

| Network | DRC khác khả thi trên cùng path/placement |
|---:|---|
| 32 | DRC6 |
| 64 | Không có trong 9 DRC |
| 128 | DRC6 |
| 256 | Không có trong 9 DRC |

Ở network 64, nếu thay bằng DRC6 thì link `1->3` cần `138.6` trên capacity
`100`; nếu thay bằng DRC10 thì CR3 cần `27.125` CPU trên capacity `16`.

Ở network 256, DRC6 cần `198` bandwidth trên link `1->19` có capacity `100`,
còn DRC10 cần `32.255` CPU tại CR19 có capacity `16`.

Như vậy, xu hướng chọn DRC8 khi network lớn xuất phát từ khả năng loại bỏ tải
shared CU/DU và BH/MH. Riêng network 32 và 128 vẫn tồn tại nghiệm tối ưu hòa
với DRC6.

## 8. Thiết kế profile tài nguyên không có universal DRC

### 8.1. Profile A

- RU CPU: `3.4`.
- Capacity của mọi link incident: `15`.

Kiểm tra trực tiếp cả 9 DRC cho kết quả:

- DRC4, DRC5, DRC10 khả thi tại endpoint.
- DRC6, DRC7, DRC8 bị loại bởi RU CPU.
- DRC1, DRC2, DRC9 bị loại bởi FH bandwidth.

Do đó:

\[
K_A=\{4,5,10\}.
\]

### 8.2. Profile B

- RU CPU: `5.2`.
- Capacity của mọi link incident: `10.5`.

Kiểm tra trực tiếp cả 9 DRC cho kết quả:

- DRC8 khả thi vì RU CPU `4.9 <= 5.2` và FH `9.9 <= 10.5`.
- DRC1, 2, 4, 5, 6, 7, 9 và 10 đều bị loại bởi FH bandwidth.

Do đó:

\[
K_B=\{8\}.
\]

Vì:

\[
K_A \cap K_B = \varnothing,
\]

không tồn tại một DRC duy nhất có thể cover cả hai vùng. Solver bắt buộc phải
dùng nhiều hơn một DRC vì physical feasibility, chứ không phải vì constraint
ép số DRC.

## 9. Quy tắc chọn vùng HET

Để hạn chế thay đổi tài nguyên và giữ problem dễ khả thi, mỗi network chỉ chọn
một CR làm profile A và một CR làm profile B. Các CR khác giữ nguyên toàn bộ
CPU và link bandwidth của PlaceRAN.

Quy tắc xác định node:

- Profile A là RU-bearing CR có ID nhỏ nhất ở đúng hai hop từ core.
- Profile B là RU-bearing CR có ID nhỏ nhất ở xa hơn hai hop từ core.

| Network | CR profile A | CR profile B |
|---:|---:|---:|
| 8 | 3 | 6 |
| 16 | 3 | 8 |
| 32 | 3 | 9 |
| 64 | 3 | 11 |
| 128 | 3 | 23 |
| 256 | 3 | 23 |

Nếu A và B cùng incident với một physical link, profile B được ưu tiên và link
đó nhận capacity `10.5`. Quy tắc này đảm bảo mọi đường vào B đều không thể mang
FH của DRC khác ngoài DRC8.

## 10. Kiểm tra feasibility sau tuning

Một nghiệm xây dựng đã được kiểm tra trên chính tập mười candidate paths/RU
hiện có:

- NSC kết thúc tại profile A sử dụng DRC10.
- Các NSC còn lại sử dụng DRC8.

Kết quả:

| Network | DRC sử dụng trong witness | Feasible |
|---:|---|---|
| 8 | 8, 10 | Có |
| 16 | 8, 10 | Có |
| 32 | 8, 10 | Có |
| 64 | 8, 10 | Có |
| 128 | 8, 10 | Có |
| 256 | 8, 10 | Có |

Tải cực đại quan sát được trong witness:

- Profile B CPU: `4.9 / 5.2 = 94.23%`.
- Profile B link bandwidth: `9.9 / 10.5 = 94.29%`.

Điều này chứng minh rule HET không chỉ loại universal DRC mà còn giữ toàn bộ
problem khả thi với candidate paths hiện tại.

## 11. Các file đã tạo

- `phy/resource_tuning.py`: rule chọn vùng A/B và thay physical capacity.
- `tune_physical_resources.py`: CLI sinh JSON HET.
- `model_files/T2_tuned_files/`: node/link JSON HET cho 8–256.
- `model_files/T2_tuned_files/resource_profiles_HET.json`: manifest của các
  node được chọn và capacity profile.
- `settings/path_gen_heterogeneous.txt`: sinh artifact HET với
  `overwrite = true`.
- `settings/ilp_heterogeneous.txt`: cấu hình chạy ILP cho HET, mặc định bắt đầu
  với network 8.
- `tests/test_resource_tuning.py`: kiểm tra topology/delay không đổi, chỉ đúng
  hai node được sửa CPU, và tập DRC endpoint của A/B được tính trực tiếp từ
  `DRC_structure_T2()`.

## 12. Cách sinh dữ liệu và chạy solver

Từ thư mục gốc `D:\Code\flexransplit`:

```powershell
python FlexRanSplitProblem/tune_physical_resources.py
python -m FlexRanSplitProblem.generate_all_networks --settings FlexRanSplitProblem/settings/path_gen_heterogeneous.txt
python -m FlexRanSplitProblem.run_ilp --settings FlexRanSplitProblem/settings/ilp_heterogeneous.txt
```

Để chạy network khác, thay giá trị `network` trong
`settings/ilp_heterogeneous.txt`. Các đường dẫn còn lại sử dụng placeholder
`{network}` nên không cần sửa thủ công.

## 13. Trạng thái kiểm chứng

Đã hoàn thành:

- Đọc đầy đủ bốn trang của draft Flex-split.
- Trace formulation sang `lp_formulation.py`.
- Đọc trực tiếp cả DRC T1 và T2 từ `phy/ran_model.py`.
- Đọc và thống kê toàn bộ JSON T1/T2.
- Xác nhận JSON Flex-split gốc giống PlaceRAN.
- Đọc và thống kê toàn bộ kết quả Flex-split/PlaceRAN hiện có.
- Kiểm tra đủ 9 DRC cho profile A và B.
- Parse thành công 13 JSON HET đã sinh.
- Kiểm tra cú pháp Python của generator, tuning module và tests.
- Dựng witness thỏa node/link capacity cho cả sáu network.

Chưa chạy lại CBC/PuLP trong môi trường hiện tại vì Python runtime không có
PuLP/NetworkX và quyền tải dependency không được cấp. Việc này không ảnh hưởng
đến chứng minh endpoint-feasibility và constructive feasibility đã thực hiện,
nhưng cần chạy ba lệnh ở Mục 12 trong môi trường dự án có đầy đủ dependency để
thu được `solution.csv` chính thức cho profile HET.

## 14. Kết luận

Kết quả một distinct DRC trên mỗi network của Flex-split là đúng với
formulation/objective hiện tại. Trong nhiều network, DRC ID được ghi nhận còn
là kết quả tie-breaking giữa nhiều nghiệm có cùng objective.

Rule HET tạo hai vùng tài nguyên có tập DRC khả thi rời nhau:

\[
K_A=\{4,5,10\}, \qquad K_B=\{8\}.
\]

Vì vậy không có universal DRC, nhưng toàn bộ problem vẫn khả thi. Cách làm này
đạt mục tiêu sử dụng nhiều DRC thông qua heterogeneity tự nhiên của physical
resources mà không thay đổi DRC, không hard-code lựa chọn, không thêm constraint
ép solver và không sửa objective.

