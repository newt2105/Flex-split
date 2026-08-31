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
| \(\mathcal N_s\) | `vupf`, `vcu`, `vdu`, `vru` | `problem.V` |
| \(\mathcal E_s\) | `vupf->vcu`, `vcu->vdu`, `vdu->vru` | `problem.virtual_links` |
| \(A_i\) | Capacity của node \(i\) | `node_cpu_cap(PHY, i)` |
| \(A_{ij}\) | Bandwidth của link \(ij\) | `edge_bw_cap(PHY, (i, j))` |
| \(R_{s,k,v}\) | Resource của VNF \(v\) với DRC \(k\) | `problem.node_req(s, k, v)` |
| \(R_{s,k,vw}\) | Bandwidth của virtual link \(vw\) | `problem.link_req(s, k, segment)` |
| \(L_p\) | Tổng latency của path \(p\) | `path_latency(p)` |
| \(L_s^{max}\) | SLA latency end-to-end tùy chọn của slice \(s\) | `problem.max_latency(s)` |

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

## Constraints

- **C1 / (4):** mỗi NSC chọn đúng một DRC.
- **C2 / (5):** mỗi NSC chọn đúng một cặp DRC/path.
- **C2b:** `sum_p y[s,k,p] = pi[s,k]`, bảo đảm DRC trong `y` trùng với DRC
  trong `pi`. Bản PDF thiếu liên kết này; nếu không thêm, hai quyết định có thể
  chọn hai DRC khác nhau.
- **C3 / (6):** `vupf` cố định tại core và `vru` cố định tại RU.
- **C4 / (7):** mỗi VNF nằm trên đúng một node của path đã chọn.
- **C5 / (8):** hai VNF của cùng NSC không được dùng chung một physical node.
- **C6 / (9):** tổng node resource và link bandwidth không vượt capacity.
- **C7 / (10):** flow conservation cho từng virtual link.
- **C8 / (11):** tắt các biến link mapping của path không được chọn.
- **C9 / (12)-(13):** `pi_tilde[k]` là phép OR của tất cả `pi[s,k]`.
- **C10:** nếu slice có SLA, path được chọn phải thỏa
  `sum_{k,p} y[s,k,p] * L_p <= max_latency[s]`.

Khi có `SliceProfile`, CPU và bandwidth gốc của DRC lần lượt được nhân với
`cpu_scale` và `bw_scale` của slice. Nếu không cấu hình profile, cả hai hệ số
mặc định bằng 1 và không có SLA latency, nên mô hình giữ hành vi cũ.

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
