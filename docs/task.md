# 작업 목록

| Phase | 작업 | 상태 | 산출물 |
|---|---|---|---|
| 0 | 해시 기록, 환경 점검, 보안 설정(읽기 거부·품질 게이트 훅), 기본값 채택 | 완료 | docs/preflight.md, .claude/ |
| 1 | POC: Track A 치환 → 한컴 열기·1쪽·직인 보존 | 완료(Go) | docs/poc_report.md |
| 2 | excel_reader·normalizer·validator·school_matcher·josa | 완료 | insa_tongji/core, tests |
| 2 | 코드리뷰(1차) 지적 반영(P1 4건 + P2 다수) | 완료 | 로그.md |
| 3 | template_registry·hwpx_engine·verifier·generator·packager·hwp_com | 완료 | insa_tongji/core |
| 4 | 로컬 서버(토큰·Host/Origin)·세션·UI | 완료 | insa_tongji/app |
| 4 | 코드리뷰(2차: Phase 3~4) 지적 반영 | 완료 | 로그.md, docs/test_report.md |
| 5 | 통합·보안 테스트(100건·소켓 차단·해시·개인정보) | 완료(부분 항목 있음) | docs/test.md, docs/test_report.md |
| 6 | PyInstaller 폴더 배포, 청결 검사, 스모크, 문서 | 완료 | tools/, dist/(재생성 가능), docs/manual.md 외 |
| 7 | **사용자 인수**: 실자료를 사용자 PC에서 직접 실행·서명 | **미완(사용자 몫)** | docs/체크리스트.md |

## 후속(범위 밖, v1 제외)
PDF 일괄 출력, 발령대장 엑셀 자동 생성, 직인 이미지 교체, 승진·휴직 등 양식 추가, 학교 웹 조회.
