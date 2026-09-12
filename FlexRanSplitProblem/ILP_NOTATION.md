# ILP notation and code mapping

Tài liệu này ánh xạ trực tiếp Section III-IV của bài báo sang
`lp_formulation.py`.

## Sets và parameters

| Ký hiệu | Ý nghĩa | Trong code |
|---|---|---|
| \(\mathcal G=(\mathcal N,\mathcal E)\) | Mạng vật lý | `problem.PHY` |
| \(\mathcal N\) | Các node vật lý | `problem.N` |
| \(\mathcal E\) | Các link vật lý | `problem.E` |
| \(\mathcal S\) | Các NSC; mỗi NSC ứng với một RU | `problem.S` |
| \(\mathcal K\) | Các DRC khả dụng | `problem.K` |
| \(\mathcal P_s\) | Path vật lý từ core đến RU của NSC \(s\) | `problem.paths_for_slice(s)` |
| \(\mathcal N_{s,k}\) | Các VNF thực sự tồn tại trong DRC \(k\) | `problem.active_vnfs(k)` |
| \(\mathcal E_{s,k}\) | Chuỗi virtual link sau khi bỏ CU/DU có CPU bằng 0 | `problem.active_virtual_links(k)` |
| \(A_i\) | Capacity của node \(i\) | `node_cpu_cap(PHY, i)` |
| \(A_{ij}\) | Bandwidth của link \(ij\) | `edge_bw_cap(PHY, (i, j))` |
| \(R_{s,k,v}\) | Resource của VNF \(v\) với DRC \(k\) | `problem.node_req(s, k, v)` |
| \(R_{s,k,vw}\) | Bandwidth của virtual link \(vw\) | `problem.link_req(s, k, segment)` |
| \(L_p\) | Tổng latency của path \(p\) | `path_latency(p)` |

`K` được lấy từ dữ liệu đầu vào, vì vậy ILP hỗ trợ cả 12 DRC trong bài báo
hoặc tập 9 DRC hiện có của `DRC_structure_T2()`.

## Binary decision variables

| Ký hiệu bài báo | Biến code | Bằng 1 khi |
|---|---|---|
| \(\widetilde\pi_k\) | `pi_tilde[k]` | DRC \(k\) được ít nhất một NSC dùng |
| \(\pi_{s,k}\) | `pi[s, k]` | NSC \(s\) chọn DRC \(k\) |
| \(y^p_{s,k}\) | `y[s, k, p]` | NSC \(s\) chọn cặp DRC/path \((k,p)\) |
| \(x^{p,i}_{s,k,v}\) | `x_node[s, k, p, i, v]` | VNF \(v\) được đặt tại node \(i\) |
| \(x^{p,ij}_{s,k,vw}\) | `x_link[s, k, p, i, j, v, w]` | Virtual link \(vw\) dùng physical link \(ij\) |

Mô hình không còn dùng `adm`, `theta` hoặc gán sẵn vị trí CU/DU trong một
path. Path chỉ là một chuỗi node vật lý; vị trí VNF do `x_node` quyết định.

Chuỗi VNF phụ thuộc vào DRC:

- CU và DU đều có tài nguyên: `vupf -> vcu -> vdu -> vru`.
- CU bằng 0: `vupf -> vdu -> vru` (dùng bandwidth MH rồi FH).
- CU và DU đều bằng 0: `vupf -> vru` (dùng bandwidth FH).

## Constraints

- **C1 / (4):** mỗi NSC chọn đúng một DRC.
- **C2 / (5):** mỗi NSC chọn đúng một cặp DRC/path.
- **C2b:** `sum_p y[s,k,p] = pi[s,k]`, bảo đảm DRC trong `y` trùng với DRC
  trong `pi`. Bản PDF thiếu liên kết này; nếu không thêm, hai quyết định có thể
  chọn hai DRC khác nhau.
- **C3 / (6):** `vupf` cố định tại core và `vru` cố định tại RU.
- **C4 / (7):** mỗi VNF đang hoạt động nằm trên đúng một node của path đã chọn.
  `vcu` hoặc `vdu` có CPU bằng 0 trong DRC sẽ không được tạo biến placement.
- **C5 / (8):** hai VNF đang hoạt động của cùng NSC không được dùng chung một
  physical node. Các VNF không tồn tại trong DRC không tham gia constraint này.
- **C6 / (9):** tổng node resource và link bandwidth không vượt capacity.
- **C7 / (10):** flow conservation cho từng virtual link.
- **C8 / (11):** tắt các biến link mapping của path không được chọn.
- **C9 / (12)-(13):** `pi_tilde[k]` là phép OR của tất cả `pi[s,k]`.

C9 được code dưới dạng `sum_s pi[s,k] <= |S| pi_tilde[k]` và
`pi_tilde[k] <= sum_s pi[s,k]`. Dạng này tương đương với (13) cho biến nhị
phân nhưng ổn định số hơn cách dùng một epsilon rất nhỏ.

## Objective

Mục tiêu (14)-(15) là

\[
\min\; \beta \sum_k \widetilde\pi_k
+ (1-\beta)\frac{\sum_{s,k,p} y^p_{s,k}L_p}{\overline L},
\qquad
\overline L=\max_{s,p\in\mathcal P_s}L_p.
\]

`beta` được truyền vào `formulateLp(problem, beta=...)` và phải thuộc `[0,1]`.
Theo đúng formulation trong PDF, các delay BH/MH/FH không phải constraints;
latency được tối ưu qua objective. Các delay bound cũ vẫn nằm trong data model
để giữ tương thích với phần RL.

## Path data

Các file path cũ chứa nhiều bản ghi có cùng chuỗi node vì CU/DU đã được gán
trước. `paths_for_slice()` tự loại trùng theo chuỗi node. Khi tạo lại dữ liệu,
dùng `python -m FlexRanSplitProblem.phy.path_gen`: generator mới chỉ sinh
physical paths và để ILP quyết định placement.
