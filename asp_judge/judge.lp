% ============================================================
% ASP-as-a-Judge — luật suy diễn cho benchmark xử phạt giao thông
% ============================================================
%
% Đầu vào (do encode.py sinh ra):
%   question_type(simple|exception|insufficient|multihop).
%   rubric_fine(min|max, V).            % ground truth mức phạt
%   rubric_points(V).                   % ground truth trừ điểm GPLX
%   rubric_revocation(min|max, V).      % ground truth tước GPLX (tháng)
%   rubric_penalized(true|false).
%   rubric_requires_clarification.      % chỉ có với loại insufficient
%   answer_fine(min|max, V).
%   answer_points(V).
%   answer_revocation(min|max, V).
%   answer_penalized(true|false).
%   answer_requires_clarification.
%
% Đầu ra: verdict(pass|fail) và violation(<tên lỗi>).
%
% Điểm mạnh so với LLM judge: mỗi phán quyết fail luôn kèm ÍT NHẤT một
% violation/1 có tên gọi, truy vết được về đúng luật nào đã kích hoạt —
% khác hẳn judge_rationale dạng văn xuôi tự do (đã bắt được trường hợp bịa
% số liệu không hề có trong câu trả lời).

#show verdict/1.
#show violation/1.

% ------------------------------------------------------------
% 1. MỨC PHẠT TIỀN — phải khớp CẢ HAI cận, không chấp nhận "gần đúng"
% ------------------------------------------------------------

rubric_has_fine :- rubric_fine(min, _).
answer_has_fine :- answer_fine(min, _).

fine_min_match :- rubric_fine(min, X), answer_fine(min, X).
fine_max_match :- rubric_fine(max, X), answer_fine(max, X).

fine_match :- fine_min_match, fine_max_match.

% Rubric có mức phạt mà câu trả lời không nêu -> bỏ sót
violation(missing_fine) :-
    rubric_has_fine,
    not answer_has_fine,
    rubric_penalized(true).

% Nêu sai mức phạt
violation(wrong_fine) :-
    rubric_has_fine,
    answer_has_fine,
    not fine_match.

% Chỉ nêu một cận (fine_partial): min đúng nhưng thiếu/sai max
violation(incomplete_fine_range) :-
    rubric_has_fine,
    answer_has_fine,
    fine_min_match,
    not fine_max_match.

% ------------------------------------------------------------
% 2. TRỪ ĐIỂM GIẤY PHÉP LÁI XE
% ------------------------------------------------------------

rubric_has_points :- rubric_points(V), V > 0.
answer_has_points :- answer_points(V), V > 0.

points_match :- rubric_points(V), answer_points(V).

violation(missing_points_deduction) :-
    rubric_has_points,
    not answer_has_points.

violation(wrong_points_deduction) :-
    rubric_has_points,
    answer_has_points,
    not points_match.

% ------------------------------------------------------------
% 3. TƯỚC QUYỀN SỬ DỤNG GPLX
% ------------------------------------------------------------

rubric_has_revocation :- rubric_revocation(min, _).
answer_has_revocation :- answer_revocation(min, _).

violation(missing_revocation) :-
    rubric_has_revocation,
    not answer_has_revocation.

% ------------------------------------------------------------
% 4. NGOẠI LỆ — rubric nói KHÔNG phạt mà câu trả lời vẫn áp phạt
% ------------------------------------------------------------
% Đây là loại lỗi mà LLM judge hay bỏ qua: câu trả lời nghe rất hợp lý,
% trích đúng điều khoản, chỉ sai ở chỗ đọc sót vế "trừ ...".

violation(exception_missed) :-
    rubric_penalized(false),
    answer_penalized(true).

violation(exception_overapplied) :-
    rubric_penalized(true),
    answer_penalized(false).

% ------------------------------------------------------------
% 5. CÂU HỎI THIẾU THÔNG TIN
% ------------------------------------------------------------

violation(overclaim_on_insufficient) :-
    rubric_requires_clarification,
    not answer_requires_clarification.

% Ngược lại: câu hỏi đủ thông tin mà lại né tránh
violation(unnecessary_clarification) :-
    question_type(T), T != insufficient,
    answer_requires_clarification,
    not rubric_requires_clarification.

% ------------------------------------------------------------
% 6. MULTIHOP — tổng phải cộng dồn đủ các quy định
% ------------------------------------------------------------
% rubric_fine ở multihop là TỔNG của các rule. Nếu câu trả lời chỉ nêu mức
% phạt của một rule (multihop_partial) thì fine_match thất bại và bị bắt bởi
% wrong_fine ở trên; luật dưới đây gắn thêm nhãn chuyên biệt để báo cáo
% tách theo loại lỗi.

violation(incomplete_aggregation) :-
    question_type(multihop),
    rubric_fine(max, T),
    answer_fine(max, A),
    A < T.

% ------------------------------------------------------------
% 7. KẾT LUẬN
% ------------------------------------------------------------

verdict(fail) :- violation(_).
verdict(pass) :- not verdict(fail).
