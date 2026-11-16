# 테스트 매핑 (T01~T36)

실행 명령: `python -m pytest -q`(한컴 불필요) / `python -m pytest -q -m hancom`(한컴 PC). 상태는 2026-11-16 실행 결과입니다.

| # | 시나리오 | 테스트 | 상태 | 비고 |
|---|---|---|---|---|
| T01 | 신규 1명 | test_core_data::test_t01_t02_sample_file | PASS | 첨부 샘플(가명) |
| T02 | 전보 1명 | 위 + test_engine 전보 생성 | PASS | |
| T03 | 신규·전보 혼합 10명 | test_t03_mixed_kinds | PASS | |
| T04 | 100명 이상 | test_integration::test_t04_bulk_120_people | PASS | 120건 약 1.6초 |
| T05 | 구분 공백·제로폭·공란 | test_t05_kind_normalized | PASS | |
| T06 | 구분 `승진` | test_t06_unknown_kind | PASS | |
| T07 | 전보 현임교 공란 | test_t07_transfer_without_cur_school | PASS | |
| T08 | 신규에 현임교 | test_t08_new_with_cur_school_warns_and_ignores | PASS | |
| T09 | 발령일 H 우선/공란 | test_t09_order_date_priority, test_review_date_modes_follow_plan | PASS | |
| T10 | 날짜 형식 | test_t10_*, test_review_numeric_date_cells | PASS | 숫자 셀 `20261101`·`2026` 포함 |
| T11 | 동명이인 | test_t11_namesakes_and_t12_duplicates | PASS | 파일명 행번호 접미 |
| T12 | 완전 중복 행 | 위 | PASS | |
| T13 | 학교명 약칭 | test_t13_abbreviations | PASS | |
| T14 | 급 없는 약칭 | test_t14_level_less_is_ambiguous, test_review_generic_level_words_never_auto_confirm | PASS | |
| T15 | 없는 조합(유사) | test_t15_no_auto_confirm_for_fuzzy, test_review_parenthesis_never_auto_confirms | PASS | 제안만 |
| T16 | 미등록 학교 | test_t16_unregistered_and_manual_choice | PASS | 웹검색 없음(직접 입력) |
| T17 | 필드 스캔 | test_engine::test_t17_field_scan | PASS | 신규 4종(직종 2회)·전보 5종 |
| T18 | 허용 외 필드 | test_t18_unknown_field_rejected | PASS | |
| T19 | 분할 필드 병합 | test_t19_split_field_is_merged | PASS | 실제 양식에는 분할 없음 → 합성 XML |
| T20 | 조사 | test_t20_josa_in_output | PASS | |
| T21 | XML 특수문자 | test_t21_xml_escape, test_review_xml_entities_follow_xml_rules | PASS | |
| T22 | 값에 `{{성명}}` | test_t22_template_injection_blocked | PASS | V14 + 사후검증 C2 |
| T23 | 긴 이름·학교명 | test_t23_long_values_build; hancom 2번째 케이스 | **부분** | 한컴 1쪽 확인은 성명 7자·학교 10자까지. 성명 11자 이상은 한컴 미확인 |
| T24 | 비텍스트 파트 해시 | test_t24_non_text_parts_identical_and_tamper_detected | PASS | |
| T25 | 사후검증 FAIL 제외 | test_t25_failed_files_excluded_from_zip | PASS | |
| T26 | 양식 위장·손상 | test_t26_*, 중복·zip-slip | PASS | |
| T27 | 한컴 미설치 | test_t27_no_hancom_hwp_registration_message | **부분** | `available()`을 모의로 False 처리. 실제 한컴 없는 PC는 미실행 |
| T28 | HWP→HWPX 변환 | hancom::test_t28_hwp_to_hwpx_conversion_and_pdf(실제), test_engine::test_t28_conversion_failure_message(모의) | PASS | 실제 변환은 이 PC(한컴 2022)에서만 확인 |
| T29 | ZIP 구조·한글 파일명 | test_t29_zip_structure_and_korean_names | **부분** | UTF-8 플래그·구조 확인. Windows 기본 압축 해제 도구 실제 해제는 **미실행** |
| T30 | 저장 오류·경로 길이 | test_t30_filenames_safe_unique_and_short | **부분** | 파일명 길이·금지문자만. 저장 권한 오류 시나리오는 **미실행** |
| T31 | 부분 실패 | test_t31_partial_failure_keeps_others, test_failure_isolation_across_whole_pipeline | PASS | |
| T32 | 토큰·Host/Origin | test_app::test_t32_token_host_origin_enforced | PASS | |
| T33 | 오프라인·비루프백 차단 | test_integration::test_t33_*, test_app::test_t33_*, test_static_scan | PASS | 소켓 connect를 비루프백 차단한 상태로 전 흐름 실행. 물리적 오프라인 PC는 미실행 |
| T34 | 원본 해시 전후 | test_t34_originals_unchanged_after_run | PASS | |
| T35 | 주민번호·성명 로그 검색 | test_t35_no_rrn_in_outputs_or_logs, test_app 로그 테스트 | PASS | |
| T36 | 임시폴더 잔존 | test_t36_no_temp_leftovers | **부분** | 한컴 미사용 경로만. 한컴 변환 경로는 `ignore_cleanup_errors`로 정리하나 잔존 검사는 **미실행** |

추가(리뷰 반영 회귀 테스트): `test_review_*` — 학교명 범용 단어·괄호, 숫자 날짜, 중첩 표/자식 태그 경계, XML 엔티티, 미리보기 인코딩, mimetype 순서, 중복 엔트리, 마스터페이지, V14 사용자 입력.

### 미실행·부분 항목 요약
T23(성명 11자 이상 한컴), T27(실제 한컴 미설치 PC), T29(Windows 압축 해제), T30(권한 오류), T36(한컴 변환 임시폴더). 이들은 Phase 7 인수 단계 또는 깨끗한 PC에서 확인해야 합니다.
